"""
TokenScribe — Application Entry Point
Author: Matteo Morreale

Usage:
    python run.py
    FLASK_ENV=production python run.py
"""

import os
from app import create_app

env = os.environ.get("FLASK_ENV", "development")
app = create_app(env)

if __name__ == "__main__":
    host = os.environ.get("TOKENSCRIBE_HOST", "0.0.0.0")
    port = int(os.environ.get("TOKENSCRIBE_PORT", 5000))
    app.run(host=host, port=port, debug=(env == "development"))
