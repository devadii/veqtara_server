"""Flask extensions initialization"""
from app.services.firebase_storage import FirebaseStorageService
from app.services.firestore_service import FirestoreService

firebase_storage = FirebaseStorageService()
firestore_db = FirestoreService()

