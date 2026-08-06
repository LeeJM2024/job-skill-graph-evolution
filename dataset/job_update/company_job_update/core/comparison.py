from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd


JOB_DEMAND_KEYS = ["standard_job", "month"]
JOB_DEMAND_COMPARE_COLUMNS = [
    "standard_category",
    "month_index",
    "monthly_jd_count",
    "cumulative_jd_count",
    "is_active_month",
]

SKILL_FREQUENCY_KEYS = ["standard_job", "skill", "month"]
SKILL_FREQUENCY_COMPARE_COLUMNS = [
    "month_index",
    "standard_category",
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
]

FREQUENCY_COLUMNS = {
    "monthly_skill_frequency",
    "cumulative_skill_frequency",
}


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    job_demand_diff: pd.DataFrame
    skill_frequency_diff: pd.DataFrame
    report: dict[str, Any]


def compare_answer_tables(
    actual_job_demand_path: str | Path,
    expected_job_demand_path: str | Path,
    actual_skill_frequency_path: str | Path,
    expected_skill_frequency_path: str | Path,
    frequency_tolerance: float = 0.0001,
    pass_threshold: float = 0.9,
) -> ComparisonResult:
    if not 0.0 <= pass_threshold <= 1.0:
        raise ValueError("pass_threshold must be between 0.0 and 1.0")
    actual_job = _read_csv(actual_job_demand_path)
    expected_job = _read_csv(expected_job_demand_path)
    actual_skill = _read_csv(actual_skill_frequency_path)
    expected_skill = _read_csv(expected_skill_frequency_path)

    job_diff = compare_tables(
        actual=actual_job,
        expected=expected_job,
        key_columns=JOB_DEMAND_KEYS,
        compare_columns=JOB_DEMAND_COMPARE_COLUMNS,
        frequency_tolerance=frequency_tolerance,
    )
    skill_diff = compare_tables(
        actual=actual_skill,
        expected=expected_skill,
        key_columns=SKILL_FREQUENCY_KEYS,
        compare_columns=SKILL_FREQUENCY_COMPARE_COLUMNS,
        frequency_tolerance=frequency_tolerance,
    )

    job_stats = _match_stats(actual_job, expected_job, JOB_DEMAND_KEYS, job_diff)
    skill_stats = _match_stats(
        actual_skill,
        expected_skill,
        SKILL_FREQUENCY_KEYS,
        skill_diff,
    )
    passed = (
        job_stats["match_rate"] > pass_threshold
        and skill_stats["match_rate"] > pass_threshold
    )

    report = {
        "job_demand_actual_rows": int(len(actual_job)),
        "job_demand_expected_rows": int(len(expected_job)),
        "job_demand_mismatch_count": int(len(job_diff)),
        "job_demand_matched_rows": job_stats["matched_rows"],
        "job_demand_total_compared_rows": job_stats["total_rows"],
        "job_demand_match_rate": job_stats["match_rate"],
        "job_demand_missing_actual_rows": _count_status(job_diff, "missing_actual"),
        "job_demand_extra_actual_rows": _count_status(job_diff, "extra_actual"),
        "skill_frequency_actual_rows": int(len(actual_skill)),
        "skill_frequency_expected_rows": int(len(expected_skill)),
        "skill_frequency_mismatch_count": int(len(skill_diff)),
        "skill_frequency_matched_rows": skill_stats["matched_rows"],
        "skill_frequency_total_compared_rows": skill_stats["total_rows"],
        "skill_frequency_match_rate": skill_stats["match_rate"],
        "skill_frequency_missing_actual_rows": _count_status(skill_diff, "missing_actual"),
        "skill_frequency_extra_actual_rows": _count_status(skill_diff, "extra_actual"),
        "frequency_tolerance": frequency_tolerance,
        "pass_threshold": pass_threshold,
        "passed": bool(passed),
    }
    return ComparisonResult(
        job_demand_diff=job_diff,
        skill_frequency_diff=skill_diff,
        report=report,
    )


