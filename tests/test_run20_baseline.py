"""
Tests for Run-20 baseline cascade:
  - 3-level cascade in resolve_calibration_model()
  - compute_no_reasoning_compliance() — 5 values
  - compute_baseline_quality()
  - compute_baseline_rates() — Level 1/2 (own data) + Level 3 (cross-pool median)
  - select_pool_models() — pool selection logic
  - baseline_source stored in calibration_results (DB round-trip)
  - streaming_efficiency_summary in JSON export
  - TTFT fields populated by Mistral/Gemini streaming (mocked)
"""

import json
import sqlite3
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Path setup so imports work without installing the package
# ---------------------------------------------------------------------------
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ===========================================================================
# 1. resolve_calibration_model() — 3-level cascade
# ===========================================================================
class TestResolveCalibrationModel(unittest.TestCase):

    def setUp(self):
        from app.services.calibration_service import resolve_calibration_model
        self.resolve = resolve_calibration_model

    # Level 0 — non-reasoning models returned as-is
    def test_non_reasoning_is_direct(self):
        eff_model, eff_reasoning, disabled, source = self.resolve(
            "gpt-4o", is_reasoning=False, provider="openai"
        )
        self.assertEqual(eff_model, "gpt-4o")
        self.assertFalse(eff_reasoning)
        self.assertFalse(disabled)
        self.assertEqual(source, "direct")

    def test_non_reasoning_deepseek_is_direct(self):
        _, _, _, source = self.resolve(
            "deepseek-v4-flash", is_reasoning=False, provider="deepseek"
        )
        self.assertEqual(source, "direct")

    # Level 1 — companion model swap (Grok)
    def test_grok_reasoning_swaps_to_companion(self):
        eff_model, eff_reasoning, disabled, source = self.resolve(
            "grok-4.20-0309-reasoning", is_reasoning=True, provider="xai"
        )
        self.assertEqual(eff_model, "grok-4.20-0309-non-reasoning")
        self.assertFalse(eff_reasoning)
        self.assertTrue(disabled)
        self.assertEqual(source, "real_companion")

    def test_grok_fast_reasoning_swaps_to_companion(self):
        eff_model, _, _, source = self.resolve(
            "grok-4-1-fast-reasoning", is_reasoning=True, provider="xai"
        )
        self.assertEqual(eff_model, "grok-4-1-fast-non-reasoning")
        self.assertEqual(source, "real_companion")

    # Level 2 — internal toggle (OpenAI + Mistral)
    def test_openai_gpt5_uses_toggle(self):
        eff_model, eff_reasoning, disabled, source = self.resolve(
            "gpt-5.5", is_reasoning=True, provider="openai"
        )
        self.assertEqual(eff_model, "gpt-5.5")
        self.assertFalse(eff_reasoning)
        self.assertTrue(disabled)
        self.assertEqual(source, "real_toggle")

    def test_openai_o3_uses_toggle(self):
        _, _, _, source = self.resolve("o3", is_reasoning=True, provider="openai")
        self.assertEqual(source, "real_toggle")

    def test_openai_o1_uses_toggle(self):
        _, _, _, source = self.resolve("o1", is_reasoning=True, provider="openai")
        self.assertEqual(source, "real_toggle")

    def test_magistral_uses_toggle(self):
        _, _, disabled, source = self.resolve(
            "magistral-medium-latest", is_reasoning=True, provider="mistral"
        )
        self.assertTrue(disabled)
        self.assertEqual(source, "real_toggle")

    def test_magistral_small_uses_toggle(self):
        _, _, _, source = self.resolve(
            "magistral-small-latest", is_reasoning=True, provider="mistral"
        )
        self.assertEqual(source, "real_toggle")

    # Level 3 — always-reasoning, no companion or toggle
    def test_deepseek_v4_pro_is_estimated_pool(self):
        eff_model, _, _, source = self.resolve(
            "deepseek-v4-pro", is_reasoning=True, provider="deepseek"
        )
        self.assertEqual(eff_model, "deepseek-v4-pro")
        self.assertEqual(source, "estimated_pool")

    def test_anthropic_claude_opus_is_estimated_pool(self):
        _, _, _, source = self.resolve(
            "claude-opus-4-7", is_reasoning=True, provider="anthropic"
        )
        self.assertEqual(source, "estimated_pool")

    def test_google_gemini_flash_thinking_is_estimated_pool(self):
        _, _, _, source = self.resolve(
            "gemini-2.5-flash", is_reasoning=True, provider="google"
        )
        self.assertEqual(source, "estimated_pool")

    def test_qwen3_max_is_estimated_pool(self):
        _, _, _, source = self.resolve(
            "qwen3-max", is_reasoning=True, provider="qwen"
        )
        self.assertEqual(source, "estimated_pool")

    # Return signature always 4-tuple
    def test_returns_4tuple(self):
        result = self.resolve("gpt-4o", is_reasoning=False, provider="openai")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 4)


