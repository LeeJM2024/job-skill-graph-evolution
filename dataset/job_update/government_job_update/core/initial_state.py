from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from company_job_update.core.frequency_store import rebuild_frequency_table
from company_job_update.core.job_profile_store import JobProfileStore
from company_job_update.core.models import JobPosting, NormalizedSkill
from company_job_update.core.skill_migration_store import SkillMigrationStore
from company_job_update.core.skill_pool_store import SKILL_POOL_COLUMNS, SkillPoolStore
from shared.text_utils import clean_text

from .database import GovernmentSQLiteStore
from .current_profile import GovernmentCurrentProfileStore
from .frequency_store import GOVERNMENT_EVENT_COLUMNS, GovernmentFrequencyStore
from .skill_lifecycle import GovernmentAnnualLifecycleStore


def extract_seed_skills(posting: pd.Series, dictionary: pd.DataFrame) -> list[NormalizedSkill]:
    text = "\n".join(
        clean_text(posting.get(column)).casefold()
        for column in ("job_title", "job_responsibility", "job_requirement")
    )
    skills: dict[str, NormalizedSkill] = {}
    for _, row in dictionary.iterrows():
        keyword = clean_text(row.get("skill_keyword"))
        normalized = clean_text(row.get("normalized_skill"))
        display = clean_text(row.get("kg_display_skill"))
        if keyword and normalized and display and keyword.casefold() in text:
            skills.setdefault(
                normalized.casefold(),
                NormalizedSkill(
                    normalized_skill=normalized,
                    kg_display_skill=display,
                    metadata={"normalization_method": "government_seed_dictionary", "normalization_status": "normalized"},
                ),
            )
    return sorted(skills.values(), key=lambda item: item.normalized_skill)


