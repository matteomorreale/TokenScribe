"""
TokenScribe — Flask Application Factory
Author: Matteo Morreale
"""

import os
from flask import Flask
from config import config_map, TokenScribeConfig
from app.models.database import DatabaseManager


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

    # Register blueprints
    from app.controllers.study_controller import study_bp
    from app.controllers.prompt_controller import prompt_bp
    from app.controllers.translation_controller import translation_bp
    from app.controllers.experiment_controller import experiment_bp
    from app.controllers.settings_controller import settings_bp
    from app.controllers.report_controller import report_bp

    app.register_blueprint(study_bp)
    app.register_blueprint(prompt_bp)
    app.register_blueprint(translation_bp)
    app.register_blueprint(experiment_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(report_bp)

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
            "app_version": "1.0.0",
            "app_author": "Matteo Morreale",
        }

    return app
