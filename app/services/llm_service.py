"""
TokenScribe — LLM Service
Author: Matteo Morreale

Unified interface to all supported LLM providers.
Providers: OpenAI, Anthropic, Google Gemini, DeepSeek, Meta Llama, Qwen, Mistral
All calls return a TokenScribeCallResult with token counts and cost.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenScribeCallResult:
    """Result of a single LLM API call."""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    source: str = "api_reported"  # or "estimated"
    response_text: str = ""
    error: Optional[str] = None
    success: bool = True


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

    def __init__(self, settings: dict):
        """
        settings: dict of key→value from SettingsModel.get_all()
        Expected keys: openai_api_key, anthropic_api_key, google_api_key,
                       deepseek_api_key, meta_api_key, qwen_api_key, mistral_api_key
        """
        self.settings = settings

    def call(
        self,
        provider: str,
        model_name: str,
        prompt_text: str,
        cost_per_input: float = 0.0,
        cost_per_output: float = 0.0,
    ) -> TokenScribeCallResult:
        """Dispatch to the appropriate provider handler."""
        dispatch = {
            self.PROVIDER_OPENAI: self._call_openai,
            self.PROVIDER_ANTHROPIC: self._call_anthropic,
            self.PROVIDER_GOOGLE: self._call_google,
            self.PROVIDER_DEEPSEEK: self._call_deepseek,
            self.PROVIDER_META: self._call_meta,
            self.PROVIDER_QWEN: self._call_qwen,
            self.PROVIDER_MISTRAL: self._call_mistral,
        }
        handler = dispatch.get(provider)
        if not handler:
            return TokenScribeCallResult(
                success=False, error=f"Unknown provider: {provider}"
            )
        result = handler(model_name, prompt_text)
        if result.success:
            result.cost = (
                result.input_tokens * cost_per_input
                + result.output_tokens * cost_per_output
            )
        return result

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    def _call_openai(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("openai_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="OpenAI API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_completion_tokens=512,
            )
            usage = response.usage
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=response.choices[0].message.content or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------

    def _call_anthropic(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("anthropic_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Anthropic API key not configured")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model_name,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt_text}],
            )
            return TokenScribeCallResult(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                response_text=response.content[0].text if response.content else "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # Google Gemini
    # ------------------------------------------------------------------

    def _call_google(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("google_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Google API key not configured")
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt_text)
            usage = response.usage_metadata
            return TokenScribeCallResult(
                input_tokens=usage.prompt_token_count,
                output_tokens=usage.candidates_token_count,
                response_text=response.text or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # DeepSeek (OpenAI-compatible API)
    # ------------------------------------------------------------------

    def _call_deepseek(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("deepseek_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="DeepSeek API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=512,
            )
            usage = response.usage
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=response.choices[0].message.content or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

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
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=512,
            )
            usage = response.usage
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=response.choices[0].message.content or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

    # ------------------------------------------------------------------
    # Qwen (via Alibaba Cloud DashScope — OpenAI-compatible)
    # ------------------------------------------------------------------

    def _call_qwen(self, model_name: str, prompt_text: str) -> TokenScribeCallResult:
        api_key = self.settings.get("qwen_api_key", "")
        if not api_key:
            return TokenScribeCallResult(success=False, error="Qwen API key not configured")
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=512,
            )
            usage = response.usage
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=response.choices[0].message.content or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))

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
            response = client.chat.complete(
                model=model_name,
                messages=[{"role": "user", "content": prompt_text}],
                max_tokens=512,
            )
            usage = response.usage
            return TokenScribeCallResult(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                response_text=response.choices[0].message.content or "",
                source="api_reported",
            )
        except Exception as e:
            return TokenScribeCallResult(success=False, error=str(e))
