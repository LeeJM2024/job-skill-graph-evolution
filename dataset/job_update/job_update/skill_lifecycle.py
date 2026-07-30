from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import pstdev
from typing import Any

import pandas as pd

from .frequency_store import FREQUENCY_COLUMNS
from .skill_pool_store import SKILL_POOL_COLUMNS
from .text import clean_text


LIFECYCLE_COLUMNS = [
    "month",
    "standard_job",
    "skill",
    "kg_display_skill",
    "lifecycle_status",
    "first_seen_month",
    "last_seen_month",
    "age_months",
    "months_since_last_seen",
    "current_monthly_skill_count",
    "current_monthly_skill_frequency",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
    "recent_3m_skill_count",
    "recent_6m_skill_count",
    "recent_3m_active_months",
    "recent_6m_active_months",
    "prev_3m_skill_count",
    "prev_6m_skill_count",
    "mom_frequency_change",
    "recent_3m_vs_prev_3m_change",
    "recent_6m_frequency_stddev",
    "covered_job_count",
    "recent_3m_covered_job_count",
    "prev_3m_covered_job_count",
    "recent_3m_covered_job_count_change",
    "lifecycle_reason",
    "updated_at",
]


@dataclass(frozen=True, slots=True)
class LifecycleRules:
    abandoned_missing_months: int = 4
    abandoned_min_cumulative_count: int = 3
    declining_drop_ratio: float = 0.5
    declining_min_prev_3m_count: int = 3
    declining_max_current_frequency: float = 0.05
    emerging_max_age_months: int = 3
    emerging_min_recent_3m_count: int = 2
    emerging_growth_max_age_months: int = 6
    emerging_growth_min_recent_3m_count: int = 3
    emerging_growth_ratio: float = 0.5
    stable_min_age_months: int = 6
    stable_min_recent_6m_active_months: int = 4
    stable_min_cumulative_frequency: float = 0.25
    stable_min_current_frequency: float = 0.15
    stable_max_recent_6m_frequency_stddev: float = 0.25
    sparse_stable_min_cumulative_count: int = 5
    sparse_stable_min_cumulative_frequency: float = 0.5
    sparse_stable_min_current_frequency: float = 0.5
    sparse_stable_min_recent_3m_count: int = 1
    active_min_recent_3m_active_months: int = 2
    active_min_current_frequency: float = 0.08
    active_min_recent_3m_count: int = 3


