"""
TokenScribe — Translation Controller
Author: Matteo Morreale
"""

import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from app.models import PromptModel, TranslationModel, StudyModel, SettingsModel
from app.services import ScoringService, LLMService

translation_bp = Blueprint("translation", __name__)

_scorer = ScoringService()


def _pm() -> PromptModel:
    return PromptModel(current_app.config["DB"])


def _tm() -> TranslationModel:
    return TranslationModel(current_app.config["DB"])


def _sm() -> StudyModel:
    return StudyModel(current_app.config["DB"])

def _setm() -> SettingsModel:
    return SettingsModel(current_app.config["DB"])

def _parse_candidate_ids() -> list[int]:
    raw_list = request.form.getlist("candidate_ids")
    raw_csv = request.form.get("candidate_ids", "")
    items = []
    if raw_list:
        items.extend(raw_list)
    if raw_csv and (not raw_list or "," in raw_csv):
        items.extend(raw_csv.split(","))
    out = []
    seen = set()
    for x in items:
        s = str(x).strip()
        if not s:
            continue
        try:
            cid = int(s)
        except Exception:
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
    return out


@translation_bp.route("/prompts/<int:prompt_id>/translations")
def list_translations(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    languages = _tm().get_all_languages()
    return render_template(
        "translations/list.html",
        prompt=prompt,
        study=study,
        candidates=candidates,
        languages=languages,
    )


@translation_bp.route("/prompts/<int:prompt_id>/translations/new", methods=["GET", "POST"])
def new_translation(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    languages = _tm().get_all_languages()
    if request.method == "POST":
        language_id = request.form.get("language_id", type=int)
        text = request.form.get("text", "").strip()
        if not language_id or not text:
            flash("Language and translation text are required.", "error")
            return render_template(
                "translations/form.html",
                prompt=prompt, study=study, languages=languages
            )
        cid = _tm().create_candidate(prompt_id, language_id, text)
        flash("Translation candidate added.", "success")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))
    return render_template(
        "translations/form.html",
        prompt=prompt, study=study, languages=languages
    )

