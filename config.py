"""
TokenScribe — Configuration
Author: Matteo Morreale
"""

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class TokenScribeConfig:
    """Base configuration for TokenScribe."""
    SECRET_KEY = os.environ.get("TOKENSCRIBE_SECRET_KEY", "tokenscribe-dev-secret-change-in-production")
    DATABASE_PATH = os.path.join(BASE_DIR, "instance", "tokenscribe.db")
    DEBUG = False
    TESTING = False

    # Pagination
    ITEMS_PER_PAGE = 25

    # Minimum reasoning_tokens to classify a model as a reasoning model.
    # Values below this threshold are treated as tokenizer drift (tiktoken vs
    # provider tokenizer) rather than true hidden reasoning chains.
    # Set to 50 — observed drift on non-reasoning models peaks at ~20 tokens,
    # so 50 provides a clear margin without masking real reasoning chains (≥100 tokens).
    REASONING_THRESHOLD = 50

    # Supported LLM providers
    SUPPORTED_PROVIDERS = [
        "openai",
        "anthropic",
        "google",
        "deepseek",
        "meta",
        "qwen",
        "mistral",
        "xai",
    ]

    # Default models per provider (pre-seeded in DB).
    # Costs in USD per million tokens ($/M).
    # Confirmed prices sourced from official API docs / pricing pages (April 2026).
    # Models marked (*) use tier-based estimates; verify in Settings if accuracy matters.
    DEFAULT_MODELS = {
        "openai": [
            # --- confirmed ---
            {"name": "gpt-5.5",       "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 5.0,    "cost_per_output_token": 30.0},
            {"name": "gpt-5.4-pro",   "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 30.0,   "cost_per_output_token": 180.0},
            {"name": "gpt-5.4-nano",  "context_window": 32000,   "is_reasoning": False, "cost_per_input_token": 0.2,    "cost_per_output_token": 1.25},
            {"name": "gpt-4.1",       "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 2.0,    "cost_per_output_token": 8.0},
            {"name": "gpt-4o",        "context_window": 128000,  "is_reasoning": False, "cost_per_input_token": 5.0,    "cost_per_output_token": 15.0},
            {"name": "gpt-4o-mini",   "context_window": 128000,  "is_reasoning": False, "cost_per_input_token": 0.15,   "cost_per_output_token": 0.6},
            {"name": "gpt-5.5-pro",   "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 30.0,   "cost_per_output_token": 180.0},
            {"name": "gpt-5.4",       "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 2.5,    "cost_per_output_token": 15.0},
            {"name": "gpt-5.4-mini",  "context_window": 128000,  "is_reasoning": False, "cost_per_input_token": 0.75,   "cost_per_output_token": 4.5},
            {"name": "gpt-4.1-mini",  "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 0.4,    "cost_per_output_token": 1.6},
            {"name": "gpt-4.1-nano",  "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 0.1,    "cost_per_output_token": 0.4},
            # --- estimated (*) ---
            {"name": "gpt-5",         "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 3.0,    "cost_per_output_token": 15.0},
        ],
        "anthropic": [
            # --- all confirmed (platform.claude.com/docs/en/about-claude/pricing) ---
            {"name": "claude-opus-4-7",   "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 5.0,   "cost_per_output_token": 25.0},
            {"name": "claude-opus-4-6",   "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 5.0,   "cost_per_output_token": 25.0},
            {"name": "claude-sonnet-4-6", "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 3.0,   "cost_per_output_token": 15.0},
            {"name": "claude-haiku-4-5",  "context_window": 200000,  "is_reasoning": False, "cost_per_input_token": 1.0,   "cost_per_output_token": 5.0},
            {"name": "claude-opus-4-5",   "context_window": 200000,  "is_reasoning": False, "cost_per_input_token": 5.0,   "cost_per_output_token": 25.0},
            {"name": "claude-sonnet-4-5", "context_window": 200000,  "is_reasoning": False, "cost_per_input_token": 3.0,   "cost_per_output_token": 15.0},
        ],
        "google": [
            # --- confirmed (ai.google.dev/gemini-api/docs/pricing) ---
            {"name": "gemini-2.5-pro",        "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 1.25,  "cost_per_output_token": 10.0},
            {"name": "gemini-2.5-flash",      "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 0.3,   "cost_per_output_token": 2.5},
            {"name": "gemini-2.5-flash-lite", "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 0.1,   "cost_per_output_token": 0.4},
        ],
        "deepseek": [
            # --- confirmed (api-docs.deepseek.com/quick_start/pricing) ---
            {"name": "deepseek-v4-pro",   "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 0.435, "cost_per_output_token": 0.87},
            {"name": "deepseek-v4-flash", "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 0.14,  "cost_per_output_token": 0.28},
        ],
        "meta": [
            # --- confirmed for Llama 4 (together.ai/pricing); Llama 3.1 estimated ---
            {"name": "meta-llama/Llama-4-Scout-17B-16E-Instruct",      "context_window": 10000000, "is_reasoning": False, "cost_per_input_token": 0.15,  "cost_per_output_token": 0.6},
            {"name": "meta-llama/Llama-4-Maverick-17B-128E-Instruct",   "context_window": 1000000,  "is_reasoning": False, "cost_per_input_token": 0.27,  "cost_per_output_token": 0.85},
            {"name": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",     "context_window": 128000,   "is_reasoning": False, "cost_per_input_token": 0.1,   "cost_per_output_token": 0.1},
            {"name": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",    "context_window": 128000,   "is_reasoning": False, "cost_per_input_token": 0.88,  "cost_per_output_token": 0.88},
        ],
        "qwen": [
            # --- confirmed (alibabacloud.com/help/en/model-studio/model-pricing, May 2026) ---
            {"name": "qwen3-max",            "context_window": 131072,  "is_reasoning": True,  "cost_per_input_token": 1.2,   "cost_per_output_token": 6.0},
            {"name": "qwen-max",             "context_window": 32000,   "is_reasoning": False, "cost_per_input_token": 1.6,   "cost_per_output_token": 6.4},
            {"name": "qwen3-235b-a22b",      "context_window": 131072,  "is_reasoning": True,  "cost_per_input_token": 0.7,   "cost_per_output_token": 2.8},
            {"name": "qwen3-30b-a3b",        "context_window": 131072,  "is_reasoning": True,  "cost_per_input_token": 0.2,   "cost_per_output_token": 0.8},
            {"name": "qwen3.5-plus",         "context_window": 131072,  "is_reasoning": True,  "cost_per_input_token": 0.4,   "cost_per_output_token": 2.4},
            {"name": "qwen3.5-flash",        "context_window": 1000000, "is_reasoning": True,  "cost_per_input_token": 0.1,   "cost_per_output_token": 0.4},
            {"name": "qwen-plus",            "context_window": 131072,  "is_reasoning": False, "cost_per_input_token": 0.4,   "cost_per_output_token": 1.2},
            {"name": "qwen-turbo",           "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 0.05,  "cost_per_output_token": 0.2},
            {"name": "qwen2.5-72b-instruct", "context_window": 131072,  "is_reasoning": False, "cost_per_input_token": 1.4,   "cost_per_output_token": 5.6},
        ],
        "mistral": [
            # --- confirmed (mistral.ai/pricing) ---
            {"name": "mistral-large-latest",    "context_window": 256000, "is_reasoning": False, "cost_per_input_token": 0.5,   "cost_per_output_token": 1.5},
            {"name": "magistral-medium-latest", "context_window": 131072, "is_reasoning": True,  "cost_per_input_token": 2.0,   "cost_per_output_token": 5.0},
            {"name": "magistral-small-latest",  "context_window": 131072, "is_reasoning": True,  "cost_per_input_token": 0.5,   "cost_per_output_token": 1.5},
            {"name": "mistral-small-latest",    "context_window": 32000,  "is_reasoning": False, "cost_per_input_token": 0.075, "cost_per_output_token": 0.2},
            {"name": "codestral-latest",        "context_window": 256000, "is_reasoning": False, "cost_per_input_token": 0.3,   "cost_per_output_token": 0.9},
            # --- estimated (*) ---
            {"name": "ministral-8b-latest",     "context_window": 128000, "is_reasoning": False, "cost_per_input_token": 0.1,   "cost_per_output_token": 0.3},
        ],
        "xai": [
            # --- confirmed (x.ai/api#pricing, May 2026) ---
            {"name": "grok-4.3",                        "context_window": 1000000, "is_reasoning": False, "cost_per_input_token": 1.25, "cost_per_output_token": 2.5},
            {"name": "grok-4.20-multi-agent-0309",      "context_window": 2000000, "is_reasoning": False, "cost_per_input_token": 1.25, "cost_per_output_token": 2.5},
            {"name": "grok-4.20-0309-reasoning",        "context_window": 2000000, "is_reasoning": True,  "cost_per_input_token": 1.25, "cost_per_output_token": 2.5},
            {"name": "grok-4.20-0309-non-reasoning",    "context_window": 2000000, "is_reasoning": False, "cost_per_input_token": 1.25, "cost_per_output_token": 2.5},
            {"name": "grok-4-1-fast-reasoning",         "context_window": 2000000, "is_reasoning": True,  "cost_per_input_token": 0.2,  "cost_per_output_token": 0.5},
            {"name": "grok-4-1-fast-non-reasoning",     "context_window": 2000000, "is_reasoning": False, "cost_per_input_token": 0.2,  "cost_per_output_token": 0.5},
            {"name": "grok-3",                          "context_window": 131072,  "is_reasoning": False, "cost_per_input_token": 3.0,  "cost_per_output_token": 15.0},
            {"name": "grok-3-fast",                     "context_window": 131072,  "is_reasoning": False, "cost_per_input_token": 5.0,  "cost_per_output_token": 25.0},
            {"name": "grok-3-mini",                     "context_window": 131072,  "is_reasoning": True,  "cost_per_input_token": 0.3,  "cost_per_output_token": 0.5},
            {"name": "grok-3-mini-fast",                "context_window": 131072,  "is_reasoning": False, "cost_per_input_token": 0.6,  "cost_per_output_token": 4.0},
        ],
    }

    # Writing systems seed data
    WRITING_SYSTEMS = [
        "Alphabetic",
        "Abjad",
        "Abugida",
        "Logographic",
        "Syllabic",
        "Featural",
        "Mixed",
    ]

    # Language seed data: (name, code, writing_system)
    SEED_LANGUAGES = [
        ("English", "en", "Alphabetic"),
        ("Italian", "it", "Alphabetic"),
        ("French", "fr", "Alphabetic"),
        ("Spanish", "es", "Alphabetic"),
        ("German", "de", "Alphabetic"),
        ("Portuguese", "pt", "Alphabetic"),
        ("Dutch", "nl", "Alphabetic"),
        ("Polish", "pl", "Alphabetic"),
        ("Russian", "ru", "Alphabetic"),
        ("Ukrainian", "uk", "Alphabetic"),
        ("Greek", "el", "Alphabetic"),
        ("Arabic", "ar", "Abjad"),
        ("Hebrew", "he", "Abjad"),
        ("Persian", "fa", "Abjad"),
        ("Hindi", "hi", "Abugida"),
        ("Bengali", "bn", "Abugida"),
        ("Thai", "th", "Abugida"),
        ("Chinese (Simplified)", "zh-Hans", "Logographic"),
        ("Chinese (Traditional)", "zh-Hant", "Logographic"),
        ("Japanese", "ja", "Mixed"),
        ("Korean", "ko", "Featural"),
        ("Turkish", "tr", "Alphabetic"),
        ("Vietnamese", "vi", "Alphabetic"),
        ("Indonesian", "id", "Alphabetic"),
        ("Swahili", "sw", "Alphabetic"),
    ]


class DevelopmentConfig(TokenScribeConfig):
    DEBUG = True


class ProductionConfig(TokenScribeConfig):
    DEBUG = False


class TestingConfig(TokenScribeConfig):
    TESTING = True
    DATABASE_PATH = ":memory:"


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