def build_skill_lifecycle_table(
    frequency: pd.DataFrame,
    skill_pool: pd.DataFrame | None = None,
    *,
    as_of_month: str | None = None,
    rules: LifecycleRules | None = None,
) -> pd.DataFrame:
    rules = rules or LifecycleRules()
    frequency = _normalize_frequency(frequency)
    if frequency.empty:
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)

    pool_map = _build_skill_pool_map(skill_pool)
    explicit_as_of_month = clean_text(as_of_month)
    fallback_month = explicit_as_of_month or max(frequency["month"].map(clean_text))
    job_as_of_months = _build_job_as_of_months(frequency, explicit_as_of_month)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    coverage = _build_coverage_metrics(frequency, fallback_month)

    rows: list[dict[str, Any]] = []
    for (standard_job, skill), group in frequency.groupby(["standard_job", "skill"], sort=True):
        current_month = job_as_of_months.get(standard_job, fallback_month)
        timeline = _build_pair_timeline(group, current_month)
        if timeline.empty:
            continue

        first_seen_month = _first_month_with_count(timeline)
        last_seen_month = _last_month_with_count(timeline)
        if not first_seen_month or not last_seen_month:
            continue

        current_row = timeline[timeline["month"] == current_month]
        if current_row.empty:
            current_monthly_skill_count = 0
            current_monthly_skill_frequency = 0.0
            cumulative_skill_count = int(timeline["monthly_skill_count"].sum())
            cumulative_skill_frequency = _latest_float(group, "cumulative_skill_frequency")
        else:
            row = current_row.iloc[0]
            current_monthly_skill_count = int(row["monthly_skill_count"])
            current_monthly_skill_frequency = float(row["monthly_skill_frequency"])
            cumulative_skill_count = int(row["cumulative_skill_count"])
            cumulative_skill_frequency = float(row["cumulative_skill_frequency"])

        recent_3m = _window(timeline, current_month, 3)
        recent_6m = _window(timeline, current_month, 6)
        prev_3m = _previous_window(timeline, current_month, 3)
        prev_6m = _previous_window(timeline, current_month, 6)
        previous_month = _shift_month(current_month, -1)
        previous_row = timeline[timeline["month"] == previous_month]
        previous_frequency = (
            float(previous_row.iloc[0]["monthly_skill_frequency"])
            if not previous_row.empty
            else 0.0
        )

        recent_3m_skill_count = int(recent_3m["monthly_skill_count"].sum())
        recent_6m_skill_count = int(recent_6m["monthly_skill_count"].sum())
        recent_3m_active_months = int((recent_3m["monthly_skill_count"] > 0).sum())
        recent_6m_active_months = int((recent_6m["monthly_skill_count"] > 0).sum())
        prev_3m_skill_count = int(prev_3m["monthly_skill_count"].sum())
        prev_6m_skill_count = int(prev_6m["monthly_skill_count"].sum())
        recent_6m_frequency_stddev = _stddev(recent_6m["monthly_skill_frequency"].tolist())
        age_months = _month_distance(first_seen_month, current_month) + 1
        months_since_last_seen = _month_distance(last_seen_month, current_month)
        mom_frequency_change = _ratio_change(current_monthly_skill_frequency, previous_frequency)
        recent_3m_vs_prev_3m_change = _ratio_change(recent_3m_skill_count, prev_3m_skill_count)

        coverage_key = clean_text(skill).casefold()
        coverage_metrics = coverage.get(
            coverage_key,
            {
                "covered_job_count": 0,
                "recent_3m_covered_job_count": 0,
                "prev_3m_covered_job_count": 0,
                "recent_3m_covered_job_count_change": 0,
            },
        )

        status, reason = _classify(
            rules=rules,
            age_months=age_months,
            months_since_last_seen=months_since_last_seen,
            current_monthly_skill_frequency=current_monthly_skill_frequency,
            cumulative_skill_count=cumulative_skill_count,
            cumulative_skill_frequency=cumulative_skill_frequency,
            recent_3m_skill_count=recent_3m_skill_count,
            recent_6m_active_months=recent_6m_active_months,
            recent_3m_active_months=recent_3m_active_months,
            prev_3m_skill_count=prev_3m_skill_count,
            recent_3m_vs_prev_3m_change=recent_3m_vs_prev_3m_change,
            recent_6m_frequency_stddev=recent_6m_frequency_stddev,
        )

        rows.append(
            {
                "month": current_month,
                "standard_job": standard_job,
                "skill": skill,
                "kg_display_skill": pool_map.get(clean_text(skill).casefold(), ""),
                "lifecycle_status": status,
                "first_seen_month": first_seen_month,
                "last_seen_month": last_seen_month,
                "age_months": age_months,
                "months_since_last_seen": months_since_last_seen,
                "current_monthly_skill_count": current_monthly_skill_count,
                "current_monthly_skill_frequency": round(current_monthly_skill_frequency, 6),
                "cumulative_skill_count": cumulative_skill_count,
                "cumulative_skill_frequency": round(cumulative_skill_frequency, 6),
                "recent_3m_skill_count": recent_3m_skill_count,
                "recent_6m_skill_count": recent_6m_skill_count,
                "recent_3m_active_months": recent_3m_active_months,
                "recent_6m_active_months": recent_6m_active_months,
                "prev_3m_skill_count": prev_3m_skill_count,
                "prev_6m_skill_count": prev_6m_skill_count,
                "mom_frequency_change": round(mom_frequency_change, 6),
                "recent_3m_vs_prev_3m_change": round(recent_3m_vs_prev_3m_change, 6),
                "recent_6m_frequency_stddev": round(recent_6m_frequency_stddev, 6),
                **coverage_metrics,
                "lifecycle_reason": reason,
                "updated_at": updated_at,
            }
        )

    return pd.DataFrame(rows, columns=LIFECYCLE_COLUMNS).sort_values(
        ["standard_job", "skill"]
    ).reset_index(drop=True)


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


