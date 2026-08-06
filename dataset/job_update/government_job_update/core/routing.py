from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from shared.similarity import SimilarityBackend
from shared.text_utils import clean_text
from company_job_update.core.models import ScoredCandidate


ROUTE_REVIEW_COLUMNS = [
    "job_id",
    "month",
    "publish_time",
    "recruitment_year",
    "source",
    "source_name",
    "source_url",
    "government_agency",
    "government_department",
    "job_title",
    "cleaned_job_title",
    "job_responsibility",
    "job_requirement",
    "routing_text",
    "top_categories_json",
    "top_jobs_json",
    "top1_standard_category",
    "top1_standard_job",
    "top1_score",
    "top2_standard_job",
    "top2_score",
    "top1_margin",
    "top1_keyword_evidence",
    "route_status",
    "route_reason",
    "selected_standard_category",
    "selected_standard_job",
]


@dataclass(frozen=True, slots=True)
class GovernmentStandardJob:
    title: str
    category: str
    match_keywords: str

    @property
    def keywords(self) -> list[str]:
        return [clean_text(value) for value in self.match_keywords.split("|") if clean_text(value)]


class GovernmentTaxonomy:
    def __init__(self, jobs: Sequence[GovernmentStandardJob]) -> None:
        self.jobs = [job for job in jobs if job.title and job.category]
        if not self.jobs:
            raise ValueError("Government taxonomy contains no valid standard jobs")
        self.jobs_by_category: dict[str, list[GovernmentStandardJob]] = {}
        for job in self.jobs:
            self.jobs_by_category.setdefault(job.category, []).append(job)

    @classmethod
    def from_csv(cls, path: Path) -> "GovernmentTaxonomy":
        jobs: list[GovernmentStandardJob] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"standard_job_title", "standard_category", "match_keywords"}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Government job dictionary is missing columns: {sorted(missing)}")
            for row in reader:
                jobs.append(
                    GovernmentStandardJob(
                        title=clean_text(row.get("standard_job_title")),
                        category=clean_text(row.get("standard_category")),
                        match_keywords=clean_text(row.get("match_keywords")),
                    )
                )
        return cls(jobs)

    def score_jobs(
        self,
        job_title: str,
        similarity: SimilarityBackend,
        jobs: Sequence[GovernmentStandardJob] | None = None,
    ) -> list[ScoredCandidate]:
        candidates = list(jobs or self.jobs)
        scores = similarity.score(clean_text(job_title), [job.title for job in candidates])
        return sorted(
            [
                ScoredCandidate(
                    name=job.title,
                    score=max(0.0, min(1.0, float(score))),
                    metadata={
                        "category": job.category,
                        "semantic_score": max(0.0, min(1.0, float(score))),
                        "match_keywords": job.match_keywords,
                        "profile_text": job.title,
                    },
                )
                for job, score in zip(candidates, scores)
            ],
            key=lambda item: item.score,
            reverse=True,
        )

    def score_categories(
        self,
        job_title: str,
        similarity: SimilarityBackend,
    ) -> list[ScoredCandidate]:
        ranked_jobs = self.score_jobs(job_title, similarity)
        category_rows: list[ScoredCandidate] = []
        for category in self.jobs_by_category:
            top_jobs = [row for row in ranked_jobs if row.metadata.get("category") == category][:3]
            if not top_jobs:
                continue
            category_rows.append(
                ScoredCandidate(
                    name=category,
                    score=top_jobs[0].score,
                    metadata={
                        "aggregation_method": "top3_job_max",
                        "top_jobs": [
                            {"name": row.name, "score": row.score} for row in top_jobs
                        ],
                    },
                )
            )
        return sorted(category_rows, key=lambda item: item.score, reverse=True)


