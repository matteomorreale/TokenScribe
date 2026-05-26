"""
TokenScribe — Study Controller
Author: Matteo Morreale
"""

import json
import threading
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, Response, jsonify
from app.models import StudyModel, ExperimentModel, PromptModel, TranslationModel, SettingsModel, SelectionScoreModel
from app.models.queue_model import QueueModel, RUN_QUEUED
from app.services import get_magi_status
from app.services.scoring_service import ScoringService

_scorer = ScoringService()

# In-memory bulk translate job tracker: study_id -> job_info dict
_BULK_JOBS: dict = {}

study_bp = Blueprint("study", __name__, url_prefix="/studies")


def _get_model() -> StudyModel:
    return StudyModel(current_app.config["DB"])


@study_bp.route("/")
def list_studies():
    model = _get_model()
    studies = model.get_all()
    for s in studies:
        s["prompt_count"] = model.get_prompt_count(s["id"])
        s["run_count"] = model.get_run_count(s["id"])
    from app.models import SettingsModel, ExperimentModel
    settings = SettingsModel(current_app.config["DB"], crypto=current_app.config.get("CRYPTO")).get_all()
    em = ExperimentModel(current_app.config["DB"])
    magi_status = get_magi_status(settings, em)
    return render_template("studies/list.html", studies=studies, magi_status=magi_status)


@study_bp.route("/new", methods=["GET", "POST"])
def new_study():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Study name is required.", "error")
            return render_template("studies/form.html", study=None)
        model = _get_model()
        study_id = model.create(name, description)
        flash(f'Study "{name}" created successfully.', "success")
        return redirect(url_for("study.detail_study", study_id=study_id))
    return render_template("studies/form.html", study=None)


