from __future__ import annotations

import pandas as pd

from company_job_update.core.analysis import analyze_event_stream
from company_job_update.core.taxonomy import JobTaxonomy, StandardJob


def test_analyze_event_stream_builds_job_demand_for_all_standard_jobs() -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("AI Engineer", "AI"),
            StandardJob("Data Engineer", "Data"),
        ]
    )
    events = pd.DataFrame(
        [
            {
                "job_id": "a",
                "month": "2026-01",
                "standard_job": "AI Engineer",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "LLM; Python",
            },
            {
                "job_id": "b",
                "month": "2026-02",
                "standard_job": "AI Engineer",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "Python",
            },
        ]
    )

    result = analyze_event_stream(events, taxonomy, "2026-01", "2026-02")

    assert len(result.job_demand) == 4
    data_feb = result.job_demand[
        (result.job_demand["standard_job"] == "Data Engineer")
        & (result.job_demand["month"] == "2026-02")
    ].iloc[0]
    assert data_feb["monthly_jd_count"] == 0
    assert data_feb["cumulative_jd_count"] == 0
    assert data_feb["is_active_month"] == "no"


def test_analyze_event_stream_builds_skill_frequency_across_full_month_range() -> None:
    taxonomy = JobTaxonomy([StandardJob("AI Engineer", "AI")])
    events = pd.DataFrame(
        [
            {
                "job_id": "a",
                "month": "2026-01",
                "standard_job": "AI Engineer",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "LLM; Python",
            },
            {
                "job_id": "b",
                "month": "2026-02",
                "standard_job": "AI Engineer",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "Python",
            },
        ]
    )

    result = analyze_event_stream(events, taxonomy, "2026-01", "2026-02")
    llm_feb = result.skill_frequency[
        (result.skill_frequency["standard_job"] == "AI Engineer")
        & (result.skill_frequency["skill"] == "LLM")
        & (result.skill_frequency["month"] == "2026-02")
    ].iloc[0]
    python_feb = result.skill_frequency[
        (result.skill_frequency["standard_job"] == "AI Engineer")
        & (result.skill_frequency["skill"] == "Python")
        & (result.skill_frequency["month"] == "2026-02")
    ].iloc[0]

    assert llm_feb["monthly_skill_count"] == 0
    assert llm_feb["cumulative_skill_count"] == 1
    assert llm_feb["cumulative_skill_frequency"] == "0.5000"
    assert python_feb["monthly_skill_frequency"] == "1.0000"
    assert python_feb["cumulative_skill_count"] == 2


def test_analyze_event_stream_includes_zero_only_skill_universe_pairs() -> None:
    taxonomy = JobTaxonomy([StandardJob("AI Engineer", "AI")])
    events = pd.DataFrame(
        [
            {
                "job_id": "a",
                "month": "2026-01",
                "standard_job": "AI Engineer",
                "job_responsibility": "",
                "job_requirement": "",
                "skills": "Python",
            },
        ]
    )
    skill_universe = pd.DataFrame(
        [
            {"standard_job": "AI Engineer", "skill": "Python"},
            {"standard_job": "AI Engineer", "skill": "LLM"},
        ]
    )

    result = analyze_event_stream(
        events,
        taxonomy,
        "2026-01",
        "2026-02",
        skill_universe=skill_universe,
    )
    llm_rows = result.skill_frequency[result.skill_frequency["skill"] == "LLM"]

    assert len(llm_rows) == 2
    assert set(llm_rows["monthly_skill_count"]) == {0}
    assert set(llm_rows["cumulative_skill_count"]) == {0}