def build_government_initial_state(
    *,
    postings: pd.DataFrame,
    assignments: pd.DataFrame,
    skill_dictionary: pd.DataFrame,
    event_stream_path: Path,
    frequency_path: Path,
    skill_pool_path: Path,
    lifecycle_path: Path,
    migration_path: Path,
    spread_path: Path,
    snapshot_path: Path,
    diff_path: Path,
    current_profile_path: Path,
    database_path: Path,
    title_dictionary_path: Path,
) -> dict[str, int]:
    # The normalized source is retained as an audit trail.  The assignment
    # file is the formal inclusion list after human/LLM review, so postings
    # rejected from the technical-job baseline must not enter formal state.
    assigned = postings.fillna("").merge(
        assignments[["job_id", "assigned_standard_category", "assigned_standard_job"]].fillna(""),
        on="job_id",
        how="inner",
        validate="one_to_one",
    )
    if assigned.empty:
        raise ValueError("No formally assigned government postings are available for bootstrap.")
    if (assigned["assigned_standard_job"].map(clean_text) == "").any():
        raise ValueError("Every formally assigned government posting needs an assigned_standard_job before bootstrap.")

    events: list[dict[str, str]] = []
    extracted_skill_count = 0
    for _, row in assigned.iterrows():
        skills = extract_seed_skills(row, skill_dictionary)
        extracted_skill_count += len(skills)
        posting = JobPosting(
            job_id=clean_text(row.get("job_id")),
            month=clean_text(row.get("month")),
            job_title=clean_text(row.get("job_title")),
            routing_job_title=clean_text(row.get("job_title")),
            job_responsibility=clean_text(row.get("job_responsibility")),
            job_requirement=clean_text(row.get("job_requirement")),
            metadata={"source": clean_text(row.get("source")) or "government"},
        )
        standard_job = clean_text(row.get("assigned_standard_job"))
        standard_category = clean_text(row.get("assigned_standard_category"))
        events.append(
            {
                "job_id": posting.job_id,
                "month": posting.month,
                "standard_job": standard_job,
                "job_title": posting.job_title,
                "job_responsibility": posting.job_responsibility,
                "job_requirement": posting.job_requirement,
                "skills": "; ".join(skill.normalized_skill for skill in skills),
                "source": clean_text(row.get("source")) or "government",
                "source_name": clean_text(row.get("source_name")),
                "publish_time": clean_text(row.get("publish_time")),
                "recruitment_year": clean_text(row.get("recruitment_year")),
                "source_url": clean_text(row.get("source_url")),
                "government_agency": clean_text(row.get("government_agency")),
                "government_department": clean_text(row.get("government_department")),
                "location": clean_text(row.get("location")),
                "cleaned_job_title": "",
                "route_status": "initial_seed_assignment",
                "event_time_type": "published",
                "source_time_granularity": "annual_recruitment_cycle",
            }
        )
    event_frame = pd.DataFrame(events, columns=GOVERNMENT_EVENT_COLUMNS)
    frequency = rebuild_frequency_table(event_frame)
    GovernmentFrequencyStore(event_stream_path, frequency_path).write_tables(event_frame, frequency)
    pool = _build_seed_skill_pool(event_frame, assigned, skill_dictionary)
    SkillPoolStore(skill_pool_path).write_pool(pool)
    lifecycle = GovernmentAnnualLifecycleStore(lifecycle_path).rebuild(
        frequency=frequency, skill_pool=pool, write=True
    )
    migration, spread = SkillMigrationStore(migration_path, spread_path).rebuild(
        frequency=frequency, skill_pool=pool, write=True
    )
    snapshots, diffs = JobProfileStore(snapshot_path, diff_path).rebuild(
        frequency=frequency, skill_pool=pool, write=True
    )
    current_profile = GovernmentCurrentProfileStore(current_profile_path).rebuild(
        snapshots=snapshots, write=True
    )
    database = GovernmentSQLiteStore(database_path)
    database.initialize_from_csv(
        title_dictionary_path=title_dictionary_path,
        event_stream_path=event_stream_path,
        frequency_path=frequency_path,
        skill_pool_path=skill_pool_path,
        lifecycle_path=lifecycle_path,
        migration_path=migration_path,
        spread_path=spread_path,
        profile_snapshot_path=snapshot_path,
        profile_diff_path=diff_path,
    )
    return {
        "event_rows": len(event_frame),
        "seed_skill_mentions": extracted_skill_count,
        "frequency_rows": len(frequency),
        "skill_pool_rows": len(pool),
        "lifecycle_rows": len(lifecycle),
        "migration_rows": len(migration),
        "spread_rows": len(spread),
        "profile_snapshot_rows": len(snapshots),
        "profile_diff_rows": len(diffs),
        "current_profile_rows": len(current_profile),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _build_seed_skill_pool(
    events: pd.DataFrame,
    assigned: pd.DataFrame,
    dictionary: pd.DataFrame,
) -> pd.DataFrame:
    display_by_skill = {
        clean_text(row.get("normalized_skill")).casefold(): clean_text(row.get("kg_display_skill"))
        for _, row in dictionary.iterrows()
        if clean_text(row.get("normalized_skill")) and clean_text(row.get("kg_display_skill"))
    }
    category_by_job_id = {
        clean_text(row.get("job_id")): clean_text(row.get("assigned_standard_category"))
        for _, row in assigned.iterrows()
    }
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pool: dict[str, dict[str, object]] = {}
    for _, event in events.iterrows():
        job_id = clean_text(event.get("job_id"))
        month = clean_text(event.get("month"))
        standard_job = clean_text(event.get("standard_job"))
        for skill in [clean_text(value) for value in str(event.get("skills") or "").split(";") if clean_text(value)]:
            key = skill.casefold()
            entry = pool.setdefault(
                key,
                {
                    "normalized_skill": skill,
                    "kg_display_skill": display_by_skill.get(key, ""),
                    "skill_type": "",
                    "standard_categories": set(),
                    "standard_jobs": set(),
                    "first_seen_month": month,
                    "last_seen_month": month,
                    "first_seen_job_id": job_id,
                    "last_seen_job_id": job_id,
                    "mention_count": 0,
                    "source_job_ids": set(),
                    "sources": set(),
                    "updated_at": now,
                },
            )
            entry["standard_categories"].add(category_by_job_id.get(job_id, ""))
            entry["standard_jobs"].add(standard_job)
            entry["source_job_ids"].add(job_id)
            entry["sources"].add(clean_text(event.get("source")))
            entry["mention_count"] = int(entry["mention_count"]) + 1
            if month < str(entry["first_seen_month"]):
                entry["first_seen_month"], entry["first_seen_job_id"] = month, job_id
            if month >= str(entry["last_seen_month"]):
                entry["last_seen_month"], entry["last_seen_job_id"] = month, job_id
    rows = []
    for entry in pool.values():
        rows.append(
            {
                "normalized_skill": entry["normalized_skill"],
                "kg_display_skill": entry["kg_display_skill"],
                "skill_type": entry["skill_type"],
                "standard_categories": "; ".join(sorted(value for value in entry["standard_categories"] if value)),
                "standard_jobs": "; ".join(sorted(value for value in entry["standard_jobs"] if value)),
                "first_seen_month": entry["first_seen_month"],
                "last_seen_month": entry["last_seen_month"],
                "first_seen_job_id": entry["first_seen_job_id"],
                "last_seen_job_id": entry["last_seen_job_id"],
                "mention_count": str(entry["mention_count"]),
                "source_job_ids": "; ".join(sorted(entry["source_job_ids"])),
                "source_count": str(len(entry["source_job_ids"])),
                "sources": "; ".join(sorted(value for value in entry["sources"] if value)),
                "updated_at": entry["updated_at"],
            }
        )
    return pd.DataFrame(rows, columns=SKILL_POOL_COLUMNS).sort_values("normalized_skill").reset_index(drop=True)
