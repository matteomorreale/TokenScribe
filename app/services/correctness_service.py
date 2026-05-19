"""
TokenScribe — CorrectnessService
Author: Matteo Morreale

Evaluates LLM responses along three orthogonal dimensions:
  - correct:              factual answer is present (in any language variant)
  - in_target_language:  answer is expressed in the requested language
  - language_leakage:    correct but in the wrong language (cross-language confusion)

Add new prompts by extending EXPECTED_ANSWERS with prompt_id as key.
"""

import re

# Maps non-ASCII digit characters to their ASCII equivalents.
# Applied before any string comparison so "١٢" and "12" match identically.
# Does NOT use unidecode — that would destroy Arabic/CJK/Devanagari script content.
_NUMERAL_MAP = str.maketrans(
    # Arabic-Indic       Eastern Arabic      Devanagari          Thai
    "٠١٢٣٤٥٦٧٨٩"       "۰۱۲۳۴۵۶۷۸۹"       "०१२३४५६७८९"       "๐๑๒๓๔๕๖๗๘๙"
    # Bengali             Gurmukhi            Gujarati            Full-width
    "০১২৩৪৫৬৭৮৯"       "੦੧੨੩੪੫੬੭੮੯"       "૦૧૨૩૪૫૬૭૮૯"       "０１２３４５６７８９",
    "0123456789" * 8,
)


def _normalize(text: str) -> str:
    """Normalise text for fuzzy matching.

    Steps (in order):
      1. Map non-ASCII numerals → ASCII digits
      2. Lowercase
      3. Strip leading/trailing whitespace and common trailing punctuation
      4. Collapse internal whitespace runs to a single space

    Deliberately does NOT touch non-Latin scripts (Arabic, CJK, Devanagari, etc.)
    so that substring matching still works correctly.
    """
    text = text.translate(_NUMERAL_MAP)
    text = text.lower().strip()
    text = text.strip(".:,!?;\"'")
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Expected-answer registry
# ---------------------------------------------------------------------------
# Structure per entry:
#   any_language_variants  : list[str]  — all acceptable surface forms across all languages
#   target_language_variants: dict[str, list[str]]  — per-language acceptable forms
#
# Matching is substring-based (after _normalize) so "The capital is Paris."
# correctly matches variant "paris".
#
# Transliteration (e.g. Russian "da" for "да", Japanese "hai" for "はい") is NOT
# listed as a target-language variant — a native speaker would not produce it.
# ---------------------------------------------------------------------------

