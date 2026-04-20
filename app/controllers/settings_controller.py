"""
TokenScribe — Settings Controller
Author: Matteo Morreale
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import SettingsModel

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

API_KEY_FIELDS = [
    ("openai_api_key", "OpenAI API Key"),
    ("anthropic_api_key", "Anthropic API Key"),
    ("google_api_key", "Google Gemini API Key"),
    ("deepseek_api_key", "DeepSeek API Key"),
    ("meta_api_key", "Meta (Together AI) API Key"),
    ("qwen_api_key", "Qwen (DashScope) API Key"),
    ("mistral_api_key", "Mistral API Key"),
]


def _stm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"])


@settings_bp.route("/")
def settings_dashboard():
    stm = _stm()
    current_settings = stm.get_all()
    providers = stm.get_all_providers()
    models_by_provider = {}
    for p in providers:
        models_by_provider[p["id"]] = stm.get_models_by_provider(p["id"])
    languages = stm.get_all_languages()
    writing_systems = stm.get_all_writing_systems()
    return render_template(
        "settings/dashboard.html",
        current_settings=current_settings,
        api_key_fields=API_KEY_FIELDS,
        providers=providers,
        models_by_provider=models_by_provider,
        languages=languages,
        writing_systems=writing_systems,
    )


@settings_bp.route("/api-keys", methods=["POST"])
def save_api_keys():
    stm = _stm()
    data = {}
    for key, _ in API_KEY_FIELDS:
        value = request.form.get(key, "").strip()
        if value:
            data[key] = value
    stm.set_many(data)
    flash("API keys saved.", "success")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/models", methods=["POST"])
def update_models():
    stm = _stm()
    model_id = request.form.get("model_id", type=int)
    cost_in = request.form.get("cost_per_input_token", type=float, default=0.0)
    cost_out = request.form.get("cost_per_output_token", type=float, default=0.0)
    is_active = 1 if request.form.get("is_active") else 0
    if model_id:
        stm.update_model_costs(model_id, cost_in, cost_out, is_active)
        flash("Model configuration updated.", "success")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/models/add", methods=["POST"])
def add_model():
    stm = _stm()
    provider_id = request.form.get("provider_id", type=int)
    name = request.form.get("model_name", "").strip()
    context_window = request.form.get("context_window", type=int, default=0)
    if provider_id and name:
        stm.add_model(provider_id, name, context_window)
        flash(f'Model "{name}" added.', "success")
    else:
        flash("Provider and model name are required.", "error")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/languages/add", methods=["POST"])
def add_language():
    stm = _stm()
    name = request.form.get("lang_name", "").strip()
    code = request.form.get("lang_code", "").strip()
    ws_id = request.form.get("writing_system_id", type=int)
    if name and code and ws_id:
        stm.add_language(name, code, ws_id)
        flash(f'Language "{name}" added.', "success")
    else:
        flash("All language fields are required.", "error")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/reset-db", methods=["POST"])
def reset_database():
    confirm = request.form.get("confirm_reset", "")
    if confirm != "RESET":
        flash('Type "RESET" to confirm database reset.', "error")
        return redirect(url_for("settings.settings_dashboard"))
    db = current_app.config["DB"]
    db.reset()
    flash("Database has been reset and re-seeded.", "success")
    return redirect(url_for("settings.settings_dashboard"))
