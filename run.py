"""
TokenScribe — Application Entry Point
Author: Matteo Morreale

Usage:
    python run.py
    FLASK_ENV=production python run.py
"""

import os
from dotenv import load_dotenv
from app import create_app

load_dotenv()

env = os.environ.get("FLASK_ENV", "development")
app = create_app(env)

if __name__ == "__main__":
    # Loopback by default: the app has no login. The Werkzeug debugger runs code, so it is opt-in.
    host = os.environ.get("TOKENSCRIBE_HOST", "127.0.0.1")
    port = int(os.environ.get("TOKENSCRIBE_PORT", 5000))
    app.run(host=host, port=port, debug=os.environ.get("TOKENSCRIBE_DEBUG") == "1")