@translation_bp.route("/prompts/<int:prompt_id>/translations/ai", methods=["POST"])
def ai_translate(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))

    language_ids_raw = request.form.getlist("language_ids")
    try:
        language_ids = sorted({int(x) for x in language_ids_raw if str(x).strip()})
    except Exception:
        flash("Invalid language selection.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    sfs_min = request.form.get("sfs_min", type=float)
    if sfs_min is None:
        flash("SFS minimum is required.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    sfs_min = max(0.0, min(1.0, float(sfs_min)))

    pei_profile = (request.form.get("pei_profile") or "homogeneous").strip()
    if pei_profile not in {"homogeneous", "moderate", "cross_script"}:
        pei_profile = "homogeneous"

    pei_max = request.form.get("pei_max", type=float)
    if pei_max is None:
        if pei_profile in {"moderate", "cross_script"}:
            pei_max = 0.35
        else:
            pei_max = 0.20
    pei_max = max(0.0, min(1.0, float(pei_max)))

    if not language_ids:
        flash("Select at least one target language.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    settings = _setm().get_all()
    llm = LLMService(settings)
    model_name = "gpt-5.4"

    languages = _tm().get_all_languages()
    lang_by_id = {l["id"]: l for l in languages}

    def _extract_json(text: str) -> dict | None:
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None

    warnings = []

    langs = []
    for language_id in language_ids:
        lang = lang_by_id.get(language_id)
        if not lang:
            warnings.append(f"Unknown language id: {language_id}")
            continue
        langs.append(lang)

    if not langs:
        flash("No valid target languages selected.", "error")
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))

    base_text = prompt["base_text"]

    def _build_prompt_text(
        lang: dict,
        sfs_target: float,
        pei_target: float,
        prev_translation: str | None,
        prev_sfs: float | None,
        structural_direction: str | None,
    ) -> str:
        direction = ""
        if prev_sfs is not None and prev_sfs < sfs_target:
            direction = "Make the translation more literal and closer to the English wording and structure."
        prompt_text = (
            "Return ONLY valid JSON (no markdown) with keys translation and back_translation.\n"
            f"Target language: {lang['name']} ({lang['code']}).\n"
            "Constraints:\n"
            "- Preserve line breaks, punctuation, bracketed placeholders, and markers like <<< >>>.\n"
            "- Preserve numbered lists, bullets, and section ordering.\n"
            "- Do not add explanations.\n"
            f"- Aim for an SFS >= {sfs_target:.4f}.\n"
            f"- Also aim for low PEI across the multilingual set (target PEI <= {pei_target:.4f}) by keeping the translation structurally comparable (similar segmentation and not wildly longer/shorter than peer translations).\n"
        )
        if direction:
            prompt_text += f"- Adjustment: {direction}\n"
        if structural_direction:
            prompt_text += f"- Structural adjustment: {structural_direction}\n"
        if prev_translation and prev_sfs is not None:
            prompt_text += (
                f"\nPrevious translation (SFS={prev_sfs:.4f}):\n"
                f"{prev_translation}\n"
            )
        prompt_text += (
            "\nText to translate (English) between <source> tags:\n"
            "<source>\n"
            f"{base_text}\n"
            "</source>\n"
        )
        return prompt_text

    def _make_candidate(
        lang: dict,
        prev_translation: str | None,
        prev_sfs: float | None,
        structural_direction: str | None,
    ) -> dict | None:
        prompt_text = _build_prompt_text(
            lang=lang,
            sfs_target=sfs_min,
            pei_target=pei_max,
            prev_translation=prev_translation,
            prev_sfs=prev_sfs,
            structural_direction=structural_direction,
        )

        result = llm.call("openai", model_name, prompt_text)
        if not result.success:
            raise RuntimeError(f"AI error ({lang['name']}): {result.error}")

        data = _extract_json(result.response_text or "")
        translation = ""
        back_translation = None
        if data and isinstance(data, dict):
            translation = str(data.get("translation", "")).strip()
            bt = str(data.get("back_translation", "")).strip()
            back_translation = bt if bt else None
        else:
            translation = (result.response_text or "").strip()

        if not translation:
            return None

        scores = _scorer.score_translation(
            original=base_text,
            translation=translation,
            back_translation=back_translation,
        )
        metrics = _scorer.compute_structural_metrics(translation)
        return {
            "translation": translation,
            "back_translation": back_translation,
            "scores": scores,
            "metrics": metrics,
        }

    def _pick_best_by_sfs(cands: list[dict]) -> dict | None:
        if not cands:
            return None
        return max(cands, key=lambda c: float(c["scores"]["sfs"]))

    def _compute_pei_from_selection(selection: dict[int, dict]) -> dict:
        texts = [selection[l["id"]]["translation"] for l in langs if l["id"] in selection]
        return _scorer.compute_pei(texts) if texts else {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0}

    def _selection_complete(selection: dict[int, dict]) -> bool:
        return all(l["id"] in selection and selection[l["id"]].get("translation") for l in langs)

    def _all_sfs_ok(selection: dict[int, dict]) -> bool:
        for l in langs:
            c = selection.get(l["id"])
            if not c:
                return False
            if float(c["scores"]["sfs"]) < sfs_min:
                return False
        return True

    def _outlier_lang_ids(selection: dict[int, dict], top_k: int = 2) -> list[int]:
        vals = []
        for l in langs:
            c = selection.get(l["id"])
            if not c:
                continue
            m = c["metrics"]
            vals.append((l["id"], float(m["char_length"]), float(m["word_count"]), float(m["token_count"])))
        if len(vals) < 2:
            return [l["id"] for l in langs]
        mean_char = sum(v[1] for v in vals) / len(vals)
        mean_word = sum(v[2] for v in vals) / len(vals)
        mean_tok = sum(v[3] for v in vals) / len(vals)
        scores = []
        for lid, ch, wd, tk in vals:
            d = 0.0
            if mean_char:
                d += abs(ch - mean_char) / mean_char
            if mean_word:
                d += abs(wd - mean_word) / mean_word
            if mean_tok:
                d += abs(tk - mean_tok) / mean_tok
            scores.append((d, lid))
        scores.sort(reverse=True)
        return [lid for _, lid in scores[: max(1, top_k)]]

    def _structural_direction_for_lang(selection: dict[int, dict], lang_id: int) -> str | None:
        other_metrics = []
        for l in langs:
            if l["id"] == lang_id:
                continue
            c = selection.get(l["id"])
            if not c:
                continue
            other_metrics.append(c["metrics"])
        if len(other_metrics) < 2:
            return None
        mean_word = sum(float(m["word_count"]) for m in other_metrics) / len(other_metrics)
        mean_char = sum(float(m["char_length"]) for m in other_metrics) / len(other_metrics)
        return (
            f"Keep roughly similar length to the peer translations: about {round(mean_word)} words and {round(mean_char)} characters, while preserving meaning and the original structure."
        )

    def _try_swap_to_reduce_pei(selection: dict[int, dict], pools_by_lang: dict[int, list[dict]]) -> tuple[dict[int, dict], dict]:
        if not _selection_complete(selection):
            return selection, {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 1.0}
        improved = True
        best_pei = _compute_pei_from_selection(selection)
        best_value = float(best_pei["pei"])
        while improved:
            improved = False
            for l in langs:
                lid = l["id"]
                pool = [c for c in pools_by_lang.get(lid, []) if float(c["scores"]["sfs"]) >= sfs_min]
                if len(pool) < 2:
                    continue
                current = selection.get(lid)
                if not current:
                    continue
                for alt in pool:
                    if alt is current:
                        continue
                    trial = dict(selection)
                    trial[lid] = alt
                    trial_pei = _compute_pei_from_selection(trial)
                    trial_value = float(trial_pei["pei"])
                    if trial_value < best_value - 1e-9:
                        selection = trial
                        best_pei = trial_pei
                        best_value = trial_value
                        improved = True
                        break
                if improved:
                    break
        return selection, best_pei

    pools_by_lang: dict[int, list[dict]] = {l["id"]: [] for l in langs}
    last_by_lang: dict[int, dict] = {l["id"]: {"translation": None, "sfs": None} for l in langs}

    max_set_rounds = 8
    candidates_per_round = 2
    regen_lang_ids = {l["id"] for l in langs}
    accepted_selection = None
    accepted_pei = None
    accepted_note = None

    for _round in range(1, max_set_rounds + 1):
        for lang in langs:
            lid = lang["id"]
            if lid not in regen_lang_ids:
                continue

            selection_now = {l_id: _pick_best_by_sfs([c for c in pools_by_lang.get(l_id, []) if float(c["scores"]["sfs"]) >= sfs_min] or pools_by_lang.get(l_id, [])) for l_id in pools_by_lang.keys()}
            selection_now = {k: v for k, v in selection_now.items() if v is not None}
            structural_direction = _structural_direction_for_lang(selection_now, lid)

            for _ in range(candidates_per_round):
                prev = last_by_lang.get(lid) or {"translation": None, "sfs": None}
                try:
                    cand = _make_candidate(
                        lang=lang,
                        prev_translation=prev.get("translation"),
                        prev_sfs=prev.get("sfs"),
                        structural_direction=structural_direction,
                    )
                except Exception as e:
                    flash(str(e), "error")
                    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
                if not cand:
                    continue
                pools_by_lang[lid].append(cand)
                last_by_lang[lid] = {"translation": cand["translation"], "sfs": float(cand["scores"]["sfs"])}

        selection = {}
        for lang in langs:
            lid = lang["id"]
            passing = [c for c in pools_by_lang.get(lid, []) if float(c["scores"]["sfs"]) >= sfs_min]
            if passing:
                selection[lid] = _pick_best_by_sfs(passing)
            else:
                selection_candidate = _pick_best_by_sfs(pools_by_lang.get(lid, []))
                if selection_candidate:
                    selection[lid] = selection_candidate

        missing = [l["id"] for l in langs if l["id"] not in selection]
        if missing:
            regen_lang_ids = set(missing)
            continue

        selection, pei = _try_swap_to_reduce_pei(selection, pools_by_lang)
        pei_value = float(pei.get("pei") or 0.0)

        if _all_sfs_ok(selection) and pei_value <= pei_max:
            accepted_selection = selection
            accepted_pei = pei
            break

        regen_lang_ids = set(_outlier_lang_ids(selection, top_k=2))

    if accepted_selection is None:
        selection = {}
        for lang in langs:
            lid = lang["id"]
            passing = [c for c in pools_by_lang.get(lid, []) if float(c["scores"]["sfs"]) >= sfs_min]
            selection[lid] = _pick_best_by_sfs(passing) or _pick_best_by_sfs(pools_by_lang.get(lid, []))
        selection = {k: v for k, v in selection.items() if v is not None}
        accepted_pei = _compute_pei_from_selection(selection) if selection else {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0}
        pei_value = float(accepted_pei.get("pei") or 0.0)
        if pei_profile == "cross_script":
            accepted_note = f"PEI high but cross-script: {pei_value:.4f}"
            flash(
                f"Set high-PEI but cross-script (PEI={pei_value:.4f}). Saving best candidates.",
                "warning",
            )
        else:
            flash(
                f"Set not accepted (PEI={pei_value:.4f} > {pei_max:.4f} and/or SFS below {sfs_min:.4f}). Saving best candidates anyway.",
                "warning",
            )
        accepted_selection = selection

    tm = _tm()
    created = 0
    for lang in langs:
        lid = lang["id"]
        cand = accepted_selection.get(lid)
        if not cand:
            continue
        translation_text = cand["translation"]
        scores = cand["scores"]
        cid = tm.create_candidate(prompt_id, lid, translation_text)
        tm.upsert_score(cid, scores["dsf"], scores["rtf"], scores["sfs"],
                        scores.get("ler_char"), scores.get("ler_token"))
        created += 1

        if float(scores["sfs"]) < sfs_min:
            warnings.append(f"{lang['name']}: best SFS {float(scores['sfs']):.4f} < {sfs_min:.4f}")

    if created:
        if accepted_pei is None:
            accepted_pei = {"pei": 0.0}
        pei_value = float(accepted_pei.get("pei") or 0.0)
        pei_band = _scorer.pei_band(pei_value)
        note = accepted_note or ""
        if not note and pei_profile == "cross_script" and pei_value > 0.35:
            note = "cross-script"
        flash(
            f"AI translations created: {created} | PEI(set)={pei_value:.4f} ({pei_band}){(' — ' + note) if note else ''}",
            "success",
        )
    if warnings:
        flash(" | ".join(warnings), "warning")

    return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))


