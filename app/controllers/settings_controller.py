"""
TokenScribe — Settings Controller
Author: Matteo Morreale
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import SettingsModel, StudyModel, PromptModel
from app.services import BatteryService

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

API_KEY_FIELDS = [
    ("openai_api_key", "OpenAI API Key"),
    ("anthropic_api_key", "Anthropic API Key"),
    ("google_api_key", "Google Gemini API Key"),
    ("deepseek_api_key", "DeepSeek API Key"),
    ("meta_api_key", "Meta (Together AI) API Key"),
    ("qwen_api_key", "Qwen (DashScope) API Key"),
    ("mistral_api_key", "Mistral API Key"),
    ("xai_api_key", "xAI (Grok) API Key"),
]

# Maps provider DB name → settings key for API key
PROVIDER_KEY_MAP = {
    "openai":    "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google":    "google_api_key",
    "deepseek":  "deepseek_api_key",
    "meta":      "meta_api_key",
    "qwen":      "qwen_api_key",
    "mistral":   "mistral_api_key",
    "xai":       "xai_api_key",
}

MAGI_JUDGE_KEYS = [
    ("magi_judge_balthasar_id", "Balthasar"),
    ("magi_judge_caspar_id",    "Caspar"),
    ("magi_judge_melchior_id",  "Melchior"),
]


def _stm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"], crypto=current_app.config.get("CRYPTO"))


def _study_model() -> StudyModel:
    return StudyModel(current_app.config["DB"])


def _prompt_model() -> PromptModel:
    return PromptModel(current_app.config["DB"])


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
    battery_status = BatteryService.get_status(_study_model())
    all_models = stm.get_all_models_flat()
    magi_judge_ids = stm.get_magi_judge_ids()
    configured_providers = {
        p for p, k in PROVIDER_KEY_MAP.items() if current_settings.get(k)
    }
    return render_template(
        "settings/dashboard.html",
        current_settings=current_settings,
        api_key_fields=API_KEY_FIELDS,
        providers=providers,
        models_by_provider=models_by_provider,
        languages=languages,
        writing_systems=writing_systems,
        battery_status=battery_status,
        all_models=all_models,
        magi_judge_ids=magi_judge_ids,
        magi_judge_keys=MAGI_JUDGE_KEYS,
        configured_providers=configured_providers,
    )


@settings_bp.route("/api-keys", methods=["POST"])
def save_api_keys():
    stm = _stm()
    data = {}
    for key, _ in API_KEY_FIELDS:
        value = request.form.get(key, "").strip()
        if value:
            data[key] = value
    qwen_region = request.form.get("qwen_region", "").strip()
    if qwen_region in ("china", "international"):
        data["qwen_region"] = qwen_region
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
    is_reasoning = 1 if request.form.get("is_reasoning") else 0
    if model_id:
        stm.update_model_costs(model_id, cost_in, cost_out, is_active, is_reasoning)
        flash("Model configuration updated.", "success")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/models/bulk", methods=["POST"])
def update_models_bulk():
    stm = _stm()
    model_ids = request.form.getlist("model_ids", type=int)
    for mid in model_ids:
        cost_in = request.form.get(f"cost_in_{mid}", type=float, default=0.0)
        cost_out = request.form.get(f"cost_out_{mid}", type=float, default=0.0)
        is_active = 1 if request.form.get(f"is_active_{mid}") else 0
        is_reasoning = 1 if request.form.get(f"is_reasoning_{mid}") else 0
        stm.update_model_costs(mid, cost_in, cost_out, is_active, is_reasoning)
    flash(f"{len(model_ids)} model(s) updated.", "success")
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


@settings_bp.route("/seed-battery", methods=["POST"])
def seed_battery():
    battery_name = request.form.get("battery_name", "").strip() or None
    results = BatteryService.seed(_study_model(), _prompt_model(), battery_name)
    created = [r for r in results if r["created"]]
    skipped = [r for r in results if not r["created"]]
    if created:
        names = ", ".join(f'"{r["name"]}"' for r in created)
        total_prompts = sum(r["prompts_added"] for r in created)
        flash(f"Seeded {len(created)} battery study{'ies' if len(created) != 1 else ''}: {names} ({total_prompts} prompts total).", "success")
    if skipped:
        names = ", ".join(f'"{r["name"]}"' for r in skipped)
        flash(f"Already present, skipped: {names}.", "info")
    if not created and not skipped:
        flash("No batteries matched the request.", "warning")
    return redirect(url_for("settings.settings_dashboard"))


@settings_bp.route("/magi-judges", methods=["POST"])
def save_magi_judges():
    stm = _stm()
    data = {}
    for key, _ in MAGI_JUDGE_KEYS:
        val = request.form.get(key, "").strip()
        if val:
            data[key] = val
    stm.set_many(data)
    flash("MAGI Judge Panel aggiornato.", "success")
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
