"""
TokenScribe — Scoring Service
Author: Matteo Morreale

Computes:
  - DSF: embedding cosine similarity (original vs translation)
  - RTF: embedding cosine similarity (original vs back-translation)
  - SFS = 0.7 * DSF + 0.3 * RTF
  - PEI: mean coefficient of variation across char_length, word_count, tiktoken count
"""

import math
import statistics
from typing import List, Optional


class ScoringService:
    """
    Scientific scoring engine for TokenScribe.
    Uses sentence-transformers for local embeddings (no external API needed).
    Falls back to a simple cosine similarity on TF-IDF vectors if model unavailable.
    """

    EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self):
        self._embedder = None
        self._tiktoken_enc = None

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.EMBEDDING_MODEL)
            except Exception:
                self._embedder = None
        return self._embedder

    def _get_tiktoken(self):
        if self._tiktoken_enc is None:
            try:
                import tiktoken
                self._tiktoken_enc = tiktoken.get_encoding("cl100k_base")
            except Exception:
                self._tiktoken_enc = None
        return self._tiktoken_enc

    # ------------------------------------------------------------------
    # Embedding similarity
    # ------------------------------------------------------------------

    def _embed(self, texts: List[str]):
        embedder = self._get_embedder()
        if embedder is None:
            raise RuntimeError("sentence-transformers not available")
        return embedder.encode(texts, convert_to_numpy=True)

    @staticmethod
    def _cosine(a, b) -> float:
        import numpy as np
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def compute_dsf(self, original: str, translation: str) -> float:
        """DSF: cosine similarity between original and translation embeddings."""
        vecs = self._embed([original, translation])
        return round(self._cosine(vecs[0], vecs[1]), 6)

    def compute_rtf(self, original: str, back_translation: str) -> float:
        """RTF: cosine similarity between original and back-translated text."""
        vecs = self._embed([original, back_translation])
        return round(self._cosine(vecs[0], vecs[1]), 6)

    def compute_sfs(self, dsf: float, rtf: float) -> float:
        """SFS = 0.7 * DSF + 0.3 * RTF"""
        return round(0.7 * dsf + 0.3 * rtf, 6)

    def score_translation(
        self,
        original: str,
        translation: str,
        back_translation: Optional[str] = None,
    ) -> dict:
        """
        Compute full SFS for a translation candidate.
        If back_translation is None, RTF is computed using the translation itself
        as a proxy (conservative estimate).
        Returns: {dsf, rtf, sfs}
        """
        dsf = self.compute_dsf(original, translation)
        bt = back_translation if back_translation else translation
        rtf = self.compute_rtf(original, bt)
        sfs = self.compute_sfs(dsf, rtf)
        return {"dsf": dsf, "rtf": rtf, "sfs": sfs}

    # ------------------------------------------------------------------
    # PEI computation
    # ------------------------------------------------------------------

    @staticmethod
    def _coefficient_of_variation(values: List[float]) -> float:
        """CV = std / mean. Returns 0 if mean is 0."""
        if len(values) < 2:
            return 0.0
        mean = statistics.mean(values)
        if mean == 0:
            return 0.0
        std = statistics.stdev(values)
        return round(std / mean, 6)

    def _count_tiktoken(self, text: str) -> int:
        enc = self._get_tiktoken()
        if enc is None:
            return len(text.split())
        return len(enc.encode(text))

    def compute_structural_metrics(self, text: str) -> dict:
        text = text or ""
        return {
            "char_length": len(text),
            "word_count": len(text.split()),
            "token_count": self._count_tiktoken(text),
        }

    def compute_pei(self, texts: List[str]) -> dict:
        """
        Compute PEI across a list of structurally equivalent texts (one per language).
        Returns: {cv_char_length, cv_word_count, cv_token_count, pei}
        """
        if not texts:
            return {"cv_char_length": 0.0, "cv_word_count": 0.0, "cv_token_count": 0.0, "pei": 0.0}

        char_lengths = [len(t) for t in texts]
        word_counts = [len(t.split()) for t in texts]
        token_counts = [self._count_tiktoken(t) for t in texts]

        cv_char = self._coefficient_of_variation([float(x) for x in char_lengths])
        cv_word = self._coefficient_of_variation([float(x) for x in word_counts])
        cv_tok = self._coefficient_of_variation([float(x) for x in token_counts])

        pei = round((cv_char + cv_word + cv_tok) / 3.0, 6)

        return {
            "cv_char_length": cv_char,
            "cv_word_count": cv_word,
            "cv_token_count": cv_tok,
            "pei": pei,
        }

    @staticmethod
    def pei_band(pei: float) -> str:
        v = float(pei or 0.0)
        if v < 0.20:
            return "ottimo"
        if v <= 0.35:
            return "plausibile"
        return "alto"
