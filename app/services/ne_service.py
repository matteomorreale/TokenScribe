"""
TokenScribe — NE Service (Named Entity Preservation Rate)
Author: Matteo Morreale

Computes NEPR: the fraction of expected named entities (as labeled by MAGI)
that appear in the correct localized form in the model's response.
"""

from app.services.correctness_service import _normalize


def compute_nepr(response_text: str, expectations: list[dict]) -> float | None:
    """
    Compute Named Entity Preservation Rate.

    expectations: list of dicts with keys:
      entity_name    — original English entity  (e.g. "France")
      expected_form  — localized expected form   (e.g. "Francia")
      allow_original — if True, original form also counts as correct

    Returns a float in [0.0, 1.0], or None if no expectations exist.
    """
    if not expectations:
        return None

    norm_resp = _normalize(response_text or "")
    correct = 0

    for exp in expectations:
        expected_norm = _normalize(exp.get("expected_form") or "")
        original_norm = _normalize(exp.get("entity_name") or "")
        in_expected  = expected_norm and expected_norm in norm_resp
        in_original  = exp.get("allow_original") and original_norm and original_norm in norm_resp
        if in_expected or in_original:
            correct += 1

    return round(correct / len(expectations), 4)
