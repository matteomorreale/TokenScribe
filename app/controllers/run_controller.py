"""
TokenScribe — Run Controller
Author: Matteo Morreale

Endpoint JSON per monitoraggio, resume e retry selettivo delle RUN.
"""

from flask import Blueprint, current_app, jsonify, request, redirect, url_for, flash

from app.models import ExperimentModel
from app.models.queue_model import QueueModel, RUN_QUEUED, ITEM_PENDING, ITEM_ERROR, ITEM_TIMEOUT

run_bp = Blueprint("run", __name__)


def _em() -> ExperimentModel:
    return ExperimentModel(current_app.config["DB"])


def _qm() -> QueueModel:
    return QueueModel(current_app.config["DB"])


# ------------------------------------------------------------------
# GET /experiments/<id>/queue-status  →  JSON live progress
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/queue-status")
def queue_status(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    qm       = _qm()
    progress = qm.get_run_progress(run_id)
    items    = qm.get_run_queue(run_id)

    # Sintetizza errori per modello (per la UI di retry selettivo)
    error_models: dict[int, dict] = {}
    for item in items:
        if item["status"] not in (ITEM_ERROR, ITEM_TIMEOUT):
            continue
        p = item.get("payload") or {}
        mid  = p.get("model_id")
        mname = p.get("model_name", "")
        prov  = p.get("provider", "")
        if mid:
            mid = int(mid)
            error_models.setdefault(mid, {
                "model_id": mid,
                "model_name": mname,
                "provider": prov,
                "count": 0,
            })
            error_models[mid]["count"] += 1

    return jsonify({
        "run_id":       run_id,
        "run_status":   run.get("status", "unknown"),
        "progress":     progress,
        "error_models": list(error_models.values()),
        "items": [
            {
                "id":             it["id"],
                "operation_type": it["operation_type"],
                "item_key":       it["item_key"],
                "status":         it["status"],
                "error_message":  it.get("error_message"),
                "started_at":     it.get("started_at"),
                "completed_at":   it.get("completed_at"),
                "model_id":       (it.get("payload") or {}).get("model_id"),
                "model_name":     (it.get("payload") or {}).get("model_name"),
                "language_name":  (it.get("payload") or {}).get("language_name"),
                "prompt_id":      (it.get("payload") or {}).get("prompt_id"),
            }
            for it in items
        ],
    })


# ------------------------------------------------------------------
# POST /experiments/<id>/resume  →  reset tutti gli item error/pending
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/resume", methods=["POST"])
def resume_run(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    qm      = _qm()
    reset_n = qm.reset_items_for_retry(run_id, model_ids=None)
    if reset_n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        flash(f"Run #{run_id} ripresa — {reset_n} operazioni riaccodate.", "success")
    else:
        flash("Nessuna operazione da riprendere.", "info")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


# ------------------------------------------------------------------
# POST /experiments/<id>/retry-models  →  retry filtrato per model_ids
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/retry-models", methods=["POST"])
def retry_models(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    model_ids_raw = request.form.getlist("model_ids", type=int)
    if not model_ids_raw:
        flash("Seleziona almeno un modello da ritentare.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    qm      = _qm()
    reset_n = qm.reset_items_for_retry(run_id, model_ids=model_ids_raw)
    if reset_n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        flash(
            f"Run #{run_id}: {reset_n} operazioni riaccodate per i modelli selezionati.",
            "success",
        )
    else:
        flash("Nessuna operazione in errore per i modelli selezionati.", "info")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))
