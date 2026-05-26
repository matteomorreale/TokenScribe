"""
TokenScribe — Translation Controller
Author: Matteo Morreale
"""

import json
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, Response
from app.models import PromptModel, TranslationModel, StudyModel, SettingsModel, ExperimentModel, SelectionScoreModel
from app.services import ScoringService, MAGIService, get_magi_status as _get_magi_status

translation_bp = Blueprint("translation", __name__)

_scorer = ScoringService()


def _compute_magi_recommendations(magi_scores: list) -> list:
    """For each language, pick the candidate with the highest score_absolute."""
    by_lang: dict = {}
    for s in magi_scores:
        lid = s.get("language_id")
        if lid is None:
            continue
        by_lang.setdefault(lid, []).append(s)
    recommendations = []
    for candidates in by_lang.values():
        best = max(candidates, key=lambda c: (c.get("score_absolute") or -999.0))
        recommendations.append(best)
    recommendations.sort(key=lambda r: r.get("language_name") or "")
    return recommendations


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])

def _setm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"], crypto=current_app.config.get("CRYPTO"))

def _parse_candidate_ids() -> list[int]:
    raw_list = request.form.getlist("candidate_ids")
    raw_csv = request.form.get("candidate_ids", "")
    items = []
    if raw_list:
        items.extend(raw_list)
    if raw_csv and (not raw_list or "," in raw_csv):
        items.extend(raw_csv.split(","))
    out = []
    seen = set()
    for x in items:
        s = str(x).strip()
        if not s:
            continue
        try:
            cid = int(s)
        except Exception:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


