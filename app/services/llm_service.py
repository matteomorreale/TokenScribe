"""
TokenScribe — LLM Service
Author: Matteo Morreale

Unified interface to all supported LLM providers.
Providers: OpenAI, Anthropic, Google Gemini, DeepSeek, Meta Llama, Qwen, Mistral, xAI (Grok)
All calls return a TokenScribeCallResult with token counts, cost, and timing metrics.

Optional LogService injection: pass log_service= to __init__ to enable non-blocking
operation logging. Each call records provider, model, tokens, cost, duration, response.

Timing fields in TokenScribeCallResult (ALL are cumulative deltas from request_start):
  total_query_time_ms      — wall time of the API call itself (always set)
  time_to_first_token_ms   — ms from request_start to first streamed token
  time_to_completion_ms    — ms from first token to last received chunk (NOT cumulative;
                             kept as duration so TTFT + completion = time to last chunk)
  time_to_stream_close_ms  — ms from request_start to stream/connection close (cumulative,
                             always set; 'inferred' from total_query_time for non-streaming)
  stream_close_source      — 'native' if measured from actual stream close event,
                             'inferred' if set equal to total_query_time_ms (non-streaming
                             fallback or providers that buffer the full response)

Timing invariant (enforced at insert time; violations logged as timing_anomaly=True):
  0 < TTFT ≤ TTFT + completion ≤ stream_close ≤ total_query_time
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional

# Serialise all Anthropic API calls to 1 at a time.
# This org tier hits both the concurrent-connection limit and the 50 req/min
# cap if multiple workers call Claude simultaneously; a single slot eliminates
# both without affecting non-Anthropic providers.
_ANTHROPIC_SEMAPHORE = threading.Semaphore(1)

# Uniform output-token cap applied to all providers.  Individual provider APIs may
# enforce a lower internal limit, but we always request 4096 so the ceiling is
# consistent across the experiment.  Reasoning models (OpenAI, DeepSeek) use a
# separate 8192 path when internal reasoning tokens exhaust the budget.
MAX_OUTPUT_TOKENS = 4096


def _openai_supports_reasoning_effort(model_name: str) -> bool:
    """True for OpenAI models that accept the reasoning_effort parameter."""
    mn = model_name.lower()
    return mn.startswith(("o1", "o3", "o4")) or "gpt-5" in mn


def _openai_low_effort(model_name: str) -> str:
    """Return the lowest supported reasoning effort for the model.

    gpt-5.5 models do not accept 'low'; their minimum is 'medium'.
    """
    if "gpt-5.5" in model_name.lower():
        return "medium"
    return "low"


def _is_not_chat_model(error_str: str) -> bool:
    s = error_str.lower()
    return "not a chat model" in s or "v1/completions" in s


def _is_model_not_found(error_str: str) -> bool:
    s = error_str.lower()
    return (
        "not_found_error" in s
        or ("error code: 404" in s and "model" in s)
        or "model_not_found" in s
        or "no such model" in s
        or "model does not exist" in s
        or "no longer available" in s
        or s.startswith("404 ")
    )


def _is_rate_limited(error_str: str) -> bool:
    s = error_str.lower()
    return (
        "429" in s
        or "rate limit" in s
        or "rate_limit" in s
        or "rate_limited" in s
        or "too many requests" in s
        or "quota exceeded" in s
        or "resource_exhausted" in s
    )


def _is_timeout(error_str: str) -> bool:
    s = error_str.lower()
    return (
        "timed out" in s
        or "timeout" in s
        or "readtimeout" in s
        or "connecttimeout" in s
        or "read operation timed out" in s
    )


def check_timing_invariant(result: "TokenScribeCallResult") -> bool:
    """Return True if all timing fields satisfy the required invariant.

    Invariant (all values in ms, cumulative from request_start):
        0 < TTFT ≤ TTFT + completion ≤ stream_close ≤ total_query_time

    Returns False (anomaly) when:
    - Any required field is negative or zero
    - TTFT + completion > stream_close  (the known Run 18 bug before this fix)
    - stream_close > total_query_time

    Returns True (no anomaly) when any of the four fields is None, because
    absence of a field is not the same as a timing violation.
    """
    ttft   = result.time_to_first_token_ms
    comp   = result.time_to_completion_ms
    sc     = result.time_to_stream_close_ms
    tqt    = result.total_query_time_ms

    if any(v is None for v in (ttft, comp, sc, tqt)):
        return True  # cannot evaluate — not an anomaly

    if ttft <= 0:
        return False
    if comp < 0:
        return False
    if ttft + comp > sc:
        return False
    if sc > tqt:
        return False
    return True


@dataclass
class TokenScribeCallResult:
    """Result of a single LLM API call."""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float = 0.0
    source: str = "api_reported"  # or "estimated"
    response_text: str = ""
    error: Optional[str] = None
    success: bool = True
    model_not_found: bool = False
    rate_limited: bool = False
    timed_out: bool = False
    # Timing (milliseconds).
    # total_query_time_ms is always set by LLMService.call() from the outer wall clock.
    # TTFT and completion are streaming-only (None for non-streaming fallback).
    # stream_close_ms is always set (native or inferred from total_query_time_ms).
    total_query_time_ms: Optional[int] = None
    time_to_first_token_ms: Optional[int] = None
    time_to_completion_ms: Optional[int] = None
    time_to_stream_close_ms: Optional[int] = None
    # 'native' = measured from actual stream close event;
    # 'inferred' = set equal to total_query_time_ms (non-streaming or no stream events).
    stream_close_source: str = "native"


class LLMService:
    """
    Unified LLM provider interface for TokenScribe.
    Reads API keys from the settings store passed at construction time.
    """

    PROVIDER_OPENAI = "openai"
    PROVIDER_ANTHROPIC = "anthropic"
    PROVIDER_GOOGLE = "google"
    PROVIDER_DEEPSEEK = "deepseek"
    PROVIDER_META = "meta"
    PROVIDER_QWEN = "qwen"
    PROVIDER_MISTRAL = "mistral"
    PROVIDER_XAI = "xai"

    def __init__(self, settings: dict, log_service=None):
        """
        settings: dict of key→value from SettingsModel.get_all()
        log_service: optional LogService instance for non-blocking operation logging
        """
        self.settings = settings
        self._log = log_service

    def call(
        self,
        provider: str,
        model_name: str,
        prompt_text: str,
        cost_per_input: float = 0.0,
        cost_per_output: float = 0.0,
        is_reasoning: bool = False,
        _ctx: Optional[dict] = None,
    ) -> TokenScribeCallResult:
        """
        Dispatch to the appropriate provider handler.
        is_reasoning: when True, provider-specific reasoning budget handling is applied.
        _ctx: optional context dict (run_id, prompt_id, language, etc.) stored in logs.
        """
        dispatch = {
            self.PROVIDER_OPENAI: self._call_openai,
            self.PROVIDER_ANTHROPIC: self._call_anthropic,
            self.PROVIDER_GOOGLE: self._call_google,
            self.PROVIDER_DEEPSEEK: self._call_deepseek,
            self.PROVIDER_META: self._call_meta,
            self.PROVIDER_QWEN: self._call_qwen,
            self.PROVIDER_MISTRAL: self._call_mistral,
            self.PROVIDER_XAI: self._call_xai,
        }
        handler = dispatch.get(provider)
        if not handler:
            err = TokenScribeCallResult(
                success=False, error=f"Unknown provider: {provider}"
            )
            self._emit_error(provider, model_name, prompt_text, err.error, 0, _ctx)
            return err

        t0 = time.monotonic()
        if provider in (self.PROVIDER_DEEPSEEK, self.PROVIDER_OPENAI, self.PROVIDER_XAI):
            result = handler(model_name, prompt_text, is_reasoning=is_reasoning)
        else:
            result = handler(model_name, prompt_text)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Anthropic handler measures from inside the semaphore and pre-sets this.
        # Other handlers leave it None, so we fill it from the outer wall clock.
        if result.total_query_time_ms is None:
            result.total_query_time_ms = duration_ms

        # Guarantee 100% stream_close coverage (Run 19 requirement):
        # When a provider buffers the full response (no streaming) or streaming
        # failed and fell back to batch, time_to_stream_close_ms is None.
        # In that case, set it equal to total_query_time_ms and mark as 'inferred'.
        if result.time_to_stream_close_ms is None:
            result.time_to_stream_close_ms = result.total_query_time_ms
            result.stream_close_source = "inferred"

        if result.success:
            result.cost = (
                result.input_tokens * cost_per_input / 1_000_000
                + result.output_tokens * cost_per_output / 1_000_000
            )
            self._emit_success(provider, model_name, prompt_text, result, duration_ms, _ctx)
        else:
            self._emit_error(provider, model_name, prompt_text, result.error, duration_ms, _ctx)

        return result

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _emit_success(self, provider, model_name, prompt_text, result, duration_ms, ctx):
        if not self._log:
            return
        op_type = (ctx or {}).get("operation_type", "llm_call")
        self._log.log(
            operation_type=op_type,
            event="llm_call_success",
            level="INFO",
            provider=provider,
            model=model_name,
            message=(
                f"{provider}/{model_name}: "
                f"{result.input_tokens} in / {result.output_tokens} out "
                f"— {duration_ms} ms"
            ),
            context_ref=ctx,
            payload={
                "prompt_preview": (prompt_text or "")[:500],
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": round(result.cost, 8),
                "source": result.source,
                "response_preview": (result.response_text or "")[:1000],
                "response_length": len(result.response_text or ""),
                "total_query_time_ms": result.total_query_time_ms,
                "time_to_first_token_ms": result.time_to_first_token_ms,
                "time_to_completion_ms": result.time_to_completion_ms,
            },
            duration_ms=duration_ms,
        )

    def _emit_error(self, provider, model_name, prompt_text, error, duration_ms, ctx):
        if not self._log:
            return
        op_type = (ctx or {}).get("operation_type", "llm_call")
        self._log.log(
            operation_type=op_type,
            event="llm_call_error",
            level="ERROR",
            provider=provider,
            model=model_name,
            message=f"{provider}/{model_name}: {error}",
            context_ref=ctx,
            payload={
                "prompt_preview": (prompt_text or "")[:500],
                "error": error,
            },
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Streaming helper (OpenAI-compatible APIs)
    # ------------------------------------------------------------------

    @staticmethod
    def _do_openai_stream(client, call_kwargs: dict):
        """Run a streaming OpenAI-compatible completion.

        Returns (content, usage, t_req, t_first_chunk, t_last_chunk, t_done).
        t_first_chunk and t_last_chunk are None if the model produced no content tokens.
        Raises on any error so the caller can fall back to non-streaming.
        """
        stream_kwargs = dict(call_kwargs, stream=True, stream_options={"include_usage": True})
        t_req = time.monotonic()
        t_first = None
        t_last = None
        text_parts = []
        usage = None

        with client.chat.completions.create(**stream_kwargs) as stream:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if chunk.choices and chunk.choices[0].delta.content:
                    if t_first is None:
                        t_first = time.monotonic()
                    t_last = time.monotonic()
                    text_parts.append(chunk.choices[0].delta.content)

        t_done = time.monotonic()
        return "".join(text_parts), usage, t_req, t_first, t_last, t_done

    @staticmethod
    def _timing_from_stream(t_req, t_first, t_last, t_done):
        """Compute (ttft_ms, completion_ms, stream_close_ms) from raw timestamps.

        All three values are deltas from t_req (request_start), ensuring the invariant:
            0 < TTFT ≤ TTFT + completion ≤ stream_close ≤ total_query_time

        - ttft_ms       : t_first - t_req  (latency to first token)
        - completion_ms : t_last  - t_first (generation duration, not cumulative from t_req)
        - stream_close_ms: t_done - t_req   (cumulative from t_req; includes teardown)

        TTFT + completion = (t_first - t_req) + (t_last - t_first) = t_last - t_req
        stream_close      = t_done - t_req ≥ t_last - t_req → invariant holds ✓

        Returns (None, None, None) when no content tokens were streamed.
        In that case the caller sets stream_close_ms via the outer inferred fallback.
        """
        if t_first is None or t_last is None:
            return None, None, None
        return (
            int((t_first - t_req) * 1000),
            int((t_last - t_first) * 1000),
            int((t_done - t_req) * 1000),   # FIX: cumulative from t_req, not from t_last
        )

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    def _call_openai(self, model_name: str, prompt_text: str, is_reasoning: bool = False) -> TokenScribeCallResult:
        api_key = self.settings.get("openai_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="OpenAI API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            max_tok = 8192 if is_reasoning else MAX_OUTPUT_TOKENS

            call_kwargs: dict = dict(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_completion_tokens=max_tok,
            )
            if _openai_supports_reasoning_effort(model_name):
                call_kwargs["reasoning_effort"] = "high" if is_reasoning else _openai_low_effort(model_name)

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None

            try:
                content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, call_kwargs)

                # If budget was exhausted and content is still empty, retry with higher cap.
                if not content and usage and usage.completion_tokens >= max_tok and max_tok < 8192:
                    retry_kwargs = dict(call_kwargs, max_completion_tokens=8192)
                    try:
                        content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, retry_kwargs)
                    except Exception:
                        response = client.chat.completions.create(**retry_kwargs)
                        usage = response.usage
                        content = response.choices[0].message.content or "" if response.choices else ""
                        t_first = None
                        t_last = None

                ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(t_req, t_first, t_last, t_done)
            except Exception:
                # Streaming not supported or failed; fall back to non-streaming.
                response = client.chat.completions.create(**call_kwargs)
                usage = response.usage
                content = response.choices[0].message.content or "" if response.choices else ""

                if not content and usage and usage.completion_tokens >= max_tok and max_tok < 8192:
                    retry_kwargs = dict(call_kwargs, max_completion_tokens=8192)
                    response = client.chat.completions.create(**retry_kwargs)
                    usage = response.usage
                    content = response.choices[0].message.content or "" if response.choices else ""

            reasoning_toks = 0
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                reasoning_toks = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                reasoning_tokens=reasoning_toks,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            if _is_not_chat_model(err):
                return self._call_openai_responses(api_key, model_name, prompt_text, is_reasoning)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    def _call_openai_responses(self, api_key: str, model_name: str, prompt_text: str, is_reasoning: bool) -> TokenScribeCallResult:
        """Fallback for models only available on the Responses API (e.g. gpt-5.4-pro)."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            effort = "high" if is_reasoning else _openai_low_effort(model_name)
            response = client.responses.create(
                model=model_name,
                input=prompt_text,
                reasoning={"effort": effort},
            )
            usage = response.usage
            reasoning_toks = 0
            details = getattr(usage, "output_tokens_details", None)
            if details:
                reasoning_toks = getattr(details, "reasoning_tokens", 0) or 0
            return TokenScribeCallResult(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=reasoning_toks,
                response_text=response.output_text or "",
                source="api_reported",
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    def _call_anthropic(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("anthropic_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Anthropic API key not configured")
        with _ANTHROPIC_SEMAPHORE:
            try:
                import anthropic
                # max_retries=0: SDK-internal rate-limit retries (with Retry-After
                # backoff) would silently contaminate total_query_time_ms. The
                # queue layer re-enqueues on RateLimitError, so retries are handled
                # explicitly and with correct per-attempt timing.
                client = anthropic.Anthropic(api_key=api_key, max_retries=0)

                t_req = time.monotonic()
                t_first = None
                t_last = None
                text_parts = []

                with client.messages.stream(
                    model=model_name,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    messages=[{"role": "user", "content": prompt_text}],
                ) as stream:
                    for text_chunk in stream.text_stream:
                        if t_first is None:
                            t_first = time.monotonic()
                        t_last = time.monotonic()
                        text_parts.append(text_chunk)
                    final_msg = stream.get_final_message()
                # t_done is set after the context manager exits so it captures
                # get_final_message() + connection teardown separately from generation.
                t_done = time.monotonic()

                ttft_ms        = int((t_first - t_req) * 1000) if t_first else None
                completion_ms  = int((t_last  - t_first) * 1000) if t_first else None
                # stream_close_ms = cumulative from t_req (NOT delta from t_last).
                # This ensures: TTFT + completion ≤ stream_close ≤ total_query_time.
                # When t_first is None (empty stream), outer inferred fallback covers it.
                stream_close_ms = int((t_done - t_req) * 1000) if t_first else None
                total_ms        = int((t_done - t_req) * 1000)

                return TokenScribeCallResult(
                    input_tokens=final_msg.usage.input_tokens,
                    output_tokens=final_msg.usage.output_tokens,
                    response_text="".join(text_parts),
                    source="api_reported",
                    total_query_time_ms=total_ms,
                    time_to_first_token_ms=ttft_ms,
                    time_to_completion_ms=completion_ms,
                    time_to_stream_close_ms=stream_close_ms,
                    stream_close_source="native" if t_first else "inferred",
                )
            except Exception as e:
                err = str(e)
                return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # Google Gemini
    # ------------------------------------------------------------------

    def _call_google(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("google_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Google API key not configured")
        try:
            from google import genai
            from google.genai import types as genai_types
            client = genai.Client(api_key=api_key)
            config = genai_types.GenerateContentConfig(max_output_tokens=MAX_OUTPUT_TOKENS)

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None
            content = ""
            usage = None

            # Try streaming first for TTFT measurement (Gemini/Run-20 requirement)
            streaming_ok = False
            try:
                t_req = time.monotonic()
                t_first = None
                t_last = None
                text_parts: list[str] = []

                for chunk in client.models.generate_content_stream(
                    model=model_name,
                    contents=prompt_text,
                    config=config,
                ):
                    try:
                        chunk_text = chunk.text
                    except Exception:
                        chunk_text = None
                    if chunk_text:
                        if t_first is None:
                            t_first = time.monotonic()
                        t_last = time.monotonic()
                        text_parts.append(chunk_text)
                    chunk_usage = getattr(chunk, "usage_metadata", None)
                    if chunk_usage:
                        usage = chunk_usage

                t_done = time.monotonic()
                if usage is not None:
                    ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(
                        t_req, t_first, t_last, t_done
                    )
                    content = "".join(text_parts)
                    streaming_ok = True
            except Exception:
                pass

            if not streaming_ok:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_text,
                    config=config,
                )
                usage = response.usage_metadata
                content = response.text or ""

            thoughts_toks = getattr(usage, "thoughts_token_count", 0) or 0
            visible_toks = getattr(usage, "candidates_token_count", 0) or 0
            return TokenScribeCallResult(
                input_tokens=usage.prompt_token_count,
                output_tokens=visible_toks + thoughts_toks,
                reasoning_tokens=thoughts_toks,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # DeepSeek (OpenAI-compatible API)
    # ------------------------------------------------------------------

    def _call_deepseek(self, model_name: str, prompt_text: str, is_reasoning: bool = False) -> TokenScribeCallResult:
        api_key = self.settings.get("deepseek_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="DeepSeek API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
            )
            max_tokens = 8192 if is_reasoning else MAX_OUTPUT_TOKENS
            call_kwargs = dict(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=max_tokens,
            )

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None
            content = None
            usage = None

            try:
                content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, call_kwargs)

                if not content and usage and usage.completion_tokens >= max_tokens and max_tokens < 8192:
                    retry_kwargs = dict(call_kwargs, max_tokens=8192)
                    try:
                        content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, retry_kwargs)
                    except Exception:
                        response = client.chat.completions.create(**retry_kwargs)
                        usage = response.usage
                        content = response.choices[0].message.content or "" if response.choices else ""
                        t_first = None
                        t_last = None

                ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(t_req, t_first, t_last, t_done)
            except Exception:
                response = client.chat.completions.create(**call_kwargs)
                usage = response.usage
                content = response.choices[0].message.content or "" if response.choices else ""

                if not content and usage and usage.completion_tokens >= max_tokens and max_tokens < 8192:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": prompt_text}],
                        max_tokens=8192,
                    )
                    usage = response.usage
                    content = response.choices[0].message.content or "" if response.choices else ""

            reasoning_toks = 0
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                reasoning_toks = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                reasoning_tokens=reasoning_toks,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # Meta Llama (via Together AI consumer API)
    # ------------------------------------------------------------------

    def _call_meta(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("meta_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Meta (Together AI) API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.together.xyz/v1",
            )
            call_kwargs = dict(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=MAX_OUTPUT_TOKENS,
            )

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None

            try:
                content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, call_kwargs)
                ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(t_req, t_first, t_last, t_done)
            except Exception:
                response = client.chat.completions.create(**call_kwargs)
                usage = response.usage
                content = response.choices[0].message.content or ""

            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # Qwen (via Alibaba Cloud DashScope — OpenAI-compatible)
    # ------------------------------------------------------------------

    def _call_qwen(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("qwen_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Qwen API key not configured")
        region = self.settings.get("qwen_region", "china")
        base_url = (
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
            if region == "international"
            else "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
            )
            call_kwargs = dict(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=MAX_OUTPUT_TOKENS,
            )

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None

            try:
                content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, call_kwargs)
                ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(t_req, t_first, t_last, t_done)
            except Exception:
                response = client.chat.completions.create(**call_kwargs)
                usage = response.usage
                content = response.choices[0].message.content or ""

            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # Mistral
    # ------------------------------------------------------------------

    def _call_mistral(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("mistral_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Mistral API key not configured")
        try:
            from mistralai.client.sdk import Mistral
            client = Mistral(api_key=api_key)

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None
            content = ""
            usage = None

            # Try streaming first for TTFT measurement (Magistral/Run-20 requirement)
            streaming_ok = False
            try:
                t_req = time.monotonic()
                t_first = None
                t_last = None
                text_parts: list[str] = []

                with client.chat.stream(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=MAX_OUTPUT_TOKENS,
                ) as stream:
                    for event in stream:
                        data = getattr(event, "data", event)
                        for choice in (getattr(data, "choices", None) or []):
                            delta = getattr(choice, "delta", None)
                            chunk_text = getattr(delta, "content", None) if delta else None
                            if chunk_text:
                                if t_first is None:
                                    t_first = time.monotonic()
                                t_last = time.monotonic()
                                text_parts.append(chunk_text)
                        ev_usage = getattr(data, "usage", None)
                        if ev_usage:
                            usage = ev_usage

                t_done = time.monotonic()
                if usage is not None:
                    ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(
                        t_req, t_first, t_last, t_done
                    )
                    content = "".join(text_parts)
                    streaming_ok = True
            except Exception:
                pass

            if not streaming_ok:
                response = client.chat.complete(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=MAX_OUTPUT_TOKENS,
                )
                usage = response.usage
                content = response.choices[0].message.content or ""

            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))

    # ------------------------------------------------------------------
    # xAI (Grok) — OpenAI-compatible API
    # ------------------------------------------------------------------

    def _call_xai(self, model_name: str, prompt_text: str, is_reasoning: bool = False) -> TokenScribeCallResult:
        api_key = self.settings.get("xai_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="xAI API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
            )
            max_tok = 8192 if is_reasoning else MAX_OUTPUT_TOKENS
            call_kwargs = dict(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=max_tok,
            )

            ttft_ms = None
            completion_ms = None
            stream_close_ms = None

            try:
                content, usage, t_req, t_first, t_last, t_done = self._do_openai_stream(client, call_kwargs)
                ttft_ms, completion_ms, stream_close_ms = self._timing_from_stream(t_req, t_first, t_last, t_done)
            except Exception:
                response = client.chat.completions.create(**call_kwargs)
                usage = response.usage
                content = response.choices[0].message.content or "" if response.choices else ""

            reasoning_toks = 0
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                reasoning_toks = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                reasoning_tokens=reasoning_toks,
                response_text=content,
                source="api_reported",
                time_to_first_token_ms=ttft_ms,
                time_to_completion_ms=completion_ms,
                time_to_stream_close_ms=stream_close_ms,
            )
        except Exception as e:
            err = str(e)
            return TokenScribeCallResult(success=False, error=err, model_not_found=_is_model_not_found(err), rate_limited=_is_rate_limited(err), timed_out=_is_timeout(err))
