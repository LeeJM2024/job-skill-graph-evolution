from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .frequency_store import FREQUENCY_COLUMNS
from .skill_pool_store import SKILL_POOL_COLUMNS
from .text import clean_text


JOB_PROFILE_SNAPSHOT_COLUMNS = [
    "month",
    "standard_job",
    "skill",
    "kg_display_skill",
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
    "snapshot_skill_status",
    "is_core_skill",
    "rank_in_month",
    "updated_at",
]


JOB_PROFILE_DIFF_COLUMNS = [
    "standard_job",
    "from_month",
    "to_month",
    "skill",
    "kg_display_skill",
    "change_type",
    "from_monthly_jd_count",
    "to_monthly_jd_count",
    "from_monthly_skill_count",
    "to_monthly_skill_count",
    "from_monthly_skill_frequency",
    "to_monthly_skill_frequency",
    "frequency_delta",
    "frequency_delta_ratio",
    "from_cumulative_skill_count",
    "to_cumulative_skill_count",
    "from_cumulative_skill_frequency",
    "to_cumulative_skill_frequency",
    "is_stable_core",
    "updated_at",
]


@dataclass(frozen=True, slots=True)
class JobProfileRules:
    core_frequency_threshold: float = 0.25
    core_min_monthly_count: int = 1
    change_frequency_threshold: float = 0.08
    stable_core_delta_threshold: float = 0.05


