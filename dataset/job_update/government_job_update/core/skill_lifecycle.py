from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from company_job_update.core.skill_lifecycle import LIFECYCLE_COLUMNS
from shared.text_utils import clean_text


@dataclass(slots=True)
class GovernmentAnnualLifecycleStore:
    """Lifecycle rules for annual government recruitment cycles, not months."""

    skill_lifecycle_path: object

    def rebuild(
        self,
        *,
        frequency: pd.DataFrame,
        skill_pool: pd.DataFrame | None = None,
        as_of_month: str | None = None,
        write: bool = True,
    ) -> pd.DataFrame:
        lifecycle = build_government_annual_lifecycle(frequency, skill_pool, as_of_month=as_of_month)
        if write:
            self.write_lifecycle(lifecycle)
        return lifecycle

    def write_lifecycle(self, lifecycle: pd.DataFrame) -> None:
        from pathlib import Path

        path = Path(self.skill_lifecycle_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lifecycle.to_csv(path, index=False, encoding="utf-8-sig")


def build_government_annual_lifecycle(
    frequency: pd.DataFrame,
    skill_pool: pd.DataFrame | None = None,
    *,
    as_of_month: str | None = None,
) -> pd.DataFrame:
    frame = frequency.copy().fillna("")
    required = {"month", "standard_job", "skill", "monthly_skill_count", "monthly_skill_frequency", "cumulative_skill_count", "cumulative_skill_frequency"}
    if required.difference(frame.columns):
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)
    for column in ["monthly_skill_count", "monthly_skill_frequency", "cumulative_skill_count", "cumulative_skill_frequency"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    frame["month"] = frame["month"].map(clean_text)
    frame["standard_job"] = frame["standard_job"].map(clean_text)
    frame["skill"] = frame["skill"].map(clean_text)
    frame = frame[(frame["month"] != "") & (frame["standard_job"] != "") & (frame["skill"] != "")]
    if frame.empty:
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)

    display = {}
    if skill_pool is not None and not skill_pool.empty:
        display = {
            clean_text(row.get("normalized_skill")).casefold(): clean_text(row.get("kg_display_skill"))
            for _, row in skill_pool.fillna("").iterrows()
            if clean_text(row.get("normalized_skill"))
        }
    all_cycles = sorted(frame["month"].unique())
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for (standard_job, skill), group in frame.groupby(["standard_job", "skill"], sort=True):
        group = group.sort_values("month").drop_duplicates("month", keep="last")
        job_cycles = sorted(frame[frame["standard_job"] == standard_job]["month"].unique())
        current = clean_text(as_of_month) or job_cycles[-1]
        observed = group.set_index("month")
        counts = [int(observed.at[cycle, "monthly_skill_count"]) if cycle in observed.index else 0 for cycle in job_cycles]
        first_index = next((index for index, value in enumerate(counts) if value > 0), None)
        last_index = next((index for index in range(len(counts) - 1, -1, -1) if counts[index] > 0), None)
        if first_index is None or last_index is None:
            continue
        first_seen, last_seen = job_cycles[first_index], job_cycles[last_index]
        current_index = job_cycles.index(current) if current in job_cycles else len(job_cycles) - 1
        current_count = counts[current_index]
        current_frequency = float(observed.at[current, "monthly_skill_frequency"]) if current in observed.index else 0.0
        active_cycles = sum(value > 0 for value in counts)
        prior_max = max(counts[:current_index], default=0)
        latest = group.iloc[-1]
        cumulative_count = int(latest["cumulative_skill_count"])
        cumulative_frequency = float(latest["cumulative_skill_frequency"])
        cycles_since_last = current_index - last_index

        if active_cycles >= 2 and current_count > 0 and cumulative_frequency >= 0.25:
            status = "稳定核心技能"
            reason = "appeared in multiple annual recruitment cycles with sustained cumulative demand"
        elif first_seen == current and current_count > 0:
            status = "新兴技能"
            reason = "first appeared in the latest annual recruitment cycle"
        elif current_count > 0:
            status = "活跃技能"
            reason = "appeared in the latest annual recruitment cycle"
        elif cycles_since_last >= 2 and cumulative_count >= 3:
            status = "废弃技能"
            reason = "absent for at least two observed annual recruitment cycles"
        elif cycles_since_last >= 1 and prior_max > 0:
            status = "衰退技能"
            reason = "appeared historically but not in the latest annual recruitment cycle"
        else:
            status = "观察中"
            reason = "insufficient annual recruitment-cycle evidence"

        recent = counts[max(0, current_index - 2): current_index + 1]
        previous = counts[max(0, current_index - 5): max(0, current_index - 2)]
        rows.append(
            {
                "month": current,
                "standard_job": standard_job,
                "skill": skill,
                "kg_display_skill": display.get(skill.casefold(), ""),
                "lifecycle_status": status,
                "first_seen_month": first_seen,
                "last_seen_month": last_seen,
                "age_months": active_cycles,
                "months_since_last_seen": cycles_since_last,
                "current_monthly_skill_count": current_count,
                "current_monthly_skill_frequency": round(current_frequency, 6),
                "cumulative_skill_count": cumulative_count,
                "cumulative_skill_frequency": round(cumulative_frequency, 6),
                "recent_3m_skill_count": sum(recent),
                "recent_6m_skill_count": sum(counts[max(0, current_index - 5): current_index + 1]),
                "recent_3m_active_months": sum(value > 0 for value in recent),
                "recent_6m_active_months": sum(value > 0 for value in counts[max(0, current_index - 5): current_index + 1]),
                "prev_3m_skill_count": sum(previous),
                "prev_6m_skill_count": 0,
                "mom_frequency_change": 0.0,
                "recent_3m_vs_prev_3m_change": 0.0,
                "recent_6m_frequency_stddev": 0.0,
                "covered_job_count": 0,
                "recent_3m_covered_job_count": 0,
                "prev_3m_covered_job_count": 0,
                "recent_3m_covered_job_count_change": 0,
                "lifecycle_reason": reason + "; government metrics use observed annual recruitment cycles",
                "updated_at": now,
            }
        )
    return pd.DataFrame(rows, columns=LIFECYCLE_COLUMNS).sort_values(["standard_job", "skill"]).reset_index(drop=True)
