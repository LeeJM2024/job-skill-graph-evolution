from __future__ import annotations

import pandas as pd

from company_job_update.core.frequency_store import rebuild_frequency_table


def test_rebuild_frequency_table_tracks_monthly_and_cumulative_counts() -> None:
    events = pd.DataFrame(
        [
            {
                "job_id": "a",
                "month": "2026-01",
                "standard_job": "AI工程师",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "LLM; Python",
            },
            {
                "job_id": "b",
                "month": "2026-01",
                "standard_job": "AI工程师",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "Python",
            },
            {
                "job_id": "c",
                "month": "2026-02",
                "standard_job": "AI工程师",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "LLM",
            },
        ]
    )

    frequency = rebuild_frequency_table(events)
    llm_feb = frequency[
        (frequency["standard_job"] == "AI工程师")
        & (frequency["skill"] == "LLM")
        & (frequency["month"] == "2026-02")
    ].iloc[0]
    python_feb = frequency[
        (frequency["standard_job"] == "AI工程师")
        & (frequency["skill"] == "Python")
        & (frequency["month"] == "2026-02")
    ].iloc[0]

    assert llm_feb["monthly_jd_count"] == 1
    assert llm_feb["monthly_skill_count"] == 1
    assert llm_feb["monthly_skill_frequency"] == 1.0
    assert llm_feb["cumulative_jd_count"] == 3
    assert llm_feb["cumulative_skill_count"] == 2
    assert llm_feb["cumulative_skill_frequency"] == 0.666667

    assert python_feb["monthly_skill_count"] == 0
    assert python_feb["cumulative_skill_count"] == 2