@study_bp.route("/<int:study_id>")
def detail_study(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    em = ExperimentModel(current_app.config["DB"])
    prompts = PromptModel(current_app.config["DB"]).get_by_study(study_id)
    runs = em.get_runs_by_study(study_id)
    settings = SettingsModel(current_app.config["DB"], crypto=current_app.config.get("CRYPTO")).get_all()
    magi_status = get_magi_status(settings, em)
    prompt_ids = [p["id"] for p in prompts]
    readiness = SelectionScoreModel(current_app.config["DB"]).get_readiness_by_prompts(prompt_ids) if prompt_ids else {}
    judge_ids = SettingsModel(current_app.config["DB"], crypto=current_app.config.get("CRYPTO")).get_magi_judge_ids()
    judges_ok = all(judge_ids) and len(judge_ids) == 3
    languages = TranslationModel(current_app.config["DB"]).get_all_languages()
    return render_template(
        "studies/detail.html", study=study, prompts=prompts, runs=runs,
        magi_status=magi_status, readiness=readiness, judges_ok=judges_ok,
        languages=languages,
    )


@study_bp.route("/<int:study_id>/export-prompts")
def export_prompts(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    from app.models import PromptModel, TranslationModel
    pm = PromptModel(current_app.config["DB"])
    tm = TranslationModel(current_app.config["DB"])
    prompts = pm.get_by_study(study_id)
    output_prompts = []
    for p in prompts:
        translations = tm.get_approved_for_export(p["id"])
        output_prompts.append({
            "id": p["id"],
            "base_text": p["base_text"],
            "category": p.get("category") or "",
            "notes": p.get("notes") or "",
            "created_at": p.get("created_at"),
            "pei": {
                "value": p.get("pei_value"),
                "cv_char": p.get("pei_cv_char"),
                "cv_word": p.get("pei_cv_word"),
                "cv_token": p.get("pei_cv_token"),
                "saved_at": p.get("pei_saved_at"),
            },
            "approved_translations": [
                {
                    "language": t["language_name"],
                    "language_code": t["language_code"],
                    "writing_system": t["writing_system"],
                    "script_group": t.get("script_group"),
                    "morphology_group": t.get("morphology_group"),
                    "text": t["text"],
                    "version": t.get("version"),
                    "approved_at": t.get("approved_at"),
                    "scores": {
                        "sfs": t.get("sfs"),
                        "ler_char": t.get("ler_char"),
                        "ler_token": t.get("ler_token"),
                        "dsf": t.get("dsf"),
                        "rtf": t.get("rtf"),
                        "scored_at": t.get("scored_at"),
                    },
                    "magi": {
                        "score_absolute": t.get("magi_score_absolute"),
                        "score_rank": t.get("magi_score_rank"),
                        "score_rank_pct": t.get("magi_score_rank_pct"),
                        "required": bool(t.get("magi_required")),
                        "score": t.get("magi_score"),
                        "disagreement": (
                            bool(t.get("magi_disagreement"))
                            if t.get("magi_disagreement") is not None else None
                        ),
                        "lambda_used": t.get("lambda_used"),
                        "nu_used": t.get("nu_used"),
                        "computed_at": t.get("magi_computed_at"),
                    },
                }
                for t in translations
            ],
        })
    payload = {
        "study": {
            "id": study["id"],
            "name": study["name"],
            "description": study.get("description"),
        },
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt_count": len(output_prompts),
        "prompts": output_prompts,
    }
    filename = f"study_{study_id}_prompts_snapshot.json"
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@study_bp.route("/<int:study_id>/edit", methods=["GET", "POST"])
def edit_study(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Study name is required.", "error")
            return render_template("studies/form.html", study=study)
        model.update(study_id, name, description)
        flash("Study updated.", "success")
        return redirect(url_for("study.detail_study", study_id=study_id))
    return render_template("studies/form.html", study=study)


@study_bp.route("/<int:study_id>/delete", methods=["POST"])
def delete_study(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if study:
        model.delete(study_id)
        flash(f'Study "{study["name"]}" deleted.', "success")
    return redirect(url_for("study.list_studies"))


@study_bp.route("/<int:study_id>/magi-repair-status")
def magi_repair_status(study_id: int):
    """JSON: progress of the most recent active MAGI repair run for this study."""
    from flask import jsonify
    db = current_app.config["DB"]
    conn = db.get_connection()
    try:
        row = conn.execute(
            """SELECT id, status FROM experiment_runs
               WHERE study_id = ? AND status IN ('queued', 'running') AND notes = '[MAGI repair]'
               ORDER BY id DESC LIMIT 1""",
            (study_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return jsonify({"active": False})
    run_id = row["id"]
    run_status = row["status"]
    progress = QueueModel(db).get_run_progress(run_id)
    return jsonify({"active": True, "run_id": run_id, "run_status": run_status, "progress": progress})


def _bulk_translate_worker(app, study_id, prompt_list, language_ids, sfs_min, pei_profile, pei_max, candidates_per_lang, run_magi, run_phase2, auto_approve):
    """Background thread: translates each prompt and optionally runs MAGI + auto-approves."""
    from app.services.translation_ai_service import run_ai_translate
    from app.services import LLMService, MAGIService

    job = _BULK_JOBS[study_id]

    with app.app_context():
        db = app.config["DB"]
        log_svc = app.config.get("LOG_SERVICE")
        settings = SettingsModel(db, crypto=app.config.get("CRYPTO")).get_all()
        tm = TranslationModel(db)
        pm = PromptModel(db)
        ssm = SelectionScoreModel(db)

        judge_models = []
        if run_magi and run_phase2:
            em = ExperimentModel(db)
            judge_id_vals = [
                settings.get("magi_judge_balthasar_id"),
                settings.get("magi_judge_caspar_id"),
                settings.get("magi_judge_melchior_id"),
            ]
            if all(judge_id_vals):
                judge_models = [em.get_model_by_id(int(jid)) for jid in judge_id_vals]
                judge_models = [m for m in judge_models if m]

        for prompt in prompt_list:
            prompt_id = prompt["id"]
            job["current_prompt_id"] = prompt_id
            job["current_prompt_text"] = (prompt.get("base_text") or "")[:60]
            job["status"] = "running"

            try:
                job["current_step"] = "translating"
                result = run_ai_translate(
                    prompt=prompt,
                    language_ids=language_ids,
                    sfs_min=sfs_min,
                    pei_profile=pei_profile,
                    pei_max=pei_max,
                    candidates_per_lang=candidates_per_lang,
                    db=db,
                    settings=settings,
                    log_service=log_svc,
                )

                if result["created"] == 0:
                    job["errors"].append(f"Prompt #{prompt_id}: no candidates generated")
                    job["done"] += 1
                    continue

                job["results"].append({
                    "prompt_id": prompt_id,
                    "created": result["created"],
                    "pei": float((result["accepted_pei"] or {}).get("pei") or 0.0),
                })

                all_new_cids = {cid for cids in result["candidates_by_lang"].values() for cid in cids}

                if run_magi:
                    job["current_step"] = "magi_phase1"
                    all_candidates = tm.get_candidates_by_prompt(prompt_id)
                    scored = [c for c in all_candidates if c["id"] in all_new_cids and c.get("sfs") is not None]

                    if scored:
                        approved = tm.get_approved_by_prompt(prompt_id)
                        approved_texts = [c["text"] for c in approved if c.get("text")]
                        if approved_texts:
                            pei_result = _scorer.compute_pei(approved_texts)
                        else:
                            new_texts = [c["text"] for c in all_candidates if c["id"] in all_new_cids and c.get("text")]
                            pei_result = _scorer.compute_pei(new_texts) if new_texts else {
                                "pei": 0.0, "cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0,
                            }
                        pei = float(pei_result.get("pei") or 0.0)

                        pm.save_pei_snapshot(
                            prompt_id,
                            pei=pei,
                            cv_char=float(pei_result.get("cv_char_length") or 0.0),
                            cv_word=float(pei_result.get("cv_word_count") or 0.0),
                            cv_token=float(pei_result.get("cv_token_count") or 0.0),
                        )
                        for c in scored:
                            c["prompt_id"] = prompt_id
                            c["pei"] = pei

                        magi_result = _scorer.compute_selection_scores(scored)
                        ssm.upsert_scores(magi_result)

                        if run_phase2 and len(judge_models) == 3:
                            job["current_step"] = "magi_phase2"
                            llm = LLMService(settings, log_service=log_svc)
                            magi_svc = MAGIService()
                            flagged = [c for c in magi_result if c.get("magi_required")]
                            offline = False
                            for fc in flagged:
                                panel = magi_svc.run_panel(
                                    original=prompt["base_text"],
                                    translation=fc.get("text", ""),
                                    language=fc.get("language_name", ""),
                                    sfs=fc.get("sfs") or 0.0,
                                    ler_char=fc.get("ler_char") or 1.0,
                                    llm_service=llm,
                                    judge_models=judge_models,
                                    log_service=log_svc,
                                    context_ref={"operation_type": "magi", "prompt_id": prompt_id},
                                )
                                if panel.get("magi_offline"):
                                    job["errors"].append(f"Prompt #{prompt_id}: MAGI offline — {panel.get('magi_offline_reason', '')}")
                                    offline = True
                                    break
                                ssm.update_magi_result(
                                    candidate_id=fc["id"],
                                    magi_score=panel["magi_score"],
                                    magi_disagreement=panel["magi_disagreement"],
                                    magi_judges=panel["judges"],
                                )
                            if offline:
                                job["done"] += 1
                                continue

                        if auto_approve:
                            job["current_step"] = "approving"
                            magi_scores = ssm.get_by_prompt(prompt_id)
                            magi_scores = [s for s in magi_scores if s["candidate_id"] in all_new_cids]
                            by_lang = {}
                            for s in magi_scores:
                                lid = s.get("language_id")
                                if lid is None:
                                    continue
                                existing = by_lang.get(lid)
                                if not existing or (s.get("score_absolute") or -999.0) > (existing.get("score_absolute") or -999.0):
                                    by_lang[lid] = s
                            for lid, s in by_lang.items():
                                tm.approve(prompt_id, lid, s["candidate_id"])

                elif auto_approve:
                    job["current_step"] = "approving"
                    all_candidates = tm.get_candidates_by_prompt(prompt_id)
                    by_lang = {}
                    for c in all_candidates:
                        if c["id"] not in all_new_cids:
                            continue
                        lid = c.get("language_id")
                        if lid is None:
                            continue
                        existing = by_lang.get(lid)
                        if not existing or (c.get("sfs") or 0.0) > (existing.get("sfs") or 0.0):
                            by_lang[lid] = c
                    for lid, c in by_lang.items():
                        tm.approve(prompt_id, lid, c["id"])

            except Exception as e:
                job["errors"].append(f"Prompt #{prompt_id}: {str(e)}")

            job["done"] += 1

        job["status"] = "done"
        job["current_step"] = ""
        job["current_prompt_id"] = None


@study_bp.route("/<int:study_id>/bulk-translate", methods=["POST"])
def bulk_translate(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))

    # Block if a job is already running for this study
    existing = _BULK_JOBS.get(study_id)
    if existing and existing.get("status") == "running":
        flash("Bulk translate already in progress for this study.", "warning")
        return redirect(url_for("study.detail_study", study_id=study_id))

    prompt_ids = request.form.getlist("bulk_prompt_ids", type=int)
    language_ids_raw = request.form.getlist("bulk_language_ids")
    try:
        language_ids = sorted({int(x) for x in language_ids_raw if str(x).strip()})
    except Exception:
        flash("Invalid language selection.", "error")
        return redirect(url_for("study.detail_study", study_id=study_id))

    if not language_ids:
        flash("Select at least one target language.", "error")
        return redirect(url_for("study.detail_study", study_id=study_id))

    sfs_min = max(0.0, min(1.0, float(request.form.get("bulk_sfs_min") or 0.92)))
    pei_profile = (request.form.get("bulk_pei_profile") or "homogeneous").strip()
    if pei_profile not in {"homogeneous", "moderate", "cross_script"}:
        pei_profile = "homogeneous"
    pei_max = 0.35 if pei_profile in {"moderate", "cross_script"} else 0.20
    candidates_per_lang = max(1, min(5, int(request.form.get("bulk_candidates_per_lang") or 2)))
    run_magi = request.form.get("bulk_run_magi") == "1"
    run_phase2 = request.form.get("bulk_run_phase2") == "1"
    auto_approve = request.form.get("bulk_auto_approve") == "1"

    all_prompts = PromptModel(current_app.config["DB"]).get_by_study(study_id)
    if prompt_ids:
        prompt_list = [p for p in all_prompts if p["id"] in set(prompt_ids)]
    else:
        prompt_list = all_prompts

    if not prompt_list:
        flash("No prompts selected.", "warning")
        return redirect(url_for("study.detail_study", study_id=study_id))

    _BULK_JOBS[study_id] = {
        "status": "starting",
        "total": len(prompt_list),
        "done": 0,
        "current_prompt_id": None,
        "current_prompt_text": "",
        "current_step": "",
        "errors": [],
        "results": [],
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    app = current_app._get_current_object()
    t = threading.Thread(
        target=_bulk_translate_worker,
        args=(app, study_id, prompt_list, language_ids, sfs_min, pei_profile, pei_max,
              candidates_per_lang, run_magi, run_phase2, auto_approve),
        daemon=True,
    )
    t.start()

    flash(f"Bulk translate started for {len(prompt_list)} prompts.", "info")
    return redirect(url_for("study.detail_study", study_id=study_id))


@study_bp.route("/<int:study_id>/bulk-translate-status")
def bulk_translate_status(study_id: int):
    job = _BULK_JOBS.get(study_id)
    if not job or job.get("status") == "done":
        if job and job.get("status") == "done":
            results = job.get("results", [])
            errors = job.get("errors", [])
            _BULK_JOBS.pop(study_id, None)
            return jsonify({"active": False, "just_completed": True, "results": results, "errors": errors})
        return jsonify({"active": False})
    total = job.get("total") or 1
    done = job.get("done") or 0
    pct = round(done / total * 100, 1)
    return jsonify({
        "active": True,
        "status": job.get("status"),
        "total": total,
        "done": done,
        "pct": pct,
        "current_prompt_id": job.get("current_prompt_id"),
        "current_prompt_text": job.get("current_prompt_text", ""),
        "current_step": job.get("current_step", ""),
        "errors": job.get("errors", []),
    })


@study_bp.route("/<int:study_id>/regen-magi", methods=["POST"])
def regen_magi(study_id: int):
    model = _get_model()
    study = model.get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))

    db = current_app.config["DB"]
    em = ExperimentModel(db)
    tm = TranslationModel(db)
    ssm = SelectionScoreModel(db)
    stm = SettingsModel(db, crypto=current_app.config.get("CRYPTO"))
    qm = QueueModel(db)

    # Determine which prompts to regenerate
    selected_ids = request.form.getlist("prompt_ids", type=int)
    all_prompts = PromptModel(db).get_by_study(study_id)
    if selected_ids:
        prompts = [p for p in all_prompts if p["id"] in set(selected_ids)]
    else:
        prompts = all_prompts

    if not prompts:
        flash("No prompts to regenerate.", "warning")
        return redirect(url_for("study.detail_study", study_id=study_id))

    # Check judge panel
    settings = stm.get_all()
    judge_id_vals = [
        settings.get("magi_judge_balthasar_id"),
        settings.get("magi_judge_caspar_id"),
        settings.get("magi_judge_melchior_id"),
    ]
    judge_models = []
    if all(judge_id_vals):
        judge_models = [em.get_model_by_id(int(jid)) for jid in judge_id_vals]
        judge_models = [m for m in judge_models if m]

    # Create a dedicated repair run
    run_id = em.create_run(study_id, "[MAGI repair]")
    em.update_run_status(run_id, RUN_QUEUED)

    phase1_count = 0
    phase2_count = 0
    phase2_skipped = False

    for prompt in prompts:
        approved = tm.get_approved_by_prompt(prompt["id"])
        scored = [c for c in approved if c.get("sfs") is not None]
        if not scored:
            continue
        pei = em.get_latest_pei_for_prompt(prompt["id"]) or 0.0
        for c in scored:
            c["id"] = c["candidate_id"]
            c["pei"] = pei
        result = _scorer.compute_selection_scores(scored)
        ssm.upsert_scores(result)
        phase1_count += len(result)

        flagged = [c for c in result if c.get("magi_required")]
        if flagged:
            if len(judge_models) == 3:
                for c in flagged:
                    qm.enqueue(
                        run_id=run_id,
                        operation_type="magi_phase2",
                        item_key=f"magi:c{c['id']}",
                        payload={
                            "run_id":           run_id,
                            "prompt_id":        prompt["id"],
                            "candidate_id":     c["id"],
                            "base_text":        prompt["base_text"],
                            "translation_text": c.get("text", ""),
                            "language_name":    c.get("language_name", ""),
                            "sfs":              c.get("sfs") or 0.0,
                            "ler_char":         c.get("ler_char") or 1.0,
                        },
                        priority=1,
                    )
                    phase2_count += 1
            else:
                phase2_skipped = True

    flash(f"MAGI Phase 1 recomputed for {phase1_count} candidates.", "info")
    if phase2_count:
        flash(f"{phase2_count} MAGI Phase 2 candidates queued (run #{run_id}).", "info")
    if phase2_skipped:
        flash("MAGI Judge Panel not configured — Phase 2 skipped. Configure the three judges in Settings.", "warning")

    return redirect(url_for("study.detail_study", study_id=study_id))
