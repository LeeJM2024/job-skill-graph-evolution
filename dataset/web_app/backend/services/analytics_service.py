from __future__ import annotations

from typing import Any

import pandas as pd

from .paths import (
    BASE_FREQUENCY_OUTPUT,
    BASE_JOB_PROFILE_DIFF,
    BASE_JOB_PROFILE_SNAPSHOTS,
    BASE_SKILL_LIFECYCLE,
    BASE_SKILL_MIGRATION,
    BASE_SKILL_MONTHLY_SPREAD,
)


STATUS_ORDER = ["新兴技能", "活跃技能", "稳定核心技能", "衰退技能", "废弃技能", "观察中"]
EMERGING_TYPES = {"新增技能", "频率上升技能"}
DECLINING_TYPES = {"消失技能", "频率下降技能"}

PROFILE_CHANGE_BUCKETS = {
    "added": "新增技能",
    "removed": "消失技能",
    "increased": "频率上升技能",
    "decreased": "频率下降技能",
    "stable_core": "稳定核心技能",
}
PROFILE_NUMBER_COLUMNS = [
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
    "rank_in_month",
    "is_core_skill",
]
DIFF_NUMBER_COLUMNS = [
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
]


def list_jobs() -> list[str]:
    frame = _read_csv(BASE_FREQUENCY_OUTPUT)
    if frame.empty or "standard_job" not in frame.columns:
        return []
    return sorted(frame["standard_job"].dropna().astype(str).unique().tolist())


def list_months() -> list[str]:
    frame = _read_csv(BASE_FREQUENCY_OUTPUT)
    if frame.empty or "month" not in frame.columns:
        return []
    return sorted(frame["month"].dropna().astype(str).unique().tolist())


def overview() -> dict[str, Any]:
    frequency = _read_csv(BASE_FREQUENCY_OUTPUT)
    lifecycle = _read_csv(BASE_SKILL_LIFECYCLE)
    migration = _read_csv(BASE_SKILL_MIGRATION)
    diff = _read_csv(BASE_JOB_PROFILE_DIFF)
    latest_month = _latest_month(frequency, "month")
    return {
        "latest_month": latest_month,
        "job_count": _nunique(frequency, "standard_job"),
        "skill_count": _nunique(frequency, "skill"),
        "frequency_rows": len(frequency),
        "lifecycle_rows": len(lifecycle),
        "migration_skill_count": len(migration),
        "latest_new_skill_count": _count_diff(diff, latest_month, "新增技能"),
        "latest_declining_skill_count": _count_diff(diff, latest_month, "频率下降技能"),
    }


def job_trend(
    standard_job: str | None,
    *,
    top_n: int = 8,
    month_start: str | None = None,
    month_end: str | None = None,
) -> dict[str, Any]:
    frame = _read_csv(BASE_FREQUENCY_OUTPUT)
    if frame.empty:
        return {"standard_job": standard_job or "", "months": [], "series": []}

    job = standard_job or _first_sorted(frame, "standard_job")
    filtered = frame[frame["standard_job"].astype(str) == job].copy()
    filtered = _filter_month_range(filtered, "month", month_start, month_end)
    if filtered.empty:
        return {"standard_job": job, "months": [], "series": []}

    filtered["monthly_skill_frequency"] = _number(filtered, "monthly_skill_frequency")
    filtered["monthly_skill_count"] = _number(filtered, "monthly_skill_count")
    filtered["cumulative_skill_count"] = _number(filtered, "cumulative_skill_count")
    skills = (
        filtered.groupby("skill", as_index=False)
        .agg(monthly_skill_count=("monthly_skill_count", "sum"), cumulative_skill_count=("cumulative_skill_count", "max"))
        .sort_values(["monthly_skill_count", "cumulative_skill_count"], ascending=False)
        .head(_clamp(top_n, 1, 20))["skill"]
        .tolist()
    )
    months = sorted(filtered["month"].astype(str).unique().tolist())
    series = []
    for skill in skills:
        rows = filtered[filtered["skill"].astype(str) == skill]
        by_month = {row["month"]: row for row in rows.to_dict(orient="records")}
        series.append(
            {
                "skill": skill,
                "points": [
                    {
                        "month": month,
                        "frequency": _round_float(by_month.get(month, {}).get("monthly_skill_frequency", 0)),
                        "count": int(float(by_month.get(month, {}).get("monthly_skill_count", 0) or 0)),
                    }
                    for month in months
                ],
            }
        )
    return {"standard_job": job, "months": months, "series": series}


