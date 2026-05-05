"""
TokenScribe — Run Controller
Author: Matteo Morreale

Endpoint JSON per monitoraggio, resume e retry selettivo delle RUN.
"""

from flask import Blueprint, current_app, jsonify, request, redirect, url_for, flash

from app.models import ExperimentModel
from app.models.queue_model import (
    QueueModel, RUN_QUEUED, RUN_STOPPED,
    ITEM_PENDING, ITEM_ERROR, ITEM_TIMEOUT, RUN_PARTIAL, RUN_COMPLETED,
)

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
# POST /experiments/<id>/stop  →  cancella tutti gli item pending, marca stopped
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/stop", methods=["POST"])
def stop_run(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    qm         = _qm()
    cancelled_n = qm.cancel_pending_items(run_id)
    qm.update_run_status(run_id, RUN_STOPPED)
    flash(f"Run #{run_id} fermata — {cancelled_n} operazioni annullate.", "info")

    next_url = request.form.get("next") or url_for("experiment.detail_experiment", run_id=run_id)
    return redirect(next_url)


# ------------------------------------------------------------------
# POST /experiments/<id>/restart  →  rimette in pending i cancelled/error, riavvia
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/restart", methods=["POST"])
def restart_run(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    qm      = _qm()
    reset_n = qm.restart_stopped_run(run_id)
    if reset_n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        flash(f"Run #{run_id} riavviata — {reset_n} operazioni riaccodate.", "success")
    else:
        flash("Nessuna operazione da riavviare.", "info")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


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


# ------------------------------------------------------------------
# POST /experiments/<id>/retry-errors  →  retry solo gli item in errore/timeout
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/retry-errors", methods=["POST"])
def retry_errors(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    qm      = _qm()
    reset_n = qm.reset_items_for_retry(run_id, model_ids=None)
    if reset_n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        flash(f"Run #{run_id}: {reset_n} operazioni in errore riaccodate.", "success")
    else:
        flash("Nessuna operazione in errore da ritentare.", "info")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


# ------------------------------------------------------------------
# POST /experiments/<id>/redo-model  →  rifai tutte le chiamate di un modello
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/redo-model", methods=["POST"])
def redo_model(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    model_id     = request.form.get("model_id", type=int)
    save_history = request.form.get("save_history") == "1"

    if not model_id:
        flash("Modello non specificato.", "error")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    em = _em()
    qm = _qm()

    model = em.get_model_by_id(model_id)
    if not model:
        flash("Modello non trovato.", "error")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    model_name = model["name"]

    # 1. Recupera payload (da coda se disponibili, altrimenti ricostruisce da risultati+snapshot)
    payloads = qm.get_model_llm_payloads(run_id, model_id)
    if not payloads:
        payloads = em.reconstruct_llm_payloads(run_id, model_id)

    if not payloads:
        flash(f"Impossibile ricostruire le chiamate per {model_name}.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    # 2. Archivia storico se richiesto
    if save_history:
        em.archive_model_results(run_id, model_id, model_name, reason="redo")

    # 3. Elimina i risultati correnti del modello
    em.delete_model_results(run_id, model_id)

    # 4. Rimetti in coda
    n = qm.redo_model_items(run_id, model_id, payloads)
    if n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        suffix = " (storico salvato)" if save_history else ""
        flash(f"Run #{run_id}: {n} chiamate per {model_name} riaccodate{suffix}.", "success")
    else:
        flash(f"Nessuna chiamata da riaccodare per {model_name}.", "warning")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


# ------------------------------------------------------------------
# POST /experiments/<id>/replace-model  →  sostituisci un modello con un altro
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/replace-model", methods=["POST"])
def replace_model(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    old_model_id = request.form.get("old_model_id", type=int)
    new_model_id = request.form.get("new_model_id", type=int)
    save_history = request.form.get("save_history") == "1"

    if not old_model_id or not new_model_id:
        flash("Modello di origine o destinazione non specificato.", "error")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    if old_model_id == new_model_id:
        flash("Il modello di destinazione è uguale a quello di origine.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    em = _em()
    qm = _qm()

    old_model = em.get_model_by_id(old_model_id)
    new_model  = em.get_model_by_id(new_model_id)

    if not old_model:
        flash("Modello di origine non trovato.", "error")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))
    if not new_model:
        flash("Modello di destinazione non trovato.", "error")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    old_name = old_model["name"]
    new_name  = new_model["name"]

    # 1. Recupera payload del vecchio modello
    payloads = qm.get_model_llm_payloads(run_id, old_model_id)
    if not payloads:
        payloads = em.reconstruct_llm_payloads(run_id, old_model_id)

    if not payloads:
        flash(f"Impossibile ricostruire le chiamate per {old_name}.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    # 2. Archivia storico se richiesto
    if save_history:
        em.archive_model_results(
            run_id, old_model_id, old_name, reason="replace",
            replaced_by_model_id=new_model_id, replaced_by_model_name=new_name,
        )

    # 3. Elimina risultati del vecchio modello
    em.delete_model_results(run_id, old_model_id)

    # 4. Sostituisce item in coda
    n = qm.replace_model_items(run_id, old_model_id, new_model_id, new_model, payloads)
    if n > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        suffix = " (storico salvato)" if save_history else ""
        flash(
            f"Run #{run_id}: {old_name} sostituito con {new_name} — {n} chiamate riaccodate{suffix}.",
            "success",
        )
    else:
        flash(f"Nessuna chiamata da sostituire per {old_name}.", "warning")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


# ------------------------------------------------------------------
# POST /experiments/<id>/add-models  →  accoda nuovi modelli su run esistente
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/add-models", methods=["POST"])
def add_models(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    run_status = run.get("status", "")
    if run_status not in ("completed", "partial", "stopped"):
        flash("Puoi aggiungere modelli solo a run completate, parziali o fermate.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    new_model_ids = request.form.getlist("model_ids", type=int)
    if not new_model_ids:
        flash("Seleziona almeno un modello da aggiungere.", "warning")
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    em = _em()
    qm = _qm()

    existing_ids = em.get_run_model_ids(run_id)
    repetitions  = qm.get_run_repetitions(run_id)

    added_items = 0
    skipped: list[str] = []

    for model_id in new_model_ids:
        if model_id in existing_ids:
            model = em.get_model_by_id(model_id)
            skipped.append(model["name"] if model else str(model_id))
            continue

        model = em.get_model_by_id(model_id)
        if not model:
            skipped.append(str(model_id))
            continue

        payloads = em.build_llm_payloads_from_snapshot(run_id, model_id, repetitions)
        if not payloads:
            flash(
                f"Snapshot mancante o vuoto per {model['name']}: nessun payload generato.",
                "warning",
            )
            continue

        for p in payloads:
            qm.enqueue(
                run_id=run_id,
                operation_type="llm_call",
                item_key=f"llm:p{p['prompt_id']}:l{p['language_id']}:m{model_id}:r{p['repetition_index']}",
                payload=p,
                priority=2,
            )
        added_items += len(payloads)

    if skipped:
        flash(f"Già presenti nella run (saltati): {', '.join(skipped)}.", "info")

    if added_items > 0:
        qm.update_run_status(run_id, RUN_QUEUED)
        flash(
            f"Run #{run_id}: {added_items} chiamate accodate per i nuovi modelli "
            f"({repetitions} ripetizioni per cella).",
            "success",
        )
    else:
        flash("Nessuna nuova chiamata accodata.", "info")

    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


# ------------------------------------------------------------------
# POST /experiments/<id>/revalidate-status  →  ricalcola status (fix run con risposte vuote)
# ------------------------------------------------------------------

@run_bp.route("/experiments/<int:run_id>/revalidate-status", methods=["POST"])
def revalidate_status(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))

    qm     = _qm()
    new_st = qm.recompute_run_status(run_id)
    label  = {
        RUN_PARTIAL:   "partial — risposte vuote rilevate",
        RUN_COMPLETED: "completed",
    }.get(new_st, new_st)
    flash(f"Run #{run_id}: status aggiornato → {label}.", "info")
    return redirect(url_for("experiment.detail_experiment", run_id=run_id))
