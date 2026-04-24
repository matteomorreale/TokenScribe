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
    REASONING_THRESHOLD = 10

    # Supported LLM providers
    SUPPORTED_PROVIDERS = [
        "openai",
        "anthropic",
        "google",
        "deepseek",
        "meta",
        "qwen",
        "mistral",
    ]

    # Default models per provider (pre-seeded in DB)
    DEFAULT_MODELS = {
        "openai": [
            {"name": "gpt-5", "context_window": 1000000},
            {"name": "gpt-5-mini", "context_window": 1000000},
            {"name": "gpt-4.1", "context_window": 1000000},
            {"name": "gpt-4.1-mini", "context_window": 1000000},
            {"name": "gpt-4.1-nano", "context_window": 1000000},
            {"name": "gpt-4o", "context_window": 128000},
            {"name": "gpt-4o-mini", "context_window": 128000},
        ],
        "anthropic": [
            {"name": "claude-opus-4-5", "context_window": 200000},
            {"name": "claude-sonnet-4-5", "context_window": 200000},
            {"name": "claude-opus-4", "context_window": 200000},
            {"name": "claude-sonnet-4", "context_window": 200000},
        ],
        "google": [
            {"name": "gemini-2.5-pro", "context_window": 1000000},
            {"name": "gemini-2.5-flash", "context_window": 1000000},
            {"name": "gemini-2.0-flash", "context_window": 1000000},
        ],
        "deepseek": [
            {"name": "deepseek-chat", "context_window": 64000},
            {"name": "deepseek-reasoner", "context_window": 64000},
        ],
        "meta": [
            {"name": "meta-llama/Llama-4-Scout-17B-16E-Instruct", "context_window": 10000000},
            {"name": "meta-llama/Llama-4-Maverick-17B-128E-Instruct", "context_window": 1000000},
            {"name": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "context_window": 128000},
            {"name": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "context_window": 128000},
        ],
        "qwen": [
            {"name": "qwen-max", "context_window": 32000},
            {"name": "qwen-plus", "context_window": 131072},
            {"name": "qwen-turbo", "context_window": 1000000},
            {"name": "qwen2.5-72b-instruct", "context_window": 131072},
            {"name": "qwen3-235b-a22b", "context_window": 131072},
            {"name": "qwen3-30b-a3b", "context_window": 131072},
        ],
        "mistral": [
            {"name": "mistral-large-latest", "context_window": 128000},
            {"name": "mistral-small-latest", "context_window": 32000},
            {"name": "codestral-latest", "context_window": 256000},
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
