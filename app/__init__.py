"""
TokenScribe — Flask Application Factory
Author: Matteo Morreale
"""

import os
from pathlib import Path
from flask import Flask
from config import config_map, TokenScribeConfig, BASE_DIR
from app.models.database import DatabaseManager
from app.models.queue_model import QueueModel
from app.services.log_service import LogService
from app.services.queue_service import QueueService
from app.services.crypto_service import CryptoService


def create_app(env: str = "default") -> Flask:
    """
    TokenScribe application factory.
    Creates and configures the Flask app, bootstraps the database,
    and registers all MVC blueprints.
    """
    app = Flask(
        __name__,
        template_folder="views/templates",
        static_folder="static",
    )

    # Load configuration
    cfg = config_map.get(env, config_map["default"])
    app.config.from_object(cfg)

    # Bootstrap database
    db = DatabaseManager(app.config["DATABASE_PATH"])
    db.bootstrap()
    app.config["DB"] = db

    # Encryption service for API keys stored in settings
    crypto_service = CryptoService(env_path=Path(BASE_DIR) / ".env")
    app.config["CRYPTO"] = crypto_service

    # Initialize async log service (daemon thread, non-blocking)
    log_service = LogService(app.config["DATABASE_PATH"])
    app.config["LOG_SERVICE"] = log_service

    # Recover stale 'running' items from a previous crash, then start queue worker
    QueueModel(db).recover_stale_running()
    queue_service = QueueService(db, log_service=log_service, crypto_service=crypto_service)
    queue_service.start()
    app.config["QUEUE_SERVICE"] = queue_service

    # Register blueprints
    from app.controllers.study_controller import study_bp
    from app.controllers.prompt_controller import prompt_bp
    from app.controllers.translation_controller import translation_bp
    from app.controllers.experiment_controller import experiment_bp
    from app.controllers.settings_controller import settings_bp
    from app.controllers.report_controller import report_bp
    from app.controllers.log_controller import log_bp
    from app.controllers.run_controller import run_bp

    app.register_blueprint(study_bp)
    app.register_blueprint(prompt_bp)
    app.register_blueprint(translation_bp)
    app.register_blueprint(experiment_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(log_bp)
    app.register_blueprint(run_bp)

    # Root redirect
    from flask import redirect, url_for

    @app.route("/")
    def index():
        return redirect(url_for("study.list_studies"))

    # Global template context
    @app.context_processor
    def inject_globals():
        return {
            "app_name": "TokenScribe",
            "app_version": "1.5.0",
            "app_author": "Matteo Morreale",
        }

    return app