@translation_bp.route("/translations/<int:candidate_id>/score", methods=["POST"])
def score_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    prompt = _pm().get_by_id(candidate["prompt_id"])
    back_translation = request.form.get("back_translation", "").strip() or None
    try:
        scores = _scorer.score_translation(
            original=prompt["base_text"],
            translation=candidate["text"],
            back_translation=back_translation,
        )
        tm.upsert_score(candidate_id, scores["dsf"], scores["rtf"], scores["sfs"],
                        scores.get("ler_char"), scores.get("ler_token"))
        flash(
            f'SFS={scores["sfs"]:.4f} (DSF={scores["dsf"]:.4f}, RTF={scores["rtf"]:.4f}) | '
            f'LER chr={scores.get("ler_char", 0):.3f}, tok={scores.get("ler_token", 0):.3f}',
            "success",
        )
    except Exception as e:
        flash(f"Scoring error: {e}", "error")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/approve", methods=["POST"])
def approve_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    tm.approve(candidate["prompt_id"], candidate["language_id"], candidate_id)
    flash("Translation approved.", "success")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/reject", methods=["POST"])
def reject_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if not candidate:
        flash("Candidate not found.", "error")
        return redirect(url_for("study.list_studies"))
    tm.update_status(candidate_id, "rejected")
    flash("Translation rejected.", "success")
    return redirect(
        url_for("translation.list_translations", prompt_id=candidate["prompt_id"])
    )