def build_job_profile_tables(
    frequency: pd.DataFrame,
    skill_pool: pd.DataFrame | None = None,
    *,
    rules: JobProfileRules | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = rules or JobProfileRules()
    frequency = _normalize_frequency(frequency)
    if frequency.empty:
        return (
            pd.DataFrame(columns=JOB_PROFILE_SNAPSHOT_COLUMNS),
            pd.DataFrame(columns=JOB_PROFILE_DIFF_COLUMNS),
        )

    pool_map = _build_skill_pool_map(skill_pool)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshots = _build_snapshots(
        frequency,
        pool_map=pool_map,
        rules=rules,
        updated_at=updated_at,
    )
    diffs = _build_diffs(
        snapshots,
        rules=rules,
        updated_at=updated_at,
    )
    return snapshots, diffs


def _normalize_frequency(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy().fillna("")
    for column in FREQUENCY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    normalized = normalized[FREQUENCY_COLUMNS]
    normalized["month"] = normalized["month"].map(clean_text)
    normalized["standard_job"] = normalized["standard_job"].map(clean_text)
    normalized["skill"] = normalized["skill"].map(clean_text)
    normalized = normalized[
        (normalized["month"] != "")
        & (normalized["standard_job"] != "")
        & (normalized["skill"] != "")
    ].copy()
    for column in [
        "monthly_jd_count",
        "monthly_skill_count",
        "cumulative_jd_count",
        "cumulative_skill_count",
    ]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0).astype(int)
    for column in ["monthly_skill_frequency", "cumulative_skill_frequency"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0).astype(float)
    return normalized


def _build_skill_pool_map(skill_pool: pd.DataFrame | None) -> dict[str, str]:
    if skill_pool is None or skill_pool.empty:
        return {}
    pool = skill_pool.copy().fillna("")
    for column in SKILL_POOL_COLUMNS:
        if column not in pool.columns:
            pool[column] = ""
    result: dict[str, str] = {}
    for _, row in pool.iterrows():
        skill = clean_text(row.get("normalized_skill")).casefold()
        family = clean_text(row.get("kg_display_skill"))
        if skill and family and skill not in result:
            result[skill] = family
    return result


def _build_snapshots(
    frequency: pd.DataFrame,
    *,
    pool_map: dict[str, str],
    rules: JobProfileRules,
    updated_at: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sorted_frequency = frequency.sort_values(
        ["standard_job", "month", "monthly_skill_count", "skill"],
        ascending=[True, True, False, True],
    )
    for (standard_job, month), group in sorted_frequency.groupby(["standard_job", "month"], sort=True):
        active = group[group["monthly_skill_count"] > 0].sort_values(
            ["monthly_skill_count", "monthly_skill_frequency", "skill"],
            ascending=[False, False, True],
        )
        ranks = {
            clean_text(row["skill"]): rank
            for rank, (_, row) in enumerate(active.iterrows(), start=1)
        }
        for _, row in group.iterrows():
            skill = clean_text(row["skill"])
            monthly_count = int(row["monthly_skill_count"])
            monthly_frequency = float(row["monthly_skill_frequency"])
            cumulative_frequency = float(row["cumulative_skill_frequency"])
            is_core = _is_core_skill(
                monthly_count=monthly_count,
                monthly_frequency=monthly_frequency,
                cumulative_frequency=cumulative_frequency,
                rules=rules,
            )
            if is_core:
                status = "稳定核心技能"
            elif monthly_count > 0:
                status = "当月活跃技能"
            else:
                status = "当月未出现"
            rows.append(
                {
                    "month": month,
                    "standard_job": standard_job,
                    "skill": skill,
                    "kg_display_skill": pool_map.get(skill.casefold(), ""),
                    "monthly_jd_count": int(row["monthly_jd_count"]),
                    "monthly_skill_count": monthly_count,
                    "monthly_skill_frequency": round(monthly_frequency, 6),
                    "cumulative_jd_count": int(row["cumulative_jd_count"]),
                    "cumulative_skill_count": int(row["cumulative_skill_count"]),
                    "cumulative_skill_frequency": round(cumulative_frequency, 6),
                    "snapshot_skill_status": status,
                    "is_core_skill": "1" if is_core else "0",
                    "rank_in_month": ranks.get(skill, ""),
                    "updated_at": updated_at,
                }
            )
    return pd.DataFrame(rows, columns=JOB_PROFILE_SNAPSHOT_COLUMNS).sort_values(
        ["standard_job", "month", "skill"]
    ).reset_index(drop=True)


def _build_diffs(
    snapshots: pd.DataFrame,
    *,
    rules: JobProfileRules,
    updated_at: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if snapshots.empty:
        return pd.DataFrame(columns=JOB_PROFILE_DIFF_COLUMNS)

    for standard_job, job_group in snapshots.groupby("standard_job", sort=True):
        months = sorted(clean_text(month) for month in job_group["month"].unique() if clean_text(month))
        by_month_skill = {
            (clean_text(row["month"]), clean_text(row["skill"])): row
            for _, row in job_group.iterrows()
        }
        skills = sorted(clean_text(skill) for skill in job_group["skill"].unique() if clean_text(skill))
        month_jd_counts = {
            clean_text(month): int(group["monthly_jd_count"].max())
            for month, group in job_group.groupby("month", sort=True)
        }

        for from_index, from_month in enumerate(months):
            for to_month in months[from_index + 1 :]:
                for skill in skills:
                    from_row = by_month_skill.get((from_month, skill))
                    to_row = by_month_skill.get((to_month, skill))
                    change = _classify_diff(from_row, to_row, rules)
                    if not change:
                        continue
                    from_frequency = _float_from_row(from_row, "monthly_skill_frequency")
                    to_frequency = _float_from_row(to_row, "monthly_skill_frequency")
                    delta = to_frequency - from_frequency
                    rows.append(
                        {
                            "standard_job": standard_job,
                            "from_month": from_month,
                            "to_month": to_month,
                            "skill": skill,
                            "kg_display_skill": _family(from_row, to_row),
                            "change_type": change,
                            "from_monthly_jd_count": month_jd_counts.get(from_month, 0),
                            "to_monthly_jd_count": month_jd_counts.get(to_month, 0),
                            "from_monthly_skill_count": _int_from_row(from_row, "monthly_skill_count"),
                            "to_monthly_skill_count": _int_from_row(to_row, "monthly_skill_count"),
                            "from_monthly_skill_frequency": round(from_frequency, 6),
                            "to_monthly_skill_frequency": round(to_frequency, 6),
                            "frequency_delta": round(delta, 6),
                            "frequency_delta_ratio": round(_ratio_change(to_frequency, from_frequency), 6),
                            "from_cumulative_skill_count": _int_from_row(from_row, "cumulative_skill_count"),
                            "to_cumulative_skill_count": _int_from_row(to_row, "cumulative_skill_count"),
                            "from_cumulative_skill_frequency": round(
                                _float_from_row(from_row, "cumulative_skill_frequency"),
                                6,
                            ),
                            "to_cumulative_skill_frequency": round(
                                _float_from_row(to_row, "cumulative_skill_frequency"),
                                6,
                            ),
                            "is_stable_core": "1" if change == "稳定核心技能" else "0",
                            "updated_at": updated_at,
                        }
                    )
    return pd.DataFrame(rows, columns=JOB_PROFILE_DIFF_COLUMNS).sort_values(
        ["standard_job", "from_month", "to_month", "change_type", "skill"]
    ).reset_index(drop=True)


def _classify_diff(
    from_row: pd.Series | None,
    to_row: pd.Series | None,
    rules: JobProfileRules,
) -> str:
    from_count = _int_from_row(from_row, "monthly_skill_count")
    to_count = _int_from_row(to_row, "monthly_skill_count")
    from_frequency = _float_from_row(from_row, "monthly_skill_frequency")
    to_frequency = _float_from_row(to_row, "monthly_skill_frequency")
    from_cumulative_count = _int_from_row(from_row, "cumulative_skill_count")
    delta = to_frequency - from_frequency
    stable_core = (
        _is_core_snapshot_row(from_row)
        and _is_core_snapshot_row(to_row)
        and abs(delta) <= rules.stable_core_delta_threshold
    )

    if from_cumulative_count == 0 and from_count == 0 and to_count > 0:
        return "新增技能"
    if from_count > 0 and to_count == 0:
        return "消失技能"
    if stable_core:
        return "稳定核心技能"
    if delta >= rules.change_frequency_threshold:
        return "频率上升技能"
    if delta <= -rules.change_frequency_threshold:
        return "频率下降技能"
    return ""


def _is_core_skill(
    *,
    monthly_count: int,
    monthly_frequency: float,
    cumulative_frequency: float,
    rules: JobProfileRules,
) -> bool:
    return (
        monthly_count >= rules.core_min_monthly_count
        and monthly_frequency >= rules.core_frequency_threshold
        and cumulative_frequency >= rules.core_frequency_threshold
    )


def _is_core_snapshot_row(row: pd.Series | None) -> bool:
    if row is None:
        return False
    return clean_text(row.get("is_core_skill")) == "1"


def _int_from_row(row: pd.Series | None, column: str) -> int:
    if row is None:
        return 0
    try:
        return int(float(clean_text(row.get(column)) or "0"))
    except ValueError:
        return 0


def _float_from_row(row: pd.Series | None, column: str) -> float:
    if row is None:
        return 0.0
    try:
        return float(clean_text(row.get(column)) or "0")
    except ValueError:
        return 0.0


def _family(*rows: pd.Series | None) -> str:
    for row in rows:
        if row is None:
            continue
        family = clean_text(row.get("kg_display_skill"))
        if family:
            return family
    return ""


def _ratio_change(current: float, previous: float) -> float:
    if previous == 0:
        return 1.0 if current > 0 else 0.0
    return (current - previous) / previous