def _build_pair_timeline(group: pd.DataFrame, current_month: str) -> pd.DataFrame:
    group = group.sort_values("month")
    first_month = min(group["month"])
    months = _month_range(first_month, current_month)
    rows: list[dict[str, Any]] = []
    by_month = {row["month"]: row for _, row in group.iterrows()}
    last_cumulative_jd = 0
    cumulative_skill_count = 0
    cumulative_skill_frequency = 0.0
    for month in months:
        source = by_month.get(month)
        if source is None:
            rows.append(
                {
                    "month": month,
                    "monthly_jd_count": 0,
                    "monthly_skill_count": 0,
                    "monthly_skill_frequency": 0.0,
                    "cumulative_jd_count": last_cumulative_jd,
                    "cumulative_skill_count": cumulative_skill_count,
                    "cumulative_skill_frequency": cumulative_skill_frequency,
                }
            )
            continue
        last_cumulative_jd = int(source["cumulative_jd_count"])
        cumulative_skill_count = int(source["cumulative_skill_count"])
        cumulative_skill_frequency = float(source["cumulative_skill_frequency"])
        rows.append(
            {
                "month": month,
                "monthly_jd_count": int(source["monthly_jd_count"]),
                "monthly_skill_count": int(source["monthly_skill_count"]),
                "monthly_skill_frequency": float(source["monthly_skill_frequency"]),
                "cumulative_jd_count": last_cumulative_jd,
                "cumulative_skill_count": cumulative_skill_count,
                "cumulative_skill_frequency": cumulative_skill_frequency,
            }
        )
    return pd.DataFrame(rows)


def _build_coverage_metrics(frequency: pd.DataFrame, current_month: str) -> dict[str, dict[str, int]]:
    frequency = frequency[frequency["month"] <= current_month].copy()
    recent_months = set(_month_range(_shift_month(current_month, -2), current_month))
    prev_months = set(_month_range(_shift_month(current_month, -5), _shift_month(current_month, -3)))
    metrics: dict[str, dict[str, int]] = {}
    for skill, group in frequency.groupby("skill"):
        skill_key = clean_text(skill).casefold()
        appeared = group[group["monthly_skill_count"] > 0]
        recent = appeared[appeared["month"].isin(recent_months)]
        prev = appeared[appeared["month"].isin(prev_months)]
        recent_count = int(recent["standard_job"].nunique())
        prev_count = int(prev["standard_job"].nunique())
        metrics[skill_key] = {
            "covered_job_count": int(appeared["standard_job"].nunique()),
            "recent_3m_covered_job_count": recent_count,
            "prev_3m_covered_job_count": prev_count,
            "recent_3m_covered_job_count_change": recent_count - prev_count,
        }
    return metrics


def _build_job_as_of_months(frequency: pd.DataFrame, explicit_as_of_month: str) -> dict[str, str]:
    if explicit_as_of_month:
        return {
            clean_text(standard_job): explicit_as_of_month
            for standard_job in frequency["standard_job"].unique()
            if clean_text(standard_job)
        }

    active = frequency[frequency["monthly_jd_count"] > 0]
    return {
        clean_text(standard_job): clean_text(month)
        for standard_job, month in active.groupby("standard_job")["month"].max().items()
        if clean_text(standard_job) and clean_text(month)
    }


def _classify(
    *,
    rules: LifecycleRules,
    age_months: int,
    months_since_last_seen: int,
    current_monthly_skill_frequency: float,
    cumulative_skill_count: int,
    cumulative_skill_frequency: float,
    recent_3m_skill_count: int,
    recent_6m_active_months: int,
    recent_3m_active_months: int,
    prev_3m_skill_count: int,
    recent_3m_vs_prev_3m_change: float,
    recent_6m_frequency_stddev: float,
) -> tuple[str, str]:
    if (
        months_since_last_seen >= rules.abandoned_missing_months
        and recent_3m_skill_count == 0
        and cumulative_skill_count >= rules.abandoned_min_cumulative_count
    ):
        return (
            "废弃技能",
            f"最近3个月未出现，距最后出现已{months_since_last_seen}个月，历史累计出现{cumulative_skill_count}次",
        )

    if (
        prev_3m_skill_count >= rules.declining_min_prev_3m_count
        and recent_3m_skill_count < prev_3m_skill_count * rules.declining_drop_ratio
        and current_monthly_skill_frequency <= rules.declining_max_current_frequency
    ):
        return (
            "衰退技能",
            f"最近3个月出现{recent_3m_skill_count}次，低于前3个月{prev_3m_skill_count}次的一半",
        )

    if age_months <= rules.emerging_max_age_months and recent_3m_skill_count >= rules.emerging_min_recent_3m_count:
        return (
            "新兴技能",
            f"首次出现距今{age_months}个月，最近3个月出现{recent_3m_skill_count}次",
        )

    if (
        age_months <= rules.emerging_growth_max_age_months
        and recent_3m_skill_count >= rules.emerging_growth_min_recent_3m_count
        and recent_3m_vs_prev_3m_change >= rules.emerging_growth_ratio
    ):
        return (
            "新兴技能",
            f"最近3个月相对前3个月增长{recent_3m_vs_prev_3m_change:.2f}",
        )

    if (
        age_months >= rules.stable_min_age_months
        and recent_6m_active_months >= rules.stable_min_recent_6m_active_months
        and cumulative_skill_frequency >= rules.stable_min_cumulative_frequency
        and current_monthly_skill_frequency >= rules.stable_min_current_frequency
        and recent_6m_frequency_stddev <= rules.stable_max_recent_6m_frequency_stddev
    ):
        return (
            "稳定核心技能",
            f"已持续{age_months}个月，近6个月活跃{recent_6m_active_months}个月，累计频率{cumulative_skill_frequency:.2f}",
        )

    if (
        age_months >= rules.stable_min_age_months
        and cumulative_skill_count >= rules.sparse_stable_min_cumulative_count
        and cumulative_skill_frequency >= rules.sparse_stable_min_cumulative_frequency
        and current_monthly_skill_frequency >= rules.sparse_stable_min_current_frequency
        and recent_3m_skill_count >= rules.sparse_stable_min_recent_3m_count
    ):
        return (
            "稳定核心技能",
            f"岗位样本较稀疏，但该技能长期累计高频，且观察月频率{current_monthly_skill_frequency:.2f}",
        )

    if (
        recent_3m_active_months >= rules.active_min_recent_3m_active_months
        and current_monthly_skill_frequency >= rules.active_min_current_frequency
    ) or recent_3m_skill_count >= rules.active_min_recent_3m_count:
        return (
            "活跃技能",
            f"最近3个月活跃{recent_3m_active_months}个月，最近3个月出现{recent_3m_skill_count}次",
        )

    return (
        "观察中",
        f"当前证据不足，最近3个月出现{recent_3m_skill_count}次，累计出现{cumulative_skill_count}次",
    )


