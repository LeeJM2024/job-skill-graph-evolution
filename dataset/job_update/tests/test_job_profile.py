from __future__ import annotations

import pandas as pd

from job_update.frequency_store import rebuild_frequency_table
from job_update.job_profile import build_job_profile_tables


def test_build_job_profile_tables_compares_monthly_skill_profile() -> None:
    events = pd.DataFrame(
        [
            {"job_id": "jan_01", "month": "2026-01", "standard_job": "Frontend Engineer", "skills": "React; JavaScript; jQuery; CSS"},
            {"job_id": "jan_02", "month": "2026-01", "standard_job": "Frontend Engineer", "skills": "React; JavaScript; jQuery"},
            {"job_id": "jan_03", "month": "2026-01", "standard_job": "Frontend Engineer", "skills": "React; JavaScript"},
            {"job_id": "jul_01", "month": "2026-07", "standard_job": "Frontend Engineer", "skills": "React; JavaScript; TypeScript; CSS"},
            {"job_id": "jul_02", "month": "2026-07", "standard_job": "Frontend Engineer", "skills": "React; JavaScript; TypeScript; CSS"},
            {"job_id": "jul_03", "month": "2026-07", "standard_job": "Frontend Engineer", "skills": "React; JavaScript; TypeScript"},
        ]
    )
    frequency = rebuild_frequency_table(events)
    skill_pool = pd.DataFrame(
        [
            {"normalized_skill": "React", "kg_display_skill": "Frontend"},
            {"normalized_skill": "JavaScript", "kg_display_skill": "Frontend"},
            {"normalized_skill": "jQuery", "kg_display_skill": "Frontend"},
            {"normalized_skill": "TypeScript", "kg_display_skill": "Frontend"},
            {"normalized_skill": "CSS", "kg_display_skill": "Frontend"},
        ]
    )

    snapshots, diffs = build_job_profile_tables(frequency, skill_pool)

    assert not snapshots.empty
    comparison = diffs[
        (diffs["standard_job"] == "Frontend Engineer")
        & (diffs["from_month"] == "2026-01")
        & (diffs["to_month"] == "2026-07")
    ]
    changes = {
        row["skill"]: row["change_type"]
        for _, row in comparison.iterrows()
    }

    assert changes["TypeScript"] == "新增技能"
    assert changes["jQuery"] == "消失技能"
    assert changes["CSS"] == "频率上升技能"
    assert changes["React"] == "稳定核心技能"


def test_job_profile_diff_marks_decreasing_skill() -> None:
    events = pd.DataFrame(
        [
            {"job_id": "jan_01", "month": "2026-01", "standard_job": "Backend Engineer", "skills": "Java; PHP"},
            {"job_id": "jan_02", "month": "2026-01", "standard_job": "Backend Engineer", "skills": "Java; PHP"},
            {"job_id": "jan_03", "month": "2026-01", "standard_job": "Backend Engineer", "skills": "Java; PHP"},
            {"job_id": "jul_01", "month": "2026-07", "standard_job": "Backend Engineer", "skills": "Java"},
            {"job_id": "jul_02", "month": "2026-07", "standard_job": "Backend Engineer", "skills": "Java"},
            {"job_id": "jul_03", "month": "2026-07", "standard_job": "Backend Engineer", "skills": "Java; PHP"},
        ]
    )

    _, diffs = build_job_profile_tables(rebuild_frequency_table(events))

    php = diffs[
        (diffs["standard_job"] == "Backend Engineer")
        & (diffs["from_month"] == "2026-01")
        & (diffs["to_month"] == "2026-07")
        & (diffs["skill"] == "PHP")
    ].iloc[0]
    assert php["change_type"] == "频率下降技能"
