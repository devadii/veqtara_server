# utils/auth.py
from functools import wraps
from flask import request, jsonify
from firebase_admin import auth

def require_firebase_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing authorization"}), 401

        token = auth_header.split(" ")[1]

        try:
            decoded_token = auth.verify_id_token(token)
            request.user = decoded_token  # Attach user info to request
        except Exception as e:
            return jsonify({"error": "Invalid or expired token"}), 401

        return f(*args, **kwargs)

    return decorated
