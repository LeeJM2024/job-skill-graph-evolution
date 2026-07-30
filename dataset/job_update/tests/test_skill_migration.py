from __future__ import annotations

import pandas as pd

from job_update.frequency_store import rebuild_frequency_table
from job_update.skill_migration import build_skill_migration_tables


def test_build_skill_migration_tables_tracks_first_jobs_and_spread() -> None:
    events = pd.DataFrame(
        [
            {
                "job_id": "jd_001",
                "month": "2026-01",
                "standard_job": "LLM App Engineer",
                "skills": "RAG",
            },
            {
                "job_id": "jd_002",
                "month": "2026-02",
                "standard_job": "Agent App Engineer",
                "skills": "RAG",
            },
            {
                "job_id": "jd_003",
                "month": "2026-03",
                "standard_job": "Backend Engineer",
                "skills": "RAG",
            },
        ]
    )
    frequency = rebuild_frequency_table(events)
    skill_pool = pd.DataFrame(
        [{"normalized_skill": "RAG", "kg_display_skill": "LLM"}]
    )

    migration, spread = build_skill_migration_tables(frequency, skill_pool)

    rag = migration[migration["skill"] == "RAG"].iloc[0]
    assert rag["first_seen_month"] == "2026-01"
    assert rag["first_seen_standard_jobs"] == "LLM App Engineer"
    assert rag["spread_job_count"] == 2
    assert rag["spread_standard_jobs"] == "Agent App Engineer; Backend Engineer"
    assert rag["peak_monthly_covered_job_count"] == 1
    assert "2026-03: Backend Engineer" in rag["migration_path"]

    backend = spread[
        (spread["skill"] == "RAG")
        & (spread["standard_job"] == "Backend Engineer")
        & (spread["month"] == "2026-03")
    ].iloc[0]
    assert backend["is_new_job_for_skill"] == "1"
    assert backend["cumulative_covered_job_count"] == 3