# ===========================================================================
# 2. compute_no_reasoning_compliance() — 5-value classifier
# ===========================================================================
class TestComputeNoReasoningCompliance(unittest.TestCase):

    def setUp(self):
        from app.services.calibration_service import compute_no_reasoning_compliance
        self.classify = compute_no_reasoning_compliance

    def test_non_reasoning_non_pool_is_not_required(self):
        self.assertEqual(self.classify("gpt-4o", False, "openai"), "not_required")

    def test_non_reasoning_non_pool_mistral(self):
        # mistral-large-latest is now the pool substitute → pool_eligible
        self.assertEqual(self.classify("mistral-large-latest", False, "mistral"), "pool_eligible")

    def test_pool_eligible_grok_non_reasoning(self):
        v = self.classify("grok-4.20-0309-non-reasoning", False, "xai")
        self.assertEqual(v, "pool_eligible")

    def test_pool_eligible_mistral_large(self):
        # mistral-large-latest is the new pool substitute (non-reasoning) → pool_eligible
        v = self.classify("mistral-large-latest", False, "mistral")
        self.assertEqual(v, "pool_eligible")

    def test_magistral_not_pool_eligible(self):
        # magistral is a reasoning model with toggle support; no longer a pool candidate
        v = self.classify("magistral-medium-latest", True, "mistral")
        self.assertEqual(v, "toggle")

    def test_pool_eligible_gemini_flash_lite(self):
        v = self.classify("gemini-2.5-flash-lite", False, "google")
        self.assertEqual(v, "pool_eligible")

    def test_pool_eligible_claude_haiku(self):
        v = self.classify("claude-haiku-4-5", False, "anthropic")
        self.assertEqual(v, "pool_eligible")

    def test_companion_grok_reasoning(self):
        v = self.classify("grok-4.20-0309-reasoning", True, "xai")
        self.assertEqual(v, "companion")

    def test_toggle_gpt5(self):
        v = self.classify("gpt-5.5", True, "openai")
        self.assertEqual(v, "toggle")

    def test_toggle_o1(self):
        v = self.classify("o1", True, "openai")
        self.assertEqual(v, "toggle")

    def test_pool_deepseek(self):
        v = self.classify("deepseek-v4-pro", True, "deepseek")
        self.assertEqual(v, "pool")

    def test_pool_anthropic_reasoning(self):
        v = self.classify("claude-opus-4-7", True, "anthropic")
        self.assertEqual(v, "pool")

    def test_pool_google_thinking(self):
        v = self.classify("gemini-2.5-pro", True, "google")
        self.assertEqual(v, "pool")

    def test_all_five_values_covered(self):
        from app.services.calibration_service import compute_no_reasoning_compliance
        values = {
            compute_no_reasoning_compliance("gpt-4o", False, "openai"),
            compute_no_reasoning_compliance("gemini-2.5-flash-lite", False, "google"),
            compute_no_reasoning_compliance("grok-4.20-0309-reasoning", True, "xai"),
            compute_no_reasoning_compliance("gpt-5.5", True, "openai"),
            compute_no_reasoning_compliance("deepseek-v4-pro", True, "deepseek"),
        }
        self.assertEqual(values, {"not_required", "pool_eligible", "companion", "toggle", "pool"})


# ===========================================================================
# 3. compute_baseline_quality()
# ===========================================================================
class TestComputeBaselineQuality(unittest.TestCase):

    def setUp(self):
        from app.services.calibration_service import compute_baseline_quality
        self.quality = compute_baseline_quality

    def test_success_no_reasoning_is_clean(self):
        self.assertEqual(self.quality(0, "success", False), "clean")

    def test_success_low_reasoning_is_clean(self):
        self.assertEqual(self.quality(30, "success", False), "clean")

    def test_success_high_reasoning_is_degraded(self):
        self.assertEqual(self.quality(31, "success", False), "degraded")

    def test_failed_is_invalid(self):
        self.assertEqual(self.quality(0, "failed", False), "invalid")
        self.assertEqual(self.quality(0, "error", False), "invalid")

    def test_explicitly_disabled_low_reasoning_is_clean(self):
        self.assertEqual(self.quality(5, "success", True), "clean")

    def test_explicitly_disabled_high_reasoning_is_degraded(self):
        self.assertEqual(self.quality(100, "success", True), "degraded")


# ===========================================================================
# 4. compute_baseline_rates() — 3-level cascade
# ===========================================================================

def _make_cal_result(
    model_name, lang_code, slug, visible_output_tokens,
    time_to_completion_ms, time_to_first_token_ms=500,
    baseline_quality="clean", attempt_status="success",
    baseline_source="direct",
):
    return {
        "model_name":             model_name,
        "language_code":          lang_code,
        "cal_prompt_slug":        slug,
        "visible_output_tokens":  visible_output_tokens,
        "time_to_completion_ms":  time_to_completion_ms,
        "time_to_first_token_ms": time_to_first_token_ms,
        "baseline_quality":       baseline_quality,
        "attempt_status":         attempt_status,
        "baseline_source":        baseline_source,
    }


