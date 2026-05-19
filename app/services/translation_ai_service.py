"""
TokenScribe — AI Translation Service
Author: Matteo Morreale
"""

import json
from .scoring_service import ScoringService
from .llm_service import LLMService
from app.models.translation_model import TranslationModel

_scorer = ScoringService()


def run_ai_translate(
    prompt: dict,
    language_ids: list,
    sfs_min: float,
    pei_profile: str,
    pei_max: float,
    candidates_per_lang: int,
    db,
    settings: dict,
    log_service=None,
) -> dict:
    """
    AI-generate translations for a single prompt across the given language IDs.

    Returns:
        created: int
        warnings: list[str]
        accepted_pei: dict | None
        accepted: bool — True if optimization converged, False if fallback
        note: str — PEI note for the success flash
        langs: list[dict]
        candidates_by_lang: dict[int, list[int]]  — lang_id -> [candidate_id, ...]

    Raises:
        RuntimeError — if an LLM call fails
    """
    tm = TranslationModel(db)
    llm = LLMService(settings, log_service=log_service)
    model_name = "gpt-5.5"

    languages = tm.get_all_languages()
    lang_by_id = {l["id"]: l for l in languages}

    prompt_id = prompt["id"]
    base_text = prompt["base_text"]
    warnings = []
    langs = []
    for lid in sorted({int(x) for x in language_ids}):
        lang = lang_by_id.get(lid)
        if not lang:
            warnings.append(f"Unknown language id: {lid}")
        else:
            langs.append(lang)

    if not langs:
        return {
            "created": 0,
            "warnings": warnings,
            "accepted_pei": None,
            "accepted": False,
            "note": "",
            "langs": [],
            "candidates_by_lang": {},
        }

    def _extract_json(text):
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None

    def _build_prompt_text(lang, sfs_target, pei_target, prev_translation, prev_sfs, structural_direction):
        direction = ""
        if prev_sfs is not None and prev_sfs < sfs_target:
            direction = "Make the translation more literal and closer to the English wording and structure."
        pt = (
            "Return ONLY valid JSON (no markdown) with keys translation and back_translation.\n"
            f"Target language: {lang['name']} ({lang['code']}).\n"
            "Constraints:\n"
            "- Preserve line breaks, punctuation, bracketed placeholders, and markers like <input> </input>.\n"
            "- Preserve numbered lists, bullets, and section ordering.\n"
            "- Do not add explanations.\n"
            f"- Aim for an SFS >= {sfs_target:.4f}.\n"
            f"- Also aim for low PEI across the multilingual set (target PEI <= {pei_target:.4f}) by keeping the translation structurally comparable (similar segmentation and not wildly longer/shorter than peer translations).\n"
        )
        if direction:
            pt += f"- Adjustment: {direction}\n"
        if structural_direction:
            pt += f"- Structural adjustment: {structural_direction}\n"
        if prev_translation and prev_sfs is not None:
            pt += (
                f"\nPrevious translation (SFS={prev_sfs:.4f}):\n"
                f"{prev_translation}\n"
            )
        pt += (
            "\nText to translate (English) between <source> tags:\n"
            "<source>\n"
            f"{base_text}\n"
            "</source>\n"
        )
        return pt

    def _make_candidate(lang, prev_translation, prev_sfs, structural_direction):
        prompt_text = _build_prompt_text(
            lang=lang,
            sfs_target=sfs_min,
            pei_target=pei_max,
            prev_translation=prev_translation,
            prev_sfs=prev_sfs,
            structural_direction=structural_direction,
        )
        ai_ctx = {
            "operation_type": "translation_ai",
            "prompt_id": prompt_id,
            "language": lang.get("name", ""),
            "language_code": lang.get("code", ""),
        }
        result = llm.call("openai", model_name, prompt_text, _ctx=ai_ctx)
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

    def _pick_best_by_sfs(cands):
        if not cands:
            return None
        return max(cands, key=lambda c: float(c["scores"]["sfs"]))

    def _compute_pei_from_selection(selection):
        texts = [selection[l["id"]]["translation"] for l in langs if l["id"] in selection]
        return _scorer.compute_pei(texts) if texts else {
            "cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0,
        }

    def _selection_complete(selection):
        return all(l["id"] in selection and selection[l["id"]].get("translation") for l in langs)

    def _all_sfs_ok(selection):
        for l in langs:
            c = selection.get(l["id"])
            if not c or float(c["scores"]["sfs"]) < sfs_min:
                return False
        return True

    def _outlier_lang_ids(selection, top_k=2):
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
        scores_list = []
        for lid, ch, wd, tk in vals:
            d = 0.0
            if mean_char:
                d += abs(ch - mean_char) / mean_char
            if mean_word:
                d += abs(wd - mean_word) / mean_word
            if mean_tok:
                d += abs(tk - mean_tok) / mean_tok
            scores_list.append((d, lid))
        scores_list.sort(reverse=True)
        return [lid for _, lid in scores_list[:max(1, top_k)]]

    def _structural_direction_for_lang(selection, lang_id):
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
            f"Keep roughly similar length to the peer translations: about {round(mean_word)} words "
            f"and {round(mean_char)} characters, while preserving meaning and the original structure."
        )

    def _try_swap_to_reduce_pei(selection, pools_by_lang):
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

    pools_by_lang: dict = {l["id"]: [] for l in langs}
    last_by_lang: dict = {l["id"]: {"translation": None, "sfs": None} for l in langs}

    max_set_rounds = 8
    regen_lang_ids = {l["id"] for l in langs}
    accepted_selection = None
    accepted_pei = None
    accepted_note = ""

    for _round in range(1, max_set_rounds + 1):
        for lang in langs:
            lid = lang["id"]
            if lid not in regen_lang_ids:
                continue
            selection_now = {
                l_id: _pick_best_by_sfs(
                    [c for c in pools_by_lang.get(l_id, []) if float(c["scores"]["sfs"]) >= sfs_min]
                    or pools_by_lang.get(l_id, [])
                )
                for l_id in pools_by_lang.keys()
            }
            selection_now = {k: v for k, v in selection_now.items() if v is not None}
            structural_direction = _structural_direction_for_lang(selection_now, lid)
            for _ in range(candidates_per_lang):
                prev = last_by_lang.get(lid) or {"translation": None, "sfs": None}
                cand = _make_candidate(
                    lang=lang,
                    prev_translation=prev.get("translation"),
                    prev_sfs=prev.get("sfs"),
                    structural_direction=structural_direction,
                )
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
                sel = _pick_best_by_sfs(pools_by_lang.get(lid, []))
                if sel:
                    selection[lid] = sel

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
        accepted_pei = _compute_pei_from_selection(selection) if selection else {
            "cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0,
        }
        pei_value = float(accepted_pei.get("pei") or 0.0)
        if pei_profile == "cross_script":
            accepted_note = f"PEI high but cross-script: {pei_value:.4f}"
        else:
            accepted_note = f"Set not accepted (PEI={pei_value:.4f} > {pei_max:.4f} and/or SFS below {sfs_min:.4f})"
        accepted_selection = selection

    # Persist candidates and collect IDs by language
    created = 0
    candidates_by_lang: dict = {}
    for lang in langs:
        lid = lang["id"]
        pool = pools_by_lang.get(lid, [])
        lang_cids = []
        for cand in pool:
            scores = cand["scores"]
            cid = tm.create_candidate(prompt_id, lid, cand["translation"])
            tm.upsert_score(cid, scores["dsf"], scores["rtf"], scores["sfs"],
                            scores.get("ler_char"), scores.get("ler_token"))
            lang_cids.append(cid)
            created += 1
        candidates_by_lang[lid] = lang_cids
        best = _pick_best_by_sfs(pool)
        if best and float(best["scores"]["sfs"]) < sfs_min:
            warnings.append(f"{lang['name']}: best SFS {float(best['scores']['sfs']):.4f} < {sfs_min:.4f}")

    return {
        "created": created,
        "warnings": warnings,
        "accepted_pei": accepted_pei,
        "accepted": accepted_selection is not None and accepted_note == "",
        "note": accepted_note,
        "langs": langs,
        "candidates_by_lang": candidates_by_lang,
    }
