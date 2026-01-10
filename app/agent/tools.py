import os
import time
import tempfile
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from langchain.tools import tool
from app.extensions import firebase_storage
import subprocess
import uuid
import shutil
import re
import requests

# Matplotlib settings for server-safe rendering
matplotlib.use("Agg")
plt.rcParams["figure.dpi"] = 100
plt.rcParams["savefig.dpi"] = 300
plt.rcParams["font.size"] = 10


# DOWNLOAD FILE TOOL  (JSON-safe)

class DownloadInput(BaseModel):
    path: str = Field(..., description="Firebase Storage path to the CSV file")

@tool(
    "download_file_as_dataframe",
    description="Downloads a CSV/XLSX from Firebase Storage and returns rows as JSON.",
    args_schema=DownloadInput,
)
def download_file_as_dataframe(path: str):
    """
    Downloads a CSV/XLSX from Firebase Storage
    and returns rows as JSON (not a DataFrame).
    """
    content = firebase_storage.download_file(path)
    suffix = os.path.splitext(path)[1] or ".csv"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(content)
        tmp.close()

        df = pd.read_csv(tmp.name)
        data = df.to_dict(orient="records")
    finally:
        if os.path.exists(tmp.name):
            os.remove(tmp.name)

    return {
        "status": "success",
        "message": "File downloaded successfully.",
        "records": data,
    }


# BACKTESTING TOOL  (JSON-safe)

class BacktestInput(BaseModel):
    records: List[Dict[str, Any]] = Field(..., description="Rows with {date, price} fields.")

@tool(
    "backtesting_tool",
    description="Runs a buy-and-hold backtest on price data.",
    args_schema=BacktestInput,
)
def backtesting_tool(records: List[Dict[str, Any]]):
    """
    Executes deterministic buy & hold backtest.
    Input = JSON rows, internally converted into a DataFrame.
    """
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["price"].astype(float).sort_index()

    rets = s.pct_change().dropna()
    eq = (1 + rets).cumprod()

    ann = 252
    mu = float(rets.mean() * ann)
    sig = float(rets.std(ddof=0) * np.sqrt(ann))
    sharpe = float(mu / sig) if sig > 0 else 0.0
    cagr = float(eq.iloc[-1] ** (ann / len(rets)) - 1)
    maxdd = float((eq / eq.cummax() - 1).min())

    # ---- PLOT TO TEMP FILE ----
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    plot_path = tmp.name
    tmp.close()

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(eq.index, eq.values, linewidth=2)
    ax.set_title("Backtest: Growth of $1")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Return")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(plot_path, dpi=300)
    plt.close()

    # Upload Plot
    file_obj = open(plot_path, "rb")
    try:
        dest = f"backtests/plot_{int(time.time())}.png"
        url = firebase_storage.upload_file(
            file_obj=file_obj,
            destination_path=dest,
            content_type="image/png",
        )
    finally:
        file_obj.close()
        if os.path.exists(plot_path):
            os.remove(plot_path)

    return {
        "url": url,
        "metrics": {
            "sharpe": sharpe,
            "cagr": cagr,
            "max_drawdown": maxdd,
            "total_return": float(eq.iloc[-1] - 1),
            "volatility_annual": sig,
            "return_annual": mu,
            "num_days": len(rets),
            "start_date": str(eq.index[0]),
            "end_date": str(eq.index[-1]),
        },
    }

# GENERATE PDF REPORT TOOL

class ReportInput(BaseModel):
    latex_content: str = Field(..., description="The complete LaTeX source code. Image URLs should be embedded directly in \\includegraphics{...}.")

