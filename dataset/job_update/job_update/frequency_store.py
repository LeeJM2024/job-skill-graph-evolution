from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .models import JobPosting, NormalizedSkill
from .text import clean_text, split_semicolon


EVENT_COLUMNS = [
    "job_id",
    "month",
    "standard_job",
    "job_responsibility",
    "job_requirement",
    "skills",
]

FREQUENCY_COLUMNS = [
    "month",
    "standard_job",
    "skill",
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
]


@dataclass(slots=True)
class FrequencyStore:
    event_stream_path: Path
    frequency_path: Path | None = None

    def load_events(self) -> pd.DataFrame:
        if not self.event_stream_path.exists():
            return pd.DataFrame(columns=EVENT_COLUMNS)
        events = pd.read_csv(self.event_stream_path, dtype=str).fillna("")
        for column in EVENT_COLUMNS:
            if column not in events.columns:
                events[column] = ""
        return events[EVENT_COLUMNS]

    def append_existing_job(
        self,
        posting: JobPosting,
        standard_job: str,
        normalized_skills: list[NormalizedSkill],
        write: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        events = self.load_events()
        if clean_text(posting.job_id) and posting.job_id in set(events["job_id"].astype(str)):
            raise ValueError(f"job_id already exists in event stream: {posting.job_id}")

        row = {
            "job_id": clean_text(posting.job_id),
            "month": clean_text(posting.month),
            "standard_job": clean_text(standard_job),
            "job_responsibility": clean_text(posting.job_responsibility),
            "job_requirement": clean_text(posting.job_requirement),
            "skills": "; ".join(skill.normalized_skill for skill in normalized_skills if skill.normalized_skill),
        }
        events = pd.concat([events, pd.DataFrame([row])], ignore_index=True)
        frequency = rebuild_frequency_table(events)
        if write:
            self.write_tables(events, frequency)
        return events, frequency

    def write_tables(self, events: pd.DataFrame, frequency: pd.DataFrame) -> None:
        self.event_stream_path.parent.mkdir(parents=True, exist_ok=True)
        events.to_csv(self.event_stream_path, index=False, encoding="utf-8-sig")
        if self.frequency_path is not None:
            self.frequency_path.parent.mkdir(parents=True, exist_ok=True)
            frequency.to_csv(self.frequency_path, index=False, encoding="utf-8-sig")


def rebuild_frequency_table(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=FREQUENCY_COLUMNS)

    normalized_events = events.copy().fillna("")
    for column in EVENT_COLUMNS:
        if column not in normalized_events.columns:
            normalized_events[column] = ""
    normalized_events = normalized_events[EVENT_COLUMNS]
    normalized_events["month"] = normalized_events["month"].map(clean_text)
    normalized_events["standard_job"] = normalized_events["standard_job"].map(clean_text)
    normalized_events["job_id"] = normalized_events["job_id"].map(clean_text)
    normalized_events = normalized_events[
        (normalized_events["month"] != "")
        & (normalized_events["standard_job"] != "")
        & (normalized_events["job_id"] != "")
    ].copy()

    monthly_jd = (
        normalized_events.groupby(["standard_job", "month"], as_index=False)["job_id"]
        .nunique()
        .rename(columns={"job_id": "monthly_jd_count"})
    )

    exploded = _explode_event_skills(normalized_events)
    if exploded.empty:
        return pd.DataFrame(columns=FREQUENCY_COLUMNS)

    monthly_skill = (
        exploded.groupby(["standard_job", "month", "skill"], as_index=False)["job_id"]
        .nunique()
        .rename(columns={"job_id": "monthly_skill_count"})
    )

    rows: list[dict[str, Any]] = []
    for standard_job, job_months in monthly_jd.groupby("standard_job"):
        month_counts = {
            row["month"]: int(row["monthly_jd_count"]) for _, row in job_months.sort_values("month").iterrows()
        }
        months = sorted(month_counts)
        job_skill_counts = monthly_skill[monthly_skill["standard_job"] == standard_job]
        skills = sorted(job_skill_counts["skill"].unique())
        cumulative_jd = 0
        cumulative_skill_counts = {skill: 0 for skill in skills}
        appeared: set[str] = set()

        for month in months:
            monthly_jd_count = month_counts[month]
            cumulative_jd += monthly_jd_count
            current = job_skill_counts[job_skill_counts["month"] == month]
            current_counts = {
                row["skill"]: int(row["monthly_skill_count"]) for _, row in current.iterrows()
            }
            appeared.update(skill for skill, count in current_counts.items() if count > 0)
            for skill in sorted(appeared):
                monthly_skill_count = current_counts.get(skill, 0)
                cumulative_skill_counts[skill] += monthly_skill_count
                rows.append(
                    {
                        "month": month,
                        "standard_job": standard_job,
                        "skill": skill,
                        "monthly_jd_count": monthly_jd_count,
                        "monthly_skill_count": monthly_skill_count,
                        "monthly_skill_frequency": _ratio(monthly_skill_count, monthly_jd_count),
                        "cumulative_jd_count": cumulative_jd,
                        "cumulative_skill_count": cumulative_skill_counts[skill],
                        "cumulative_skill_frequency": _ratio(cumulative_skill_counts[skill], cumulative_jd),
                    }
                )

    return pd.DataFrame(rows, columns=FREQUENCY_COLUMNS).sort_values(
        ["standard_job", "skill", "month"]
    )


def _explode_event_skills(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for _, row in events.iterrows():
        skills = sorted(set(split_semicolon(row.get("skills"))))
        for skill in skills:
            rows.append(
                {
                    "job_id": clean_text(row.get("job_id")),
                    "month": clean_text(row.get("month")),
                    "standard_job": clean_text(row.get("standard_job")),
                    "skill": skill,
                }
            )
    return pd.DataFrame(rows, columns=["job_id", "month", "standard_job", "skill"])


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