@translation_bp.route("/translations/<int:candidate_id>/delete", methods=["POST"])
def delete_translation(candidate_id: int):
    tm = _tm()
    candidate = tm.get_candidate_by_id(candidate_id)
    if candidate:
        prompt_id = candidate["prompt_id"]
        tm.delete_candidate(candidate_id)
        flash("Translation candidate deleted.", "success")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))
    return redirect(url_for("study.list_studies"))

@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/approve", methods=["POST"])
def bulk_approve_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    candidates = []
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        candidates.append(c)

    by_lang = {}
    duplicates = 0
    for c in candidates:
        lid = c.get("language_id")
        if not lid:
            skipped += 1
            continue
        existing = by_lang.get(lid)
        if not existing:
            by_lang[lid] = c
            continue
        duplicates += 1
        if (c.get("version") or 0) > (existing.get("version") or 0):
            by_lang[lid] = c

    updated = 0
    for c in by_lang.values():
        tm.approve(prompt_id, c["language_id"], c["id"])
        updated += 1

    if updated:
        extra = []
        if duplicates:
            extra.append(f"Duplicates: {duplicates}")
        if skipped:
            extra.append(f"Skipped: {skipped}")
        flash(f"Approved: {updated}" + (f" | " + " | ".join(extra) if extra else ""), "success")
    else:
        flash("No candidates approved.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/reject", methods=["POST"])
