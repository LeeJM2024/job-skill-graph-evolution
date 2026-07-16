from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import JobRoute, ScoredCandidate
from .similarity import SimilarityBackend
from .text import clean_text


@dataclass(slots=True)
class StandardJob:
    title: str
    category: str
    match_keywords: str = ""

    @property
    def profile_text(self) -> str:
        return " ".join(part for part in [self.title, self.match_keywords] if part)


class JobTaxonomy:
    def __init__(self, jobs: list[StandardJob]) -> None:
        self.jobs = [job for job in jobs if job.title and job.category]
        self.jobs_by_category: dict[str, list[StandardJob]] = {}
        for job in self.jobs:
            self.jobs_by_category.setdefault(job.category, []).append(job)

    @classmethod
    def from_csv(cls, path: str | Path) -> "JobTaxonomy":
        rows: list[StandardJob] = []
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"standard_job_title", "standard_category"}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing required columns in {path}: {sorted(missing)}")
            for record in reader:
                rows.append(
                    StandardJob(
                        title=clean_text(record.get("standard_job_title")),
                        category=clean_text(record.get("standard_category")),
                        match_keywords=clean_text(record.get("match_keywords")),
                    )
                )
        return cls(rows)

    def category_profiles(self) -> dict[str, str]:
        profiles: dict[str, str] = {}
        for category, jobs in self.jobs_by_category.items():
            parts = [category]
            for job in jobs:
                parts.append(job.title)
                if job.match_keywords:
                    parts.append(job.match_keywords)
            profiles[category] = " ".join(parts)
        return profiles

    def route(
        self,
        job_title: str,
        similarity: SimilarityBackend,
        category_threshold: float = 0.6,
        job_threshold: float = 0.85,
        tie_delta: float = 0.03,
        max_categories: int = 3,
    ) -> JobRoute:
        title = clean_text(job_title)
        category_scores = self._score_categories(title, similarity)
        best_category = category_scores[0] if category_scores else None
        if best_category is None or best_category.score < category_threshold:
            return JobRoute(
                status="new_family",
                selected_categories=[],
                selected_jobs=[],
                best_category=best_category,
                reason=f"best category score is below {category_threshold}",
            )

        selected_categories = [
            candidate
            for candidate in category_scores
            if candidate.score >= category_threshold and best_category.score - candidate.score <= tie_delta
        ][:max_categories]

        job_candidates = [
            job for category in selected_categories for job in self.jobs_by_category.get(category.name, [])
        ]
        selected_jobs = self._score_jobs(title, similarity, job_candidates)
        best_job = selected_jobs[0] if selected_jobs else None
        if best_job is None or best_job.score < job_threshold:
            return JobRoute(
                status="potential_new_job",
                selected_categories=selected_categories,
                selected_jobs=selected_jobs,
                best_category=best_category,
                best_job=best_job,
                reason=f"best job score is below {job_threshold}",
            )

        tied_jobs = [
            candidate for candidate in selected_jobs if best_job.score - candidate.score <= tie_delta
        ]
        return JobRoute(
            status="existing_job",
            selected_categories=selected_categories,
            selected_jobs=tied_jobs,
            best_category=best_category,
            best_job=best_job,
            reason="matched existing standard job",
        )

    def _score_categories(self, job_title: str, similarity: SimilarityBackend) -> list[ScoredCandidate]:
        profiles = self.category_profiles()
        names = list(profiles)
        semantic_scores = similarity.score(job_title, [profiles[name] for name in names])
        candidates: list[ScoredCandidate] = []
        for name, score in zip(names, semantic_scores):
            semantic_score = self._bounded(score)
            candidates.append(
                ScoredCandidate(
                    name=name,
                    score=semantic_score,
                    metadata={
                        "profile": profiles[name],
                        "semantic_score": semantic_score,
                    },
                )
            )
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score_jobs(
        self,
        job_title: str,
        similarity: SimilarityBackend,
        jobs: list[StandardJob],
    ) -> list[ScoredCandidate]:
        if not jobs:
            return []
        semantic_scores = similarity.score(job_title, [job.title for job in jobs])
        candidates: list[ScoredCandidate] = []
        for job, score in zip(jobs, semantic_scores):
            final_score = self._bounded(score)
            candidates.append(
                ScoredCandidate(
                    name=job.title,
                    score=final_score,
                    metadata={
                        "category": job.category,
                        "semantic_score": self._bounded(score),
                        "match_keywords": job.match_keywords,
                        "profile_text": job.title,
                    },
                )
            )
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _bounded(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0
