from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from company_job_update.core.frequency_store import EVENT_COLUMNS, FREQUENCY_COLUMNS, rebuild_frequency_table
from company_job_update.core.models import JobPosting, NormalizedSkill
from shared.text_utils import clean_text


# The shared frequency algorithm consumes the seven EVENT_COLUMNS above.  This
# domain store deliberately retains government provenance beside those fields.
GOVERNMENT_EVENT_COLUMNS = [
    *EVENT_COLUMNS,
    "source",
    "source_name",
    "publish_time",
    "recruitment_year",
    "source_url",
    "government_agency",
    "government_department",
    "location",
    "cleaned_job_title",
    "route_status",
    "event_time_type",
    "source_time_granularity",
]


@dataclass(slots=True)
class GovernmentFrequencyStore:
    event_stream_path: Path
    frequency_path: Path | None = None

    def load_events(self) -> pd.DataFrame:
        if not self.event_stream_path.exists():
            return pd.DataFrame(columns=GOVERNMENT_EVENT_COLUMNS)
        events = pd.read_csv(self.event_stream_path, dtype=str, encoding="utf-8-sig").fillna("")
        for column in GOVERNMENT_EVENT_COLUMNS:
            if column not in events.columns:
                events[column] = ""
        return events[GOVERNMENT_EVENT_COLUMNS]

    def append_existing_job(
        self,
        posting: JobPosting,
        standard_job: str,
        normalized_skills: list[NormalizedSkill],
        write: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        events = self.load_events()
        if clean_text(posting.job_id) and posting.job_id in set(events["job_id"].astype(str)):
            raise ValueError(f"job_id already exists in government event stream: {posting.job_id}")
        metadata = posting.metadata
        row = {
            "job_id": clean_text(posting.job_id),
            "month": clean_text(posting.month),
            "standard_job": clean_text(standard_job),
            "job_title": clean_text(posting.job_title),
            "job_responsibility": clean_text(posting.job_responsibility),
            "job_requirement": clean_text(posting.job_requirement),
            "skills": "; ".join(skill.normalized_skill for skill in normalized_skills if skill.normalized_skill),
            "source": clean_text(metadata.get("source")) or "government",
            "source_name": clean_text(metadata.get("source_name")),
            "publish_time": clean_text(metadata.get("publish_time")),
            "recruitment_year": clean_text(metadata.get("recruitment_year")),
            "source_url": clean_text(metadata.get("source_url")),
            "government_agency": clean_text(metadata.get("government_agency")),
            "government_department": clean_text(metadata.get("government_department")),
            "location": clean_text(metadata.get("location")),
            "cleaned_job_title": clean_text(posting.routing_job_title),
            "route_status": "existing_job",
            "event_time_type": "published",
            "source_time_granularity": "annual_recruitment_cycle",
        }
        events = pd.concat([events, pd.DataFrame([row], columns=GOVERNMENT_EVENT_COLUMNS)], ignore_index=True)
        frequency = rebuild_frequency_table(events)
        if write:
            self.write_tables(events, frequency)
        return events, frequency

    def write_tables(self, events: pd.DataFrame, frequency: pd.DataFrame) -> None:
        self.event_stream_path.parent.mkdir(parents=True, exist_ok=True)
        events[GOVERNMENT_EVENT_COLUMNS].to_csv(self.event_stream_path, index=False, encoding="utf-8-sig")
        if self.frequency_path is not None:
            self.frequency_path.parent.mkdir(parents=True, exist_ok=True)
            frequency.to_csv(self.frequency_path, index=False, encoding="utf-8-sig")
