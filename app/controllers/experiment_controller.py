"""
TokenScribe — Experiment Controller
Author: Matteo Morreale
"""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app, jsonify
)
from app.models import StudyModel, ExperimentModel, PromptModel, TranslationModel, SettingsModel, SelectionScoreModel
from app.models.queue_model import QueueModel, RUN_QUEUED
from app.services import LLMService, ScoringService, MAGIService, get_magi_status

experiment_bp = Blueprint("experiment", __name__)

_scorer = ScoringService()

_PROVIDER_KEY_MAP = {
    "openai":    "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google":    "google_api_key",
    "deepseek":  "deepseek_api_key",
    "meta":      "meta_api_key",
    "qwen":      "qwen_api_key",
    "mistral":   "mistral_api_key",
}


def _em() -> ExperimentModel:
    return ExperimentModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _stm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"])


def _ssm() -> SelectionScoreModel:
    return SelectionScoreModel(current_app.config["DB"])


def _qm() -> QueueModel:
    return QueueModel(current_app.config["DB"])


@experiment_bp.route("/experiments")
def list_experiments():
    runs = _em().get_all_runs()
    em = _em()
    settings = _stm().get_all()
    magi_status = get_magi_status(settings, em)
    return render_template("experiments/list.html", runs=runs, magi_status=magi_status)


@experiment_bp.route("/experiments/<int:run_id>/delete", methods=["POST"])
def delete_experiment(run_id: int):
    run = _em().get_run_by_id(run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))
    _em().delete_run(run_id)
    flash(f"Run #{run_id} deleted.", "success")
    next_url = request.form.get("next") or url_for("experiment.list_experiments")
    return redirect(next_url)


