from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .frequency_store import EVENT_COLUMNS
from .taxonomy import JobTaxonomy
from .text import clean_text, split_semicolon


JOB_DEMAND_ANALYSIS_COLUMNS = [
    "standard_job",
    "standard_category",
    "month",
    "month_index",
    "monthly_jd_count",
    "cumulative_jd_count",
    "is_active_month",
]

SKILL_FREQUENCY_ANALYSIS_COLUMNS = [
    "month",
    "month_index",
    "standard_job",
    "standard_category",
    "skill",
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    job_demand: pd.DataFrame
    skill_frequency: pd.DataFrame
    quality_report: dict[str, Any]


def analyze_event_stream(
    events: pd.DataFrame,
    taxonomy: JobTaxonomy,
    month_start: str | None = None,
    month_end: str | None = None,
    skill_universe: pd.DataFrame | None = None,
) -> AnalysisResult:
    normalized_events = _normalize_events(events)
    months = _analysis_months(normalized_events, month_start, month_end)
    standard_jobs = [job.title for job in taxonomy.jobs]
    category_by_job = {job.title: job.category for job in taxonomy.jobs}

    unknown_jobs = sorted(
        set(normalized_events["standard_job"].dropna()) - set(standard_jobs)
    )

    job_demand = _build_job_demand_table(
        normalized_events=normalized_events,
        standard_jobs=standard_jobs,
        category_by_job=category_by_job,
        months=months,
    )
    skill_frequency = _build_skill_frequency_table(
        normalized_events=normalized_events,
        category_by_job=category_by_job,
        months=months,
        skill_universe=skill_universe,
    )

    quality_report = {
        "event_stream_rows": int(len(normalized_events)),
        "valid_event_rows": int(
            len(
                normalized_events[
                    (normalized_events["job_id"] != "")
                    & (normalized_events["month"] != "")
                    & (normalized_events["standard_job"] != "")
                ]
            )
        ),
        "month_start": months[0] if months else "",
        "month_end": months[-1] if months else "",
        "month_count": len(months),
        "standard_job_count": len(standard_jobs),
        "event_jobs_in_dictionary": int(
            normalized_events["standard_job"].isin(standard_jobs).sum()
        ),
        "unknown_standard_jobs": unknown_jobs,
        "job_demand_rows": int(len(job_demand)),
        "skill_frequency_rows": int(len(skill_frequency)),
        "unique_event_jobs": int(normalized_events["standard_job"].nunique()),
        "unique_event_skills": int(
            skill_frequency["skill"].nunique() if not skill_frequency.empty else 0
        ),
        "jobs_without_events": [
            job
            for job in standard_jobs
            if job not in set(normalized_events["standard_job"])
        ],
    }
    return AnalysisResult(
        job_demand=job_demand,
        skill_frequency=skill_frequency,
        quality_report=quality_report,
    )


def read_events(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def read_skill_universe(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def write_analysis_outputs(result: AnalysisResult, output_dir: str | Path) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    job_demand_path = output_path / "job_demand_monthly_analysis.csv"
    skill_frequency_path = output_path / "job_skill_monthly_frequency_analysis.csv"
    quality_report_path = output_path / "analysis_quality_report.json"

    result.job_demand.to_csv(job_demand_path, index=False, encoding="utf-8-sig")
    result.skill_frequency.to_csv(skill_frequency_path, index=False, encoding="utf-8-sig")
    with quality_report_path.open("w", encoding="utf-8") as handle:
        json.dump(result.quality_report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "job_demand": str(job_demand_path),
        "skill_frequency": str(skill_frequency_path),
        "quality_report": str(quality_report_path),
    }


def _normalize_events(events: pd.DataFrame) -> pd.DataFrame:
    normalized = events.copy().fillna("")
    for column in EVENT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[EVENT_COLUMNS].copy()
    for column in EVENT_COLUMNS:
        normalized[column] = normalized[column].map(clean_text)
    return normalized


def _analysis_months(
    events: pd.DataFrame,
    month_start: str | None,
    month_end: str | None,
) -> list[str]:
    start = clean_text(month_start)
    end = clean_text(month_end)
    event_months = sorted(
        month
        for month in events["month"].dropna().map(clean_text).unique()
        if month
    )
    if not start and event_months:
        start = event_months[0]
    if not end and event_months:
        end = event_months[-1]
    if not start or not end:
        return []
    return month_sequence(start, end)


def month_sequence(start: str, end: str) -> list[str]:
    start_year, start_month = [int(part) for part in start.split("-")]
    end_year, end_month = [int(part) for part in end.split("-")]
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def _build_job_demand_table(
    normalized_events: pd.DataFrame,
    standard_jobs: list[str],
    category_by_job: dict[str, str],
    months: list[str],
) -> pd.DataFrame:
    valid = normalized_events[
        (normalized_events["job_id"] != "")
        & (normalized_events["month"] != "")
        & (normalized_events["standard_job"] != "")
    ].copy()
    monthly_counts = (
        valid.groupby(["standard_job", "month"])["job_id"].nunique().to_dict()
    )

    rows: list[dict[str, Any]] = []
    for job in standard_jobs:
        cumulative = 0
        for month_index, month in enumerate(months, start=1):
            monthly_count = int(monthly_counts.get((job, month), 0))
            cumulative += monthly_count
            rows.append(
                {
                    "standard_job": job,
                    "standard_category": category_by_job.get(job, ""),
                    "month": month,
                    "month_index": month_index,
                    "monthly_jd_count": monthly_count,
                    "cumulative_jd_count": cumulative,
                    "is_active_month": "yes" if monthly_count > 0 else "no",
                }
            )
    return pd.DataFrame(rows, columns=JOB_DEMAND_ANALYSIS_COLUMNS)


def _build_skill_frequency_table(
    normalized_events: pd.DataFrame,
    category_by_job: dict[str, str],
    months: list[str],
    skill_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    valid = normalized_events[
        (normalized_events["job_id"] != "")
        & (normalized_events["month"] != "")
        & (normalized_events["standard_job"] != "")
    ].copy()
    if valid.empty:
        return pd.DataFrame(columns=SKILL_FREQUENCY_ANALYSIS_COLUMNS)

    monthly_jd_counts = (
        valid.groupby(["standard_job", "month"])["job_id"].nunique().to_dict()
    )
    exploded = _explode_event_skills(valid)
    skills_by_job = _skills_by_job_from_universe(skill_universe)
    if not exploded.empty:
        observed_skills_by_job = (
            exploded.groupby("standard_job")["skill"]
            .apply(lambda series: sorted(set(series)))
            .to_dict()
        )
        for job, skills in observed_skills_by_job.items():
            skills_by_job.setdefault(job, set()).update(skills)

    if not skills_by_job:
        return pd.DataFrame(columns=SKILL_FREQUENCY_ANALYSIS_COLUMNS)

    if exploded.empty:
        monthly_skill_counts = {}
    else:
        monthly_skill_counts = (
            exploded.groupby(["standard_job", "month", "skill"])["job_id"]
            .nunique()
            .to_dict()
        )

    rows: list[dict[str, Any]] = []
    for job in sorted(skills_by_job):
        cumulative_jd = 0
        skills = sorted(skills_by_job[job])
        cumulative_skill_counts = {skill: 0 for skill in skills}
        for month_index, month in enumerate(months, start=1):
            monthly_jd_count = int(monthly_jd_counts.get((job, month), 0))
            cumulative_jd += monthly_jd_count
            for skill in skills:
                monthly_skill_count = int(
                    monthly_skill_counts.get((job, month, skill), 0)
                )
                cumulative_skill_counts[skill] += monthly_skill_count
                rows.append(
                    {
                        "month": month,
                        "month_index": month_index,
                        "standard_job": job,
                        "standard_category": category_by_job.get(job, ""),
                        "skill": skill,
                        "monthly_jd_count": monthly_jd_count,
                        "monthly_skill_count": monthly_skill_count,
                        "monthly_skill_frequency": _ratio(
                            monthly_skill_count,
                            monthly_jd_count,
                        ),
                        "cumulative_jd_count": cumulative_jd,
                        "cumulative_skill_count": cumulative_skill_counts[skill],
                        "cumulative_skill_frequency": _ratio(
                            cumulative_skill_counts[skill],
                            cumulative_jd,
                        ),
                    }
                )
    return pd.DataFrame(rows, columns=SKILL_FREQUENCY_ANALYSIS_COLUMNS)


def _explode_event_skills(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for _, row in events.iterrows():
        for skill in sorted(set(split_semicolon(row.get("skills")))):
            rows.append(
                {
                    "job_id": clean_text(row.get("job_id")),
                    "month": clean_text(row.get("month")),
                    "standard_job": clean_text(row.get("standard_job")),
                    "skill": skill,
                }
            )
    return pd.DataFrame(rows, columns=["job_id", "month", "standard_job", "skill"])


def _skills_by_job_from_universe(
    skill_universe: pd.DataFrame | None,
) -> dict[str, set[str]]:
    if skill_universe is None or skill_universe.empty:
        return {}
    if "standard_job" not in skill_universe.columns or "skill" not in skill_universe.columns:
        raise ValueError("Skill universe must include standard_job and skill columns")

    skills_by_job: dict[str, set[str]] = {}
    for _, row in skill_universe.fillna("").iterrows():
        job = clean_text(row.get("standard_job"))
        skill = clean_text(row.get("skill"))
        if not job or not skill:
            continue
        skills_by_job.setdefault(job, set()).add(skill)
    return skills_by_job


def _ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0000"
    return f"{numerator / denominator:.4f}"
