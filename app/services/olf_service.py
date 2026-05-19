"""
TokenScribe — OLF Service (Output Language Fidelity)
Author: Matteo Morreale

Computes the fraction of characters in the response that belong to the target
language, using fasttext lid.176 for per-chunk language detection.

Model file:  data/lid.176.bin  (130 MB — not bundled, download once)
Download:    https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "lid.176.bin"
)
_model = None          # loaded lazily; False = load attempted and failed

MIN_CHUNK_CHARS = 15   # chunks shorter than this are skipped (too noisy)

# Language name (as stored in TokenScribe DB) → fasttext ISO 639-1 label
LANG_TO_FT = {
    "Arabic":   "ar",
    "Chinese":  "zh",
    "English":  "en",
    "French":   "fr",
    "German":   "de",
    "Hindi":    "hi",
    "Italian":  "it",
    "Japanese": "ja",
    "Korean":   "ko",
    "Polish":   "pl",
    "Russian":  "ru",
    "Spanish":  "es",
}

# Sentence-boundary splitter: after . ! ? and their CJK equivalents, or newlines
_SENT_SPLIT = re.compile(r'(?<=[.!?。！？\n])\s*')


def _load_model():
    global _model
    if _model is not None:
        return _model if _model is not False else None
    model_path = os.path.abspath(_MODEL_PATH)
    if not os.path.isfile(model_path):
        logger.warning(
            "OLF: fasttext model not found at %s — download lid.176.bin from "
            "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
            model_path,
        )
        _model = False
        return None
    try:
        import fasttext
        fasttext.FastText.eprint = lambda x: None   # suppress verbose stderr
        _model = fasttext.load_model(model_path)
        logger.info("OLF: fasttext model loaded from %s", model_path)
        return _model
    except Exception as exc:
        logger.warning("OLF: failed to load fasttext model: %s", exc)
        _model = False
        return None


def _detect(model, text: str) -> str | None:
    """Return the ISO 639-1 language code predicted by fasttext, or None."""
    text = text.strip().replace("\n", " ")
    if not text:
        return None
    try:
        labels, _ = model.predict(text, k=1)
        return labels[0].replace("__label__", "")
    except Exception:
        return None


def compute_olf(response_text: str, language_name: str) -> float | None:
    """
    Compute Output Language Fidelity: fraction of response characters
    detected as belonging to *language_name*.

    Returns a float in [0.0, 1.0], or None when:
      - fasttext model is unavailable
      - language_name is not in LANG_TO_FT
      - response is too short to be reliable
    """
    model = _load_model()
    if model is None:
        return None

    target_code = LANG_TO_FT.get(language_name)
    if target_code is None:
        return None

    text = response_text or ""

    # Split into sentence-level chunks
    chunks = [c.strip() for c in _SENT_SPLIT.split(text) if len(c.strip()) >= MIN_CHUNK_CHARS]

    # Fallback: whole response as one chunk if splitting produced nothing
    if not chunks:
        if len(text.strip()) < MIN_CHUNK_CHARS:
            return None
        chunks = [text.strip()]

    target_chars = 0
    total_chars = 0
    for chunk in chunks:
        detected = _detect(model, chunk)
        n = len(chunk)
        total_chars += n
        if detected == target_code:
            target_chars += n

    if total_chars == 0:
        return None

    return round(target_chars / total_chars, 4)