@experiment_bp.route("/studies/<int:study_id>/experiments/new", methods=["GET", "POST"])
def new_experiment(study_id: int):
    study = _sm().get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    models = _em().get_all_models()
    prompts = _pm().get_by_study(study_id)
    if request.method == "GET":
        prompt_ids = [p["id"] for p in prompts]
        readiness = _ssm().get_readiness_by_prompts(prompt_ids) if prompt_ids else {}
        settings_get = _stm().get_all()
        configured_providers = {
            p for p, k in _PROVIDER_KEY_MAP.items() if settings_get.get(k)
        }
        judge_ids = _stm().get_magi_judge_ids()
        em_get = _em()
        judge_info = [
            em_get.get_model_by_id(int(jid)) if jid else None
            for jid in judge_ids
        ]
        judge_model_ids = {jid for jid in judge_ids if jid}
        return render_template(
            "experiments/new.html",
            study=study, models=models, prompts=prompts, readiness=readiness,
            configured_providers=configured_providers,
            judge_info=judge_info,
            judge_model_ids=judge_model_ids,
        )

    # ------------------------------------------------------------------ POST
    selected_model_ids = request.form.getlist("model_ids", type=int)
    notes = request.form.get("notes", "").strip()
    if not selected_model_ids:
        flash("Select at least one model.", "error")
        prompt_ids = [p["id"] for p in prompts]
        readiness = _ssm().get_readiness_by_prompts(prompt_ids) if prompt_ids else {}
        settings_err = _stm().get_all()
        configured_providers = {
            p for p, k in _PROVIDER_KEY_MAP.items() if settings_err.get(k)
        }
        judge_ids_err = _stm().get_magi_judge_ids()
        em_err = _em()
        judge_info_err = [
            em_err.get_model_by_id(int(jid)) if jid else None
            for jid in judge_ids_err
        ]
        return render_template(
            "experiments/new.html",
            study=study, models=models, prompts=prompts, readiness=readiness,
            configured_providers=configured_providers,
            judge_info=judge_info_err,
            judge_model_ids={jid for jid in judge_ids_err if jid},
        )

    em      = _em()
    qm      = _qm()
    ssm     = _ssm()
    settings = _stm().get_all()
    log_svc  = current_app.config.get("LOG_SERVICE")

    # Verifica presenza della lingua inglese prima di creare la run
    all_languages = _tm().get_all_languages()
    english = next((l for l in all_languages if l.get("code") == "en"), None)
    if not english:
        flash("English language (en) not found in languages table.", "error")
        return redirect(url_for("experiment.list_experiments"))
    english_language_id = int(english["id"])

    # Crea la run con status 'queued'
    run_id = em.create_run(study_id, notes)
    em.update_run_status(run_id, RUN_QUEUED)

    if log_svc:
        log_svc.info(
            "experiment", "run_queued",
            message=f"Experiment run #{run_id} queued for study '{study['name']}'",
            context_ref={"run_id": run_id, "study_id": study_id},
            payload={
                "study_name": study["name"],
                "model_ids": selected_model_ids,
                "prompt_count": len(prompts),
                "notes": notes or "",
            },
        )

    # ------------------------------------------------------------------
    # 1. Snapshot translations (priority 0)
    # ------------------------------------------------------------------
    qm.enqueue(
        run_id=run_id,
        operation_type="snapshot_translations",
        item_key="snapshot",
        payload={"run_id": run_id, "study_id": study_id},
        priority=0,
    )

    # ------------------------------------------------------------------
    # 2. MAGI Phase 1 (locale, veloce) + enqueue Phase 2 per i flagged
    # ------------------------------------------------------------------
    judge_id_vals = [
        settings.get("magi_judge_balthasar_id"),
        settings.get("magi_judge_caspar_id"),
        settings.get("magi_judge_melchior_id"),
    ]
    judge_models = []
    if all(judge_id_vals):
        judge_models = [em.get_model_by_id(int(jid)) for jid in judge_id_vals]
        judge_models = [m for m in judge_models if m]

    prompt_ids = [p["id"] for p in prompts]
    readiness  = ssm.get_readiness_by_prompts(prompt_ids)
    magi_auto_count = 0
    magi_phase2_skipped = False
    magi_queued_count   = 0

    for prompt in prompts:
        r = readiness.get(prompt["id"], {})
        if r.get("magi_count", 0) == 0 and r.get("scored_count", 0) > 0:
            approved = _tm().get_approved_by_prompt(prompt["id"])
            scored   = [c for c in approved if c.get("sfs") is not None]
            if scored:
                pei = em.get_latest_pei_for_prompt(prompt["id"]) or 0.0
                for c in scored:
                    c["id"]  = c["candidate_id"]
                    c["pei"] = pei
                result = _scorer.compute_selection_scores(scored)
                ssm.upsert_scores(result)
                magi_auto_count += len(result)
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
                            magi_queued_count += 1
                    else:
                        magi_phase2_skipped = True

    if magi_auto_count > 0:
        flash(f"MAGI Phase 1 auto-calcolato per {magi_auto_count} candidati.", "info")
    if magi_queued_count > 0:
        flash(f"{magi_queued_count} candidati MAGI Phase 2 accodati.", "info")
    if magi_phase2_skipped:
        flash(
            "MAGI Judge Panel non configurato — Phase 2 saltata. "
            "Configura i tre judge in Settings.",
            "warning",
        )

    # ------------------------------------------------------------------
    # 3. LLM calls (priority 2) — un item per prompt × model × language
    # ------------------------------------------------------------------
    llm_item_count = 0
    for prompt in prompts:
        approved = _tm().get_approved_by_prompt(prompt["id"])
        by_language: dict[int, dict] = {
            english_language_id: {
                "language_id":       english_language_id,
                "language_name":     english.get("name") or "English",
                "language_code":     english.get("code") or "en",
                "script_group":      english.get("script_group") or "alphabetic",
                "morphology_group":  english.get("morphology_group") or "",
                "text":              prompt["base_text"],
            }
        }
        for t in approved:
            lid = int(t["language_id"])
            if lid == english_language_id:
                continue
            by_language[lid] = {
                "language_id":      lid,
                "language_name":    t.get("language_name") or "",
                "language_code":    t.get("language_code") or "",
                "script_group":     t.get("script_group") or "alphabetic",
                "morphology_group": t.get("morphology_group") or "",
                "text":             t.get("text") or "",
            }
        inputs = [v for v in by_language.values() if v.get("text")]

        for model_id in selected_model_ids:
            model_info = em.get_model_by_id(model_id)
            if not model_info:
                continue
            for trans in inputs:
                qm.enqueue(
                    run_id=run_id,
                    operation_type="llm_call",
                    item_key=f"llm:p{prompt['id']}:l{trans['language_id']}:m{model_id}",
                    payload={
                        "run_id":       run_id,
                        "study_id":     study_id,
                        "prompt_id":    prompt["id"],
                        "language_id":  trans["language_id"],
                        "language_name": trans["language_name"],
                        "language_code": trans["language_code"],
                        "model_id":     model_id,
                        "provider":     model_info["provider_name"],
                        "model_name":   model_info["name"],
                        "cost_per_input":  model_info.get("cost_per_input_token", 0.0) or 0.0,
                        "cost_per_output": model_info.get("cost_per_output_token", 0.0) or 0.0,
                        "is_reasoning":    bool(model_info.get("is_reasoning", 0)),
                        "text":         trans["text"],
                    },
                    priority=2,
                )
                llm_item_count += 1

    # ------------------------------------------------------------------
    # 4. Compute PEI per prompt (priority 3)
    # ------------------------------------------------------------------
    for prompt in prompts:
        qm.enqueue(
            run_id=run_id,
            operation_type="compute_pei",
            item_key=f"pei:p{prompt['id']}",
            payload={"run_id": run_id, "prompt_id": prompt["id"], "study_id": study_id},
            priority=3,
        )

    # ------------------------------------------------------------------
    # 5. Finalizza baseline gruppi PEI (priority 4)
    # ------------------------------------------------------------------
    qm.enqueue(
        run_id=run_id,
        operation_type="finalize_pei_groups",
        item_key="finalize_pei",
        payload={"run_id": run_id},
        priority=4,
    )

    total_items = 1 + magi_queued_count + llm_item_count + len(prompts) + 1
    flash(
        f"Experiment run #{run_id} avviata — {total_items} operazioni in coda.",
        "success",
    )
    return redirect(url_for("experiment.detail_experiment", run_id=run_id))