def lifecycle(standard_job: str | None = None, status: str | None = None, limit: int = 120) -> dict[str, Any]:
    frame = _read_csv(BASE_SKILL_LIFECYCLE)
    if frame.empty:
        return {"standard_job": standard_job or "", "summary": [], "rows": []}

    job = standard_job or _first_sorted(frame, "standard_job")
    filtered = frame[frame["standard_job"].astype(str) == job].copy()
    if status:
        filtered = filtered[filtered["lifecycle_status"].astype(str) == status]

    for column in ["current_monthly_skill_frequency", "recent_3m_skill_count", "mom_frequency_change"]:
        filtered[column] = _number(filtered, column)

    summary_counts = filtered["lifecycle_status"].value_counts().to_dict()
    summary = [{"status": item, "count": int(summary_counts.get(item, 0))} for item in STATUS_ORDER if item in summary_counts]

    rows = (
        filtered.sort_values(
            ["lifecycle_status", "current_monthly_skill_frequency", "recent_3m_skill_count"],
            ascending=[True, False, False],
        )
        .head(_clamp(limit, 1, 500))
        .to_dict(orient="records")
    )
    return {"standard_job": job, "summary": summary, "rows": [_clean_record(row) for row in rows]}


def migration(skill: str | None = None, limit: int = 20) -> dict[str, Any]:
    migration_frame = _read_csv(BASE_SKILL_MIGRATION)
    spread_frame = _read_csv(BASE_SKILL_MONTHLY_SPREAD)
    if migration_frame.empty:
        return {"skills": [], "selected": None, "spread": []}

    migration_frame["spread_job_count"] = _number(migration_frame, "spread_job_count")
    migration_frame["total_skill_mentions"] = _number(migration_frame, "total_skill_mentions")
    top_skills = (
        migration_frame.sort_values(["spread_job_count", "total_skill_mentions"], ascending=False)
        .head(_clamp(limit, 1, 100))["skill"]
        .astype(str)
        .tolist()
    )
    selected_skill = skill or (top_skills[0] if top_skills else "")
    selected_rows = migration_frame[migration_frame["skill"].astype(str) == selected_skill]
    selected = _clean_record(selected_rows.iloc[0].to_dict()) if not selected_rows.empty else None

    spread = []
    if selected and not spread_frame.empty:
        spread_rows = spread_frame[spread_frame["skill"].astype(str) == selected_skill].copy()
        spread_rows["monthly_skill_frequency"] = _number(spread_rows, "monthly_skill_frequency")
        spread_rows["monthly_frequency_change"] = _number(spread_rows, "monthly_frequency_change")
        spread = (
            spread_rows.sort_values(["month", "standard_job"])
            .tail(120)
            .to_dict(orient="records")
        )
    return {"skills": top_skills, "selected": selected, "spread": [_clean_record(row) for row in spread]}


