"""
TokenScribe — CryptoService
Author: Matteo Morreale

Symmetric encryption for sensitive settings (API keys) stored in SQLite.
Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography package.
The encryption key is read from TOKENSCRIBE_ENCRYPTION_KEY in the environment
(populated from .env). If absent on first run, a key is generated and appended
to the .env file automatically.
"""

import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY_NAME = "TOKENSCRIBE_ENCRYPTION_KEY"


def _generate_and_persist(env_path: Path) -> bytes:
    key = Fernet.generate_key()
    existing = env_path.read_text() if env_path.exists() else ""
    separator = "\n" if existing and not existing.endswith("\n") else ""
    env_path.write_text(f"{existing}{separator}{_ENV_KEY_NAME}={key.decode()}\n")
    os.environ[_ENV_KEY_NAME] = key.decode()
    return key


class CryptoService:
    """Fernet-based encrypt/decrypt for API key fields."""

    def __init__(self, env_path: Path | None = None):
        raw = os.environ.get(_ENV_KEY_NAME)
        if raw:
            key = raw.encode()
        else:
            ep = env_path or Path(".env")
            key = _generate_and_persist(ep)
        self._fernet = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        """Decrypt a Fernet token. Returns the value unchanged for legacy
        plain-text values stored before encryption was introduced. Returns ""
        for Fernet tokens that can't be decrypted (key mismatch), so callers
        treat them as "not configured" rather than forwarding the raw token."""
        if not value:
            return value
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except (InvalidToken, Exception):
            # Fernet tokens start with gAAAAAB — if decryption fails on one,
            # the encryption key has changed; return empty so the API call
            # fails with "key not configured" instead of using a garbage value.
            if value.startswith("gAAAAAB"):
                return ""
            return value