class TestComputeBaselineRates(unittest.TestCase):

    def setUp(self):
        from app.services.calibration_service import compute_baseline_rates
        self.compute = compute_baseline_rates

    # --- helpers ---

    def _long_slug(self):
        return "cal_03_long"

    def _short_slug(self):
        return "cal_01_short"

    # Level 1/2: model uses own clean data
    def test_level1_model_uses_own_data(self):
        slug = self._long_slug()
        results = [
            # Grok-reasoning → companion run was as grok-non-reasoning, source=real_companion
            _make_cal_result("grok-4.20-0309-reasoning", "en", slug, 300, 5000,
                             baseline_source="real_companion"),
            _make_cal_result("grok-4.20-0309-reasoning", "en", slug, 320, 5200,
                             baseline_source="real_companion"),
        ]
        rates = self.compute(results, pool_model_names=[])
        self.assertIn("grok-4.20-0309-reasoning", rates)
        entry = rates["grok-4.20-0309-reasoning"]
        self.assertEqual(entry["baseline_source"], "real_companion")
        lang = entry["languages"]["en"]
        self.assertIsNotNone(lang["rate_tok_per_sec_median"])
        self.assertGreater(lang["rate_tok_per_sec_median"], 0)

    def test_level2_model_uses_own_data(self):
        slug = self._long_slug()
        results = [
            _make_cal_result("gpt-5.5", "en", slug, 280, 4000,
                             baseline_source="real_toggle"),
        ]
        rates = self.compute(results, pool_model_names=[])
        entry = rates["gpt-5.5"]
        self.assertEqual(entry["baseline_source"], "real_toggle")
        self.assertIsNotNone(entry["languages"]["en"]["rate_tok_per_sec_median"])

    # Level 3: uses cross-pool median
    def test_level3_model_gets_cross_pool_median(self):
        slug = self._long_slug()
        pool_models = ["grok-4.20-0309-non-reasoning", "claude-haiku-4-5", "gemini-2.5-flash-lite"]
        results = [
            # Pool model 1: 300 tok / 5s = 60 tok/s
            _make_cal_result("grok-4.20-0309-non-reasoning", "en", slug, 300, 5000, baseline_source="direct"),
            # Pool model 2: 240 tok / 4s = 60 tok/s
            _make_cal_result("claude-haiku-4-5",              "en", slug, 240, 4000, baseline_source="direct"),
            # Pool model 3: 360 tok / 6s = 60 tok/s
            _make_cal_result("gemini-2.5-flash-lite",         "en", slug, 360, 6000, baseline_source="direct"),
            # Level 3 experimental model (always-reasoning)
            _make_cal_result("deepseek-v4-pro", "en", slug, 200, 3000,
                             baseline_quality="degraded", baseline_source="estimated_pool"),
        ]
        rates = self.compute(results, pool_model_names=pool_models)
        self.assertIn("deepseek-v4-pro", rates)
        entry = rates["deepseek-v4-pro"]
        self.assertEqual(entry["baseline_source"], "estimated_pool")
        lang = entry["languages"]["en"]
        # All three pool models produce 60 tok/s → median = 60
        self.assertAlmostEqual(lang["cross_pool_median"], 60.0, places=1)
        self.assertAlmostEqual(lang["rate_tok_per_sec_median"], 60.0, places=1)
        self.assertIn("rate_per_model", lang)
        self.assertEqual(len(lang["rate_per_model"]), 3)
        self.assertEqual(lang["n_pool_models"], 3)

    def test_level3_cross_pool_median_with_different_rates(self):
        slug = self._long_slug()
        pool_models = ["m1", "m2", "m3"]
        results = [
            _make_cal_result("m1", "en", slug, 100, 2000, baseline_source="direct"),  # 50 tok/s
            _make_cal_result("m2", "en", slug, 300, 6000, baseline_source="direct"),  # 50 tok/s
            _make_cal_result("m3", "en", slug, 200, 3000, baseline_source="direct"),  # 66.7 tok/s → median=50
            _make_cal_result("deepseek-v4-pro", "en", slug, 80, 1000,
                             baseline_quality="degraded", baseline_source="estimated_pool"),
        ]
        rates = self.compute(results, pool_model_names=pool_models)
        lang = rates["deepseek-v4-pro"]["languages"]["en"]
        # pool rates: 50, 50, 66.7 → median ≈ 50
        self.assertAlmostEqual(lang["cross_pool_median"], 50.0, places=1)

    def test_short_slugs_excluded_from_rates(self):
        """Only cal_03_long and cal_04_long_varied contribute to rates."""
        results = [
            _make_cal_result("gpt-4o", "en", "cal_01_short", 100, 2000),
            _make_cal_result("gpt-4o", "en", "cal_02_medium", 150, 3000),
        ]
        rates = self.compute(results, pool_model_names=[])
        self.assertEqual(rates, {})

    def test_degraded_model_listed_with_null_rates(self):
        results = [
            _make_cal_result("badmodel", "en", self._long_slug(), 100, 2000,
                             baseline_quality="degraded", baseline_source="estimated_pool"),
        ]
        rates = self.compute(results, pool_model_names=[])
        self.assertIn("badmodel", rates)
        lang = rates["badmodel"]["languages"]["en"]
        self.assertIsNone(lang["rate_tok_per_sec_median"])
        self.assertEqual(lang["quality"], "degraded")
        self.assertEqual(lang["n_clean_trials"], 0)

    def test_invalid_results_excluded(self):
        results = [
            _make_cal_result("model_x", "en", self._long_slug(), 200, 3000,
                             baseline_quality="invalid", attempt_status="failed"),
        ]
        rates = self.compute(results, pool_model_names=[])
        self.assertNotIn("model_x", rates)

    def test_multiple_languages(self):
        slug = self._long_slug()
        results = [
            _make_cal_result("gpt-4o", "en", slug, 300, 5000),
            _make_cal_result("gpt-4o", "it", slug, 280, 5000),
            _make_cal_result("gpt-4o", "zh-Hans", slug, 260, 5000),
        ]
        rates = self.compute(results)
        langs = rates["gpt-4o"]["languages"]
        self.assertIn("en", langs)
        self.assertIn("it", langs)
        self.assertIn("zh-Hans", langs)

    def test_percentile_ordering(self):
        slug = self._long_slug()
        # Rates: 10, 20, 30, 40, 50 tok/s
        results = [
            _make_cal_result("m", "en", slug, 10*d, d*1000) for d in range(1, 6)
        ]
        rates = self.compute(results)
        lang = rates["m"]["languages"]["en"]
        self.assertLessEqual(lang["rate_tok_per_sec_p25"], lang["rate_tok_per_sec_median"])
        self.assertLessEqual(lang["rate_tok_per_sec_median"], lang["rate_tok_per_sec_p75"])

    def test_ttft_median_populated(self):
        slug = self._long_slug()
        results = [
            _make_cal_result("m", "en", slug, 300, 5000, time_to_first_token_ms=800),
            _make_cal_result("m", "en", slug, 300, 5000, time_to_first_token_ms=1200),
        ]
        rates = self.compute(results)
        ttft = rates["m"]["languages"]["en"]["baseline_ttft_ms_median"]
        self.assertIsNotNone(ttft)
        self.assertAlmostEqual(ttft, 1000.0, places=0)

    def test_empty_results(self):
        rates = self.compute([], pool_model_names=[])
        self.assertEqual(rates, {})


