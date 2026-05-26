"""
TokenScribe — Log Controller
Author: Matteo Morreale

Provides the log viewer UI and a JSON API endpoint for auto-refresh.
"""

from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for, flash
from app.models.log_model import LogModel

log_bp = Blueprint("log", __name__)

_PAGE_SIZE = 100


def _lm() -> LogModel:
    return LogModel(current_app.config["DB"])


@log_bp.route("/logs")
def log_list():
    lm = _lm()
    filters = _parse_filters()
    logs = lm.get_logs(limit=_PAGE_SIZE, offset=0, **filters)
    total = lm.count_logs(**filters)
    stats = lm.get_stats()
    distinct = lm.get_distinct_values()
    return render_template(
        "logs/list.html",
        logs=logs,
        total=total,
        page_size=_PAGE_SIZE,
        filters=filters,
        stats=stats,
        distinct=distinct,
    )


@log_bp.route("/logs/api")
def log_api():
    """JSON endpoint for live-tail / auto-refresh via fetch()."""
    lm = _lm()
    filters = _parse_filters()
    limit = min(request.args.get("limit", _PAGE_SIZE, type=int), 500)
    offset = request.args.get("offset", 0, type=int)
    logs = lm.get_logs(limit=limit, offset=offset, **filters)
    total = lm.count_logs(**filters)
    return jsonify({"logs": logs, "total": total, "limit": limit, "offset": offset})


@log_bp.route("/logs/clear", methods=["POST"])
def log_clear():
    """Delete all log entries."""
    lm = _lm()
    deleted = lm.delete_all()
    flash(f"Log cleared: {deleted} entries deleted.", "success")
    return redirect(url_for("log.log_list"))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_filters() -> dict:
    return {
        "operation_type": request.args.get("operation_type") or None,
        "level": request.args.get("level") or None,
        "provider": request.args.get("provider") or None,
        "model": request.args.get("model") or None,
        "event": request.args.get("event") or None,
        "search": request.args.get("search") or None,
    }
