import os
import uuid
import urllib.parse
import logging
import json
import base64
from typing import Optional, BinaryIO, Dict, Any
import firebase_admin
from firebase_admin import credentials, storage

# Configure logger
logger = logging.getLogger(__name__)

class FirebaseStorageService:
    """
    Service for interacting with Firebase Storage using Secure Download Tokens.
    """
    
    def __init__(self, app: Optional[Any] = None) -> None:
        self.app = app
        self.bucket = None
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Any) -> None:
        """
        Initialize Firebase Storage with credentials from Base64 Environment Variable.
        """
        self.app = app
        try:
            bucket_name = app.config.get('FIREBASE_STORAGE_BUCKET')
            
            if not bucket_name:
                logger.warning("[Firebase Storage] FIREBASE_STORAGE_BUCKET is not set. Service disabled.")
                self.bucket = None
                return

            # Check if Firebase App is already initialized (e.g., by FirestoreService)
            if not firebase_admin._apps:
                cred = None
                
                # ONLY try Base64 Environment Variable
                firebase_base64 = os.environ.get("FIREBASE_CREDENTIALS_BASE64")
                
                if firebase_base64:
                    try:
                        logger.info("[Firebase Storage] Loading credentials from Base64 ENV...")
                        decoded_json = base64.b64decode(firebase_base64).decode('utf-8')
                        cred_dict = json.loads(decoded_json)
                        cred = credentials.Certificate(cred_dict)
                    except Exception as e:
                        logger.error(f"[Firebase Storage] Failed to decode Base64 credentials: {e}")
                        self.bucket = None
                        return # Stop initialization if Base64 fails
                else:
                    logger.warning("[Firebase Storage] FIREBASE_CREDENTIALS_BASE64 not found. Storage Service Disabled.")
                    self.bucket = None # Explicitly set bucket to None if credentials not found
                    return # Stop initialization if Base64 ENV is missing

                # Initialize the App
                firebase_admin.initialize_app(cred, {
                    'storageBucket': bucket_name
                })
                logger.info("[Firebase Storage] Admin SDK initialized successfully.")
            
            else:
                logger.info("[Firebase Storage] Admin SDK already initialized. Using existing app.")

            # Connect to the bucket
            self.bucket = storage.bucket()
            logger.info(f"[Firebase Storage] Connected to bucket: {bucket_name}")

        except Exception as e:
            logger.exception(f"[Firebase Storage] Initialization failed: {str(e)}")
            self.bucket = None # Ensure bucket is None on any initialization failure
    
    def _construct_token_url(self, blob_path: str, token: str) -> str:
        """Helper to construct the Firebase Storage URL with a download token."""
        if not self.bucket:
            raise RuntimeError("Firebase Storage not initialized. Call init_app first.")
        encoded_path = urllib.parse.quote(blob_path, safe='')
        return (
            f"https://firebasestorage.googleapis.com/v0/b/{self.bucket.name}/o/"
            f"{encoded_path}?alt=media&token={token}"
        )

    def upload_file(self, 
                    file_obj: BinaryIO, 
                    destination_path: str, 
                    content_type: Optional[str] = None) -> Optional[str]:
        """Uploads a file and returns a secure, persistent URL."""
        if not self.bucket:
            logger.error("[Firebase Storage] Attempted upload but storage is not initialized.")
            raise RuntimeError("Firebase Storage service is not initialized.")
        
        try:
            logger.debug(f"[Firebase Storage] Starting upload to: {destination_path}")
            
            blob = self.bucket.blob(destination_path)
            if content_type:
                blob.content_type = content_type
            
            # Generate UUID token
            download_token = str(uuid.uuid4())
            blob.metadata = {"firebaseStorageDownloadTokens": download_token}
            
            file_obj.seek(0)
            blob.upload_from_file(file_obj)
            
            public_url = self._construct_token_url(destination_path, download_token)
            
            logger.info(f"[Firebase Storage] Upload success: {destination_path}")
            return public_url

        except Exception as e:
            logger.exception(f"[Firebase Storage] Upload failed for {destination_path}")
            raise
    
    def download_file(self, source_path: str) -> Optional[bytes]:
        """Downloads a file as bytes."""
        if not self.bucket:
            raise RuntimeError("Firebase Storage service is not initialized.")
        
        try:
            logger.debug(f"[Firebase Storage] Downloading file: {source_path}")
            blob = self.bucket.blob(source_path)
            data = blob.download_as_bytes()
            return data
        except Exception as e:
            logger.exception(f"[Firebase Storage] Download failed for {source_path}")
            raise
    
    def delete_file(self, file_path: str) -> bool:
        """Deletes a file."""
        if not self.bucket:
            raise RuntimeError("Firebase Storage service is not initialized.")
        
        try:
            blob = self.bucket.blob(file_path)
            blob.delete()
            logger.info(f"[Firebase Storage] Deleted file: {file_path}")
            return True
        except Exception as e:
            logger.warning(f"[Firebase Storage] Delete failed for {file_path}: {e}")
            return False
    
    def get_public_url(self, file_path: str) -> Optional[str]:
        """Retrieves or creates a secure Download URL."""
        if not self.bucket:
            raise RuntimeError("Firebase Storage service is not initialized.")
        
        try:
            blob = self.bucket.blob(file_path)
            blob.reload()
            
            if not blob.exists():
                return None

            metadata = blob.metadata or {}
            token = metadata.get("firebaseStorageDownloadTokens")

            if not token:
                token = str(uuid.uuid4())
                metadata["firebaseStorageDownloadTokens"] = token
                blob.metadata = metadata
                blob.patch()
            
            return self._construct_token_url(file_path, token)

        except Exception as e:
            logger.exception(f"[Firebase Storage] Failed to retrieve URL for {file_path}")
            return None