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

        for prompt in prompts:
            # Get approved translations for this prompt
            approved = _tm().get_approved_by_prompt(prompt["id"])
            if not approved:
                continue

            for model_id in selected_model_ids:
                model_info = em.get_model_by_id(model_id)
                if not model_info:
                    continue
                provider = model_info["provider_name"]
                model_name = model_info["name"]
                cost_in = model_info.get("cost_per_input_token", 0.0) or 0.0
                cost_out = model_info.get("cost_per_output_token", 0.0) or 0.0

                for trans in approved:
                    result = llm.call(
                        provider=provider,
                        model_name=model_name,
                        prompt_text=trans["text"],
                        cost_per_input=cost_in,
                        cost_per_output=cost_out,
                    )
                    if result.success:
                        em.insert_token_result(
                            run_id=run_id,
                            prompt_id=prompt["id"],
                            language_id=trans["language_id"],
                            model_id=model_id,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost=result.cost,
                            source=result.source,
                        )
                        result_count += 1
                    else:
                        errors.append(
                            f"[{provider}/{model_name}] {trans['language_name']}: {result.error}"
                        )

            # Compute PEI for this prompt across all approved translations
            texts = [t["text"] for t in approved]
            if len(texts) > 1:
                pei_data = _scorer.compute_pei(texts)
                em.insert_pei_result(
                    run_id=run_id,
                    prompt_id=prompt["id"],
                    cv_char=pei_data["cv_char_length"],
                    cv_word=pei_data["cv_word_count"],
                    cv_token=pei_data["cv_token_count"],
                    pei=pei_data["pei"],
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
    return render_template(
        "experiments/detail.html",
        run=run, results=results, pei_results=pei_results
    )


@experiment_bp.route("/experiments/<int:run_id>/pei")
def pei_results(run_id: int):
    em = _em()
    run = em.get_run_by_id(run_id)
    if not run:
        flash("Experiment run not found.", "error")
        return redirect(url_for("experiment.list_experiments"))
    pei_results = em.get_pei_by_run(run_id)
    return render_template(
        "experiments/pei.html", run=run, pei_results=pei_results
    )
