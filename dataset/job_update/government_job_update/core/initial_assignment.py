from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from shared.text_utils import clean_text


ASSIGNMENT_COLUMNS = [
    "job_id",
    "month",
    "job_title",
    "government_agency",
    "government_department",
    "assigned_standard_category",
    "assigned_standard_job",
    "assignment_status",
    "assignment_score",
    "assignment_margin",
    "matched_keywords_json",
    "candidate_scores_json",
    "assignment_reason",
]

ASSIGNMENT_REVIEW_COLUMNS = [
    "job_id",
    "month",
    "job_title",
    "government_agency",
    "government_department",
    "job_responsibility",
    "job_requirement",
    "assigned_standard_category",
    "assigned_standard_job",
    "assignment_status",
    "assignment_score",
    "assignment_margin",
    "matched_keywords_json",
    "candidate_scores_json",
    "assignment_reason",
    "audit_decision",
    "corrected_standard_category",
    "corrected_standard_job",
    "audit_note",
]


# Government source titles are frequently generic administrative titles.  The
# actual job description is therefore stronger evidence than academic-major
# requirements; a major alone may only support the generic computer job.
TEXT_WEIGHTS = {
    "job_title": 6,
    "job_responsibility": 5,
    "job_requirement": 1,
}

SPECIALTY_PRIORITY = {
    "政府电子数据取证与情报技术岗": 100,
    "政府信息化审计岗": 95,
    "政府警务信息技术保障岗": 90,
    "政府网络与数据安全岗": 85,
    "政府地理信息与空间数据技术岗": 80,
    "政府智能化与自动化技术岗": 75,
    "政府通信电子技术岗": 70,
    "政府网络与通信运维岗": 65,
    "政府信息系统开发岗": 60,
    "政府信息系统运维岗": 55,
    "政府数据治理与统计分析岗": 50,
    "政府数字监管与科技执法岗": 45,
    "政府信息化建设与管理岗": 40,
    "政府通用计算机技术岗": 0,
}


@dataclass(frozen=True, slots=True)
class SeedJob:
    title: str
    category: str
    keywords: list[str]


def build_initial_assignment(postings: pd.DataFrame, dictionary_path: Path) -> pd.DataFrame:
    jobs = _read_jobs(dictionary_path)
    rows = [_assign_row(row, jobs) for _, row in postings.fillna("").iterrows()]
    return pd.DataFrame(rows, columns=ASSIGNMENT_COLUMNS)


def build_initial_assignment_review(postings: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    review = postings.fillna("").merge(assignments.fillna(""), on="job_id", how="inner", validate="one_to_one")
    review = review[review["assignment_status"] == "needs_review"].copy()
    for column in ASSIGNMENT_REVIEW_COLUMNS:
        if column not in review.columns:
            review[column] = ""
    return review[ASSIGNMENT_REVIEW_COLUMNS].sort_values(
        ["assignment_margin", "assignment_score", "assigned_standard_job", "job_id"],
        ascending=[True, True, True, True],
    ).reset_index(drop=True)


def _read_jobs(path: Path) -> list[SeedJob]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            SeedJob(
                title=clean_text(row.get("standard_job_title")),
                category=clean_text(row.get("standard_category")),
                keywords=[clean_text(value) for value in str(row.get("match_keywords") or "").split("|") if clean_text(value)],
            )
            for row in reader
            if clean_text(row.get("standard_job_title")) and clean_text(row.get("standard_category"))
        ]


def _assign_row(row: pd.Series, jobs: list[SeedJob]) -> dict[str, str | float]:
    fields = {field: clean_text(row.get(field)).casefold() for field in TEXT_WEIGHTS}
    candidates: list[dict[str, object]] = []
    for job in jobs:
        evidence: list[dict[str, object]] = []
        score = 0
        for field, weight in TEXT_WEIGHTS.items():
            matched = [keyword for keyword in job.keywords if keyword.casefold() in fields[field]]
            if matched:
                score += weight * len(matched)
                evidence.append({"field": field, "keywords": matched, "weight": weight})
        # The generic computer job can be supported by the screened technical
        # tags and degree requirements, but never outranks a named function.
        if job.title == "政府通用计算机技术岗" and not evidence:
            tags = clean_text(row.get("tags")).casefold()
            if "computer_software" in tags:
                score = 1
                evidence.append({"field": "tags", "keywords": ["computer_software"], "weight": 1})
        candidates.append(
            {
                "standard_job": job.title,
                "standard_category": job.category,
                "score": score,
                "priority": SPECIALTY_PRIORITY.get(job.title, 0),
                "evidence": evidence,
            }
        )
    ranked = sorted(candidates, key=lambda item: (int(item["score"]), int(item["priority"])), reverse=True)
    best = ranked[0]
    second = ranked[1]
    score = int(best["score"])
    margin = score - int(second["score"])
    specialty = int(best["priority"]) > 0
    if score <= 0:
        status = "needs_review"
        reason = "no seed-keyword evidence"
    elif specialty and score <= 1:
        status = "needs_review"
        reason = "specialty assignment relies on weak evidence only"
    elif score == int(second["score"]) and int(second["score"]) > 0:
        status = "needs_review"
        reason = "top seed-rule candidates are tied"
    elif margin <= 1 and int(second["score"]) > 0:
        status = "needs_review"
        reason = "top seed-rule candidates are close"
    else:
        status = "assigned"
        reason = "seed taxonomy keyword rule"
    return {
        "job_id": clean_text(row.get("job_id")),
        "month": clean_text(row.get("month")),
        "job_title": clean_text(row.get("job_title")),
        "government_agency": clean_text(row.get("government_agency")),
        "government_department": clean_text(row.get("government_department")),
        "assigned_standard_category": str(best["standard_category"]),
        "assigned_standard_job": str(best["standard_job"]),
        "assignment_status": status,
        "assignment_score": score,
        "assignment_margin": margin,
        "matched_keywords_json": json.dumps(best["evidence"], ensure_ascii=False),
        "candidate_scores_json": json.dumps(
            [
                {
                    "standard_job": candidate["standard_job"],
                    "score": candidate["score"],
                    "evidence": candidate["evidence"],
                }
                for candidate in ranked[:5]
            ],
            ensure_ascii=False,
        ),
        "assignment_reason": reason,
    }