@tool(
    "generate_latex_report_as_pdf",
    description="Compiles LaTeX to PDF. Automatically downloads remote image URLs found in the code, compiles, and returns the PDF URL.",
    args_schema=ReportInput,
)
def generate_latex_report_as_pdf(latex_content: str):
    """
    1. Scans latex_content for remote URLs (http/https) inside \includegraphics.
    2. Downloads them to a temporary directory.
    3. Replaces remote URLs with local filenames in the LaTeX source.
    4. Compiles with pdflatex.
    5. Uploads the final PDF to Firebase.
    6. Cleans up all temp files.
    """
    
    # 1. Validation
    if shutil.which("pdflatex") is None:
        return "Error: 'pdflatex' executable not found. Please install 'texlive-latex-extra'."

    # 2. Create Temporary Environment
    # logic: everything inside this 'with' block is deleted automatically when done
    with tempfile.TemporaryDirectory() as temp_dir:
        
        # --- Internal Helper: Download & Swap Images ---
        def replace_remote_image_urls(match):
            # match.group(1) = \includegraphics[options]
            # match.group(2) = The URL (https://...)
            prefix = match.group(1)
            url = match.group(2)
            
            try:
                # Determine extension
                ext = ".png" # fallback
                if ".jpg" in url.lower() or ".jpeg" in url.lower(): ext = ".jpg"
                if ".pdf" in url.lower(): ext = ".pdf"
                
                # Create unique local filename
                local_filename = f"img_{uuid.uuid4().hex[:8]}{ext}"
                local_path = os.path.join(temp_dir, local_filename)
                
                # Download
                print(f"Downloading image for report: {url[:30]}...")
                response = requests.get(url, timeout=15)
                
                if response.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(response.content)
                    # Return the LaTeX string using the LOCAL filename
                    return f'{prefix}{{{local_filename}}}'
                else:
                    return f"\\textbf{{[Image Download Error: {response.status_code}]}}"
            except Exception as e:
                print(f"Image processing error: {e}")
                return f"\\textbf{{[Image Error]}}"

        # Regex to capture \includegraphics[...]{http...}
        # Handles optional arguments [] and brace {} containing http/s
        pattern = r'(\\includegraphics(?:\[.*?\])?)\{(https?://[^}]+)\}'
        
        try:
            # Execute the replacement
            processed_latex = re.sub(pattern, replace_remote_image_urls, latex_content)
        except Exception as e:
            return f"Error processing embedded images: {str(e)}"

        # 3. Write LaTeX to Disk
        tex_path = os.path.join(temp_dir, "report.tex")
        pdf_filename = "report.pdf"
        pdf_path = os.path.join(temp_dir, pdf_filename)

        try:
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(processed_latex)
        except Exception as e:
            return f"Error writing .tex file: {str(e)}"

        # 4. Compile (Run twice for layout/references)
        cmd = [
            "pdflatex", 
            "-interaction=nonstopmode", 
            "-halt-on-error",
            "-no-shell-escape",
            "-output-directory", temp_dir, 
            tex_path
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
        except subprocess.TimeoutExpired:
            return "Error: LaTeX compilation timed out."
        except subprocess.CalledProcessError as e:
            # Decode log to show user the error
            full_log = e.stdout.decode("latin-1", errors="ignore")
            return f"LaTeX Compilation Failed. Log tail: {full_log[-600:]}"

        # 5. Upload to Firebase
        if os.path.exists(pdf_path):
            try:
                unique_id = uuid.uuid4().hex[:8]
                timestamp = int(time.time())
                destination = f"reports/report_{timestamp}_{unique_id}.pdf"
                
                # Assuming 'firebase_storage' is your globally initialized wrapper
                with open(pdf_path, "rb") as file_obj:
                    url = firebase_storage.upload_file(
                        file_obj=file_obj,
                        destination_path=destination,
                        content_type="application/pdf",
                    )
                
                return {
                    "status": "success",
                    "pdf_url": url,
                    "latex_source": latex_content,
                    "message": "Report generated successfully."
                }
            except Exception as e:
                return f"Error uploading PDF to storage: {str(e)}"
        else:
            return "Error: PDF file was not generated."


AVAILABLE_TOOLS = [
    download_file_as_dataframe,
    backtesting_tool,
    generate_latex_report_as_pdf
]