def monthly_rank(
    month: str | None = None,
    rank_type: str = "emerging",
    standard_job: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    frame = _read_csv(BASE_JOB_PROFILE_DIFF)
    if frame.empty:
        return {"month": month or "", "type": rank_type, "rows": []}

    selected_month = month or _latest_month(frame, "to_month")
    filtered = frame[frame["to_month"].astype(str) == selected_month].copy()
    if standard_job:
        filtered = filtered[filtered["standard_job"].astype(str) == standard_job]

    if rank_type == "declining":
        filtered = filtered[filtered["change_type"].astype(str).isin(DECLINING_TYPES)]
        ascending = True
    else:
        filtered = filtered[filtered["change_type"].astype(str).isin(EMERGING_TYPES)]
        ascending = False

    filtered["frequency_delta"] = _number(filtered, "frequency_delta")
    filtered["to_monthly_skill_frequency"] = _number(filtered, "to_monthly_skill_frequency")
    filtered["from_monthly_skill_frequency"] = _number(filtered, "from_monthly_skill_frequency")
    rows = (
        filtered.sort_values(["frequency_delta", "to_monthly_skill_frequency"], ascending=[ascending, False])
        .head(_clamp(limit, 1, 100))
        .to_dict(orient="records")
    )
    return {"month": selected_month, "type": rank_type, "rows": [_clean_record(row) for row in rows]}


def profile_compare(
    standard_job: str | None = None,
    from_month: str | None = None,
    to_month: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    snapshots = _read_csv(BASE_JOB_PROFILE_SNAPSHOTS)
    diff = _read_csv(BASE_JOB_PROFILE_DIFF)
    if snapshots.empty:
        return _empty_profile_compare(standard_job or "", from_month or "", to_month or "")

    job = _resolve_job(snapshots, standard_job)
    job_snapshots = snapshots[snapshots["standard_job"].astype(str) == job].copy()
    months = sorted(job_snapshots["month"].dropna().astype(str).unique().tolist())
    if not months:
        return _empty_profile_compare(job, from_month or "", to_month or "")

    selected_from = from_month if from_month in months else months[0]
    selected_to = to_month if to_month in months else months[-1]
    if selected_from > selected_to:
        selected_from, selected_to = selected_to, selected_from

    from_profile = _snapshot_profile(job_snapshots, selected_from, limit=30)
    to_profile = _snapshot_profile(job_snapshots, selected_to, limit=30)
    changes_frame = _profile_diff_rows(diff, job, selected_from, selected_to)
    if changes_frame.empty:
        changes_frame = _build_profile_diff_from_snapshots(job_snapshots, job, selected_from, selected_to)

    changes_frame = _prepare_diff_frame(changes_frame)
    changes = {}
    summary = {}
    row_limit = _clamp(limit, 1, 300)
    for key, change_type in PROFILE_CHANGE_BUCKETS.items():
        rows = changes_frame[changes_frame["change_type"].astype(str) == change_type].copy()
        summary[key] = int(len(rows))
        if not rows.empty:
            rows["delta_abs"] = rows["frequency_delta"].abs()
            rows = rows.sort_values(
                ["delta_abs", "to_monthly_skill_frequency", "from_monthly_skill_frequency"],
                ascending=[False, False, False],
            )
        changes[key] = [
            _clean_record(row)
            for row in rows.head(row_limit).drop(columns=["delta_abs"], errors="ignore").to_dict(orient="records")
        ]

    summary["modified"] = summary.get("increased", 0) + summary.get("decreased", 0)
    return {
        "standard_job": job,
        "from_month": selected_from,
        "to_month": selected_to,
        "months": months,
        "summary": summary,
        "from_profile": from_profile,
        "to_profile": to_profile,
        "changes": changes,
    }


def _read_csv(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _resolve_job(frame: pd.DataFrame, standard_job: str | None) -> str:
    jobs = sorted(frame["standard_job"].dropna().astype(str).unique().tolist())
    if not jobs:
        return standard_job or ""
    if not standard_job:
        return jobs[0]
    job = str(standard_job).strip()
    if job in jobs:
        return job
    lowered = job.lower()
    for candidate in jobs:
        if lowered and lowered in candidate.lower():
            return candidate
    return job


def _snapshot_profile(frame: pd.DataFrame, month: str, *, limit: int) -> list[dict[str, Any]]:
    if frame.empty or not month:
        return []
    filtered = frame[frame["month"].astype(str) == month].copy()
    if filtered.empty:
        return []
    for column in PROFILE_NUMBER_COLUMNS:
        filtered[column] = _number(filtered, column)
    rows = (
        filtered.sort_values(
            ["is_core_skill", "monthly_skill_frequency", "monthly_skill_count", "rank_in_month"],
            ascending=[False, False, False, True],
        )
        .head(_clamp(limit, 1, 1000))
        .to_dict(orient="records")
    )
    return [_clean_record(row) for row in rows]


def _profile_diff_rows(diff: pd.DataFrame, job: str, from_month: str, to_month: str) -> pd.DataFrame:
    if diff.empty:
        return pd.DataFrame()
    return diff[
        (diff["standard_job"].astype(str) == job)
        & (diff["from_month"].astype(str) == from_month)
        & (diff["to_month"].astype(str) == to_month)
    ].copy()


def _prepare_diff_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in DIFF_NUMBER_COLUMNS:
        output[column] = _number(output, column)
    return output


def _build_profile_diff_from_snapshots(
    snapshots: pd.DataFrame,
    job: str,
    from_month: str,
    to_month: str,
) -> pd.DataFrame:
    before = snapshots[snapshots["month"].astype(str) == from_month].copy()
    after = snapshots[snapshots["month"].astype(str) == to_month].copy()
    if before.empty and after.empty:
        return pd.DataFrame()
    for frame in (before, after):
        for column in PROFILE_NUMBER_COLUMNS:
            frame[column] = _number(frame, column)

    before_map = {row["skill"]: row for row in before.to_dict(orient="records")}
    after_map = {row["skill"]: row for row in after.to_dict(orient="records")}
    skills = sorted(set(before_map) | set(after_map))
    rows = []
    for skill in skills:
        before_row = before_map.get(skill, {})
        after_row = after_map.get(skill, {})
        before_frequency = float(before_row.get("monthly_skill_frequency", 0) or 0)
        after_frequency = float(after_row.get("monthly_skill_frequency", 0) or 0)
        if skill not in before_map:
            change_type = PROFILE_CHANGE_BUCKETS["added"]
        elif skill not in after_map:
            change_type = PROFILE_CHANGE_BUCKETS["removed"]
        elif after_frequency > before_frequency:
            change_type = PROFILE_CHANGE_BUCKETS["increased"]
        elif after_frequency < before_frequency:
            change_type = PROFILE_CHANGE_BUCKETS["decreased"]
        else:
            change_type = PROFILE_CHANGE_BUCKETS["stable_core"]
        rows.append(
            {
                "standard_job": job,
                "from_month": from_month,
                "to_month": to_month,
                "skill": skill,
                "kg_display_skill": after_row.get("kg_display_skill") or before_row.get("kg_display_skill") or "",
                "change_type": change_type,
                "from_monthly_jd_count": before_row.get("monthly_jd_count", 0),
                "to_monthly_jd_count": after_row.get("monthly_jd_count", 0),
                "from_monthly_skill_count": before_row.get("monthly_skill_count", 0),
                "to_monthly_skill_count": after_row.get("monthly_skill_count", 0),
                "from_monthly_skill_frequency": before_frequency,
                "to_monthly_skill_frequency": after_frequency,
                "frequency_delta": after_frequency - before_frequency,
                "frequency_delta_ratio": 0 if before_frequency == 0 else (after_frequency - before_frequency) / before_frequency,
                "from_cumulative_skill_count": before_row.get("cumulative_skill_count", 0),
                "to_cumulative_skill_count": after_row.get("cumulative_skill_count", 0),
                "from_cumulative_skill_frequency": before_row.get("cumulative_skill_frequency", 0),
                "to_cumulative_skill_frequency": after_row.get("cumulative_skill_frequency", 0),
                "is_stable_core": 1 if change_type == PROFILE_CHANGE_BUCKETS["stable_core"] else 0,
            }
        )
    return pd.DataFrame(rows)


def _empty_profile_compare(job: str, from_month: str, to_month: str) -> dict[str, Any]:
    return {
        "standard_job": job,
        "from_month": from_month,
        "to_month": to_month,
        "months": [],
        "summary": {"added": 0, "removed": 0, "increased": 0, "decreased": 0, "stable_core": 0, "modified": 0},
        "from_profile": [],
        "to_profile": [],
        "changes": {"added": [], "removed": [], "increased": [], "decreased": [], "stable_core": []},
    }


def _filter_month_range(frame: pd.DataFrame, column: str, month_start: str | None, month_end: str | None) -> pd.DataFrame:
    output = frame
    if month_start:
        output = output[output[column].astype(str) >= month_start]
    if month_end:
        output = output[output[column].astype(str) <= month_end]
    return output


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([0] * len(frame), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _latest_month(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values = sorted(frame[column].dropna().astype(str).unique().tolist())
    return values[-1] if values else ""


def _first_sorted(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values = sorted(frame[column].dropna().astype(str).unique().tolist())
    return values[0] if values else ""


def _nunique(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].nunique())


def _count_diff(frame: pd.DataFrame, month: str, change_type: str) -> int:
    if frame.empty or not month:
        return 0
    return int(((frame["to_month"].astype(str) == month) & (frame["change_type"].astype(str) == change_type)).sum())


def _round_float(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _clean_value(value) for key, value in row.items()}


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return round(value, 6)
    return value
