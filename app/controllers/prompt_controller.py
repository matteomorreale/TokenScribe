"""
TokenScribe — Prompt Controller
Author: Matteo Morreale
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import PromptModel, StudyModel, TranslationModel

prompt_bp = Blueprint("prompt", __name__)


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


@prompt_bp.route("/studies/<int:study_id>/prompts")
def list_prompts(study_id: int):
    study = _sm().get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    prompts = _pm().get_by_study(study_id)
    for p in prompts:
        p["translation_count"] = _pm().get_translation_count(p["id"])
    return render_template("prompts/list.html", study=study, prompts=prompts)


@prompt_bp.route("/studies/<int:study_id>/prompts/new", methods=["GET", "POST"])
def new_prompt(study_id: int):
    study = _sm().get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    if request.method == "POST":
        base_text = request.form.get("base_text", "").strip()
        category = request.form.get("category", "").strip()
        if not base_text:
            flash("Prompt text is required.", "error")
            return render_template("prompts/form.html", study=study, prompt=None)
        prompt_id = _pm().create(study_id, base_text, category)
        flash("Prompt created.", "success")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return render_template("prompts/form.html", study=study, prompt=None)


@prompt_bp.route("/prompts/<int:prompt_id>")
def detail_prompt(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    approved = _tm().get_approved_by_prompt(prompt_id)
    languages = _tm().get_all_languages()
    return render_template(
        "prompts/detail.html",
        prompt=prompt,
        study=study,
        candidates=candidates,
        approved=approved,
        languages=languages,
    )


@prompt_bp.route("/prompts/<int:prompt_id>/edit", methods=["GET", "POST"])
def edit_prompt(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    if request.method == "POST":
        base_text = request.form.get("base_text", "").strip()
        category = request.form.get("category", "").strip()
        if not base_text:
            flash("Prompt text is required.", "error")
            return render_template("prompts/form.html", study=study, prompt=prompt)
        _pm().update(prompt_id, base_text, category)
        flash("Prompt updated.", "success")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return render_template("prompts/form.html", study=study, prompt=prompt)


@prompt_bp.route("/prompts/<int:prompt_id>/delete", methods=["POST"])
def delete_prompt(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if prompt:
        study_id = prompt["study_id"]
        _pm().delete(prompt_id)
        flash("Prompt deleted.", "success")
        return redirect(url_for("prompt.list_prompts", study_id=study_id))
    return redirect(url_for("study.list_studies"))