EXPECTED_ANSWERS: dict[int, dict] = {
    18: {  # "What is the capital of France?" — single-word factual
        "any_language_variants": [
            "paris",         # EN, DE, ES, FR, PL (without diacritic), many others
            "parigi",        # IT
            "باريس",         # AR
            "पेरिस",         # HI (main variant)
            "पैरिस",         # HI (alt spelling)
            "巴黎",          # ZH
            "パリ",          # JA (katakana, dominant)
            "巴里",          # JA (kanji, rare)
            "파리",          # KO
            "париж",         # RU
            "paryż",         # PL (with diacritic)
            "paryz",         # PL (without diacritic, informal)
        ],
        "target_language_variants": {
            "Arabic":   ["باريس"],
            "Chinese":  ["巴黎"],
            "English":  ["paris"],
            "French":   ["paris"],
            "German":   ["paris"],
            "Hindi":    ["पेरिस", "पैरिस"],
            "Italian":  ["parigi"],
            "Japanese": ["パリ", "巴里"],
            "Korean":   ["파리"],
            "Polish":   ["paryż", "paryz"],
            "Russian":  ["париж"],
            "Spanish":  ["paris"],
        },
    },

    # -----------------------------------------------------------------------
    # Prompt 19 — fill in with actual prompt text and expected answers.
    # Leave any_language_variants empty to skip evaluation for this prompt.
    # -----------------------------------------------------------------------
    19: {
        "any_language_variants": [],
        "target_language_variants": {},
    },

    20: {  # "What does HTTP stand for?" — multi-word acronym expansion
        "any_language_variants": [
            # All normalised to lowercase + collapsed spaces
            "hypertext transfer protocol",
            "hyper text transfer protocol",     # space variant
            "hypertext transfer protocol",      # same after normalise, kept for clarity
            "http",                             # bare acronym counts as correct
        ],
        "target_language_variants": {
            "Arabic":   ["بروتوكول نقل النص التشعبي",
                         "بروتوكول نقل النص الفائق",
                         "hypertext transfer protocol"],
            "Chinese":  ["超文本传输协议",
                         "超文本轉送協定",            # Traditional ZH
                         "hypertext transfer protocol"],
            "English":  ["hypertext transfer protocol",
                         "hyper text transfer protocol"],
            "French":   ["protocole de transfert hypertexte",
                         "protocole hypertexte",
                         "hypertext transfer protocol"],
            "German":   ["hypertext transfer protocol",
                         "hypertext-transfer-protokoll"],
            "Hindi":    ["हाइपरटेक्स्ट ट्रांसफर प्रोटोकॉल",
                         "hypertext transfer protocol"],
            "Italian":  ["protocollo di trasferimento ipertestuale",
                         "hypertext transfer protocol"],
            "Japanese": ["ハイパーテキスト転送プロトコル",
                         "hypertext transfer protocol"],
            "Korean":   ["하이퍼텍스트 전송 프로토콜",
                         "hypertext transfer protocol"],
            "Polish":   ["protokół przesyłania hipertekstu",
                         "hypertext transfer protocol"],
            "Russian":  ["протокол передачи гипертекста",
                         "hypertext transfer protocol"],
            "Spanish":  ["protocolo de transferencia de hipertexto",
                         "protocolo de hipertexto",
                         "hypertext transfer protocol"],
        },
    },

    21: {  # Boolean affirmative — "yes" in target language
        "any_language_variants": [
            "yes",
            "sí", "si",   # ES / IT (without accent covered by normalize-strip)
            "sì",          # IT
            "oui",         # FR
            "ja",          # DE / AF / NL
            "да",          # RU / BG
            "نعم",         # AR
            "是", "对", "对的",  # ZH
            "はい",         # JA
            "예", "네",    # KO
            "हाँ", "हां", "हा",  # HI
            "tak",         # PL
        ],
        "target_language_variants": {
            "Arabic":   ["نعم"],
            "Chinese":  ["是", "对", "对的"],
            "English":  ["yes"],
            "French":   ["oui"],
            "German":   ["ja"],
            "Hindi":    ["हाँ", "हां", "हा"],
            "Italian":  ["sì", "si"],
            "Japanese": ["はい"],
            "Korean":   ["예", "네"],
            "Polish":   ["tak"],
            "Russian":  ["да"],
            "Spanish":  ["sí", "si"],
        },
    },
}


def evaluate(
    response_text: str,
    prompt_id: int,
    language_name: str,
    extra_any_variants: list[str] | None = None,
    extra_target_variants: list[str] | None = None,
) -> dict | None:
    """Evaluate a model response against expected answers for a given prompt/language.

    Returns a dict with three boolean keys, or None if no expected answers are
    registered for this prompt_id (meaning: evaluation not applicable).

    extra_any_variants    — MAGI-discovered variants valid in any language (language_id IS NULL)
    extra_target_variants — MAGI-discovered variants specific to this language

    Keys:
      correct              — factual answer is present in any recognised language form
      in_target_language   — answer is in the language that was requested
      language_leakage     — correct fact but expressed in the wrong language
    """
    spec = EXPECTED_ANSWERS.get(prompt_id)
    has_static = spec is not None and bool(spec.get("any_language_variants"))
    has_dynamic = bool(extra_any_variants) or bool(extra_target_variants)

    if not has_static and not has_dynamic:
        return None

    norm = _normalize(response_text or "")

    # Merge static + dynamic any-language variants
    any_variants = list(spec.get("any_language_variants", [])) if spec else []
    if extra_any_variants:
        any_variants = any_variants + [v for v in extra_any_variants if v not in any_variants]

    correct = any(_normalize(v) in norm for v in any_variants)

    # Merge static + dynamic target-language variants
    target_variants = []
    if spec:
        target_variants = list(spec.get("target_language_variants", {}).get(language_name, []))
    if extra_target_variants:
        target_variants = target_variants + [v for v in extra_target_variants if v not in target_variants]

    in_target = any(_normalize(v) in norm for v in target_variants)

    # A MAGI-discovered cross-language variant that matches also counts as in_target
    if not in_target and extra_target_variants:
        in_target = any(_normalize(v) in norm for v in extra_target_variants)

    return {
        "correct": correct,
        "in_target_language": in_target,
        "language_leakage": correct and not in_target,
    }