def build_government_route_review(
    postings: pd.DataFrame,
    *,
    taxonomy: GovernmentTaxonomy,
    similarity: SimilarityBackend,
    top_k: int = 5,
    candidate_floor: float = 0.45,
    progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    required = {"job_id", "routing_text", "job_title", "cleaned_job_title"}
    missing = sorted(required.difference(postings.columns))
    if missing:
        raise ValueError(f"Normalized government postings are missing columns: {missing}")
    if top_k < 2:
        raise ValueError("top_k must be at least 2")

    # Keep the text2vec stage faithful to the company routing rule: title only.
    # Government JD text is retained solely for LLM adjudication and human review.
    if (postings["cleaned_job_title"].map(clean_text) == "").any():
        raise ValueError("Run clean-titles first; text2vec must receive LLM-cleaned government job titles.")
    queries = [clean_text(value) for value in postings["cleaned_job_title"]]
    standard_job_titles = [job.title for job in taxonomy.jobs]
    score_rows = _score_many(similarity, queries, standard_job_titles, progress=progress)
    rows: list[dict[str, Any]] = []
    for (_, posting), scores in zip(postings.iterrows(), score_rows):
        ranked = _rank_jobs(taxonomy.jobs, scores, clean_text(posting.get("routing_text")))
        categories = _rank_categories(ranked)
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        margin = best["score"] - second["score"] if second else 1.0
        status, reason = _route_status(best, second, candidate_floor)
        rows.append(
            {
                **{column: clean_text(posting.get(column)) for column in ROUTE_REVIEW_COLUMNS if column in postings.columns},
                "top_categories_json": json.dumps(categories[:top_k], ensure_ascii=False),
                "top_jobs_json": json.dumps(ranked[:top_k], ensure_ascii=False),
                "top1_standard_category": best["category"],
                "top1_standard_job": best["standard_job"],
                "top1_score": round(float(best["score"]), 6),
                "top2_standard_job": second["standard_job"] if second else "",
                "top2_score": round(float(second["score"]), 6) if second else 0.0,
                "top1_margin": round(float(margin), 6),
                "top1_keyword_evidence": "; ".join(best["keyword_evidence"]),
                "route_status": status,
                "route_reason": reason,
                "selected_standard_category": "",
                "selected_standard_job": "",
            }
        )
    return pd.DataFrame(rows, columns=ROUTE_REVIEW_COLUMNS)


def _score_many(
    similarity: SimilarityBackend,
    queries: list[str],
    profiles: list[str],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> list[list[float]]:
    score_many = getattr(similarity, "score_many", None)
    if callable(score_many):
        try:
            return score_many(queries, profiles, batch_size=32, progress=progress)
        except TypeError:
            return score_many(queries, profiles)
    return [similarity.score(query, profiles) for query in queries]


def _rank_jobs(
    jobs: Sequence[GovernmentStandardJob],
    scores: Sequence[float],
    routing_text: str,
) -> list[dict[str, Any]]:
    rows = []
    lowered_text = routing_text.casefold()
    for job, raw_score in zip(jobs, scores):
        evidence = [keyword for keyword in job.keywords if keyword.casefold() in lowered_text]
        rows.append(
            {
                "standard_job": job.title,
                "category": job.category,
                "score": max(0.0, min(1.0, float(raw_score))),
                "keyword_evidence": evidence,
            }
        )
    return sorted(rows, key=lambda row: (row["score"], len(row["keyword_evidence"])), reverse=True)


def _rank_categories(ranked_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_category: dict[str, dict[str, Any]] = {}
    for row in ranked_jobs:
        best_by_category.setdefault(row["category"], row)
    return [
        {
            "standard_category": category,
            "score": row["score"],
            "top_standard_job": row["standard_job"],
        }
        for category, row in sorted(
            best_by_category.items(), key=lambda item: item[1]["score"], reverse=True
        )
    ]


def _route_status(
    best: dict[str, Any],
    second: dict[str, Any] | None,
    candidate_floor: float,
) -> tuple[str, str]:
    if best["score"] < candidate_floor:
        return "needs_human_review", f"top1 text2vec score below candidate floor {candidate_floor:.2f}"
    if not best["keyword_evidence"]:
        return "needs_llm_adjudication", "semantic candidate has no exact government dictionary keyword evidence"
    if second is not None and best["score"] - second["score"] < 0.05:
        return "needs_llm_adjudication", "top1/top2 semantic margin is below 0.05"
    return "needs_llm_adjudication", "government routes require LLM adjudication before formal event assignment"
