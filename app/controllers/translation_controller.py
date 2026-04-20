"""
TokenScribe — Translation Controller
Author: Matteo Morreale
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from app.models import PromptModel, TranslationModel, StudyModel
from app.services import ScoringService

translation_bp = Blueprint("translation", __name__)

_scorer = ScoringService()


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])


@translation_bp.route("/prompts/<int:prompt_id>/translations")
def list_translations(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    languages = _tm().get_all_languages()
    return render_template(
        "translations/list.html",
        prompt=prompt,
        study=study,
        candidates=candidates,
        languages=languages,
    )


@translation_bp.route("/prompts/<int:prompt_id>/translations/new", methods=["GET", "POST"])
def new_translation(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    languages = _tm().get_all_languages()
    if request.method == "POST":
        language_id = request.form.get("language_id", type=int)
        text = request.form.get("text", "").strip()
        if not language_id or not text:
            flash("Language and translation text are required.", "error")
            return render_template(
                "translations/form.html",
                prompt=prompt, study=study, languages=languages
            )
        cid = _tm().create_candidate(prompt_id, language_id, text)
        flash("Translation candidate added.", "success")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))
    return render_template(
        "translations/form.html",
        prompt=prompt, study=study, languages=languages
    )


@translation_bp.route("/translations/<int:candidate_id>/score", methods=["POST"])
def score_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    prompt = _pm().get_by_id(candidate["prompt_id"])
    back_translation = request.form.get("back_translation", "").strip() or None
    try:
        scores = _scorer.score_translation(
            original=prompt["base_text"],
            translation=candidate["text"],
            back_translation=back_translation,
        )
        tm.upsert_score(candidate_id, scores["dsf"], scores["rtf"], scores["sfs"])
        flash(
            f'SFS computed: {scores["sfs"]:.4f} (DSF={scores["dsf"]:.4f}, RTF={scores["rtf"]:.4f})',
            "success",
        )
    except Exception as e:
        flash(f"Scoring error: {e}", "error")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/approve", methods=["POST"])
def approve_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    tm.approve(candidate["prompt_id"], candidate["language_id"], candidate_id)
    flash("Translation approved.", "success")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/reject", methods=["POST"])
def reject_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    tm.update_status(candidate_id, "rejected")
    flash("Translation rejected.", "success")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/delete", methods=["POST"])
def delete_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if candidate:
        prompt_id = candidate["prompt_id"]
        tm.delete_candidate(candidate_id)
        flash("Translation candidate deleted.", "success")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))
    return redirect(url_for("study.list_studies"))


@translation_bp.route("/prompts/<int:prompt_id>/translations/compare")
def compare_translations(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    approved = _tm().get_approved_by_prompt(prompt_id)
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    return render_template(
        "translations/compare.html",
        prompt=prompt,
        study=study,
        approved=approved,
        candidates=candidates,
    )