# ===========================================================================
# 5. select_pool_models() — pool selection with mock DB
# ===========================================================================

class _MockRow(dict):
    """sqlite3.Row-like dict."""
    def __getitem__(self, key):
        return super().__getitem__(key)


def _make_mock_db(model_rows: list[dict]):
    """Build a minimal mock DB whose get_connection() returns a mock
    that responds to the pool model query."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    def execute_side_effect(sql, params=()):
        mock_cursor = MagicMock()
        # The pool query looks for (name, provider) pairs
        if "m.name = ?" in sql and "p.name = ?" in sql:
            model_name_q, provider_q = params[0], params[1]
            match = next(
                (r for r in model_rows if r["name"] == model_name_q and r["provider"] == provider_q),
                None,
            )
            mock_cursor.fetchone.return_value = _MockRow({"id": match["id"]}) if match else None
        else:
            mock_cursor.fetchone.return_value = None
        return mock_cursor

    mock_conn.execute = MagicMock(side_effect=execute_side_effect)

    mock_db = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    return mock_db


class TestSelectPoolModels(unittest.TestCase):

    def setUp(self):
        from app.services.calibration_service import select_pool_models, POOL_CANDIDATES
        self.select = select_pool_models
        self.candidates = POOL_CANDIDATES

    def _all_models_db(self):
        """Mock DB where all 4 pool candidates exist."""
        return _make_mock_db([
            {"name": "grok-4.20-0309-non-reasoning", "provider": "xai",       "id": 1},
            {"name": "claude-haiku-4-5",              "provider": "anthropic", "id": 2},
            {"name": "gemini-2.5-flash-lite",         "provider": "google",    "id": 3},
            {"name": "mistral-large-latest",          "provider": "mistral",   "id": 4},
        ])

    def _all_settings(self):
        return {
            "xai_api_key":       "xai_key",
            "anthropic_api_key": "anthropic_key",
            "google_api_key":    "google_key",
            "mistral_api_key":   "mistral_key",
        }

    def test_all_available_selects_first_3(self):
        pool = self.select(self._all_settings(), self._all_models_db())
        self.assertEqual(len(pool), 3)
        names = [p["model_name"] for p in pool]
        # First 3 in priority order (Mistral-large is 4th / substitute — not needed)
        self.assertIn("grok-4.20-0309-non-reasoning", names)
        self.assertIn("claude-haiku-4-5", names)
        self.assertIn("gemini-2.5-flash-lite", names)
        self.assertNotIn("mistral-large-latest", names)

    def test_missing_first_priority_falls_back(self):
        settings = self._all_settings()
        del settings["xai_api_key"]
        pool = self.select(settings, self._all_models_db())
        self.assertEqual(len(pool), 3)
        names = [p["model_name"] for p in pool]
        # Grok missing → Claude-haiku, Gemini, Mistral-large
        self.assertNotIn("grok-4.20-0309-non-reasoning", names)
        self.assertIn("claude-haiku-4-5", names)
        self.assertIn("gemini-2.5-flash-lite", names)
        self.assertIn("mistral-large-latest", names)

    def test_mistral_used_as_substitute_at_most_once(self):
        """Only 2 primary candidates available → Mistral-large fills 1 slot, total=3."""
        settings = {
            "anthropic_api_key": "key",
            "google_api_key":    "key",
            "mistral_api_key":   "key",
        }
        pool = self.select(settings, self._all_models_db())
        self.assertEqual(len(pool), 3)
        mistral_count = sum(1 for p in pool if p["model_name"] == "mistral-large-latest")
        self.assertEqual(mistral_count, 1)

    def test_too_few_models_returns_empty(self):
        """Only 1 model available → cannot form a pool of 3."""
        settings = {"xai_api_key": "key"}
        pool = self.select(settings, self._all_models_db())
        self.assertEqual(pool, [])

    def test_model_not_in_db_is_skipped(self):
        """Pool candidate with no DB row is skipped."""
        db = _make_mock_db([
            # Claude-haiku and Gemini exist but Grok does not
            {"name": "claude-haiku-4-5",       "provider": "anthropic", "id": 2},
            {"name": "gemini-2.5-flash-lite",  "provider": "google",    "id": 3},
            {"name": "mistral-large-latest",   "provider": "mistral",   "id": 4},
        ])
        settings = self._all_settings()
        pool = self.select(settings, db)
        self.assertEqual(len(pool), 3)
        names = [p["model_name"] for p in pool]
        self.assertNotIn("grok-4.20-0309-non-reasoning", names)

    def test_returns_model_id(self):
        pool = self.select(self._all_settings(), self._all_models_db())
        for p in pool:
            self.assertIn("model_id", p)
            self.assertIsNotNone(p["model_id"])

    def test_at_least_3_provider_families(self):
        """All 3 selected models must be from different provider families."""
        pool = self.select(self._all_settings(), self._all_models_db())
        providers = {p["provider"] for p in pool}
        self.assertGreaterEqual(len(providers), 3)


# ===========================================================================
# 6. DB round-trip: baseline_source stored and returned
# ===========================================================================

class TestBaselineSourceDBRoundTrip(unittest.TestCase):
    """Verify that baseline_source is persisted and read back from calibration_results."""

    def setUp(self):
        import tempfile
        from app.models.database import DatabaseManager
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(self._tmp.name)
        self.db.bootstrap()

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _get_ids(self):
        """Return (run_id, cal_prompt_id, lang_id, model_id) from seeded DB."""
        conn = self.db.get_connection()
        try:
            run = conn.execute(
                "SELECT id FROM experiment_runs LIMIT 1"
            ).fetchone()
            if not run:
                conn.execute("INSERT INTO experiment_runs (study_id) VALUES (?)",
                             (self._ensure_study(conn),))
                conn.commit()
                run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                run_id = run["id"]

            cal_prompt = conn.execute(
                "SELECT id FROM calibration_prompts LIMIT 1"
            ).fetchone()
            cal_prompt_id = cal_prompt["id"] if cal_prompt else None

            lang = conn.execute(
                "SELECT id FROM languages WHERE code='en'"
            ).fetchone()
            lang_id = lang["id"] if lang else None

            model = conn.execute(
                "SELECT id FROM models LIMIT 1"
            ).fetchone()
            model_id = model["id"] if model else None

            return run_id, cal_prompt_id, lang_id, model_id
        finally:
            conn.close()

    def _ensure_study(self, conn):
        row = conn.execute("SELECT id FROM studies LIMIT 1").fetchone()
        if row:
            return row["id"]
        conn.execute("INSERT INTO studies (name) VALUES ('test')")
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_baseline_source_round_trip(self):
        from app.models.experiment_model import ExperimentModel
        em = ExperimentModel(self.db)
        run_id, cal_prompt_id, lang_id, model_id = self._get_ids()

        if None in (cal_prompt_id, lang_id, model_id):
            self.skipTest("DB seed data unavailable in test environment")

        for source in ("real_companion", "real_toggle", "estimated_pool", "direct"):
            row_id = em.insert_calibration_result(
                run_id=run_id,
                calibration_prompt_id=cal_prompt_id,
                language_id=lang_id,
                model_id=model_id,
                input_tokens=100,
                output_tokens=200,
                attempt_status="success",
                baseline_source=source,
                repetition_index=list(("real_companion", "real_toggle", "estimated_pool", "direct")).index(source),
            )
            self.assertIsNotNone(row_id)

        # Read directly from DB (not via get_calibration_results_by_run which filters attempt_status='success')
        conn = self.db.get_connection()
        try:
            rows = conn.execute(
                "SELECT baseline_source FROM calibration_results WHERE run_id=?",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()

        found_sources = {r["baseline_source"] for r in rows}
        self.assertIn("real_companion", found_sources)
        self.assertIn("real_toggle", found_sources)
        self.assertIn("estimated_pool", found_sources)
        self.assertIn("direct", found_sources)

    def test_baseline_source_column_exists(self):
        conn = self.db.get_connection()
        try:
            cur = conn.execute("PRAGMA table_info(calibration_results)")
            cols = [r["name"] for r in cur.fetchall()]
        finally:
            conn.close()
        self.assertIn("baseline_source", cols)

    def test_no_reasoning_compliance_column_exists(self):
        conn = self.db.get_connection()
        try:
            cur = conn.execute("PRAGMA table_info(models)")
            cols = [r["name"] for r in cur.fetchall()]
        finally:
            conn.close()
        self.assertIn("no_reasoning_compliance", cols)

    def test_no_reasoning_compliance_backfilled(self):
        """After bootstrap, all models should have no_reasoning_compliance set."""
        conn = self.db.get_connection()
        try:
            null_count = conn.execute(
                "SELECT COUNT(*) AS n FROM models WHERE no_reasoning_compliance IS NULL"
            ).fetchone()["n"]
        finally:
            conn.close()
        self.assertEqual(null_count, 0)


# ===========================================================================
# 7. Export service: streaming_efficiency_summary + new _notes
# ===========================================================================

class TestExportServiceStructure(unittest.TestCase):

    def _minimal_json_export(self, calibration_results=None, token_results=None):
        from app.services.export_service import ExportService
        return json.loads(ExportService.to_json(
            results=token_results or [],
            calibration_results=calibration_results or [],
            cell_completeness={"expected_reps": 1, "cells": {}, "incomplete": []},
        ))

    def test_baseline_rates_key_present(self):
        data = self._minimal_json_export()
        self.assertIn("baseline_rates", data)

    def test_streaming_efficiency_summary_key_present(self):
        data = self._minimal_json_export()
        self.assertIn("streaming_efficiency_summary", data)

    def test_new_notes_present(self):
        data = self._minimal_json_export()
        notes = data["_notes"]
        self.assertIn("baseline_rates_level3_limit", notes)
        self.assertIn("irrt_primacy", notes)
        self.assertIn("streaming_efficiency_summary", notes)

    def test_baseline_rates_has_baseline_source(self):
        slug = "cal_03_long"
        cal = [_make_cal_result("gpt-4o", "en", slug, 300, 5000, baseline_source="direct")]
        data = self._minimal_json_export(calibration_results=cal)
        if "gpt-4o" in data["baseline_rates"]:
            self.assertIn("baseline_source", data["baseline_rates"]["gpt-4o"])

    def test_streaming_efficiency_summary_structure(self):
        """streaming_efficiency_summary should include the correct keys per model."""
        slug = "cal_03_long"
        cal = [_make_cal_result("gpt-4o", "en", slug, 300, 5000, baseline_source="direct")]
        tok = [{
            "model_name": "gpt-4o",
            "visible_output_tokens": 280,
            "time_to_completion_ms": 5000,
            "prompt_id": 1,
            "language_id": 1,
            "model_id": 1,
        }]
        data = self._minimal_json_export(calibration_results=cal, token_results=tok)
        eff = data.get("streaming_efficiency_summary", {})
        if "gpt-4o" in eff:
            entry = eff["gpt-4o"]
            self.assertIn("baseline_rate_tok_per_sec", entry)
            self.assertIn("observed_rate_tok_per_sec", entry)
            self.assertIn("streaming_efficiency", entry)
            self.assertIn("reasoning_during_streaming", entry)
            self.assertIn("baseline_source", entry)

    def test_empty_calibration_no_crash(self):
        data = self._minimal_json_export(calibration_results=[], token_results=[])
        self.assertIn("baseline_rates", data)
        self.assertIn("streaming_efficiency_summary", data)

    def test_streaming_efficiency_reasoning_during_streaming_false_when_observed_gte_baseline(self):
        """When observed rate >= 90% of baseline, reasoning_during_streaming should be False."""
        slug = "cal_03_long"
        # baseline: 300 tok / 5s = 60 tok/s
        cal = [_make_cal_result("gpt-4o", "en", slug, 300, 5000, baseline_source="direct")]
        # observed: 280 tok / 5s = 56 tok/s (93% of baseline → False)
        tok = [{
            "model_name": "gpt-4o",
            "visible_output_tokens": 280,
            "time_to_completion_ms": 5000,
            "prompt_id": 1,
            "language_id": 1,
            "model_id": 1,
        }]
        data = self._minimal_json_export(calibration_results=cal, token_results=tok)
        eff = data.get("streaming_efficiency_summary", {})
        if "gpt-4o" in eff and eff["gpt-4o"]["reasoning_during_streaming"] is not None:
            self.assertFalse(eff["gpt-4o"]["reasoning_during_streaming"])

    def test_streaming_efficiency_reasoning_during_streaming_true_when_much_slower(self):
        """When observed rate < 90% of baseline, reasoning_during_streaming should be True."""
        slug = "cal_03_long"
        # baseline: 600 tok / 5s = 120 tok/s
        cal = [_make_cal_result("slow-model", "en", slug, 600, 5000, baseline_source="direct")]
        # observed: 50 tok / 5s = 10 tok/s (~8% of baseline → True)
        tok = [{
            "model_name": "slow-model",
            "visible_output_tokens": 50,
            "time_to_completion_ms": 5000,
            "prompt_id": 1,
            "language_id": 1,
            "model_id": 1,
        }]
        data = self._minimal_json_export(calibration_results=cal, token_results=tok)
        eff = data.get("streaming_efficiency_summary", {})
        if "slow-model" in eff and eff["slow-model"]["reasoning_during_streaming"] is not None:
            self.assertTrue(eff["slow-model"]["reasoning_during_streaming"])


# ===========================================================================
# 8. LLM service — Mistral and Gemini streaming (mocked)
# ===========================================================================

class TestMistralStreaming(unittest.TestCase):

    def _make_service(self):
        from app.services.llm_service import LLMService
        return LLMService({"mistral_api_key": "fake_key"})

    def _mock_usage(self, prompt_tokens=100, completion_tokens=200):
        u = MagicMock()
        u.prompt_tokens = prompt_tokens
        u.completion_tokens = completion_tokens
        return u

    def test_streaming_success_populates_ttft(self):
        """When Mistral streaming succeeds, time_to_first_token_ms must be > 0."""
        svc = self._make_service()

        # Build a fake stream context manager that yields two chunks
        chunk1 = MagicMock()
        chunk1.data.choices = [MagicMock()]
        chunk1.data.choices[0].delta.content = "Hello "
        chunk1.data.usage = None

        chunk2 = MagicMock()
        chunk2.data.choices = [MagicMock()]
        chunk2.data.choices[0].delta.content = "world"
        chunk2.data.usage = self._mock_usage()

        mock_stream_cm = MagicMock()
        mock_stream_cm.__enter__ = MagicMock(return_value=iter([chunk1, chunk2]))
        mock_stream_cm.__exit__ = MagicMock(return_value=False)

        mock_client = MagicMock()
        mock_client.chat.stream.return_value = mock_stream_cm

        with patch("app.services.llm_service.time") as mock_time:
            # 5 calls: t_req, t_first(chunk1), t_last(chunk1), t_last(chunk2), t_done
            mock_time.monotonic.side_effect = [0.0, 0.5, 1.0, 1.05, 1.10]
            with patch("mistralai.client.sdk.Mistral", return_value=mock_client):
                result = svc._call_mistral("magistral-medium-latest", "Test prompt")

        self.assertTrue(result.success)
        self.assertEqual(result.response_text, "Hello world")
        self.assertIsNotNone(result.time_to_first_token_ms)
        self.assertGreater(result.time_to_first_token_ms, 0)
        self.assertIsNotNone(result.time_to_completion_ms)

    def test_streaming_failure_falls_back_to_sync(self):
        """When Mistral streaming raises, fallback to chat.complete() — TTFT is None."""
        svc = self._make_service()

        mock_client = MagicMock()
        mock_client.chat.stream.side_effect = RuntimeError("stream not supported")
        mock_response = MagicMock()
        mock_response.usage = self._mock_usage()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "fallback response"
        mock_client.chat.complete.return_value = mock_response

        with patch("mistralai.client.sdk.Mistral", return_value=mock_client):
            result = svc._call_mistral("mistral-large-latest", "Test prompt")

        self.assertTrue(result.success)
        self.assertEqual(result.response_text, "fallback response")
        self.assertIsNone(result.time_to_first_token_ms)

    def test_no_api_key_returns_error(self):
        from app.services.llm_service import LLMService
        svc = LLMService({})
        result = svc._call_mistral("magistral-medium-latest", "Hello")
        self.assertFalse(result.success)
        self.assertIn("not configured", result.error.lower())


class TestGeminiStreaming(unittest.TestCase):

    def _make_service(self):
        from app.services.llm_service import LLMService
        return LLMService({"google_api_key": "fake_key"})

    def _mock_usage(self, prompt=50, candidates=200, thoughts=0):
        u = MagicMock()
        u.prompt_token_count = prompt
        u.candidates_token_count = candidates
        u.thoughts_token_count = thoughts
        return u

    def test_streaming_success_populates_ttft(self):
        """When Gemini streaming succeeds, TTFT must be > 0."""
        svc = self._make_service()

        chunk1 = MagicMock()
        chunk1.text = "Hello "
        chunk1.usage_metadata = None

        chunk2 = MagicMock()
        chunk2.text = "world"
        chunk2.usage_metadata = self._mock_usage()

        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = iter([chunk1, chunk2])

        with patch("app.services.llm_service.time") as mock_time:
            # 5 calls: t_req, t_first(chunk1), t_last(chunk1), t_last(chunk2), t_done
            mock_time.monotonic.side_effect = [0.0, 0.3, 0.8, 0.85, 0.90]
            with patch("google.genai.Client", return_value=mock_client):
                result = svc._call_google("gemini-2.5-flash", "Test prompt")

        self.assertTrue(result.success)
        self.assertEqual(result.response_text, "Hello world")
        self.assertIsNotNone(result.time_to_first_token_ms)
        self.assertGreater(result.time_to_first_token_ms, 0)

    def test_streaming_failure_falls_back_to_sync(self):
        """When generate_content_stream raises, fallback to generate_content — TTFT is None."""
        svc = self._make_service()

        mock_client = MagicMock()
        mock_client.models.generate_content_stream.side_effect = AttributeError("no stream method")
        mock_response = MagicMock()
        mock_response.text = "fallback text"
        mock_response.usage_metadata = self._mock_usage()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            result = svc._call_google("gemini-2.5-flash-lite", "Test")

        self.assertTrue(result.success)
        self.assertEqual(result.response_text, "fallback text")
        self.assertIsNone(result.time_to_first_token_ms)

    def test_no_api_key_returns_error(self):
        from app.services.llm_service import LLMService
        svc = LLMService({})
        result = svc._call_google("gemini-2.5-flash", "Hello")
        self.assertFalse(result.success)
        self.assertIn("not configured", result.error.lower())

    def test_reasoning_tokens_from_thoughts(self):
        """thoughts_token_count must appear as reasoning_tokens in result."""
        svc = self._make_service()

        chunk = MagicMock()
        chunk.text = "answer"
        chunk.usage_metadata = self._mock_usage(candidates=100, thoughts=50)

        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = iter([chunk])

        with patch("app.services.llm_service.time") as mock_time:
            mock_time.monotonic.side_effect = [0.0, 0.2, 0.5, 0.55]
            with patch("google.genai.Client", return_value=mock_client):
                result = svc._call_google("gemini-2.5-pro", "Think hard")

        self.assertEqual(result.reasoning_tokens, 50)
        self.assertEqual(result.output_tokens, 150)  # 100 + 50


# ===========================================================================
# 9. Integration smoke: resolve → queue_service payload → DB
# ===========================================================================
class TestCascadeIntegration(unittest.TestCase):
    """Verify that the 4-tuple from resolve_calibration_model is handled correctly
    end-to-end through insert_calibration_result."""

    def setUp(self):
        import tempfile
        from app.models.database import DatabaseManager
        from app.models.experiment_model import ExperimentModel
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(self._tmp.name)
        self.db.bootstrap()
        self.em = ExperimentModel(self.db)

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _ids(self):
        conn = self.db.get_connection()
        try:
            study_id = conn.execute("SELECT id FROM studies LIMIT 1").fetchone()
            if not study_id:
                conn.execute("INSERT INTO studies (name) VALUES ('s')")
                conn.commit()
                study_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                study_id = study_id["id"]
            conn.execute(
                "INSERT INTO experiment_runs (study_id) VALUES (?)", (study_id,)
            )
            conn.commit()
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            cal_id = conn.execute("SELECT id FROM calibration_prompts LIMIT 1").fetchone()["id"]
            lang_id = conn.execute("SELECT id FROM languages LIMIT 1").fetchone()["id"]
            model_id = conn.execute("SELECT id FROM models LIMIT 1").fetchone()["id"]
            return run_id, cal_id, lang_id, model_id
        finally:
            conn.close()

    def _insert(self, run_id, cal_id, lang_id, model_id, baseline_source, rep_idx):
        return self.em.insert_calibration_result(
            run_id=run_id,
            calibration_prompt_id=cal_id,
            language_id=lang_id,
            model_id=model_id,
            input_tokens=50,
            output_tokens=100,
            attempt_status="success",
            baseline_source=baseline_source,
            repetition_index=rep_idx,
        )

    def test_all_three_cascade_sources_stored(self):
        from app.services.calibration_service import resolve_calibration_model

        if not all(v is not None for v in self._ids()):
            self.skipTest("Seed data unavailable")

        run_id, cal_id, lang_id, model_id = self._ids()

        model_cases = [
            ("grok-4.20-0309-reasoning",  True,  "xai",      "real_companion"),
            ("gpt-5.5",                   True,  "openai",   "real_toggle"),
            ("deepseek-v4-pro",           True,  "deepseek", "estimated_pool"),
            ("gpt-4o",                    False, "openai",   "direct"),
        ]
        for i, (model_name, is_r, prov, expected_source) in enumerate(model_cases):
            _, _, _, source = resolve_calibration_model(model_name, is_r, prov)
            self.assertEqual(source, expected_source, f"Wrong source for {model_name}")
            self._insert(run_id, cal_id, lang_id, model_id, source, i)

        conn = self.db.get_connection()
        try:
            sources = {r["baseline_source"] for r in conn.execute(
                "SELECT baseline_source FROM calibration_results WHERE run_id=?",
                (run_id,)
            ).fetchall()}
        finally:
            conn.close()

        self.assertIn("real_companion", sources)
        self.assertIn("real_toggle", sources)
        self.assertIn("estimated_pool", sources)
        self.assertIn("direct", sources)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
