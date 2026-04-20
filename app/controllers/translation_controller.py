"""
TokenScribe — Translation Controller
Author: Matteo Morreale
"""

import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import PromptModel, TranslationModel, StudyModel, SettingsModel
from app.services import ScoringService, LLMService

translation_bp = Blueprint("translation", __name__)

_scorer = ScoringService()


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])

def _setm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"])


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

@translation_bp.route("/prompts/<int:prompt_id>/translations/ai", methods=["POST"])
def ai_translate(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))

    language_ids_raw = request.form.getlist("language_ids")
    try:
        language_ids = sorted({int(x) for x in language_ids_raw if str(x).strip()})
    except Exception:
        flash("Invalid language selection.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    sfs_min = request.form.get("sfs_min", type=float)
    sfs_max = request.form.get("sfs_max", type=float)
    if sfs_min is None or sfs_max is None:
        flash("SFS range is required.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    sfs_min = max(0.0, min(1.0, float(sfs_min)))
    sfs_max = max(0.0, min(1.0, float(sfs_max)))
    if sfs_min > sfs_max:
        sfs_min, sfs_max = sfs_max, sfs_min

    if not language_ids:
        flash("Select at least one target language.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    settings = _setm().get_all()
    llm = LLMService(settings)
    model_name = "gpt-5.4"

    languages = _tm().get_all_languages()
    lang_by_id = {l["id"]: l for l in languages}

    def _extract_json(text: str) -> dict | None:
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None

    created = 0
    warnings = []
    max_attempts = 4

    for language_id in language_ids:
        lang = lang_by_id.get(language_id)
        if not lang:
            warnings.append(f"Unknown language id: {language_id}")
            continue

        best = None
        best_dist = None
        last_score = None
        last_translation = None

        for attempt in range(1, max_attempts + 1):
            direction = ""
            if last_score is not None:
                if last_score < sfs_min:
                    direction = "Make the translation more literal and closer to the English wording and structure."
                elif last_score > sfs_max:
                    direction = "Make the translation more natural and slightly more paraphrastic while keeping exactly the same meaning and structure."

            prompt_text = (
                "Return ONLY valid JSON (no markdown) with keys translation and back_translation.\n"
                f"Target language: {lang['name']} ({lang['code']}).\n"
                "Constraints:\n"
                "- Preserve line breaks, punctuation, bracketed placeholders, and markers like <<< >>>.\n"
                "- Do not add explanations.\n"
                f"- Aim for an SFS between {sfs_min:.4f} and {sfs_max:.4f}.\n"
            )
            if direction:
                prompt_text += f"- Adjustment: {direction}\n"
            if last_translation and last_score is not None:
                prompt_text += (
                    f"\nPrevious translation (SFS={last_score:.4f}):\n"
                    f"{last_translation}\n"
                )
            prompt_text += (
                "\nText to translate (English) between <source> tags:\n"
                "<source>\n"
                f"{prompt['base_text']}\n"
                "</source>\n"
            )

            result = llm.call("openai", model_name, prompt_text)
            if not result.success:
                flash(f"AI error ({lang['name']}): {result.error}", "error")
                return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

            data = _extract_json(result.response_text or "")
            translation = ""
            back_translation = None
            if data and isinstance(data, dict):
                translation = str(data.get("translation", "")).strip()
                bt = str(data.get("back_translation", "")).strip()
                back_translation = bt if bt else None
            else:
                translation = (result.response_text or "").strip()

            if not translation:
                last_translation = translation
                last_score = 0.0
                continue

            scores = _scorer.score_translation(
                original=prompt["base_text"],
                translation=translation,
                back_translation=back_translation,
            )
            sfs = float(scores["sfs"])

            dist = 0.0
            if sfs < sfs_min:
                dist = sfs_min - sfs
            elif sfs > sfs_max:
                dist = sfs - sfs_max
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = (translation, scores)

            last_translation = translation
            last_score = sfs

            if sfs_min <= sfs <= sfs_max:
                break

        if not best:
            warnings.append(f"{lang['name']}: no output produced")
            continue

        translation_text, scores = best
        cid = _tm().create_candidate(prompt_id, language_id, translation_text)
        _tm().upsert_score(cid, scores["dsf"], scores["rtf"], scores["sfs"])
        created += 1

        if not (sfs_min <= float(scores["sfs"]) <= sfs_max):
            warnings.append(
                f"{lang['name']}: best SFS {float(scores['sfs']):.4f} outside [{sfs_min:.4f}, {sfs_max:.4f}]"
            )

    if created:
        flash(f"AI translations created: {created}", "success")
    if warnings:
        flash(" | ".join(warnings), "warning")

    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))


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
