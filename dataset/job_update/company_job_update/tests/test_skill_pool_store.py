from __future__ import annotations

import pandas as pd

from company_job_update.core.skill_pool_store import rebuild_skill_pool_table


def test_rebuild_skill_pool_table_uses_skill_universe_metadata() -> None:
    events = pd.DataFrame(
        [
            {
                "job_id": "jd_001",
                "month": "2026-06",
                "standard_job": "Backend Engineer",
                "skills": "Python; Redis",
            },
            {
                "job_id": "jd_002",
                "month": "2026-07",
                "standard_job": "Backend Engineer",
                "skills": "Python",
            },
        ]
    )
    universe = pd.DataFrame(
        [
            {
                "standard_job": "Backend Engineer",
                "skill": "Python",
                "kg_display_skill": "Programming",
                "skill_stage": "traditional",
            },
            {
                "standard_job": "Backend Engineer",
                "skill": "Redis",
                "kg_display_skill": "Database",
                "skill_stage": "traditional",
            },
        ]
    )

    pool = rebuild_skill_pool_table(
        events,
        standard_job_categories={"Backend Engineer": "Software"},
        skill_universe=universe,
    )

    python = pool[pool["normalized_skill"] == "Python"].iloc[0]
    assert python["kg_display_skill"] == "Programming"
    assert python["standard_categories"] == "Software"
    assert python["standard_jobs"] == "Backend Engineer"
    assert python["mention_count"] == "2"
    assert python["first_seen_month"] == "2026-06"
    assert python["last_seen_month"] == "2026-07"
