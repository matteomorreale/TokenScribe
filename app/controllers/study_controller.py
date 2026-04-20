"""
TokenScribe — Study Controller
Author: Matteo Morreale
"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import StudyModel

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
    return render_template("studies/list.html", studies=studies)


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
    from app.models import PromptModel, ExperimentModel
    prompts = PromptModel(current_app.config["DB"]).get_by_study(study_id)
    runs = ExperimentModel(current_app.config["DB"]).get_runs_by_study(study_id)
    return render_template(
        "studies/detail.html", study=study, prompts=prompts, runs=runs
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
