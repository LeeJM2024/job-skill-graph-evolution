from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .job_profile import JOB_PROFILE_SNAPSHOT_COLUMNS
from .text import clean_text


CURRENT_PROFILE_COLUMNS = [
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
    "source_month",
    "source_type",
    "profile_generated_at",
]


def build_current_profile(snapshot_frame: pd.DataFrame) -> pd.DataFrame:
    """Select each standard job's latest active system skill snapshot."""
    snapshots = snapshot_frame.copy().fillna("")
    for column in JOB_PROFILE_SNAPSHOT_COLUMNS:
        if column not in snapshots.columns:
            snapshots[column] = ""
    snapshots = snapshots[JOB_PROFILE_SNAPSHOT_COLUMNS]
    for column in ["month", "standard_job", "skill", "kg_display_skill", "snapshot_skill_status"]:
        snapshots[column] = snapshots[column].map(clean_text)
    snapshots = snapshots[
        (snapshots["month"] != "")
        & (snapshots["standard_job"] != "")
        & (snapshots["skill"] != "")
    ].copy()
    if snapshots.empty:
        return pd.DataFrame(columns=CURRENT_PROFILE_COLUMNS)

    for column in [
        "monthly_jd_count",
        "monthly_skill_count",
        "cumulative_jd_count",
        "cumulative_skill_count",
    ]:
        snapshots[column] = pd.to_numeric(snapshots[column], errors="coerce").fillna(0).astype(int)
    for column in ["monthly_skill_frequency", "cumulative_skill_frequency"]:
        snapshots[column] = pd.to_numeric(snapshots[column], errors="coerce").fillna(0.0)

    latest_month_by_job = snapshots.groupby("standard_job")["month"].max()
    current = snapshots[
        snapshots.apply(
            lambda row: row["month"] == latest_month_by_job[row["standard_job"]],
            axis=1,
        )
    ].copy()
    # A current profile shows current demand only. Historical zero-count skills
    # remain available in job_profile_snapshots.csv for time-series analysis.
    current = current[current["monthly_skill_count"] > 0].copy()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = pd.DataFrame(
        {
            "standard_job": current["standard_job"],
            "skill": current["skill"],
            "kg_display_skill": current["kg_display_skill"],
            "monthly_jd_count": current["monthly_jd_count"],
            "monthly_skill_count": current["monthly_skill_count"],
            "monthly_skill_frequency": current["monthly_skill_frequency"].round(6),
            "cumulative_jd_count": current["cumulative_jd_count"],
            "cumulative_skill_count": current["cumulative_skill_count"],
            "cumulative_skill_frequency": current["cumulative_skill_frequency"].round(6),
            "snapshot_skill_status": current["snapshot_skill_status"],
            "is_core_skill": current["is_core_skill"].map(clean_text),
            "rank_in_month": current["rank_in_month"].map(clean_text),
            "source_month": current["month"],
            "source_type": "system",
            "profile_generated_at": generated_at,
        }
    )
    result["_rank_sort"] = pd.to_numeric(result["rank_in_month"], errors="coerce").fillna(float("inf"))
    return result.sort_values(
        ["standard_job", "_rank_sort", "skill"],
        kind="stable",
    ).drop(columns=["_rank_sort"]).reset_index(drop=True)[CURRENT_PROFILE_COLUMNS]
