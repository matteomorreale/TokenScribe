"""
TokenScribe — Prompt Controller
Author: Matteo Morreale
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import PromptModel, StudyModel, TranslationModel, SelectionScoreModel
from app.services import ScoringService

prompt_bp = Blueprint("prompt", __name__)

_scorer = ScoringService()


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _ssm() -> SelectionScoreModel:
    return SelectionScoreModel(current_app.config["DB"])


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
        notes = request.form.get("notes", "").strip()
        analysis_type = request.form.get("analysis_type", "standard").strip()
        if analysis_type not in ("standard", "tsf"):
            analysis_type = "standard"
        if not base_text:
            flash("Prompt text is required.", "error")
            return render_template("prompts/form.html", study=study, prompt=None)
        prompt_id = _pm().create(study_id, base_text, category, notes, analysis_type)
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

    by_lang = {}
    for c in candidates:
        lid = c.get("language_id")
        if not lid:
            continue
        existing = by_lang.get(lid)
        if existing is None:
            by_lang[lid] = c
            continue
        c_status = c.get("status")
        e_status = existing.get("status")
        if e_status != "approved" and c_status == "approved":
            by_lang[lid] = c
            continue
        if e_status == "approved" and c_status != "approved":
            continue
        if e_status == "rejected" and c_status != "rejected":
            by_lang[lid] = c
            continue
        if (c.get("version") or 0) > (existing.get("version") or 0):
            by_lang[lid] = c

    baseline_by_lang = {
        lid: c
        for lid, c in by_lang.items()
        if c.get("status") != "rejected" and c.get("text")
    }
    pei_texts = [c["text"] for c in baseline_by_lang.values()]
    pei = (
        _scorer.compute_pei(pei_texts)
        if pei_texts
        else {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0}
    )
    pei_band = _scorer.pei_band(float(pei.get("pei") or 0.0))

    def _group_baseline_pei(key: str) -> dict:
        buckets = {}
        for c in baseline_by_lang.values():
            gv = (c.get(key) or "").strip()
            if not gv:
                continue
            buckets.setdefault(gv, []).append(c.get("text") or "")
        out = {}
        for gv, texts in buckets.items():
            if len(texts) < 2:
                continue
            out[gv] = _scorer.compute_pei(texts)
            out[gv]["pei_band"] = _scorer.pei_band(float(out[gv].get("pei") or 0.0))
        return out

    pei_script_groups = _group_baseline_pei("script_group")
    pei_morph_groups = _group_baseline_pei("morphology_group")

    baseline_text_by_lang = {lid: c["text"] for lid, c in baseline_by_lang.items()}
    baseline_pei_value = float(pei.get("pei") or 0.0)

    for c in candidates:
        metrics = _scorer.compute_structural_metrics(c.get("text") or "")
        c["char_length"] = metrics["char_length"]
        c["word_count"] = metrics["word_count"]
        c["token_count"] = metrics["token_count"]

        c["pei_with_candidate"] = None
        c["pei_with_cv_char_length"] = None
        c["pei_with_cv_word_count"] = None
        c["pei_with_cv_token_count"] = None
        c["pei_delta"] = None

        c["pei_script_group_baseline"] = None
        c["pei_script_group_with_candidate"] = None
        c["pei_script_group_delta"] = None
        c["pei_script_group_band"] = None

        c["pei_morphology_group_baseline"] = None
        c["pei_morphology_group_with_candidate"] = None
        c["pei_morphology_group_delta"] = None
        c["pei_morphology_group_band"] = None

        if c.get("status") == "rejected" or not c.get("text"):
            continue

        sim_text_by_lang = dict(baseline_text_by_lang)
        sim_text_by_lang[c["language_id"]] = c["text"]
        sim_texts = list(sim_text_by_lang.values())
        sim_pei = _scorer.compute_pei(sim_texts) if sim_texts else {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0}

        c["pei_with_candidate"] = sim_pei["pei"]
        c["pei_with_cv_char_length"] = sim_pei["cv_char_length"]
        c["pei_with_cv_word_count"] = sim_pei["cv_word_count"]
        c["pei_with_cv_token_count"] = sim_pei["cv_token_count"]
        c["pei_delta"] = round(float(sim_pei["pei"]) - baseline_pei_value, 6)

        script_group = (c.get("script_group") or "").strip()
        if script_group and script_group in pei_script_groups:
            group_lang_ids = [
                lid for lid, bc in baseline_by_lang.items() if (bc.get("script_group") or "").strip() == script_group
            ]
            sim_group_texts_by_lang = {lid: baseline_text_by_lang[lid] for lid in group_lang_ids if lid in baseline_text_by_lang}
            sim_group_texts_by_lang[c["language_id"]] = c["text"]
            sim_group_texts = list(sim_group_texts_by_lang.values())
            sim_group_pei = _scorer.compute_pei(sim_group_texts) if len(sim_group_texts) > 1 else {"pei": 0.0}
            baseline_group_pei = float(pei_script_groups[script_group].get("pei") or 0.0)
            c["pei_script_group_baseline"] = baseline_group_pei
            c["pei_script_group_with_candidate"] = float(sim_group_pei.get("pei") or 0.0)
            c["pei_script_group_delta"] = round(float(sim_group_pei.get("pei") or 0.0) - baseline_group_pei, 6)
            c["pei_script_group_band"] = _scorer.pei_band(float(sim_group_pei.get("pei") or 0.0))

        morphology_group = (c.get("morphology_group") or "").strip()
        if morphology_group and morphology_group in pei_morph_groups:
            group_lang_ids = [
                lid for lid, bc in baseline_by_lang.items() if (bc.get("morphology_group") or "").strip() == morphology_group
            ]
            sim_group_texts_by_lang = {lid: baseline_text_by_lang[lid] for lid in group_lang_ids if lid in baseline_text_by_lang}
            sim_group_texts_by_lang[c["language_id"]] = c["text"]
            sim_group_texts = list(sim_group_texts_by_lang.values())
            sim_group_pei = _scorer.compute_pei(sim_group_texts) if len(sim_group_texts) > 1 else {"pei": 0.0}
            baseline_group_pei = float(pei_morph_groups[morphology_group].get("pei") or 0.0)
            c["pei_morphology_group_baseline"] = baseline_group_pei
            c["pei_morphology_group_with_candidate"] = float(sim_group_pei.get("pei") or 0.0)
            c["pei_morphology_group_delta"] = round(float(sim_group_pei.get("pei") or 0.0) - baseline_group_pei, 6)
            c["pei_morphology_group_band"] = _scorer.pei_band(float(sim_group_pei.get("pei") or 0.0))

    magi_readiness = _ssm().get_readiness_by_prompts([prompt_id]).get(prompt_id, {})

    pei_saved_at = prompt.get("pei_saved_at")
    latest_approved_at = _tm().get_latest_approved_at(prompt_id)
    pei_stale = (not pei_saved_at) or bool(latest_approved_at and latest_approved_at > pei_saved_at)

    pending_count = sum(1 for c in candidates if c.get("status") == "candidate")
    magi_suggest = (
        pending_count > 0
        or (magi_readiness.get("approved_count", 0) > 0 and magi_readiness.get("magi_count", 0) == 0)
        or magi_readiness.get("magi_required_count", 0) > 0
    )

    return render_template(
        "prompts/detail.html",
        prompt=prompt,
        study=study,
        candidates=candidates,
        approved=approved,
        languages=languages,
        pei=pei,
        pei_band=pei_band,
        pei_count=len(pei_texts),
        pei_script_groups=pei_script_groups,
        pei_morph_groups=pei_morph_groups,
        magi_readiness=magi_readiness,
        pei_stale=pei_stale,
        pei_saved_at=pei_saved_at,
        pending_count=pending_count,
        magi_suggest=magi_suggest,
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
        notes = request.form.get("notes", "").strip()
        analysis_type = request.form.get("analysis_type", "standard").strip()
        if analysis_type not in ("standard", "tsf"):
            analysis_type = "standard"
        if not base_text:
            flash("Prompt text is required.", "error")
            return render_template("prompts/form.html", study=study, prompt=prompt)
        _pm().update(prompt_id, base_text, category, notes, analysis_type)
        flash("Prompt updated.", "success")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return render_template("prompts/form.html", study=study, prompt=prompt)


@prompt_bp.route("/prompts/<int:prompt_id>/pei/refresh", methods=["POST"])
def refresh_pei(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    approved = _tm().get_approved_by_prompt(prompt_id)
    texts = [c["text"] for c in approved if c.get("text")]
    if not texts:
        flash("No approved translations — PEI cannot be computed.", "warning")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    pei_result = _scorer.compute_pei(texts)
    _pm().save_pei_snapshot(
        prompt_id,
        pei=float(pei_result.get("pei") or 0.0),
        cv_char=float(pei_result.get("cv_char_length") or 0.0),
        cv_word=float(pei_result.get("cv_word_count") or 0.0),
        cv_token=float(pei_result.get("cv_token_count") or 0.0),
    )
    flash(
        f"PEI updated: {float(pei_result.get('pei') or 0.0):.4f} ({len(texts)} approved languages).",
        "success",
    )
    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))


@prompt_bp.route("/prompts/<int:prompt_id>/notes", methods=["POST"])
def update_notes(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    notes = request.form.get("notes", "").strip()
    _pm().update(prompt_id, prompt["base_text"], prompt["category"], notes, prompt.get("analysis_type", "standard"))
    flash("Notes saved.", "success")
    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))


@prompt_bp.route("/prompts/migrate-delimiters", methods=["POST"])
def migrate_delimiters():
    old_open = request.form.get("old_open", "<<<")
    old_close = request.form.get("old_close", ">>>")
    new_open = request.form.get("new_open", "<input>")
    new_close = request.form.get("new_close", "</input>")
    count = _pm().migrate_delimiters(old_open, old_close, new_open, new_close)
    flash(f"Migration completed: {count} prompts updated ({old_open}…{old_close} → {new_open}…{new_close}).", "success")
    return redirect(request.referrer or url_for("study.list_studies"))


@prompt_bp.route("/prompts/<int:prompt_id>/delete", methods=["POST"])
def delete_prompt(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if prompt:
        study_id = prompt["study_id"]
        _pm().delete(prompt_id)
        flash("Prompt deleted.", "success")
        return redirect(url_for("prompt.list_prompts", study_id=study_id))
    return redirect(url_for("study.list_studies"))
