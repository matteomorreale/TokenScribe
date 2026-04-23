"""
TokenScribe — Experiment Controller
Author: Matteo Morreale
"""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app, jsonify
)
from app.models import StudyModel, ExperimentModel, PromptModel, TranslationModel, SettingsModel
from app.services import LLMService, ScoringService

experiment_bp = Blueprint("experiment", __name__)

_scorer = ScoringService()


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


@experiment_bp.route("/experiments")
def list_experiments():
    runs = _em().get_all_runs()
    return render_template("experiments/list.html", runs=runs)


@experiment_bp.route("/studies/<int:study_id>/experiments/new", methods=["GET", "POST"])
def new_experiment(study_id: int):
    study = _sm().get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("study.list_studies"))
    models = _em().get_all_models()
    prompts = _pm().get_by_study(study_id)
    if request.method == "POST":
        selected_model_ids = request.form.getlist("model_ids", type=int)
        notes = request.form.get("notes", "").strip()
        if not selected_model_ids:
            flash("Select at least one model.", "error")
            return render_template(
                "experiments/new.html",
                study=study, models=models, prompts=prompts
            )
        # Create run
        em = _em()
        run_id = em.create_run(study_id, notes)
        settings = _stm().get_all()
        llm = LLMService(settings)

        errors = []
        result_count = 0
        pei_group_pending = []
        all_languages = _tm().get_all_languages()
        english = next((l for l in all_languages if l.get("code") == "en"), None)
        if not english:
            flash("English language (en) not found in languages table.", "error")
            return redirect(url_for("experiment.list_experiments"))
        english_language_id = int(english["id"])

        for prompt in prompts:
            # Get approved translations for this prompt
            approved = _tm().get_approved_by_prompt(prompt["id"])
            by_language = {}
            by_language[english_language_id] = {
                "language_id": english_language_id,
                "language_name": english.get("name") or "English",
                "language_code": english.get("code") or "en",
                "writing_system": english.get("writing_system") or "",
                "script_group": english.get("script_group") or "",
                "morphology_group": english.get("morphology_group") or "",
                "text": prompt["base_text"],
            }
            for t in approved:
                lid = int(t["language_id"])
                if lid == english_language_id:
                    continue
                by_language[lid] = {
                    "language_id": lid,
                    "language_name": t.get("language_name") or "",
                    "language_code": t.get("language_code") or "",
                    "writing_system": t.get("writing_system") or "",
                    "script_group": t.get("script_group") or "",
                    "morphology_group": t.get("morphology_group") or "",
                    "text": t.get("text") or "",
                }
            inputs = [v for v in by_language.values() if v.get("text")]

            for model_id in selected_model_ids:
                model_info = em.get_model_by_id(model_id)
                if not model_info:
                    continue
                provider = model_info["provider_name"]
                model_name = model_info["name"]
                cost_in = model_info.get("cost_per_input_token", 0.0) or 0.0
                cost_out = model_info.get("cost_per_output_token", 0.0) or 0.0

                for trans in inputs:
                    result = llm.call(
                        provider=provider,
                        model_name=model_name,
                        prompt_text=trans["text"],
                        cost_per_input=cost_in,
                        cost_per_output=cost_out,
                    )
                    if result.success:
                        visible_output_tokens = _scorer.compute_structural_metrics(
                            result.response_text or ""
                        )["token_count"]
                        em.insert_token_result(
                            run_id=run_id,
                            prompt_id=prompt["id"],
                            language_id=trans["language_id"],
                            model_id=model_id,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost=result.cost,
                            source=result.source,
                            response_text=result.response_text,
                            visible_output_tokens=visible_output_tokens,
                        )
                        result_count += 1
                    else:
                        errors.append(
                            f"[{provider}/{model_name}] {trans['language_name']}: {result.error}"
                        )

            # Compute PEI for this prompt across English + approved translations
            texts = [t["text"] for t in inputs]
            if len(texts) > 1:
                pei_data = _scorer.compute_pei(texts)
                pei_value = float(pei_data["pei"])
                script_groups = {t.get("script_group") for t in inputs if t.get("script_group")}
                morphology_groups = {t.get("morphology_group") for t in inputs if t.get("morphology_group")}
                pei_band = _scorer.pei_band(pei_value)
                em.insert_pei_result(
                    run_id=run_id,
                    prompt_id=prompt["id"],
                    cv_char=pei_data["cv_char_length"],
                    cv_word=pei_data["cv_word_count"],
                    cv_token=pei_data["cv_token_count"],
                    pei=pei_value,
                    script_group_count=len(script_groups) if script_groups else 0,
                    morphology_group_count=len(morphology_groups) if morphology_groups else 0,
                    pei_band=pei_band,
                )

                def _collect_group_results(group_type: str, key: str):
                    buckets = {}
                    for t in inputs:
                        gv = (t.get(key) or "").strip()
                        if not gv:
                            continue
                        buckets.setdefault(gv, []).append(t["text"])
                    for gv, bucket_texts in buckets.items():
                        if len(bucket_texts) < 2:
                            continue
                        g = _scorer.compute_pei(bucket_texts)
                        g_pei = float(g["pei"])
                        pei_group_pending.append(
                            {
                                "run_id": run_id,
                                "prompt_id": prompt["id"],
                                "group_type": group_type,
                                "group_value": gv,
                                "language_count": len(bucket_texts),
                                "cv_char_length": g["cv_char_length"],
                                "cv_word_count": g["cv_word_count"],
                                "cv_token_count": g["cv_token_count"],
                                "pei": g_pei,
                                "pei_delta_vs_global": round(g_pei - pei_value, 6),
                                "pei_band": _scorer.pei_band(g_pei),
                            }
                        )

                _collect_group_results("script_group", "script_group")
                _collect_group_results("morphology_group", "morphology_group")

        if pei_group_pending:
            by_group = {}
            for r in pei_group_pending:
                k = (r["group_type"], r["group_value"])
                by_group.setdefault(k, []).append(float(r["pei"]))

            baseline_by_group = {
                k: (sum(v) / len(v) if v else 0.0) for k, v in by_group.items()
            }

            for r in pei_group_pending:
                baseline = float(baseline_by_group.get((r["group_type"], r["group_value"])) or 0.0)
                em.insert_pei_group_result(
                    run_id=r["run_id"],
                    prompt_id=r["prompt_id"],
                    group_type=r["group_type"],
                    group_value=r["group_value"],
                    language_count=int(r["language_count"] or 0),
                    cv_char=float(r["cv_char_length"] or 0.0),
                    cv_word=float(r["cv_word_count"] or 0.0),
                    cv_token=float(r["cv_token_count"] or 0.0),
                    pei=float(r["pei"] or 0.0),
                    pei_delta_vs_global=float(r["pei_delta_vs_global"] or 0.0),
                    baseline_pei=round(baseline, 6),
                    pei_delta_vs_group=round(float(r["pei"] or 0.0) - baseline, 6),
                    pei_band=r["pei_band"],
                )

        if errors:
            for err in errors[:5]:
                flash(f"Warning: {err}", "warning")
        flash(
            f"Experiment run #{run_id} completed with {result_count} results.",
            "success",
        )
        return redirect(url_for("experiment.detail_experiment", run_id=run_id))

    return render_template(
        "experiments/new.html",
        study=study, models=models, prompts=prompts
    )


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
    return render_template(
        "experiments/detail.html",
        run=run, results=results, pei_results=pei_results, pei_group_results=pei_group_results
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
