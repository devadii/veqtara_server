import os
import logging
import json
import base64
from typing import List, Dict, Optional, Any
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)


class FirestoreService:
    """Firestore service for user ↔ bot chat with multiple conversations."""

    def __init__(self, app=None):
        self.app = app
        self.db = None

        if app is not None:
            self.init_app(app)

    # ------------------------------------------------------
    # INIT
    # ------------------------------------------------------

    def init_app(self, app):
        """Initialize Firestore with credentials from Base64 Environment Variable."""
        self.app = app
        try:
            # Check if Firebase App is already initialized (e.g., by StorageService)
            if not firebase_admin._apps:
                cred = None
                
                # ONLY try Base64 Environment Variable
                firebase_base64 = os.environ.get("FIREBASE_CREDENTIALS_BASE64")
                print("firebase_base64",firebase_base64)
                
                if firebase_base64:
                    try:
                        logger.info("[Firestore] Loading credentials from Base64 ENV...")
                        decoded_json = base64.b64decode(firebase_base64).decode('utf-8')
                        cred_dict = json.loads(decoded_json)
                        cred = credentials.Certificate(cred_dict)
                    except Exception as e:
                        logger.error(f"[Firestore] Failed to decode Base64 credentials: {e}")
                        return # Stop initialization if Base64 fails
                else:
                    logger.warning("[Firestore] FIREBASE_CREDENTIALS_BASE64 not found. Firestore Service Disabled.")
                    self.db = None # Explicitly set db to None if credentials not found
                    return # Stop initialization if Base64 ENV is missing

                # Initialize App (bucket is optional for Firestore, but good practice if available)
                bucket_name = app.config.get('FIREBASE_STORAGE_BUCKET')
                options = {'storageBucket': bucket_name} if bucket_name else {}
                
                firebase_admin.initialize_app(cred, options)
                logger.info("[Firestore] Admin SDK initialized successfully.")
            
            else:
                logger.info("[Firestore] Admin SDK already initialized. Using existing app.")

            self.db = firestore.client()
            logger.info("[Firestore] Client connected successfully")

        except Exception as e:
            logger.error(f"[Firestore] Failed to initialize: {e}")
            self.db = None # Ensure db is None on any initialization failure

    # ------------------------------------------------------
    # FIRESTORE PATH HELPERS
    # ------------------------------------------------------

    def _conversation_ref(self, user_id: str, conversation_id: str):
        if not self.db:
            raise RuntimeError("Firestore not initialized. Call init_app first.")
        return (
            self.db.collection("users")
            .document(user_id)
            .collection("conversations")
            .document(conversation_id)
        )

    def _messages_ref(self, user_id: str, conversation_id: str):
        if not self.db:
            raise RuntimeError("Firestore not initialized. Call init_app first.")
        return (
            self._conversation_ref(user_id, conversation_id)
            .collection("messages")
        )

    # ------------------------------------------------------
    # MESSAGES
    # ------------------------------------------------------

    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: List[Dict[str, Any]],
    ) -> str:
        """
        Add a message to a specific conversation.
        """

        if not self.db:
            raise RuntimeError("Firestore service is not initialized.")

        message_data = {
            "role": role,
            "content": content,
            "createdAt": firestore.SERVER_TIMESTAMP
        }

        # Store message
        ref = self._messages_ref(user_id, conversation_id)
        doc_ref, _ = ref.add(message_data)

        # Update conversation metadata
        preview = ""
        # If content has text, use it as preview
        if content and isinstance(content, list) and len(content) > 0:
             # Basic check for first block being text
             if content[0].get("type") == "text":
                 preview = content[0].get("text", "")[:100]

        self._conversation_ref(user_id, conversation_id).set(
            {
                "last_message": preview,
                "updatedAt": firestore.SERVER_TIMESTAMP
            },
            merge=True
        )

        return None

    def get_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """Get recent N messages for a conversation."""

        if not self.db:
            raise RuntimeError("Firestore service is not initialized.")

        ref = (
            self._messages_ref(user_id, conversation_id)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )

        docs = list(ref.stream())

        # Return in chronological order
        messages = []
        for doc in reversed(docs):
            msg = doc.to_dict()
            msg["id"] = doc.id
            messages.append(msg)

        return messages