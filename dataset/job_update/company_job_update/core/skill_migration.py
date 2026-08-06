from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .frequency_store import FREQUENCY_COLUMNS
from .skill_pool_store import SKILL_POOL_COLUMNS
from .text import clean_text, split_semicolon


SKILL_MIGRATION_COLUMNS = [
    "skill",
    "kg_display_skill",
    "skill_type",
    "confirmation_min_job_mentions",
    "first_seen_month",
    "first_seen_standard_jobs",
    "first_seen_job_count",
    "is_left_censored",
    "migration_confidence",
    "migration_interpretation",
    "latest_seen_month",
    "latest_covered_job_count",
    "cumulative_covered_job_count",
    "spread_job_count",
    "spread_standard_jobs",
    "all_standard_jobs",
    "confirmed_first_seen_month",
    "confirmed_first_seen_standard_jobs",
    "confirmed_first_seen_job_count",
    "confirmed_cumulative_covered_job_count",
    "confirmed_spread_job_count",
    "confirmed_spread_standard_jobs",
    "confirmed_migration_path",
    "peak_monthly_covered_job_count",
    "peak_monthly_covered_job_month",
    "total_skill_mentions",
    "migration_path",
    "updated_at",
]


SKILL_JOB_MONTHLY_SPREAD_COLUMNS = [
    "month",
    "skill",
    "kg_display_skill",
    "standard_job",
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
    "job_first_seen_month",
    "skill_first_seen_month",
    "months_since_skill_first_seen",
    "is_first_seen_job",
    "is_new_job_for_skill",
    "covered_job_count_this_month",
    "cumulative_covered_job_count",
    "monthly_frequency_change",
    "cumulative_frequency_change",
    "is_left_censored",
    "updated_at",
]