def bulk_reject_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    updated = 0
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        tm.update_status(cid, "rejected")
        updated += 1

    if updated:
        flash(f"Rejected: {updated}" + (f" | Skipped: {skipped}" if skipped else ""), "success")
    else:
        flash("No candidates rejected.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


@translation_bp.route("/prompts/<int:prompt_id>/translations/bulk/delete", methods=["POST"])
def bulk_delete_translations(prompt_id: int):
    tm = _tm()
    candidate_ids = _parse_candidate_ids()
    if not candidate_ids:
        flash("No candidates selected.", "warning")
        return redirect(url_for("translation.list_translations", prompt_id=prompt_id))

    deleted = 0
    skipped = 0
    for cid in candidate_ids:
        c = tm.get_candidate_by_id(cid)
        if not c or c.get("prompt_id") != prompt_id:
            skipped += 1
            continue
        tm.delete_candidate(cid)
        deleted += 1

    if deleted:
        flash(f"Deleted: {deleted}" + (f" | Skipped: {skipped}" if skipped else ""), "success")
    else:
        flash("No candidates deleted.", "warning")

    next_view = (request.form.get("next") or "").strip()
    if next_view == "prompt":
        return redirect(url_for("prompt.detail_prompt", prompt_id=prompt_id))
    return redirect(url_for("translation.list_translations", prompt_id=prompt_id))


@translation_bp.route("/prompts/<int:prompt_id>/translations/compare")
def compare_translations(prompt_id: int):
    prompt = _pm().get_by_id(prompt_id)
    if not prompt:
        flash("Prompt not found.", "error")
        return redirect(url_for("study.list_studies"))
    study = _sm().get_by_id(prompt["study_id"])
    approved = _tm().get_approved_by_prompt(prompt_id)
    candidates = _tm().get_candidates_by_prompt(prompt_id)
    return render_template(
        "translations/compare.html",
        prompt=prompt,
        study=study,
        approved=approved,
        candidates=candidates,
    )
