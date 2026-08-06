from __future__ import annotations

import math
from typing import Protocol, Sequence


class SimilarityBackend(Protocol):
    def score(self, query: str, candidates: Sequence[str]) -> list[float]:
        ...


class Text2VecSimilarity:
    """Adapter for shibing624/text2vec SentenceModel.

    Example:
        backend = Text2VecSimilarity("shibing624/text2vec-base-chinese")
    """

    def __init__(self, model_name_or_path: str = "shibing624/text2vec-base-chinese") -> None:
        try:
            from text2vec import SentenceModel
        except ImportError as exc:
            raise ImportError(
                "text2vec is required for job routing. Install it with `pip install text2vec`."
            ) from exc
        self.model = SentenceModel(model_name_or_path)

    def score(self, query: str, candidates: Sequence[str]) -> list[float]:
        if not candidates:
            return []
        texts = [query, *candidates]
        embeddings = self.model.encode(texts)
        query_vec = embeddings[0]
        return [self._cosine(query_vec, candidate_vec) for candidate_vec in embeddings[1:]]

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
