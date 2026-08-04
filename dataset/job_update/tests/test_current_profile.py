from __future__ import annotations

import pandas as pd

from job_update.current_profile import CURRENT_PROFILE_COLUMNS, build_current_profile


def test_current_profile_uses_each_job_latest_month_and_only_active_skills() -> None:
    snapshots = pd.DataFrame(
        [
            _snapshot("2026-05", "岗位A", "Python", monthly_count=2, rank="1"),
            _snapshot("2026-06", "岗位A", "Python", monthly_count=3, rank="1"),
            _snapshot("2026-06", "岗位A", "Java", monthly_count=0, rank=""),
            _snapshot("2026-04", "岗位B", "SQL", monthly_count=1, rank="1"),
        ]
    )

    current = build_current_profile(snapshots)

    assert list(current.columns) == CURRENT_PROFILE_COLUMNS
    assert set(zip(current["standard_job"], current["skill"])) == {("岗位A", "Python"), ("岗位B", "SQL")}
    assert current.loc[current["standard_job"] == "岗位A", "source_month"].iloc[0] == "2026-06"
    assert current.loc[current["standard_job"] == "岗位B", "source_month"].iloc[0] == "2026-04"
    assert set(current["source_type"]) == {"system"}


def _snapshot(month: str, job: str, skill: str, *, monthly_count: int, rank: str) -> dict[str, object]:
    return {
        "month": month,
        "standard_job": job,
        "skill": skill,
        "kg_display_skill": "编程语言",
        "monthly_jd_count": 3,
        "monthly_skill_count": monthly_count,
        "monthly_skill_frequency": monthly_count / 3,
        "cumulative_jd_count": 10,
        "cumulative_skill_count": 5,
        "cumulative_skill_frequency": 0.5,
        "snapshot_skill_status": "稳定核心技能" if monthly_count else "当月未出现",
        "is_core_skill": "1" if monthly_count else "0",
        "rank_in_month": rank,
        "updated_at": "2026-08-04T00:00:00+00:00",
    }
