from __future__ import annotations

import pandas as pd

from job_update.frequency_store import rebuild_frequency_table
from job_update.skill_lifecycle import build_skill_lifecycle_table


def test_build_skill_lifecycle_classifies_current_skill_states() -> None:
    events = pd.DataFrame(
        [
            {"job_id": "core_01", "month": "2026-01", "standard_job": "Frontend Engineer", "skills": "React; LegacyJS"},
            {"job_id": "core_02", "month": "2026-02", "standard_job": "Frontend Engineer", "skills": "React; LegacyJS"},
            {"job_id": "core_03", "month": "2026-03", "standard_job": "Frontend Engineer", "skills": "React; LegacyJS"},
            {"job_id": "core_04", "month": "2026-04", "standard_job": "Frontend Engineer", "skills": "React"},
            {"job_id": "core_05", "month": "2026-05", "standard_job": "Frontend Engineer", "skills": "React; WebAssembly"},
            {"job_id": "core_06", "month": "2026-06", "standard_job": "Frontend Engineer", "skills": "React; WebAssembly"},
        ]
    )
    frequency = rebuild_frequency_table(events)
    skill_pool = pd.DataFrame(
        [
            {"normalized_skill": "React", "kg_display_skill": "Frontend"},
            {"normalized_skill": "LegacyJS", "kg_display_skill": "Frontend"},
            {"normalized_skill": "WebAssembly", "kg_display_skill": "Frontend"},
        ]
    )

    lifecycle = build_skill_lifecycle_table(frequency, skill_pool, as_of_month="2026-06")

    statuses = {
        row["skill"]: row["lifecycle_status"]
        for _, row in lifecycle[lifecycle["standard_job"] == "Frontend Engineer"].iterrows()
    }
    assert statuses["React"] == "稳定核心技能"
    assert statuses["LegacyJS"] == "衰退技能"
    assert statuses["WebAssembly"] == "新兴技能"

    webassembly = lifecycle[lifecycle["skill"] == "WebAssembly"].iloc[0]
    assert webassembly["kg_display_skill"] == "Frontend"
    assert webassembly["recent_3m_skill_count"] == 2


def test_sparse_job_high_frequency_skill_can_be_stable_core() -> None:
    events = pd.DataFrame(
        [
            {"job_id": "db_01", "month": "2025-01", "standard_job": "Database Engineer", "skills": "PostgreSQL"},
            {"job_id": "db_02", "month": "2025-05", "standard_job": "Database Engineer", "skills": "PostgreSQL"},
            {"job_id": "db_03", "month": "2025-07", "standard_job": "Database Engineer", "skills": "PostgreSQL"},
            {"job_id": "db_04", "month": "2025-12", "standard_job": "Database Engineer", "skills": "PostgreSQL"},
            {"job_id": "db_05", "month": "2026-05", "standard_job": "Database Engineer", "skills": "PostgreSQL"},
        ]
    )
    frequency = rebuild_frequency_table(events)
    skill_pool = pd.DataFrame(
        [{"normalized_skill": "PostgreSQL", "kg_display_skill": "Database"}]
    )

    lifecycle = build_skill_lifecycle_table(frequency, skill_pool)

    postgresql = lifecycle[lifecycle["skill"] == "PostgreSQL"].iloc[0]
    assert postgresql["month"] == "2026-05"
    assert postgresql["lifecycle_status"] == "稳定核心技能"