def compare_tables(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    key_columns: list[str],
    compare_columns: list[str],
    frequency_tolerance: float,
) -> pd.DataFrame:
    _require_columns(actual, key_columns, "actual")
    _require_columns(expected, key_columns, "expected")
    columns = [
        column
        for column in compare_columns
        if column in actual.columns and column in expected.columns
    ]

    actual_map = _rows_by_key(actual, key_columns)
    expected_map = _rows_by_key(expected, key_columns)
    rows: list[dict[str, Any]] = []

    for key in sorted(set(actual_map) | set(expected_map)):
        key_payload = dict(zip(key_columns, key))
        actual_row = actual_map.get(key)
        expected_row = expected_map.get(key)
        if actual_row is None:
            rows.append({**key_payload, "status": "missing_actual", "column": ""})
            continue
        if expected_row is None:
            rows.append({**key_payload, "status": "extra_actual", "column": ""})
            continue

        for column in columns:
            actual_value = actual_row.get(column, "")
            expected_value = expected_row.get(column, "")
            if _values_equal(column, actual_value, expected_value, frequency_tolerance):
                continue
            rows.append(
                {
                    **key_payload,
                    "status": "value_mismatch",
                    "column": column,
                    "actual": actual_value,
                    "expected": expected_value,
                }
            )
            break

    return pd.DataFrame(
        rows,
        columns=[
            *key_columns,
            "status",
            "column",
            "actual",
            "expected",
        ],
    )


def write_comparison_outputs(
    result: ComparisonResult,
    output_dir: str | Path,
) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    job_diff_path = output_path / "job_demand_diff.csv"
    skill_diff_path = output_path / "skill_frequency_diff.csv"
    report_path = output_path / "comparison_report.json"

    result.job_demand_diff.to_csv(job_diff_path, index=False, encoding="utf-8-sig")
    result.skill_frequency_diff.to_csv(
        skill_diff_path,
        index=False,
        encoding="utf-8-sig",
    )
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(result.report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "job_demand_diff": str(job_diff_path),
        "skill_frequency_diff": str(skill_diff_path),
        "comparison_report": str(report_path),
    }


def _read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


def _require_columns(df: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{label} table is missing columns: {missing}")


def _rows_by_key(
    df: pd.DataFrame,
    key_columns: list[str],
) -> dict[tuple[str, ...], dict[str, str]]:
    rows: dict[tuple[str, ...], dict[str, str]] = {}
    duplicate_keys: list[tuple[str, ...]] = []
    for _, row in df.iterrows():
        key = tuple(str(row.get(column, "")) for column in key_columns)
        if key in rows:
            duplicate_keys.append(key)
        rows[key] = {column: str(value) for column, value in row.items()}
    if duplicate_keys:
        raise ValueError(f"Duplicate keys found: {duplicate_keys[:5]}")
    return rows


def _values_equal(
    column: str,
    actual: str,
    expected: str,
    frequency_tolerance: float,
) -> bool:
    if column in FREQUENCY_COLUMNS:
        return abs(_to_float(actual) - _to_float(expected)) <= frequency_tolerance
    return str(actual) == str(expected)


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _count_status(diff: pd.DataFrame, status: str) -> int:
    if diff.empty or "status" not in diff.columns:
        return 0
    return int((diff["status"] == status).sum())


def _match_stats(
    actual: pd.DataFrame,
    expected: pd.DataFrame,
    key_columns: list[str],
    diff: pd.DataFrame,
) -> dict[str, int | float]:
    actual_keys = {
        tuple(str(row.get(column, "")) for column in key_columns)
        for _, row in actual.iterrows()
    }
    expected_keys = {
        tuple(str(row.get(column, "")) for column in key_columns)
        for _, row in expected.iterrows()
    }
    total_rows = len(actual_keys | expected_keys)
    mismatched_rows = int(len(diff))
    matched_rows = max(total_rows - mismatched_rows, 0)
    match_rate = 1.0 if total_rows == 0 else round(matched_rows / total_rows, 6)
    return {
        "total_rows": int(total_rows),
        "matched_rows": int(matched_rows),
        "match_rate": match_rate,
    }
