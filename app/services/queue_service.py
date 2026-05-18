"""
TokenScribe — QueueService
Author: Matteo Morreale

Daemon thread che processa la run_queue un item alla volta.
Ogni operazione è atomica e ha il proprio timeout.
Alla fine di ogni item aggiorna lo status della RUN.
"""

import concurrent.futures
import logging
import time
import threading

from app.models.database import DatabaseManager
from app.models.queue_model import QueueModel, RUN_RUNNING, RUN_QUEUED
from app.models.experiment_model import ExperimentModel
from app.models.settings_model import SettingsModel
from app.models.selection_score_model import SelectionScoreModel

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Sollevato quando un provider risponde 429 — l'item va rimesso in fondo alla coda."""

_PROVIDER_KEY_MAP = {
    "openai":    "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google":    "google_api_key",
    "deepseek":  "deepseek_api_key",
    "meta":      "meta_api_key",
    "qwen":      "qwen_api_key",
    "mistral":   "mistral_api_key",
}

# Timeout per tipo di operazione (secondi)
_TIMEOUTS = {
    "snapshot_translations": 15,
    "magi_phase2":           150,
    "llm_call":              150,
    "compute_pei":           45,
    "finalize_pei_groups":   30,
}

_POLL_INTERVAL = 2  # secondi tra un poll e il successivo quando la coda è vuota

# Language codes whose scripts are logographic (CJK + related).
# Used to pick the right suspicion threshold for inflated API token counts.
_LOGOGRAPHIC_PREFIXES = {"zh", "ja", "ko", "yue", "wuu", "hak", "nan"}


def _is_logographic(language_code: str) -> bool:
    return (language_code or "").lower()[:3].rstrip("-") in _LOGOGRAPHIC_PREFIXES or \
           (language_code or "").lower()[:2] in _LOGOGRAPHIC_PREFIXES