@experiment_bp.route("/experiments/<int:run_id>")
def detail_experiment(run_id: int):
    em = _em()
    run = em.get_run_by_id(run_id)
    if not run:
        flash("Experiment run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))
    results = em.get_results_by_run(run_id)
    pei_results = em.get_pei_by_run(run_id)
    pei_group_results = em.get_pei_groups_by_run(run_id)
    settings = _stm().get_all()
    magi_status = get_magi_status(settings, em)
    queue_items = _qm().get_run_queue(run_id)
    progress    = _qm().get_run_progress(run_id)
    all_models  = em.get_all_models()
    run_history = em.get_run_history(run_id)
    return render_template(
        "experiments/detail.html",
        run=run, results=results, pei_results=pei_results, pei_group_results=pei_group_results,
        magi_status=magi_status,
        queue_items=queue_items,
        progress=progress,
        all_models=all_models,
        run_history=run_history,
    )


@experiment_bp.route("/experiments/<int:run_id>/pei")
def pei_results(run_id: int):
    em = _em()
    run = em.get_run_by_id(run_id)
    if not run:
        flash("Experiment run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))
    pei_results = em.get_pei_by_run(run_id)
    pei_group_results = em.get_pei_groups_by_run(run_id)
    return render_template(
        "experiments/pei.html", run=run, pei_results=pei_results, pei_group_results=pei_group_results
    )
