"""
TokenScribe — Experiment Model
Author: Matteo Morreale
"""

import logging

from .database import DatabaseManager
from config import TokenScribeConfig

_log = logging.getLogger(__name__)

_REASONING_THRESHOLD = TokenScribeConfig.REASONING_THRESHOLD


class ExperimentModel:
    def __init__(self, db: DatabaseManager):
        self.db = db

    # --- Runs ---

    def get_all_runs(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT er.*, s.name as study_name,
                          COUNT(tr.id) as result_count
                   FROM experiment_runs er
                   JOIN studies s ON s.id = er.study_id
                   LEFT JOIN token_results tr ON tr.run_id = er.id
                   GROUP BY er.id
                   ORDER BY er.timestamp DESC""",
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_runs_by_study(self, study_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT er.*, COUNT(tr.id) as result_count
                   FROM experiment_runs er
                   LEFT JOIN token_results tr ON tr.run_id = er.id
                   WHERE er.study_id=?
                   GROUP BY er.id
                   ORDER BY er.timestamp DESC""",
                (study_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_run_by_id(self, run_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT er.*, s.name as study_name
                   FROM experiment_runs er
                   JOIN studies s ON s.id = er.study_id
                   WHERE er.id=?""",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def create_run(self, study_id: int, notes: str = "") -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO experiment_runs (study_id, notes) VALUES (?, ?)",
                (study_id, notes),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def snapshot_translations(self, run_id: int, study_id: int):
        """Freeze the currently approved translations for this run.

        Must be called before any LLM calls so the snapshot reflects exactly
        which candidate was approved at run time, immune to future re-approvals.
        """
        conn = self.db.get_connection()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO run_translation_snapshot
                          (run_id, prompt_id, language_id, candidate_id)
                   SELECT ?, at.prompt_id, at.language_id, at.candidate_id
                   FROM approved_translations at
                   JOIN prompts p ON p.id = at.prompt_id
                   WHERE p.study_id = ?""",
                (run_id, study_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_invalid_token_result(
        self,
        run_id: int,
        prompt_id: int,
        language_id: int,
        model_id: int,
    ) -> None:
        """Rimuove record con response_valid=0 per questa combinazione (usato prima di un retry)."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """DELETE FROM token_results
                   WHERE run_id=? AND prompt_id=? AND language_id=? AND model_id=? AND response_valid=0""",
                (run_id, prompt_id, language_id, model_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            conn.execute("DELETE FROM experiment_runs WHERE id=?", (run_id,))
            conn.commit()
        finally:
            conn.close()

    def delete_runs_bulk(self, run_ids: list):
        if not run_ids:
            return
        conn = self.db.get_connection()
        try:
            placeholders = ",".join("?" * len(run_ids))
            conn.execute(f"DELETE FROM experiment_runs WHERE id IN ({placeholders})", run_ids)
            conn.commit()
        finally:
            conn.close()

    # --- Token Results (immutable) ---

    def insert_token_result(
        self,
        run_id: int,
        prompt_id: int,
        language_id: int,
        model_id: int,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        source: str = "api_reported",
        response_text: str = None,
        visible_output_text_length: int = None,
        api_reported_output_tokens: int = None,
        token_accounting_mode: str = None,
        normalized_output_tokens: int = None,
        visible_output_tokens: int = None,
        response_valid: bool = None,
    ) -> int:
        conn = self.db.get_connection()
        try:
            if visible_output_text_length is None:
                visible_output_text_length = len(response_text or "")
            if token_accounting_mode is None:
                token_accounting_mode = source
            if api_reported_output_tokens is None and source == "api_reported":
                api_reported_output_tokens = output_tokens
            # visible_output_tokens supersedes normalized_output_tokens
            vot = visible_output_tokens if visible_output_tokens is not None else normalized_output_tokens
            if response_valid is None:
                rv = 1 if (response_text or "").strip() and (vot is None or vot > 0) else 0
            else:
                rv = 1 if response_valid else 0

            cur = conn.execute(
                """INSERT INTO token_results
                   (run_id, prompt_id, language_id, model_id,
                    input_tokens, output_tokens,
                    visible_output_text_length, api_reported_output_tokens,
                    cost, source, token_accounting_mode, response_text,
                    normalized_output_tokens, visible_output_tokens, response_valid)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, prompt_id, language_id, model_id,
                 input_tokens, output_tokens,
                 visible_output_text_length, api_reported_output_tokens,
                 cost, source, token_accounting_mode, response_text,
                 vot, vot, rv),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_results_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT
                          tr.id,
                          tr.run_id,
                          tr.prompt_id,
                          tr.language_id,
                          tr.model_id,
                          tr.input_tokens,
                          tr.output_tokens,
                          COALESCE(tr.visible_output_text_length, LENGTH(COALESCE(tr.response_text, ''))) AS visible_output_text_length,
                          COALESCE(
                              tr.api_reported_output_tokens,
                              CASE WHEN tr.source = 'api_reported' THEN tr.output_tokens ELSE NULL END
                          ) AS api_reported_output_tokens,
                          tr.cost,
                          tr.source,
                          COALESCE(tr.token_accounting_mode, tr.source) AS token_accounting_mode,
                          tr.response_text,
                          COALESCE(tr.visible_output_tokens, tr.normalized_output_tokens) AS visible_output_tokens,
                          COALESCE(tr.response_valid, CASE WHEN COALESCE(tr.response_text, '') = '' THEN 0 ELSE 1 END) AS response_valid,
                          tr.created_at,
                          p.base_text, p.category, p.notes as prompt_notes,
                          l.name as language_name, l.code as language_code,
                          l.script_group as script_group,
                          l.morphology_group as morphology_group,
                          ws.name as writing_system,
                          m.name as model_name,
                          m.cost_per_input_token,
                          m.cost_per_output_token,
                          m.is_reasoning as is_reasoning_capable,
                          pr.name as provider_name
                   FROM token_results tr
                   JOIN prompts p ON p.id = tr.prompt_id
                   JOIN languages l ON l.id = tr.language_id
                   JOIN writing_systems ws ON ws.id = l.writing_system_id
                   JOIN models m ON m.id = tr.model_id
                   JOIN providers pr ON pr.id = m.provider_id
                   WHERE tr.run_id=?
                   ORDER BY p.id, l.name, m.name""",
                (run_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                vot = d.get("visible_output_tokens") or 0
                arot = d.get("api_reported_output_tokens") or 0
                cpi = d.get("cost_per_input_token") or 0.0
                cpo = d.get("cost_per_output_token") or 0.0
                d["visible_output_tokens"] = vot
                d["reasoning_tokens"] = max(0, arot - vot)
                d["cost_visible_only"] = round(vot * cpo / 1_000_000, 8)
                d["cost"] = round(((d.get("input_tokens") or 0) * cpi + arot * cpo) / 1_000_000, 8)
                d["ror"] = round(d["reasoning_tokens"] / vot, 3) if vot > 0 else 0.0
                is_capable = bool(d.get("is_reasoning_capable"))
                reasoning_observed = d["reasoning_tokens"] > _REASONING_THRESHOLD
                d["reasoning_observed"] = reasoning_observed
                if is_capable and reasoning_observed:
                    d["reasoning_state"] = "active"
                elif is_capable and not reasoning_observed:
                    d["reasoning_state"] = "capable_but_inactive"
                elif not is_capable and reasoning_observed:
                    d["reasoning_state"] = "anomaly"
                    _log.warning("reasoning anomaly: model=%s provider=%s run_id=%s hidden_tokens=%d",
                                 d.get("model_name"), d.get("provider_name"), run_id, d["reasoning_tokens"])
                else:
                    d["reasoning_state"] = "non_reasoning"
                results.append(d)
            return results
        finally:
            conn.close()

    # --- PEI Results ---

    def insert_pei_result(
        self,
        run_id: int,
        prompt_id: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        script_group_count: int = None,
        morphology_group_count: int = None,
        pei_band: str = None,
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_results
                   (run_id, prompt_id, cv_char_length, cv_word_count, cv_token_count, pei,
                    script_group_count, morphology_group_count, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    prompt_id,
                    cv_char,
                    cv_word,
                    cv_token,
                    pei,
                    script_group_count,
                    morphology_group_count,
                    pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_latest_pei_for_prompt(self, prompt_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                """SELECT pr.pei FROM pei_results pr
                   JOIN experiment_runs er ON er.id = pr.run_id
                   WHERE pr.prompt_id = ?
                   ORDER BY er.timestamp DESC
                   LIMIT 1""",
                (prompt_id,),
            ).fetchone()
            return float(row["pei"]) if row else None
        finally:
            conn.close()

    def get_pei_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT pr.*, p.base_text, p.category
                   FROM pei_results pr
                   JOIN prompts p ON p.id = pr.prompt_id
                   WHERE pr.run_id=?
                   ORDER BY p.id""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def insert_pei_group_result(
        self,
        run_id: int,
        prompt_id: int,
        group_type: str,
        group_value: str,
        language_count: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        pei_delta_vs_global: float,
        baseline_pei: float,
        pei_delta_vs_group: float,
        pei_band: str,
    ) -> int:
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_group_results
                   (run_id, prompt_id, group_type, group_value, language_count,
                    cv_char_length, cv_word_count, cv_token_count, pei,
                    pei_delta_vs_global, baseline_pei, pei_delta_vs_group, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    prompt_id,
                    group_type,
                    group_value,
                    language_count,
                    cv_char,
                    cv_word,
                    cv_token,
                    pei,
                    pei_delta_vs_global,
                    baseline_pei,
                    pei_delta_vs_group,
                    pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_pei_groups_by_run(self, run_id: int):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT pgr.*, p.base_text, p.category
                   FROM pei_group_results pgr
                   JOIN prompts p ON p.id = pgr.prompt_id
                   WHERE pgr.run_id=?
                   ORDER BY p.id, pgr.group_type, pgr.group_value""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # --- Models ---

    def get_all_models(self):
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT m.*, p.name as provider_name
                   FROM models m
                   JOIN providers p ON p.id = m.provider_id
                   WHERE m.is_active=1
                   ORDER BY p.name, m.name""",
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_model_by_id(self, model_id: int):
        conn = self.db.get_connection()
        try:
            row = conn.execute(
                "SELECT m.*, p.name as provider_name FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.id=?",
                (model_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_run_status(self, run_id: int, status: str) -> None:
        conn = self.db.get_connection()
        try:
            conn.execute(
                "UPDATE experiment_runs SET status = ? WHERE id = ?",
                (status, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_pei_group_partial(
        self,
        run_id: int,
        prompt_id: int,
        group_type: str,
        group_value: str,
        language_count: int,
        cv_char: float,
        cv_word: float,
        cv_token: float,
        pei: float,
        pei_delta_vs_global: float,
        pei_band: str,
    ) -> int:
        """Inserisce un record pei_group_results senza baseline (calcolata da finalize_pei_groups)."""
        conn = self.db.get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO pei_group_results
                   (run_id, prompt_id, group_type, group_value, language_count,
                    cv_char_length, cv_word_count, cv_token_count, pei,
                    pei_delta_vs_global, baseline_pei, pei_delta_vs_group, pei_band)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    run_id, prompt_id, group_type, group_value, language_count,
                    cv_char, cv_word, cv_token, pei,
                    pei_delta_vs_global, pei_band,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def update_pei_group_baselines(self, run_id: int) -> None:
        """Calcola e aggiorna baseline_pei e pei_delta_vs_group per tutti i gruppi della run."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                """UPDATE pei_group_results
                   SET baseline_pei = (
                       SELECT AVG(g2.pei) FROM pei_group_results g2
                       WHERE g2.run_id = pei_group_results.run_id
                         AND g2.group_type = pei_group_results.group_type
                         AND g2.group_value = pei_group_results.group_value
                   )
                   WHERE run_id = ?""",
                (run_id,),
            )
            conn.execute(
                """UPDATE pei_group_results
                   SET pei_delta_vs_group = ROUND(pei - baseline_pei, 6)
                   WHERE run_id = ? AND baseline_pei IS NOT NULL""",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run_snapshot_inputs(self, run_id: int, prompt_id: int) -> list[dict]:
        """
        Restituisce i testi (base_text inglese + traduzioni approvate snapshot) per un prompt
        in una run, con i metadati di lingua necessari per il calcolo PEI.
        """
        conn = self.db.get_connection()
        try:
            # Inglese (base_text del prompt)
            prompt_row = conn.execute(
                "SELECT base_text FROM prompts WHERE id = ?", (prompt_id,)
            ).fetchone()
            en_row = conn.execute(
                "SELECT id, name, code, script_group, morphology_group FROM languages WHERE code = 'en'"
            ).fetchone()

            inputs = []
            if prompt_row and en_row:
                inputs.append({
                    "language_id":       int(en_row["id"]),
                    "language_name":     en_row["name"],
                    "language_code":     en_row["code"],
                    "script_group":      en_row["script_group"] or "alphabetic",
                    "morphology_group":  en_row["morphology_group"] or "",
                    "text":              prompt_row["base_text"],
                })

            # Traduzioni dalla snapshot
            rows = conn.execute(
                """SELECT tc.text,
                          l.id as language_id, l.name as language_name,
                          l.code as language_code,
                          l.script_group, l.morphology_group
                   FROM run_translation_snapshot rts
                   JOIN translation_candidates tc ON tc.id = rts.candidate_id
                   JOIN languages l ON l.id = rts.language_id
                   WHERE rts.run_id = ? AND rts.prompt_id = ? AND l.code != 'en'""",
                (run_id, prompt_id),
            ).fetchall()
            for r in rows:
                inputs.append({
                    "language_id":      int(r["language_id"]),
                    "language_name":    r["language_name"],
                    "language_code":    r["language_code"],
                    "script_group":     r["script_group"] or "alphabetic",
                    "morphology_group": r["morphology_group"] or "",
                    "text":             r["text"],
                })
            return inputs
        finally:
            conn.close()

    # --- Run History (archivio per redo/replace) ---

    def archive_model_results(
        self,
        run_id: int,
        model_id: int,
        model_name: str,
        reason: str,
        replaced_by_model_id: int = None,
        replaced_by_model_name: str = None,
    ) -> int:
        """Salva in run_history i token_results correnti per un modello. Ritorna l'id del record."""
        import json as _json
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT tr.*, m.name as model_name, p.base_text,
                          l.name as language_name, l.code as language_code
                   FROM token_results tr
                   JOIN models m ON m.id = tr.model_id
                   JOIN prompts p ON p.id = tr.prompt_id
                   JOIN languages l ON l.id = tr.language_id
                   WHERE tr.run_id=? AND tr.model_id=?""",
                (run_id, model_id),
            ).fetchall()
            results = [dict(r) for r in rows]
            cur = conn.execute(
                """INSERT INTO run_history
                   (run_id, model_id, model_name, reason,
                    replaced_by_model_id, replaced_by_model_name, results_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, model_id, model_name, reason,
                    replaced_by_model_id, replaced_by_model_name,
                    _json.dumps(results, default=str),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def delete_model_results(self, run_id: int, model_id: int) -> int:
        """Elimina tutti i token_results di un modello in una run."""
        conn = self.db.get_connection()
        try:
            conn.execute(
                "DELETE FROM token_results WHERE run_id=? AND model_id=?",
                (run_id, model_id),
            )
            conn.commit()
            return conn.execute("SELECT changes()").fetchone()[0]
        finally:
            conn.close()

    def get_run_history(self, run_id: int) -> list[dict]:
        """Ritorna le voci di storico archiviate per una run."""
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT id, run_id, model_id, model_name, archived_at, reason,
                          replaced_by_model_id, replaced_by_model_name
                   FROM run_history WHERE run_id=? ORDER BY archived_at DESC""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def reconstruct_llm_payloads(self, run_id: int, model_id: int) -> list[dict]:
        """Ricostruisce i payload llm_call da token_results + snapshot (run senza queue items)."""
        conn = self.db.get_connection()
        try:
            model_row = conn.execute(
                """SELECT m.*, p.name as provider_name
                   FROM models m JOIN providers p ON p.id=m.provider_id WHERE m.id=?""",
                (model_id,),
            ).fetchone()
            if not model_row:
                return []
            model = dict(model_row)

            run_row = conn.execute(
                "SELECT study_id FROM experiment_runs WHERE id=?", (run_id,)
            ).fetchone()
            study_id = int(run_row["study_id"]) if run_row else None

            result_rows = conn.execute(
                "SELECT DISTINCT prompt_id, language_id FROM token_results WHERE run_id=? AND model_id=?",
                (run_id, model_id),
            ).fetchall()

            payloads = []
            for r in result_rows:
                prompt_id   = r["prompt_id"]
                language_id = r["language_id"]

                lang_row = conn.execute(
                    "SELECT name, code, script_group, morphology_group FROM languages WHERE id=?",
                    (language_id,),
                ).fetchone()
                if not lang_row:
                    continue
                lang = dict(lang_row)

                if lang["code"] == "en":
                    p_row = conn.execute(
                        "SELECT base_text FROM prompts WHERE id=?", (prompt_id,)
                    ).fetchone()
                    text = p_row["base_text"] if p_row else None
                else:
                    snap_row = conn.execute(
                        """SELECT tc.text FROM run_translation_snapshot rts
                           JOIN translation_candidates tc ON tc.id = rts.candidate_id
                           WHERE rts.run_id=? AND rts.prompt_id=? AND rts.language_id=?""",
                        (run_id, prompt_id, language_id),
                    ).fetchone()
                    text = snap_row["text"] if snap_row else None

                if not text:
                    continue

                payloads.append({
                    "run_id":        run_id,
                    "study_id":      study_id,
                    "prompt_id":     prompt_id,
                    "language_id":   language_id,
                    "language_name": lang["name"],
                    "language_code": lang["code"],
                    "model_id":      model_id,
                    "provider":      model["provider_name"],
                    "model_name":    model["name"],
                    "cost_per_input":  float(model.get("cost_per_input_token") or 0.0),
                    "cost_per_output": float(model.get("cost_per_output_token") or 0.0),
                    "is_reasoning":    bool(model.get("is_reasoning", 0)),
                    "text":          text,
                })
            return payloads
        finally:
            conn.close()

    def get_translation_scores_by_run(self, run_id: int) -> list:
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                """SELECT DISTINCT snap.prompt_id, snap.language_id,
                          l.name  AS language_name,
                          l.code  AS language_code,
                          p.base_text,
                          ts.dsf, ts.rtf, ts.sfs, ts.ler_char, ts.ler_token,
                          ts.computed_at,
                          ssr.score_absolute AS magi_score_absolute,
                          ssr.score_rank     AS magi_score_rank,
                          ssr.score_rank_pct AS magi_score_rank_pct,
                          ssr.magi_required,
                          ssr.magi_score,
                          ssr.magi_disagreement,
                          ssr.magi_judges
                   FROM token_results tr
                   JOIN run_translation_snapshot snap
                        ON snap.run_id = tr.run_id
                       AND snap.prompt_id = tr.prompt_id
                       AND snap.language_id = tr.language_id
                   JOIN translation_scores ts ON ts.candidate_id = snap.candidate_id
                   JOIN languages l ON l.id = snap.language_id
                   JOIN prompts p ON p.id = snap.prompt_id
                   LEFT JOIN selection_score_results ssr ON ssr.candidate_id = snap.candidate_id
                   WHERE tr.run_id = ?
                   ORDER BY snap.prompt_id, l.name""",
                (run_id,),
            ).fetchall()
            import json as _json
            result = []
            for r in rows:
                d = dict(r)
                if d.get("magi_judges"):
                    try:
                        d["magi_judges"] = _json.loads(d["magi_judges"])
                    except (ValueError, TypeError):
                        d["magi_judges"] = None
                result.append(d)
            return result
        finally:
            conn.close()
