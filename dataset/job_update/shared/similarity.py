from __future__ import annotations

import math
from typing import Callable, Protocol, Sequence


class SimilarityBackend(Protocol):
    def score(self, query: str, candidates: Sequence[str]) -> list[float]:
        ...


class Text2VecSimilarity:
    """Shared adapter for the real shibing624/text2vec SentenceModel."""

    def __init__(self, model_name_or_path: str = "shibing624/text2vec-base-chinese") -> None:
        try:
            from text2vec import SentenceModel
        except ImportError as exc:
            raise ImportError(
                "text2vec is required for job routing. Install it with `pip install text2vec`."
            ) from exc
        self.model = SentenceModel(model_name_or_path)

    def score(self, query: str, candidates: Sequence[str]) -> list[float]:
        return self.score_many([query], candidates)[0] if candidates else []

    def score_many(
        self,
        queries: Sequence[str],
        candidates: Sequence[str],
        *,
        batch_size: int = 32,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        if not queries:
            return []
        if not candidates:
            return [[] for _ in queries]
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        candidate_vectors = self.model.encode(list(candidates), batch_size=batch_size)
        results: list[list[float]] = []
        total = len(queries)
        for start in range(0, total, batch_size):
            batch = queries[start : start + batch_size]
            query_vectors = self.model.encode(list(batch), batch_size=batch_size)
            results.extend(
                [
                    [self._cosine(query_vector, candidate_vector) for candidate_vector in candidate_vectors]
                    for query_vector in query_vectors
                ]
            )
            if progress is not None:
                progress(min(start + len(batch), total), total)
        return results

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)
