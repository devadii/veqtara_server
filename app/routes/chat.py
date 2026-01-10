"""Chat routes: message endpoint for the financial agent."""

from flask import Blueprint, request, jsonify
from app.extensions import firestore_db
from app.utils.auth import require_firebase_auth
from app.utils.logger import get_logger
from langchain.messages import HumanMessage, AIMessage, SystemMessage
from app.agent.core import agent
from app.agent.prompts import SYSTEM_PROMPT

logger = get_logger("chat")
bp = Blueprint("chat", __name__)

# Singleton financial agent

@bp.route("/message", methods=["POST"])
@require_firebase_auth
def handle_message():
    try:
        # Get the request payload
        request_payload = request.get_json(silent=True) or {}

        # Hardcoded user ID for testing; replace with auth when ready
        user_id = request.user.get("uid")
        # user_id = "KyOR9xLmhZSbTF96fAAWpr0CWuH3"
        conversation_id = request_payload.get("conversation_id")
        incoming_messages = request_payload.get("messages", [])

        # Validate input
        if not conversation_id:
            return jsonify({"error": "conversation_id is required"}), 400
        if not incoming_messages:
            return jsonify({"error": "messages array is required"}), 400

        # Get the first message in the array
        user_message = incoming_messages[0]
        content_blocks = user_message.get("content", [])

        # Extract user text and uploaded file URLs
        user_text = " ".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        ).strip()

        uploaded_file_urls = [
            block.get("file_url")
            for block in content_blocks
            if block.get("type") in ("file", "file_url")
        ]

        # Fetch conversation history 
        history_documents = firestore_db.get_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=10
        )
        
        # Convert Firestore history to LangChain message objects
        conversation_history = []

        for doc in history_documents:
            role = doc["role"]
            doc_content = doc.get("content", [])

            # 1. Flatten text from content blocks
            flattened_text = " ".join(
                block.get("text", "") for block in doc_content if block.get("type") == "text"
            ).strip()

            # 2. Collect image URLs
            image_urls_blocks = [
                block for block in doc_content if block.get("type") == "image_urls"
            ]

            urls_text = ""
            if image_urls_blocks:
                urls_text_list = []
                for img_block in image_urls_blocks:
                    for u in img_block.get("urls", []):
                        urls_text_list.append(f"{u.get('label')}: {u.get('url')}")
                urls_text = "\n".join(urls_text_list)

            # 3. [NEW] Collect PDF URLs and LaTeX Source
            pdf_url_blocks = [
                block for block in doc_content if block.get("type") == "pdf_url"
            ]

            pdf_text = ""
            if pdf_url_blocks:
                pdf_entries = []
                for block in pdf_url_blocks:
                    p_url = block.get("url", "N/A")
                    p_label = block.get("label", "Financial Report")
                    p_source = block.get("latex_source", "")

                    # We wrap the source in markdown code blocks so the LLM understands it's code
                    entry = (
                        f"[{p_label}]\n"
                        f"URL: {p_url}\n"
                        f"LaTeX Source:\n```latex\n{p_source}\n```"
                    )
                    pdf_entries.append(entry)
                pdf_text = "\n\n".join(pdf_entries)

            # 4. Combine everything
            combined_text = flattened_text
            
            if urls_text:
                combined_text += "\n\n[Images/Plots]\n" + urls_text
            
            if pdf_text:
                combined_text += "\n\n[Generated Reports]\n" + pdf_text

            if not combined_text:
                continue
            
            if role == "user":
                conversation_history.append(HumanMessage(content=combined_text))
            else:
                conversation_history.append(AIMessage(content=combined_text))

        # Append the current user message (in-memory only)
        
        agent_input_text = user_text
        if uploaded_file_urls:
            agent_input_text += "\n\n[SYSTEM NOTE: User uploaded files: " + ", ".join(uploaded_file_urls or []) + "]"

        conversation_history.append(HumanMessage(content=agent_input_text))

        agent_input = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                *conversation_history
            ],
            "data_store": None,
            "output": None
        }

        # Invoke the agent
        agent_state = agent.invoke(agent_input, {"recursion_limit": 6})

        assistant_text = agent_state["messages"][-1].content
        output_data = agent_state["output"] or []

        assistant_blocks = [{"type": "text", "text": f"{assistant_text}"}]

        if output_data: 
            assistant_blocks.extend(output_data)

        # Save user and assistant messages to Firestore AFTER agent response
        firestore_db.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=content_blocks,
        )

        firestore_db.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_blocks,
        )

        return jsonify({
            "response": assistant_blocks,
            "conversation_id": conversation_id
        })

    except Exception:
        logger.exception("Chat handler error")
        return jsonify({"error": "internal server error"}), 500
