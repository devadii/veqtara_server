# app/__init__.py
from flask import Flask
from flask_cors import CORS
from app.config import Config # Import the Config class
from app.extensions import firebase_storage, firestore_db
import logging

def create_app(config_class=Config): # Default to our Config class
    """Application factory pattern"""
    app = Flask(__name__)
    app.config.from_object(config_class) # Load configuration from the Config class
    
    # Initialize extensions
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    firebase_storage.init_app(app)
    firestore_db.init_app(app)
    
    # Register blueprints
    from app.routes.chat import bp as chat_bp
    from app.routes.health import bp as health_bp
    
    app.register_blueprint(chat_bp, url_prefix='/api/chat')
    app.register_blueprint(health_bp, url_prefix='/api/health')
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )
    
    return app