def build_skill_migration_tables(
    frequency: pd.DataFrame,
    skill_pool: pd.DataFrame | None = None,
    *,
    confirmation_min_job_mentions: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frequency = _normalize_frequency(frequency)
    if frequency.empty:
        return (
            pd.DataFrame(columns=SKILL_MIGRATION_COLUMNS),
            pd.DataFrame(columns=SKILL_JOB_MONTHLY_SPREAD_COLUMNS),
        )

    pool_map, type_map = _build_skill_pool_maps(skill_pool)
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    active = frequency[frequency["monthly_skill_count"] > 0].copy()
    if active.empty:
        return (
            pd.DataFrame(columns=SKILL_MIGRATION_COLUMNS),
            pd.DataFrame(columns=SKILL_JOB_MONTHLY_SPREAD_COLUMNS),
        )

    skill_first_month = active.groupby("skill")["month"].min().to_dict()
    data_start_month = min(frequency["month"])
    job_first_month = active.groupby(["skill", "standard_job"])["month"].min().to_dict()
    first_jobs_by_skill = _build_first_jobs_by_skill(active, skill_first_month)
    monthly_coverage = _build_monthly_coverage(active)
    cumulative_coverage = _build_cumulative_coverage(active)
    confirmed_job_first_month = _build_confirmed_job_first_month(
        frequency,
        min_mentions=confirmation_min_job_mentions,
    )
    spread = _build_spread_table(
        frequency,
        pool_map=pool_map,
        data_start_month=data_start_month,
        skill_first_month=skill_first_month,
        job_first_month=job_first_month,
        confirmed_job_first_month=confirmed_job_first_month,
        first_jobs_by_skill=first_jobs_by_skill,
        monthly_coverage=monthly_coverage,
        cumulative_coverage=cumulative_coverage,
        updated_at=updated_at,
    )
    migration = _build_migration_table(
        active,
        pool_map=pool_map,
        type_map=type_map,
        data_start_month=data_start_month,
        skill_first_month=skill_first_month,
        job_first_month=job_first_month,
        confirmed_job_first_month=confirmed_job_first_month,
        first_jobs_by_skill=first_jobs_by_skill,
        monthly_coverage=monthly_coverage,
        confirmation_min_job_mentions=confirmation_min_job_mentions,
        updated_at=updated_at,
    )
    return migration, spread


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


def _build_skill_pool_maps(skill_pool: pd.DataFrame | None) -> tuple[dict[str, str], dict[str, str]]:
    if skill_pool is None or skill_pool.empty:
        return {}, {}
    pool = skill_pool.copy().fillna("")
    for column in SKILL_POOL_COLUMNS:
        if column not in pool.columns:
            pool[column] = ""
    family_map: dict[str, str] = {}
    type_map: dict[str, str] = {}
    for _, row in pool.iterrows():
        skill = clean_text(row.get("normalized_skill")).casefold()
        family = clean_text(row.get("kg_display_skill"))
        skill_type = clean_text(row.get("skill_type"))
        if skill and family and skill not in family_map:
            family_map[skill] = family
        if skill and skill_type and skill not in type_map:
            type_map[skill] = skill_type
    return family_map, type_map


def _build_first_jobs_by_skill(
    active: pd.DataFrame,
    skill_first_month: dict[str, str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for skill, first_month in skill_first_month.items():
        jobs = sorted(
            active[
                (active["skill"] == skill)
                & (active["month"] == first_month)
            ]["standard_job"].unique()
        )
        result[skill] = [clean_text(job) for job in jobs if clean_text(job)]
    return result


def _build_monthly_coverage(active: pd.DataFrame) -> dict[tuple[str, str], int]:
    coverage = (
        active.groupby(["skill", "month"])["standard_job"]
        .nunique()
        .reset_index(name="covered_job_count_this_month")
    )
    return {
        (clean_text(row["skill"]), clean_text(row["month"])): int(row["covered_job_count_this_month"])
        for _, row in coverage.iterrows()
    }


def _build_cumulative_coverage(active: pd.DataFrame) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for skill, group in active.groupby("skill", sort=True):
        seen_jobs: set[str] = set()
        for month in sorted(group["month"].unique()):
            month_jobs = group[group["month"] == month]["standard_job"].map(clean_text)
            seen_jobs.update(job for job in month_jobs if job)
            result[(clean_text(skill), clean_text(month))] = len(seen_jobs)
    return result


def _build_confirmed_job_first_month(
    frequency: pd.DataFrame,
    *,
    min_mentions: int,
) -> dict[tuple[str, str], str]:
    confirmed: dict[tuple[str, str], str] = {}
    threshold = max(1, int(min_mentions))
    for (skill, standard_job), group in frequency.groupby(["skill", "standard_job"], sort=True):
        cumulative = 0
        for _, row in group.sort_values("month").iterrows():
            cumulative += int(row["monthly_skill_count"])
            if cumulative >= threshold:
                confirmed[(skill, standard_job)] = clean_text(row["month"])
                break
    return confirmed


def _build_spread_table(
    frequency: pd.DataFrame,
    *,
    pool_map: dict[str, str],
    data_start_month: str,
    skill_first_month: dict[str, str],
    job_first_month: dict[tuple[str, str], str],
    confirmed_job_first_month: dict[tuple[str, str], str],
    first_jobs_by_skill: dict[str, list[str]],
    monthly_coverage: dict[tuple[str, str], int],
    cumulative_coverage: dict[tuple[str, str], int],
    updated_at: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sorted_frequency = frequency.sort_values(["skill", "standard_job", "month"])
    for (skill, standard_job), group in sorted_frequency.groupby(["skill", "standard_job"], sort=True):
        previous_monthly_frequency = 0.0
        previous_cumulative_frequency = 0.0
        first_job_month = job_first_month.get((skill, standard_job), "")
        first_skill_month = skill_first_month.get(skill, "")
        is_left_censored = first_skill_month == data_start_month
        first_jobs = set(first_jobs_by_skill.get(skill, []))
        for _, row in group.iterrows():
            month = clean_text(row["month"])
            monthly_frequency = float(row["monthly_skill_frequency"])
            cumulative_frequency = float(row["cumulative_skill_frequency"])
            rows.append(
                {
                    "month": month,
                    "skill": skill,
                    "kg_display_skill": pool_map.get(clean_text(skill).casefold(), ""),
                    "standard_job": standard_job,
                    "monthly_jd_count": int(row["monthly_jd_count"]),
                    "monthly_skill_count": int(row["monthly_skill_count"]),
                    "monthly_skill_frequency": round(monthly_frequency, 6),
                    "cumulative_jd_count": int(row["cumulative_jd_count"]),
                    "cumulative_skill_count": int(row["cumulative_skill_count"]),
                    "cumulative_skill_frequency": round(cumulative_frequency, 6),
                    "job_first_seen_month": first_job_month,
                    "skill_first_seen_month": first_skill_month,
                    "months_since_skill_first_seen": _month_distance(first_skill_month, month)
                    if first_skill_month
                    else "",
                    "is_first_seen_job": "1" if standard_job in first_jobs else "0",
                    "is_new_job_for_skill": "1" if month == first_job_month else "0",
                    "covered_job_count_this_month": monthly_coverage.get((skill, month), 0),
                    "cumulative_covered_job_count": cumulative_coverage.get((skill, month), 0),
                    "monthly_frequency_change": round(monthly_frequency - previous_monthly_frequency, 6),
                    "cumulative_frequency_change": round(cumulative_frequency - previous_cumulative_frequency, 6),
                    "is_left_censored": "1" if is_left_censored else "0",
                    "updated_at": updated_at,
                }
            )
            previous_monthly_frequency = monthly_frequency
            previous_cumulative_frequency = cumulative_frequency
    return pd.DataFrame(rows, columns=SKILL_JOB_MONTHLY_SPREAD_COLUMNS).sort_values(
        ["skill", "standard_job", "month"]
    ).reset_index(drop=True)


def _build_migration_table(
    active: pd.DataFrame,
    *,
    pool_map: dict[str, str],
    type_map: dict[str, str],
    data_start_month: str,
    skill_first_month: dict[str, str],
    job_first_month: dict[tuple[str, str], str],
    confirmed_job_first_month: dict[tuple[str, str], str],
    first_jobs_by_skill: dict[str, list[str]],
    monthly_coverage: dict[tuple[str, str], int],
    confirmation_min_job_mentions: int,
    updated_at: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for skill, group in active.groupby("skill", sort=True):
        first_month = skill_first_month[skill]
        first_jobs = first_jobs_by_skill.get(skill, [])
        is_left_censored = first_month == data_start_month
        job_month_pairs = sorted(
            (
                (month, job)
                for (pair_skill, job), month in job_first_month.items()
                if pair_skill == skill
            ),
            key=lambda item: (item[0], item[1]),
        )
        confirmed_job_month_pairs = sorted(
            (
                (month, job)
                for (pair_skill, job), month in confirmed_job_first_month.items()
                if pair_skill == skill
            ),
            key=lambda item: (item[0], item[1]),
        )
        all_jobs = [job for _, job in job_month_pairs]
        spread_jobs = [job for month, job in job_month_pairs if month > first_month]
        confirmed_first_month = confirmed_job_month_pairs[0][0] if confirmed_job_month_pairs else ""
        confirmed_first_jobs = [
            job for month, job in confirmed_job_month_pairs if month == confirmed_first_month
        ]
        confirmed_all_jobs = [job for _, job in confirmed_job_month_pairs]
        confirmed_spread_jobs = [
            job for month, job in confirmed_job_month_pairs if confirmed_first_month and month > confirmed_first_month
        ]
        latest_month = max(group["month"])
        latest_covered = monthly_coverage.get((skill, latest_month), 0)
        peak_month, peak_count = _peak_month(monthly_coverage, skill)
        confidence, interpretation = _interpret_migration(
            skill_type=type_map.get(clean_text(skill).casefold(), ""),
            is_left_censored=is_left_censored,
            first_seen_job_count=len(first_jobs),
            spread_job_count=len(spread_jobs),
        )
        rows.append(
            {
                "skill": skill,
                "kg_display_skill": pool_map.get(clean_text(skill).casefold(), ""),
                "skill_type": type_map.get(clean_text(skill).casefold(), ""),
                "confirmation_min_job_mentions": confirmation_min_job_mentions,
                "first_seen_month": first_month,
                "first_seen_standard_jobs": "; ".join(first_jobs),
                "first_seen_job_count": len(first_jobs),
                "is_left_censored": "1" if is_left_censored else "0",
                "migration_confidence": confidence,
                "migration_interpretation": interpretation,
                "latest_seen_month": latest_month,
                "latest_covered_job_count": latest_covered,
                "cumulative_covered_job_count": len(all_jobs),
                "spread_job_count": len(spread_jobs),
                "spread_standard_jobs": "; ".join(spread_jobs),
                "all_standard_jobs": "; ".join(all_jobs),
                "confirmed_first_seen_month": confirmed_first_month,
                "confirmed_first_seen_standard_jobs": "; ".join(confirmed_first_jobs),
                "confirmed_first_seen_job_count": len(confirmed_first_jobs),
                "confirmed_cumulative_covered_job_count": len(confirmed_all_jobs),
                "confirmed_spread_job_count": len(confirmed_spread_jobs),
                "confirmed_spread_standard_jobs": "; ".join(confirmed_spread_jobs),
                "confirmed_migration_path": _format_migration_path(confirmed_job_month_pairs),
                "peak_monthly_covered_job_count": peak_count,
                "peak_monthly_covered_job_month": peak_month,
                "total_skill_mentions": int(group["monthly_skill_count"].sum()),
                "migration_path": _format_migration_path(job_month_pairs),
                "updated_at": updated_at,
            }
        )
    return pd.DataFrame(rows, columns=SKILL_MIGRATION_COLUMNS).sort_values(
        ["skill"]
    ).reset_index(drop=True)


def _interpret_migration(
    *,
    skill_type: str,
    is_left_censored: bool,
    first_seen_job_count: int,
    spread_job_count: int,
) -> tuple[str, str]:
    if is_left_censored and first_seen_job_count >= 5:
        return (
            "low",
            "观测起点已覆盖多个岗位，只能说明观测期内的覆盖和扩散，不能推断真实起源岗位",
        )
    if is_left_censored:
        return (
            "medium",
            "技能在观测起点已出现，首现岗位是观测窗口内首批岗位，不等同于真实起源岗位",
        )
    if clean_text(skill_type).casefold() == "traditional":
        return (
            "medium",
            "传统技能在观测期内首次出现，可分析样本内扩散，但不代表行业真实首次出现",
        )
    if spread_job_count == 0:
        return (
            "high",
            "技能在观测期内首次出现，但目前尚未扩散到其他标准岗位",
        )
    return (
        "high",
        "技能在观测期内首次出现，后续扩散路径可用于分析样本内技能迁移",
    )


def _peak_month(monthly_coverage: dict[tuple[str, str], int], skill: str) -> tuple[str, int]:
    candidates = [
        (month, count)
        for (item_skill, month), count in monthly_coverage.items()
        if item_skill == skill
    ]
    if not candidates:
        return "", 0
    return max(candidates, key=lambda item: (item[1], item[0]))


def _format_migration_path(job_month_pairs: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for month, jobs in _group_jobs_by_month(job_month_pairs).items():
        parts.append(f"{month}: {'; '.join(jobs)}")
    return " -> ".join(parts)


def _group_jobs_by_month(job_month_pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for month, job in job_month_pairs:
        grouped.setdefault(month, []).append(job)
    return grouped


def _month_distance(start_month: str, end_month: str) -> int:
    start_year, start_index = _parse_month(start_month)
    end_year, end_index = _parse_month(end_month)
    return end_year * 12 + end_index - (start_year * 12 + start_index)


def _parse_month(month: str) -> tuple[int, int]:
    year_text, month_text = clean_text(month).split("-", 1)
    return int(year_text), int(month_text) - 1
