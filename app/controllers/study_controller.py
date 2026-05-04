"""
TokenScribe — Study Controller
Author: Matteo Morreale
"""

import json
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, Response
from app.models import StudyModel, ExperimentModel, PromptModel, TranslationModel, SettingsModel, SelectionScoreModel
from app.models.queue_model import QueueModel, RUN_QUEUED
from app.services import get_magi_status
from app.services.scoring_service import ScoringService

_scorer = ScoringService()

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
    settings = SettingsModel(current_app.config["DB"]).get_all()
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
    settings = SettingsModel(current_app.config["DB"]).get_all()
    magi_status = get_magi_status(settings, em)
    prompt_ids = [p["id"] for p in prompts]
    readiness = SelectionScoreModel(current_app.config["DB"]).get_readiness_by_prompts(prompt_ids) if prompt_ids else {}
    judge_ids = SettingsModel(current_app.config["DB"]).get_magi_judge_ids()
    judges_ok = all(judge_ids) and len(judge_ids) == 3
    return render_template(
        "studies/detail.html", study=study, prompts=prompts, runs=runs,
        magi_status=magi_status, readiness=readiness, judges_ok=judges_ok,
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
    stm = SettingsModel(db)
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

    flash(f"MAGI Phase 1 ricalcolato per {phase1_count} candidati.", "info")
    if phase2_count:
        flash(f"{phase2_count} candidati MAGI Phase 2 accodati (run #{run_id}).", "info")
    if phase2_skipped:
        flash("MAGI Judge Panel non configurato — Phase 2 saltata. Configura i tre judge in Settings.", "warning")

    return redirect(url_for("study.detail_study", study_id=study_id))