def _first_month_with_count(timeline: pd.DataFrame) -> str:
    rows = timeline[timeline["monthly_skill_count"] > 0]
    return clean_text(rows.iloc[0]["month"]) if not rows.empty else ""


def _last_month_with_count(timeline: pd.DataFrame) -> str:
    rows = timeline[timeline["monthly_skill_count"] > 0]
    return clean_text(rows.iloc[-1]["month"]) if not rows.empty else ""


def _latest_float(group: pd.DataFrame, column: str) -> float:
    if group.empty:
        return 0.0
    return float(group.sort_values("month").iloc[-1][column])


def _window(timeline: pd.DataFrame, end_month: str, size: int) -> pd.DataFrame:
    start_month = _shift_month(end_month, -(size - 1))
    months = set(_month_range(start_month, end_month))
    return timeline[timeline["month"].isin(months)]


def _previous_window(timeline: pd.DataFrame, end_month: str, size: int) -> pd.DataFrame:
    previous_end = _shift_month(end_month, -size)
    previous_start = _shift_month(previous_end, -(size - 1))
    months = set(_month_range(previous_start, previous_end))
    return timeline[timeline["month"].isin(months)]


def _stddev(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    return float(pstdev(values))


def _ratio_change(current: float | int, previous: float | int) -> float:
    current_value = float(current)
    previous_value = float(previous)
    if previous_value == 0:
        return 1.0 if current_value > 0 else 0.0
    return (current_value - previous_value) / previous_value


def _month_range(start_month: str, end_month: str) -> list[str]:
    start_year, start_index = _parse_month(start_month)
    end_year, end_index = _parse_month(end_month)
    start_total = start_year * 12 + start_index
    end_total = end_year * 12 + end_index
    if end_total < start_total:
        return []
    return [_format_month(total) for total in range(start_total, end_total + 1)]


def _month_distance(start_month: str, end_month: str) -> int:
    start_year, start_index = _parse_month(start_month)
    end_year, end_index = _parse_month(end_month)
    return end_year * 12 + end_index - (start_year * 12 + start_index)


def _shift_month(month: str, offset: int) -> str:
    year, month_index = _parse_month(month)
    return _format_month(year * 12 + month_index + offset)


def _parse_month(month: str) -> tuple[int, int]:
    text = clean_text(month)
    if not re_match_month(text):
        raise ValueError(f"month must use YYYY-MM format: {month}")
    year_text, month_text = text.split("-", 1)
    return int(year_text), int(month_text) - 1


def _format_month(total_months: int) -> str:
    year = total_months // 12
    month_index = total_months % 12
    return f"{year:04d}-{month_index + 1:02d}"


def re_match_month(text: str) -> bool:
    if len(text) != 7 or text[4] != "-":
        return False
    year, month = text.split("-", 1)
    return year.isdigit() and month.isdigit() and 1 <= int(month) <= 12