def _local_visible_token_count(text: str) -> int:
    """Count tokens in *text* with tiktoken cl100k_base as a provider-neutral proxy."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return 0


class QueueService:
    """
    Singleton daemon worker per la run_queue.

    Uso:
        qs = QueueService(db, log_service=log_svc)
        qs.start()
    """

    def __init__(self, db: DatabaseManager, log_service=None, crypto_service=None):
        self._db = db
        self._log = log_service
        self._crypto = crypto_service
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="ts-queue-worker",
        )
        # ScoringService è stateless/locale — istanza condivisa sicura
        from app.services.scoring_service import ScoringService
        self._scorer = ScoringService()

    def start(self) -> None:
        self._thread.start()
        logger.info("QueueService started (daemon thread)")

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        qm = QueueModel(self._db)
        while not self._stop.is_set():
            try:
                item = qm.dequeue_next()
                if item is None:
                    time.sleep(_POLL_INTERVAL)
                    continue

                run_id   = item["run_id"]
                item_id  = item["id"]
                op_type  = item["operation_type"]
                payload  = item["payload"]
                timeout  = _TIMEOUTS.get(op_type, 120)

                logger.info("Queue: processing item %d run=%d op=%s", item_id, run_id, op_type)
                qm.update_run_status(run_id, RUN_RUNNING)

                # Esegui l'operazione con timeout in un sub-thread
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(self._dispatch, op_type, payload)
                    try:
                        future.result(timeout=timeout)
                        qm.mark_done(item_id)
                        logger.info("Queue: item %d done", item_id)
                    except concurrent.futures.TimeoutError:
                        future.cancel()
                        qm.mark_timeout(item_id)
                        logger.warning("Queue: item %d TIMEOUT (op=%s, %ds)", item_id, op_type, timeout)
                        if self._log:
                            self._log.error(
                                "queue", "item_timeout",
                                message=f"Item {item_id} op={op_type} run={run_id} timed out after {timeout}s",
                                context_ref={"run_id": run_id, "item_id": item_id},
                            )
                    except RateLimitError as exc:
                        requeued = qm.requeue_at_end(item_id)
                        if requeued:
                            logger.warning(
                                "Queue: item %d RATE LIMITED (op=%s run=%d) — rimesso in coda: %s",
                                item_id, op_type, run_id, exc,
                            )
                            if self._log:
                                self._log.error(
                                    "queue", "rate_limit",
                                    message=f"Item {item_id} op={op_type} run={run_id} rate limited, requeued: {exc}",
                                    context_ref={"run_id": run_id, "item_id": item_id},
                                )
                        else:
                            logger.error(
                                "Queue: item %d RATE LIMITED max retries exceeded (op=%s run=%d)",
                                item_id, op_type, run_id,
                            )
                            if self._log:
                                self._log.error(
                                    "queue", "rate_limit_failed",
                                    message=f"Item {item_id} op={op_type} run={run_id} rate limited, max retries exceeded",
                                    context_ref={"run_id": run_id, "item_id": item_id},
                                )
                    except Exception as exc:
                        qm.mark_error(item_id, str(exc))
                        logger.exception("Queue: item %d ERROR: %s", item_id, exc)
                        if self._log:
                            self._log.error(
                                "queue", "item_error",
                                message=f"Item {item_id} op={op_type} run={run_id}: {exc}",
                                context_ref={"run_id": run_id, "item_id": item_id},
                            )

                # Aggiorna lo status della RUN dopo ogni item
                qm.recompute_run_status(run_id)

            except Exception:
                logger.exception("QueueService: unexpected error in worker loop")
                time.sleep(1)

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _dispatch(self, op_type: str, payload: dict) -> None:
        dispatch_map = {
            "snapshot_translations": self._exec_snapshot,
            "magi_phase2":           self._exec_magi_phase2,
            "llm_call":              self._exec_llm_call,
            "compute_pei":           self._exec_compute_pei,
            "finalize_pei_groups":   self._exec_finalize_pei_groups,
        }
        handler = dispatch_map.get(op_type)
        if handler is None:
            raise ValueError(f"Unknown operation type: {op_type}")
        handler(payload)

    # ------------------------------------------------------------------
    # Operatori
    # ------------------------------------------------------------------

    def _exec_snapshot(self, payload: dict) -> None:
        run_id   = int(payload["run_id"])
        study_id = int(payload["study_id"])
        em = ExperimentModel(self._db)
        em.snapshot_translations(run_id, study_id)

    def _exec_magi_phase2(self, payload: dict) -> None:
        from app.services.magi_service import MAGIService
        from app.services.llm_service import LLMService

        run_id       = int(payload["run_id"])
        candidate_id = int(payload["candidate_id"])
        prompt_id    = int(payload["prompt_id"])

        settings  = SettingsModel(self._db, crypto=self._crypto).get_all()
        em        = ExperimentModel(self._db)
        ssm       = SelectionScoreModel(self._db)

        judge_id_vals = [
            settings.get("magi_judge_balthasar_id"),
            settings.get("magi_judge_caspar_id"),
            settings.get("magi_judge_melchior_id"),
        ]
        if not all(judge_id_vals):
            raise ValueError("MAGI judge IDs not fully configured")
        judge_models = [em.get_model_by_id(int(jid)) for jid in judge_id_vals]
        judge_models = [m for m in judge_models if m]
        if len(judge_models) != 3:
            raise ValueError("One or more MAGI judge models not found in DB")

        llm_magi = LLMService(settings, log_service=self._log)
        magi_svc = MAGIService()

        magi_ctx = {
            "operation_type": "magi",
            "run_id": run_id,
            "prompt_id": prompt_id,
            "candidate_id": candidate_id,
        }
        panel = magi_svc.run_panel(
            original=payload["base_text"],
            translation=payload["translation_text"],
            language=payload["language_name"],
            sfs=float(payload.get("sfs") or 0.0),
            ler_char=float(payload.get("ler_char") or 1.0),
            llm_service=llm_magi,
            judge_models=judge_models,
            log_service=self._log,
            context_ref=magi_ctx,
        )
        if panel.get("magi_offline"):
            raise RuntimeError(f"MAGI offline: {panel.get('magi_offline_reason', 'unknown')}")

        ssm.update_magi_result(
            candidate_id=candidate_id,
            magi_score=panel["magi_score"],
            magi_disagreement=panel["magi_disagreement"],
            magi_judges=panel["judges"],
        )

    def _get_fallback_model(self, provider_name: str, exclude_model_id: int,
                            original_model_name: str = "") -> dict | None:
        conn = self._db.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT m.id, m.name, m.is_reasoning,
                       m.cost_per_input_token, m.cost_per_output_token
                FROM models m
                JOIN providers p ON p.id = m.provider_id
                WHERE p.name = ? AND m.is_active = 1 AND m.id != ?
                ORDER BY m.id DESC
                """,
                (provider_name, exclude_model_id),
            ).fetchall()
            if not rows:
                return None
            # Prefer same-tier model (e.g. flash→flash, sonnet→sonnet, turbo→turbo)
            _TIERS = ["flash", "sonnet", "haiku", "opus", "turbo", "pro", "mini", "nano"]
            orig = original_model_name.lower()
            for tier in _TIERS:
                if tier in orig:
                    same_tier = [r for r in rows if tier in r["name"].lower()]
                    if same_tier:
                        return dict(same_tier[0])
            return dict(rows[0])
        finally:
            conn.close()

    def _exec_llm_call(self, payload: dict) -> None:
        from app.services.llm_service import LLMService

        run_id      = int(payload["run_id"])
        prompt_id   = int(payload["prompt_id"])
        language_id = int(payload["language_id"])
        model_id    = int(payload["model_id"])

        settings = SettingsModel(self._db, crypto=self._crypto).get_all()
        llm      = LLMService(settings, log_service=self._log)
        em       = ExperimentModel(self._db)

        # Re-read is_reasoning from DB at execution time: the payload may have been
        # serialised before the user toggled the flag in settings.
        _conn = self._db.get_connection()
        try:
            _row = _conn.execute(
                "SELECT is_reasoning FROM models WHERE id=?", (model_id,)
            ).fetchone()
            is_reasoning = bool(_row["is_reasoning"]) if _row else bool(payload.get("is_reasoning", False))
        finally:
            _conn.close()

        # Apply per-run reasoning override if set ('on' or 'off').
        _override = (payload.get("reasoning_override") or "").strip()
        if _override == "on":
            is_reasoning = True
        elif _override == "off":
            is_reasoning = False

        llm_ctx = {
            "operation_type": "experiment",
            "run_id": run_id,
            "study_id": payload.get("study_id"),
            "prompt_id": prompt_id,
            "language": payload.get("language_name", ""),
            "language_code": payload.get("language_code", ""),
        }
        repetition_index = int(payload.get("repetition_index", 0))

        result = llm.call(
            provider=payload["provider"],
            model_name=payload["model_name"],
            prompt_text=payload["text"],
            cost_per_input=float(payload.get("cost_per_input") or 0.0),
            cost_per_output=float(payload.get("cost_per_output") or 0.0),
            is_reasoning=is_reasoning,
            _ctx=llm_ctx,
        )
        if not result.success and (result.rate_limited or result.timed_out):
            raise RateLimitError(result.error)

        if not result.success and result.model_not_found:
            fallback = self._get_fallback_model(payload["provider"], model_id, payload["model_name"])
            if fallback:
                logger.warning(
                    "Model %s (id=%d) not found, retrying with fallback %s (id=%d)",
                    payload["model_name"], model_id, fallback["name"], fallback["id"],
                )
                result = llm.call(
                    provider=payload["provider"],
                    model_name=fallback["name"],
                    prompt_text=payload["text"],
                    cost_per_input=float(fallback.get("cost_per_input_token") or 0.0),
                    cost_per_output=float(fallback.get("cost_per_output_token") or 0.0),
                    is_reasoning=bool(fallback.get("is_reasoning", False)),
                    _ctx=llm_ctx,
                )
                if result.success:
                    model_id = fallback["id"]
                elif result.rate_limited or result.timed_out:
                    raise RateLimitError(result.error)

        # model_id is now final (possibly updated to fallback). attempt_index is
        # computed atomically inside insert_token_result via a MAX+1 subquery.
        if not result.success:
            em.insert_token_result(
                run_id=run_id,
                prompt_id=prompt_id,
                language_id=language_id,
                model_id=model_id,
                input_tokens=0,
                output_tokens=0,
                cost=0.0,
                response_text=result.error,
                response_valid=False,
                repetition_index=repetition_index,
                attempt_status="failed",
            )
            raise RuntimeError(f"LLM call failed: {result.error}")

        has_text = bool((result.response_text or "").strip())
        response_text = result.response_text or ""
        char_len = len(response_text)
        api_output = result.output_tokens
        lang_code = payload.get("language_code", "")

        # Sanity-check: if tokens-per-character exceeds a plausibility ceiling the
        # provider is bundling undisclosed reasoning tokens into completion_tokens.
        # This is known for Qwen reasoning models but the check is provider-agnostic
        # so any future offender is caught automatically.
        # Ceilings: alphabetic scripts ~4 chars/token → 2.0 tok/char is already 2×
        # the worst-case; logographic scripts (CJK) are denser → 1.5 tok/char.
        _use_local = False
        if has_text and char_len > 0 and api_output > 0:
            tpc = api_output / char_len
            threshold = 1.5 if _is_logographic(lang_code) else 2.0
            if tpc > threshold:
                _use_local = True
                logger.warning(
                    "Inflated API token count detected: provider=%s model=%s "
                    "lang=%s api_output=%d char_len=%d tpc=%.2f threshold=%.1f — "
                    "recomputing visible_output_tokens via tiktoken",
                    payload.get("provider", "?"), payload.get("model_name", "?"),
                    lang_code or "?", api_output, char_len, tpc, threshold,
                )

        if _use_local:
            local_toks = _local_visible_token_count(response_text)
            if local_toks > 0:
                visible_output_tokens = local_toks
                result.reasoning_tokens = max(0, api_output - local_toks)
            else:
                visible_output_tokens = max(0, api_output - result.reasoning_tokens)
        else:
            visible_output_tokens = api_output - result.reasoning_tokens
            # Some xAI models report reasoning_tokens == completion_tokens even
            # when there is visible output; fall back to the total.
            if has_text and visible_output_tokens <= 0 and api_output > 0:
                visible_output_tokens = api_output

        is_valid = has_text

        em.insert_token_result(
            run_id=run_id,
            prompt_id=prompt_id,
            language_id=language_id,
            model_id=model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost=result.cost,
            source=result.source,
            response_text=result.response_text,
            visible_output_tokens=visible_output_tokens,
            response_valid=is_valid,
            repetition_index=repetition_index,
            attempt_status="success" if is_valid else "failed",
        )

        if not is_valid:
            raw_len = len(result.response_text or "")
            msg = (
                f"Empty visible output — model={payload['model_name']} "
                f"provider={payload.get('provider', '?')} "
                f"prompt={prompt_id} lang={payload.get('language_name', '?')} "
                f"[raw_len={raw_len} input_tok={result.input_tokens} output_tok={result.output_tokens}]"
            )
            logger.error("Queue: LLM empty response: %s", msg)
            if self._log:
                self._log.error(
                    "queue", "empty_response",
                    message=msg,
                    context_ref={
                        "run_id": run_id,
                        "prompt_id": prompt_id,
                        "language_id": language_id,
                        "model_id": model_id,
                        "model_name": payload["model_name"],
                        "provider": payload.get("provider"),
                        "language_name": payload.get("language_name"),
                    },
                )
            raise RuntimeError(msg)

    def _exec_compute_pei(self, payload: dict) -> None:
        run_id    = int(payload["run_id"])
        prompt_id = int(payload["prompt_id"])
        em        = ExperimentModel(self._db)

        inputs = em.get_run_snapshot_inputs(run_id, prompt_id)
        texts  = [t["text"] for t in inputs if t.get("text")]
        if len(texts) < 2:
            return  # non abbastanza lingue per PEI

        pei_data    = self._scorer.compute_pei(texts)
        pei_value   = float(pei_data["pei"])
        script_groups     = {t.get("script_group") for t in inputs if t.get("script_group")}
        morphology_groups = {t.get("morphology_group") for t in inputs if t.get("morphology_group")}
        pei_band    = self._scorer.pei_band(pei_value)

        em.insert_pei_result(
            run_id=run_id,
            prompt_id=prompt_id,
            cv_char=pei_data["cv_char_length"],
            cv_word=pei_data["cv_word_count"],
            cv_token=pei_data["cv_token_count"],
            pei=pei_value,
            script_group_count=len(script_groups) if script_groups else 0,
            morphology_group_count=len(morphology_groups) if morphology_groups else 0,
            pei_band=pei_band,
        )

        # Gruppi (script_group, morphology_group) — senza baseline (calcolata da finalize_pei_groups)
        for group_type, key in [("script_group", "script_group"), ("morphology_group", "morphology_group")]:
            buckets: dict[str, list[str]] = {}
            for t in inputs:
                gv = (t.get(key) or "").strip()
                if not gv:
                    continue
                buckets.setdefault(gv, []).append(t["text"])
            for gv, bucket_texts in buckets.items():
                if len(bucket_texts) < 2:
                    continue
                g     = self._scorer.compute_pei(bucket_texts)
                g_pei = float(g["pei"])
                em.insert_pei_group_partial(
                    run_id=run_id,
                    prompt_id=prompt_id,
                    group_type=group_type,
                    group_value=gv,
                    language_count=len(bucket_texts),
                    cv_char=g["cv_char_length"],
                    cv_word=g["cv_word_count"],
                    cv_token=g["cv_token_count"],
                    pei=g_pei,
                    pei_delta_vs_global=round(g_pei - pei_value, 6),
                    pei_band=self._scorer.pei_band(g_pei),
                )

    def _exec_finalize_pei_groups(self, payload: dict) -> None:
        run_id = int(payload["run_id"])
        ExperimentModel(self._db).update_pei_group_baselines(run_id)
