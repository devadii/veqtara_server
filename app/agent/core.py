import os
from typing import Any, Dict, List, TypedDict, Annotated, Optional
from pprint import pp
import json
from app.agent.tools import AVAILABLE_TOOLS, download_file_as_dataframe, backtesting_tool, generate_latex_report_as_pdf
from langchain_groq import ChatGroq
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from app.config import Config 

config = Config()

# LLM & TOOL BINDING
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.0,
    api_key=config.GROQ_API_KEY,
)
llm_with_tools = llm.bind_tools(AVAILABLE_TOOLS)

# AGENT STATE DEFINITION
class AgentState(TypedDict):
    """
    The state of the conversation.
    """
    # 'add_messages' ensures we keep the history (user -> ai -> tool -> ai)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # This is where we store the "Data" separate from messages so other tools can access it and we can send data to the UI also. 
    data_store: Optional[List[Dict[str, Any]]]
    output: Optional[List[Dict[str, Any]]]

# GRAPH NODES
def call_model_node(state: AgentState) -> Dict[str, Any]:
    """
    The primary node that calls the LLM and will decide on tool usage.
    """

    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def call_tool_node(state: AgentState) -> Dict[str, Any]:

    last_message: AIMessage = state["messages"][-1]
    tool_responses: List[ToolMessage] = []
    state_update: Dict[str, Any] = {"data_store": {}, "output": {}}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_id = tool_call["id"]
        tool_args = tool_call["args"]

        content = ""

        if tool_name == "download_file_as_dataframe":

            result = download_file_as_dataframe.invoke(tool_args)
            df = result.get("records", [])
            state_update["data_store"]["df"] = df
            content = f"Success: {result['message']}."

        elif tool_name == "generate_latex_report_as_pdf":
            
            result = generate_latex_report_as_pdf.invoke(tool_args)
            
            if isinstance(result, dict) and result.get("status") == "success":
                pdf_url = result.get("pdf_url")
                content = f"Report generated successfully. URL: {pdf_url}"
                latex_source = result.get("latex_source", "")
                
                # Add to output for Frontend to render
                state_update["output"] = [{
                    "type": "pdf_url", 
                    "url": pdf_url, 
                    "latex_source": latex_source,
                    "label": "Financial Report"
                }]
            else:
                content = f"Failed to generate report: {result}"

        elif tool_name in ["backtesting_tool"]:
            
            downloaded_df = (state.get("data_store") or {}).get("df")

            if not downloaded_df:
                content = "Error: No data loaded. Tell the user there's some error in downloading the file."

            else:
                
                if tool_name == "backtesting_tool":
                    result = backtesting_tool.invoke({"records": downloaded_df})
                    metrics = result.get("metrics", {})
                    plot_image_url = result.get("url", "N/A")
                    content = f"Backtesting Summary:\n{metrics}\n"

                    # Here's we are adding plot urls in output and the way we are adding that how it will be saved in firestore and UI expects same format
                    state_update["output"] = [{"type": "image_urls", "urls": [{"label": "Backtesting Plot", "url": plot_image_url}]}]
                
        else:
            content = "Error: Unknown tool."

        tool_responses.append(
            ToolMessage(content=content, tool_call_id=tool_id)
        )

    return {
        "messages": tool_responses,
        **state_update
    }


# ROUTER
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "call_tool"
    return END


# BUILD THE STATE GRAPH
workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model_node)
workflow.add_node("tools", call_tool_node)

workflow.set_entry_point("agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "call_tool": "tools",
        END: END,
    },
)

workflow.add_edge("tools", "agent")

agent = workflow.compile()
