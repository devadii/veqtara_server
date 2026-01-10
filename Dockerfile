FROM python:3.11-slim

# 1. Install System Dependencies & LaTeX
# We need 'texlive-latex-extra' because LLMs often use packages like
# 'geometry', 'tcolorbox', 'hyperref', etc.
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-fonts-extra \
    ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Ensure logs appear instantly
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "run:app"]