@translation_bp.route("/prompts/<int:prompt_id>/translations")
def list_translations(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    languages = _tm().get_all_languages()
    em = ExperimentModel(current_app.config["DB"])
    magi_scores = SelectionScoreModel(current_app.config["DB"]).get_by_prompt(prompt_id)
    magi_by_cid = {s["candidate_id"]: s for s in magi_scores}
    for c in candidates:
        ms = magi_by_cid.get(c["id"])
        c["score_absolute"] = ms["score_absolute"] if ms else None
        c["score_rank"] = ms["score_rank"] if ms else None
        c["magi_required"] = bool(ms["magi_required"]) if ms else None
    settings = _setm().get_all()
    magi_status = _get_magi_status(settings, em)
    magi_recommendations = _compute_magi_recommendations(magi_scores)
    return render_template(
        "translations/list.html",
        prompt=prompt,
        study=study,
        candidates=candidates,
        languages=languages,
        magi_results=magi_scores,
        magi_status=magi_status,
        magi_recommendations=magi_recommendations,
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
    from app.services.translation_ai_service import run_ai_translate

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

    if not language_ids:
        flash("Select at least one target language.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    sfs_min = request.form.get("sfs_min", type=float)
    if sfs_min is None:
        flash("SFS minimum is required.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    sfs_min = max(0.0, min(1.0, float(sfs_min)))

    pei_profile = (request.form.get("pei_profile") or "homogeneous").strip()
    if pei_profile not in {"homogeneous", "moderate", "cross_script"}:
        pei_profile = "homogeneous"

    pei_max = request.form.get("pei_max", type=float)
    if pei_max is None:
        pei_max = 0.35 if pei_profile in {"moderate", "cross_script"} else 0.20
    pei_max = max(0.0, min(1.0, float(pei_max)))

    candidates_per_lang = max(1, min(5, request.form.get("candidates_per_lang", type=int) or 2))
    settings = _setm().get_all()
    log_svc = current_app.config.get("LOG_SERVICE")

    try:
        result = run_ai_translate(
            prompt=prompt,
            language_ids=language_ids,
            sfs_min=sfs_min,
            pei_profile=pei_profile,
            pei_max=pei_max,
            candidates_per_lang=candidates_per_lang,
            db=current_app.config["DB"],
            settings=settings,
            log_service=log_svc,
        )
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    created = result["created"]
    if not result["accepted"] and created:
        pei_v = float((result["accepted_pei"] or {}).get("pei") or 0.0)
        if pei_profile == "cross_script":
            flash(f"Set high-PEI but cross-script (PEI={pei_v:.4f}). Saving best candidates.", "warning")
        else:
            flash(f"Set not accepted (PEI={pei_v:.4f} > {pei_max:.4f} and/or SFS below {sfs_min:.4f}). Saving best candidates anyway.", "warning")

    if created:
        pei_value = float((result["accepted_pei"] or {}).get("pei") or 0.0)
        pei_band = _scorer.pei_band(pei_value)
        note = result["note"] or ("cross-script" if pei_profile == "cross_script" and pei_value > 0.35 else "")
        flash(
            f"AI translations created: {created} | PEI(set)={pei_value:.4f} ({pei_band}){(' — ' + note) if note else ''}",
            "success",
        )
    if result["warnings"]:
        flash(" | ".join(result["warnings"]), "warning")

    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))


@translation_bp.route("/translations/<int:candidate_id>/edit", methods=["GET", "POST"])
def edit_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Translation candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    prompt = _pm().get_by_id(candidate["prompt_id"])
    study = _sm().get_by_id(prompt["study_id"])
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if not text:
            flash("Translation text is required.", "error")
            return render_template(
                "translations/form.html",
                prompt=prompt, study=study, candidate=candidate, editing=True
            )
        tm.update_candidate_text(candidate_id, text)
        flash("Translation updated.", "success")
        return redirect(url_for("prompt.detail_prompt", prompt_id=candidate["prompt_id"]))
    return render_template(
        "translations/form.html",
        prompt=prompt, study=study, candidate=candidate, editing=True
    )


@translation_bp.route("/prompts/<int:prompt_id>/translations/export.json")
def export_candidates_json(prompt_id: int):
    pm = _pm()
    prompt = pm.get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    candidates = _tm().get_candidates_for_export(prompt_id)
    payload = {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "study": {
            "id": study["id"],
            "name": study["name"],
        },
        "prompt": {
            "id": prompt["id"],
            "base_text": prompt["base_text"],
            "category": prompt.get("category"),
            "created_at": prompt.get("created_at"),
        },
        "candidates": candidates,
    }
    filename = f"candidates_prompt_{prompt_id}.json"
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
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
        tm.upsert_score(candidate_id, scores["dsf"], scores["rtf"], scores["sfs"],
                        scores.get("ler_char"), scores.get("ler_token"))
        flash(
            f'SFS={scores["sfs"]:.4f} (DSF={scores["dsf"]:.4f}, RTF={scores["rtf"]:.4f}) | '
            f'LER chr={scores.get("ler_char", 0):.3f}, tok={scores.get("ler_token", 0):.3f}',
            "success",
        )
    except Exception as e:
        flash(f"Scoring error: {e}", "error")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/prompts/<int:prompt_id>/selection-scores", methods=["POST"])
def compute_selection_scores(prompt_id: int):
    all_candidates = _tm().get_candidates_by_prompt(prompt_id)

    # Filter by IDs submitted from the modal
    selected_raw = request.form.get("magi_candidate_ids", "").strip()
    if selected_raw:
        selected_ids = {int(x) for x in selected_raw.split(",") if x.strip().isdigit()}
        pool = [c for c in all_candidates if c["id"] in selected_ids]
    else:
        pool = all_candidates

    scored = [c for c in pool if c.get("sfs") is not None]
    if not scored:
        flash("No candidates with SFS in the selection. Score translations first.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    prompt = _pm().get_by_id(prompt_id)
    approved = _tm().get_approved_by_prompt(prompt_id)
    approved_texts = [c["text"] for c in approved if c.get("text")]
    if approved_texts:
        pei_result = _scorer.compute_pei(approved_texts)
    else:
        em = ExperimentModel(current_app.config["DB"])
        pei_result = {"pei": em.get_latest_pei_for_prompt(prompt_id) or 0.0,
                      "cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0}
    pei = float(pei_result.get("pei") or 0.0)

    _pm().save_pei_snapshot(
        prompt_id,
        pei=pei,
        cv_char=float(pei_result.get("cv_char_length") or 0.0),
        cv_word=float(pei_result.get("cv_word_count") or 0.0),
        cv_token=float(pei_result.get("cv_token_count") or 0.0),
    )

    for c in scored:
        c["prompt_id"] = prompt_id
        c["pei"] = pei

    result = _scorer.compute_selection_scores(scored)
    ssm = SelectionScoreModel(current_app.config["DB"])
    ssm.upsert_scores(result)

    # Phase 2 — MAGI judge panel
    run_phase2 = request.form.get("run_phase2") == "1"
    force_magi = request.form.get("force_magi") == "1"
    settings = _setm().get_all()
    em = ExperimentModel(current_app.config["DB"])
    judge_ids = [
        settings.get("magi_judge_balthasar_id"),
        settings.get("magi_judge_caspar_id"),
        settings.get("magi_judge_melchior_id"),
    ]
    judge_models = [em.get_model_by_id(int(mid)) for mid in judge_ids if mid]
    judge_models = [m for m in judge_models if m]

    panel_ran = 0
    magi_went_offline = False
    if run_phase2 and len(judge_models) == 3:
        panel_candidates = result if force_magi else [c for c in result if c.get("magi_required")]
        if panel_candidates:
            log_svc_magi = current_app.config.get("LOG_SERVICE")
            llm = LLMService(settings, log_service=log_svc_magi)
            magi_svc = MAGIService()
            original = prompt["base_text"] if prompt else ""
            for c in panel_candidates:
                magi_ctx = {
                    "operation_type": "magi",
                    "prompt_id": prompt_id,
                    "candidate_id": c.get("id"),
                    "language": c.get("language_name", ""),
                }
                panel = magi_svc.run_panel(
                    original=original,
                    translation=c.get("text", ""),
                    language=c.get("language_name", ""),
                    sfs=c.get("sfs") or 0.0,
                    ler_char=c.get("ler_char") or 1.0,
                    llm_service=llm,
                    judge_models=judge_models,
                    log_service=log_svc_magi,
                    context_ref=magi_ctx,
                )
                if panel.get("magi_offline"):
                    magi_went_offline = True
                    flash(
                        f"MAGI System offline — {panel.get('magi_offline_reason', 'unknown error')}. "
                        "Processing stopped.",
                        "error",
                    )
                    break
                ssm.update_magi_result(
                    candidate_id=c["id"],
                    magi_score=panel["magi_score"],
                    magi_disagreement=panel["magi_disagreement"],
                    magi_judges=panel["judges"],
                )
                panel_ran += 1

    excluded = len(pool) - len(scored)
    msg = f"MAGI Phase 1: {len(result)} candidates classified (λ=0.5, ν=0.5, PEI={pei:.4f})"
    if excluded:
        msg += f" — {excluded} excluded (no SFS)"
    if magi_went_offline:
        msg += f" · Phase 2: MAGI offline after {panel_ran} candidates"
    elif panel_ran:
        msg += f" · Phase 2: {panel_ran} candidates evaluated by judges"
    elif run_phase2 and len(judge_models) == 3:
        msg += " · Phase 2: no candidates require judges"
    elif run_phase2 and len(judge_models) < 3:
        msg += " · Phase 2: configure 3 judges in Settings"
    flash(msg, "success" if not magi_went_offline else "warning")
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


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

@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/approve", methods=["POST"])
def bulk_approve_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    candidates = []
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        candidates.append(c)

    by_lang = {}
    duplicates = 0
    for c in candidates:
        lid = c.get("language_id")
        if not lid:
            skipped += 1
            continue
        existing = by_lang.get(lid)
        if not existing:
            by_lang[lid] = c
            continue
        duplicates += 1
        if (c.get("version") or 0) > (existing.get("version") or 0):
            by_lang[lid] = c

    updated = 0
    for c in by_lang.values():
        tm.approve(prompt_id, c["language_id"], c["id"])
        updated += 1

    if updated:
        extra = []
        if duplicates:
            extra.append(f"Duplicates: {duplicates}")
        if skipped:
            extra.append(f"Skipped: {skipped}")
        flash(f"Approved: {updated}" + (f" | " + " | ".join(extra) if extra else ""), "success")
    else:
        flash("No candidates approved.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/reject", methods=["POST"])
def bulk_reject_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    updated = 0
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        tm.update_status(cid, "rejected")
        updated += 1

    if updated:
        flash(f"Rejected: {updated}" + (f" | Skipped: {skipped}" if skipped else ""), "success")
    else:
        flash("No candidates rejected.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/delete", methods=["POST"])
def bulk_delete_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    deleted = 0
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        tm.delete_candidate(cid)
        deleted += 1

    if deleted:
        flash(f"Deleted: {deleted}" + (f" | Skipped: {skipped}" if skipped else ""), "success")
    else:
        flash("No candidates deleted.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


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
