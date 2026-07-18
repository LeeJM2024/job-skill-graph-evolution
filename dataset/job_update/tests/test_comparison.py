from __future__ import annotations

import pandas as pd

from job_update.comparison import compare_answer_tables


def test_compare_answer_tables_passes_for_matching_tables(tmp_path) -> None:
    job = pd.DataFrame(
        [
            {
                "standard_job": "AI Engineer",
                "standard_category": "AI",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "2",
                "cumulative_jd_count": "2",
                "is_active_month": "yes",
            }
        ]
    )
    skill = pd.DataFrame(
        [
            {
                "standard_job": "AI Engineer",
                "standard_category": "AI",
                "skill": "Python",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "2",
                "monthly_skill_count": "1",
                "monthly_skill_frequency": "0.5000",
                "cumulative_jd_count": "2",
                "cumulative_skill_count": "1",
                "cumulative_skill_frequency": "0.5000",
            }
        ]
    )
    actual_job = tmp_path / "actual_job.csv"
    expected_job = tmp_path / "expected_job.csv"
    actual_skill = tmp_path / "actual_skill.csv"
    expected_skill = tmp_path / "expected_skill.csv"
    job.to_csv(actual_job, index=False)
    job.to_csv(expected_job, index=False)
    skill.to_csv(actual_skill, index=False)
    skill.to_csv(expected_skill, index=False)

    result = compare_answer_tables(
        actual_job,
        expected_job,
        actual_skill,
        expected_skill,
    )

    assert result.report["passed"] is True
    assert result.report["job_demand_mismatch_count"] == 0
    assert result.report["skill_frequency_mismatch_count"] == 0


def test_compare_answer_tables_reports_missing_and_value_mismatches(tmp_path) -> None:
    actual_job = pd.DataFrame(
        [
            {
                "standard_job": "AI Engineer",
                "standard_category": "AI",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "cumulative_jd_count": "1",
                "is_active_month": "yes",
            }
        ]
    )
    expected_job = pd.DataFrame(
        [
            {
                "standard_job": "AI Engineer",
                "standard_category": "AI",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "2",
                "cumulative_jd_count": "2",
                "is_active_month": "yes",
            }
        ]
    )
    actual_skill = pd.DataFrame(
        [
            {
                "standard_job": "AI Engineer",
                "standard_category": "AI",
                "skill": "Python",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "monthly_skill_count": "1",
                "monthly_skill_frequency": "1.0000",
                "cumulative_jd_count": "1",
                "cumulative_skill_count": "1",
                "cumulative_skill_frequency": "1.0000",
            }
        ]
    )
    expected_skill = pd.concat(
        [
            actual_skill,
            pd.DataFrame(
                [
                    {
                        "standard_job": "AI Engineer",
                        "standard_category": "AI",
                        "skill": "LLM",
                        "month": "2026-01",
                        "month_index": "1",
                        "monthly_jd_count": "1",
                        "monthly_skill_count": "0",
                        "monthly_skill_frequency": "0.0000",
                        "cumulative_jd_count": "1",
                        "cumulative_skill_count": "0",
                        "cumulative_skill_frequency": "0.0000",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    paths = {}
    for name, frame in {
        "actual_job": actual_job,
        "expected_job": expected_job,
        "actual_skill": actual_skill,
        "expected_skill": expected_skill,
    }.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path

    result = compare_answer_tables(
        paths["actual_job"],
        paths["expected_job"],
        paths["actual_skill"],
        paths["expected_skill"],
    )

    assert result.report["passed"] is False
    assert result.report["job_demand_mismatch_count"] == 1
    assert result.report["skill_frequency_missing_actual_rows"] == 1


def test_compare_answer_tables_fails_when_match_rate_equals_threshold(tmp_path) -> None:
    job_expected = pd.DataFrame(
        [
            {
                "standard_job": f"Job {index}",
                "standard_category": "Category",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "cumulative_jd_count": "1",
                "is_active_month": "yes",
            }
            for index in range(10)
        ]
    )
    job_actual = job_expected.copy()
    job_actual.loc[0, "monthly_jd_count"] = "2"
    skill_expected = pd.DataFrame(
        [
            {
                "standard_job": f"Job {index}",
                "standard_category": "Category",
                "skill": "Python",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "monthly_skill_count": "1",
                "monthly_skill_frequency": "1.0000",
                "cumulative_jd_count": "1",
                "cumulative_skill_count": "1",
                "cumulative_skill_frequency": "1.0000",
            }
            for index in range(10)
        ]
    )
    skill_actual = skill_expected.copy()
    skill_actual.loc[0, "monthly_skill_count"] = "0"
    paths = {}
    for name, frame in {
        "actual_job": job_actual,
        "expected_job": job_expected,
        "actual_skill": skill_actual,
        "expected_skill": skill_expected,
    }.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path

    result = compare_answer_tables(
        paths["actual_job"],
        paths["expected_job"],
        paths["actual_skill"],
        paths["expected_skill"],
        pass_threshold=0.9,
    )

    assert result.report["passed"] is False
    assert result.report["job_demand_match_rate"] == 0.9
    assert result.report["skill_frequency_match_rate"] == 0.9


def test_compare_answer_tables_passes_when_match_rate_exceeds_threshold(tmp_path) -> None:
    job_expected = pd.DataFrame(
        [
            {
                "standard_job": f"Job {index}",
                "standard_category": "Category",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "cumulative_jd_count": "1",
                "is_active_month": "yes",
            }
            for index in range(11)
        ]
    )
    job_actual = job_expected.copy()
    job_actual.loc[0, "monthly_jd_count"] = "2"
    skill_expected = pd.DataFrame(
        [
            {
                "standard_job": f"Job {index}",
                "standard_category": "Category",
                "skill": "Python",
                "month": "2026-01",
                "month_index": "1",
                "monthly_jd_count": "1",
                "monthly_skill_count": "1",
                "monthly_skill_frequency": "1.0000",
                "cumulative_jd_count": "1",
                "cumulative_skill_count": "1",
                "cumulative_skill_frequency": "1.0000",
            }
            for index in range(11)
        ]
    )
    skill_actual = skill_expected.copy()
    skill_actual.loc[0, "monthly_skill_count"] = "0"
    paths = {}
    for name, frame in {
        "actual_job": job_actual,
        "expected_job": job_expected,
        "actual_skill": skill_actual,
        "expected_skill": skill_expected,
    }.items():
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path

    result = compare_answer_tables(
        paths["actual_job"],
        paths["expected_job"],
        paths["actual_skill"],
        paths["expected_skill"],
        pass_threshold=0.9,
    )

    assert result.report["passed"] is True
    assert result.report["job_demand_match_rate"] == 0.909091
    assert result.report["skill_frequency_match_rate"] == 0.909091
