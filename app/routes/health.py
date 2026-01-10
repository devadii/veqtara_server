"""Health check and status endpoints"""
from flask import Blueprint, jsonify, current_app
from app.extensions import firebase_storage, firestore_db
import os

bp = Blueprint('health', __name__)

@bp.route('/check', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Check Firebase Storage
        firebase_storage_status = "connected" if firebase_storage.bucket else "not_configured"
        
        # Check Firestore
        firestore_status = "connected" if firestore_db.db else "not_configured"
        
        # Check OpenAI
        openai_status = "configured" if current_app.config.get('OPENAI_API_KEY') else "not_configured"
        
        return jsonify({
            'status': 'healthy',
            'services': {
                'firebase_storage': firebase_storage_status,
                'firestore': firestore_status,
                'openai': openai_status
            },
            'version': '1.0.0'
        })
    
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

