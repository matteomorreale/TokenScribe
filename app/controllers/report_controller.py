"""
TokenScribe — Report Controller
Author: Matteo Morreale
"""

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app, Response
)
from app.models import StudyModel, ExperimentModel, PromptModel
from app.services import ExportService

report_bp = Blueprint("report", __name__, url_prefix="/reports")


def _em() -> ExperimentModel:
    return ExperimentModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


@report_bp.route("/")
def reports_dashboard():
    studies = _sm().get_all()
    runs = _em().get_all_runs()
    return render_template("reports/dashboard.html", studies=studies, runs=runs)


@report_bp.route("/export/csv")
def export_csv():
    run_id = request.args.get("run_id", type=int)
    if not run_id:
        flash("Specify a run_id to export.", "error")
        return redirect(url_for("report.reports_dashboard"))
    results = _em().get_results_by_run(run_id)
    csv_data = ExportService.to_csv(results)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tokenscribe_run_{run_id}.csv"},
    )


@report_bp.route("/export/json")
def export_json():
    run_id = request.args.get("run_id", type=int)
    if not run_id:
        flash("Specify a run_id to export.", "error")
        return redirect(url_for("report.reports_dashboard"))
    results = _em().get_results_by_run(run_id)
    pei = _em().get_pei_by_run(run_id)
    json_data = ExportService.to_json(results, pei)
    return Response(
        json_data,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=tokenscribe_run_{run_id}.json"},
    )


@report_bp.route("/scores")
def scores_view():
    run_id = request.args.get("run_id", type=int)
    runs = _em().get_all_runs()
    results = []
    pei_results = []
    selected_run = None
    if run_id:
        selected_run = _em().get_run_by_id(run_id)
        results = _em().get_results_by_run(run_id)
        pei_results = _em().get_pei_by_run(run_id)
    return render_template(
        "reports/scores.html",
        runs=runs,
        selected_run=selected_run,
        results=results,
        pei_results=pei_results,
    )


@report_bp.route("/studies/<int:study_id>")
def study_report(study_id: int):
    study = _sm().get_by_id(study_id)
    if not study:
        flash("Study not found.", "error")
        return redirect(url_for("report.reports_dashboard"))
    prompts = _pm().get_by_study(study_id)
    runs = _em().get_runs_by_study(study_id)
    all_results = []
    for run in runs:
        all_results.extend(_em().get_results_by_run(run["id"]))
    return render_template(
        "reports/study_report.html",
        study=study,
        prompts=prompts,
        runs=runs,
        results=all_results,
    )
