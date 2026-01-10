import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # This block ONLY runs if you execute "python run.py"
    # It does NOT run if Gunicorn imports this file.
    
    # Check env var, default to True if running directly
    debug_mode = os.environ.get('FLASK_DEBUG', '1') == '1'
    
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)