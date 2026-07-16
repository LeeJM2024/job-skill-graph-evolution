"""Generate monthly job demand plans.

Step 2 decides how many JD records each standard job should have in each
month. It does not create JD text or skill combinations.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"
PROFILE_PATH = PROJECT_ROOT / "outputs" / "input_profile.csv"
OUTPUT_MONTHLY_PLAN = PROJECT_ROOT / "outputs" / "job_demand_monthly_plan.csv"
OUTPUT_TREND_DESIGN = PROJECT_ROOT / "outputs" / "job_demand_trend_design.csv"
OUTPUT_QUALITY_REPORT = PROJECT_ROOT / "outputs" / "job_demand_quality_report.json"

TREND_TYPES = [
    "持续上升",
    "持续下降",
    "先上升后稳定",
    "先上升后下降",
    "稳定波动",
    "间歇出现",
    "消失后再出现",
]

TREND_WEIGHTS_BY_CATEGORY = {
    "AI算法": {
        "持续上升": 3.0,
        "先上升后稳定": 2.5,
        "稳定波动": 1.5,
        "先上升后下降": 1.2,
    },
    "AI应用": {
        "持续上升": 2.8,
        "先上升后稳定": 2.6,
        "消失后再出现": 1.4,
        "稳定波动": 1.2,
    },
    "AI工程": {
        "持续上升": 2.3,
        "先上升后稳定": 2.2,
        "稳定波动": 1.5,
    },
    "软件研发": {
        "稳定波动": 2.4,
        "先上升后稳定": 1.8,
        "持续下降": 1.5,
        "间歇出现": 1.2,
    },
    "数据": {
        "稳定波动": 2.1,
        "先上升后稳定": 1.8,
        "持续上升": 1.5,
        "间歇出现": 1.3,
    },
    "测试": {
        "稳定波动": 2.4,
        "持续下降": 1.7,
        "间歇出现": 1.4,
    },
    "芯片": {
        "稳定波动": 2.0,
        "先上升后稳定": 1.5,
        "间歇出现": 1.4,
        "消失后再出现": 1.3,
    },
    "机器人": {
        "先上升后稳定": 2.0,
        "间歇出现": 1.8,
        "消失后再出现": 1.5,
        "稳定波动": 1.4,
    },
}


@dataclass(frozen=True)
class JobProfile:
    standard_job: str
    standard_category: str
    source_jd_count: int
    unique_skill_count: int
    notes: str


def read_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_int(value: str | int | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def month_sequence(start: str, end: str) -> list[str]:
    start_year, start_month = [int(part) for part in start.split("-")]
    end_year, end_month = [int(part) for part in end.split("-")]
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def load_profiles() -> list[JobProfile]:
    rows = read_csv_dicts(PROFILE_PATH)
    profiles: list[JobProfile] = []
    for row in rows:
        profiles.append(
            JobProfile(
                standard_job=(row.get("standard_job") or "").strip(),
                standard_category=(row.get("standard_category") or "").strip(),
                source_jd_count=parse_int(row.get("source_jd_count")),
                unique_skill_count=parse_int(row.get("unique_skill_count")),
                notes=(row.get("notes") or "").strip(),
            )
        )
    return profiles


def choose_trend(profile: JobProfile, rng: random.Random) -> str:
    if profile.source_jd_count <= 0 or profile.unique_skill_count <= 0:
        return "无样本不生成"

    core_trends = [
        "持续上升",
        "持续下降",
        "先上升后稳定",
        "先上升后下降",
        "稳定波动",
    ]
    weights = {trend: 1.0 for trend in TREND_TYPES}
    for trend, weight in TREND_WEIGHTS_BY_CATEGORY.get(
        profile.standard_category, {}
    ).items():
        weights[trend] = weights.get(trend, 1.0) + weight

    if profile.source_jd_count < 10:
        weights["间歇出现"] += 3.0
        weights["消失后再出现"] += 2.0
        weights["稳定波动"] += 1.0
    elif profile.source_jd_count > 300:
        weights["稳定波动"] += 2.0
        weights["先上升后稳定"] += 1.5
        weights["间歇出现"] = 0.05
        weights["消失后再出现"] = 0.05

    trends = list(weights)
    trend_weights = [weights[trend] for trend in trends]
    chosen = rng.choices(trends, weights=trend_weights, k=1)[0]
    if profile.source_jd_count > 300 and chosen in {"间歇出现", "消失后再出现"}:
        core_weights = [weights[trend] for trend in core_trends]
        return rng.choices(core_trends, weights=core_weights, k=1)[0]
    return chosen


def base_curve(trend: str, n: int, rng: random.Random) -> list[float]:
    if n <= 0:
        return []
    values: list[float] = []
    peak_index = max(2, min(n - 2, int(n * rng.uniform(0.45, 0.7))))
    plateau_index = max(3, min(n - 1, int(n * rng.uniform(0.45, 0.65))))
    reappear_gap_start = rng.randint(4, max(4, n - 8))
    reappear_gap_len = rng.randint(3, 6)

    for idx in range(n):
        t = idx / max(n - 1, 1)
        if trend == "持续上升":
            value = 0.25 + 0.9 * (t**1.15)
        elif trend == "持续下降":
            value = 1.1 - 0.9 * (t**0.9)
        elif trend == "先上升后稳定":
            if idx <= plateau_index:
                value = 0.25 + 0.85 * (idx / plateau_index)
            else:
                value = 1.05
        elif trend == "先上升后下降":
            if idx <= peak_index:
                value = 0.25 + 0.9 * (idx / peak_index)
            else:
                value = 1.15 - 0.75 * ((idx - peak_index) / max(n - peak_index - 1, 1))
        elif trend == "稳定波动":
            value = 0.75 + 0.2 * math.sin(idx * 0.9 + rng.uniform(-0.3, 0.3))
        elif trend == "间歇出现":
            cycle_on = (idx % rng.choice([4, 5, 6])) in (0, 1, 2)
            value = rng.uniform(0.55, 1.0) if cycle_on else 0.0
        elif trend == "消失后再出现":
            in_gap = reappear_gap_start <= idx < reappear_gap_start + reappear_gap_len
            if in_gap:
                value = 0.0
            elif idx < reappear_gap_start:
                value = 0.75 + 0.18 * math.sin(idx * 0.7)
            else:
                value = 0.55 + 0.45 * ((idx - reappear_gap_start - reappear_gap_len + 1) / max(n - reappear_gap_start - reappear_gap_len, 1))
        else:
            value = 0.0

        if value > 0:
            value *= rng.uniform(0.82, 1.18)
        values.append(max(value, 0.0))

    return values


def apply_activity_mask(
    values: list[float], profile: JobProfile, trend: str, rng: random.Random
) -> tuple[list[float], str]:
    if profile.source_jd_count <= 0:
        return [0.0 for _ in values], "无样本全周期不出现"

    masked = list(values)
    n = len(masked)
    zero_probability = 0.04
    if profile.source_jd_count < 10:
        zero_probability = 0.34
    elif profile.source_jd_count < 30:
        zero_probability = 0.18
    elif trend in {"间歇出现", "消失后再出现"}:
        zero_probability = 0.12

    for idx, value in enumerate(masked):
        if value <= 0:
            continue
        if rng.random() < zero_probability:
            masked[idx] = 0.0

    if trend == "间歇出现":
        # Ensure this trend visibly has multiple inactive months.
        zero_months = rng.sample(range(n), k=max(3, n // 5))
        for idx in zero_months:
            masked[idx] = 0.0

    positive_indices = [idx for idx, value in enumerate(masked) if value > 0]
    if not positive_indices and profile.source_jd_count > 0:
        idx = rng.randrange(n)
        masked[idx] = max(values[idx], 0.6)
        positive_indices = [idx]

    if (
        trend == "消失后再出现"
        and len(positive_indices) >= 2
        and not has_reappearance(masked)
    ):
        start = rng.randint(3, max(3, n - 7))
        gap_len = rng.randint(2, min(5, n - start - 1))
        for idx in range(start, start + gap_len):
            masked[idx] = 0.0
        if all(value <= 0 for value in masked[:start]):
            masked[max(0, start - 1)] = 0.7
        if all(value <= 0 for value in masked[start + gap_len :]):
            masked[min(n - 1, start + gap_len)] = 0.7

    if profile.source_jd_count < 10:
        return masked, "小样本岗位，允许较多月份不出现"
    if trend in {"间歇出现", "消失后再出现"}:
        return masked, "趋势包含阶段性不出现"
    return masked, "常规月度波动"


def has_reappearance(values: list[float] | list[int]) -> bool:
    seen_positive = False
    seen_zero_after_positive = False
    for value in values:
        if value > 0:
            if seen_zero_after_positive:
                return True
            seen_positive = True
        elif seen_positive:
            seen_zero_after_positive = True
    return False


def raw_job_weight(profile: JobProfile, rng: random.Random) -> float:
    if profile.source_jd_count <= 0 or profile.unique_skill_count <= 0:
        return 0.0
    count_component = math.log1p(profile.source_jd_count)
    skill_component = math.log1p(profile.unique_skill_count) * 0.28
    noise = rng.uniform(0.75, 1.25)
    if profile.source_jd_count < 10:
        noise *= rng.uniform(0.35, 0.75)
    return max(0.2, (count_component + skill_component) * noise)


def distribute_counts(
    raw_values_by_job: dict[str, list[float]], target_total: int
) -> dict[str, list[int]]:
    flat: list[tuple[str, int, float]] = []
    for job, values in raw_values_by_job.items():
        for idx, value in enumerate(values):
            if value > 0:
                flat.append((job, idx, value))

    raw_total = sum(value for _job, _idx, value in flat)
    if raw_total <= 0:
        raise ValueError("No positive demand values were generated.")

    scaled: dict[str, list[int]] = {
        job: [0 for _ in values] for job, values in raw_values_by_job.items()
    }
    remainders: list[tuple[float, str, int]] = []
    assigned = 0

    for job, idx, value in flat:
        exact = value * target_total / raw_total
        count = int(math.floor(exact))
        if count == 0:
            count = 1
        scaled[job][idx] = count
        assigned += count
        remainders.append((exact - math.floor(exact), job, idx))

    if assigned < target_total:
        for _remainder, job, idx in sorted(remainders, reverse=True)[
            : target_total - assigned
        ]:
            scaled[job][idx] += 1
    elif assigned > target_total:
        to_remove = assigned - target_total
        for _remainder, job, idx in sorted(remainders):
            if to_remove <= 0:
                break
            if scaled[job][idx] > 1:
                scaled[job][idx] -= 1
                to_remove -= 1

    return scaled


def active_month_summary(months: list[str], counts: list[int]) -> dict[str, str | int]:
    active = [(month, count) for month, count in zip(months, counts) if count > 0]
    if not active:
        return {
            "total_planned_jd_count": 0,
            "active_month_count": 0,
            "zero_month_count": len(months),
            "first_active_month": "",
            "last_active_month": "",
            "peak_month": "",
            "min_monthly_jd": 0,
            "max_monthly_jd": 0,
            "has_reappearance": "no",
        }

    peak_month, max_count = max(active, key=lambda item: item[1])
    positive_counts = [count for _month, count in active]
    return {
        "total_planned_jd_count": sum(counts),
        "active_month_count": len(active),
        "zero_month_count": len(months) - len(active),
        "first_active_month": active[0][0],
        "last_active_month": active[-1][0],
        "peak_month": peak_month,
        "min_monthly_jd": min(positive_counts),
        "max_monthly_jd": max_count,
        "has_reappearance": "yes" if has_reappearance(counts) else "no",
    }


def generate_plan() -> tuple[list[dict], list[dict], dict]:
    config = read_config()
    rng = random.Random(config["seed"] + 2)
    months = month_sequence(config["month_start"], config["month_end"])
    profiles = load_profiles()

    target_total = rng.randint(
        int(config["target_total_jd_min"]), int(config["target_total_jd_max"])
    )

    trends_by_job: dict[str, str] = {}
    activity_notes_by_job: dict[str, str] = {}
    raw_values_by_job: dict[str, list[float]] = {}

    for profile in profiles:
        trend = choose_trend(profile, rng)
        trends_by_job[profile.standard_job] = trend
        if trend == "无样本不生成":
            raw_values_by_job[profile.standard_job] = [0.0 for _ in months]
            activity_notes_by_job[profile.standard_job] = (
                "无真实JD和技能池，按方案1保留标准岗位但不生成事件"
            )
            continue

        curve = base_curve(trend, len(months), rng)
        masked_curve, activity_note = apply_activity_mask(curve, profile, trend, rng)
        weight = raw_job_weight(profile, rng)
        raw_values_by_job[profile.standard_job] = [
            value * weight for value in masked_curve
        ]
        activity_notes_by_job[profile.standard_job] = activity_note

    counts_by_job = distribute_counts(raw_values_by_job, target_total)

    monthly_rows: list[dict] = []
    trend_rows: list[dict] = []

    profile_by_job = {profile.standard_job: profile for profile in profiles}
    for profile in profiles:
        counts = counts_by_job[profile.standard_job]
        trend = trends_by_job[profile.standard_job]
        for idx, (month, count) in enumerate(zip(months, counts), start=1):
            monthly_rows.append(
                {
                    "standard_job": profile.standard_job,
                    "standard_category": profile.standard_category,
                    "month": month,
                    "month_index": idx,
                    "demand_trend_type": trend,
                    "planned_jd_count": count,
                    "is_active_month": "yes" if count > 0 else "no",
                }
            )

        summary = active_month_summary(months, counts)
        trend_rows.append(
            {
                "standard_job": profile.standard_job,
                "standard_category": profile.standard_category,
                "source_jd_count": profile.source_jd_count,
                "unique_skill_count": profile.unique_skill_count,
                "has_source_data": "yes"
                if profile.source_jd_count > 0 and profile.unique_skill_count > 0
                else "no",
                "demand_trend_type": trend,
                "activity_pattern": activity_notes_by_job[profile.standard_job],
                **summary,
                "profile_notes": profile.notes,
            }
        )

    trend_counts: dict[str, int] = {}
    for trend in trends_by_job.values():
        trend_counts[trend] = trend_counts.get(trend, 0) + 1

    no_sample_jobs = [
        profile.standard_job
        for profile in profiles
        if profile.source_jd_count <= 0 or profile.unique_skill_count <= 0
    ]
    jobs_with_reappearance = [
        row["standard_job"]
        for row in trend_rows
        if row["has_reappearance"] == "yes"
    ]
    jobs_with_zero_months = [
        row["standard_job"]
        for row in trend_rows
        if int(row["zero_month_count"]) > 0
    ]

    quality_report = {
        "config_seed": config["seed"],
        "plan_seed": config["seed"] + 2,
        "month_start": config["month_start"],
        "month_end": config["month_end"],
        "month_count": len(months),
        "standard_job_count": len(profiles),
        "target_total_jd_count": target_total,
        "actual_total_jd_count": sum(
            int(row["planned_jd_count"]) for row in monthly_rows
        ),
        "jobs_with_generated_jd": sum(
            1 for row in trend_rows if int(row["total_planned_jd_count"]) > 0
        ),
        "jobs_without_generated_jd": [
            row["standard_job"]
            for row in trend_rows
            if int(row["total_planned_jd_count"]) == 0
        ],
        "no_sample_jobs_kept_zero": no_sample_jobs,
        "jobs_with_zero_months_count": len(jobs_with_zero_months),
        "jobs_with_reappearance_count": len(jobs_with_reappearance),
        "trend_type_counts": trend_counts,
        "planned_monthly_total_min": min(
            sum(
                counts_by_job[profile.standard_job][idx]
                for profile in profiles
            )
            for idx in range(len(months))
        ),
        "planned_monthly_total_max": max(
            sum(
                counts_by_job[profile.standard_job][idx]
                for profile in profiles
            )
            for idx in range(len(months))
        ),
    }

    # Keep this lookup local for easier debugging if profile ordering changes.
    _ = profile_by_job
    return monthly_rows, trend_rows, quality_report


def main() -> None:
    monthly_rows, trend_rows, quality_report = generate_plan()

    write_csv(
        OUTPUT_MONTHLY_PLAN,
        [
            "standard_job",
            "standard_category",
            "month",
            "month_index",
            "demand_trend_type",
            "planned_jd_count",
            "is_active_month",
        ],
        monthly_rows,
    )
    write_csv(
        OUTPUT_TREND_DESIGN,
        [
            "standard_job",
            "standard_category",
            "source_jd_count",
            "unique_skill_count",
            "has_source_data",
            "demand_trend_type",
            "activity_pattern",
            "total_planned_jd_count",
            "active_month_count",
            "zero_month_count",
            "first_active_month",
            "last_active_month",
            "peak_month",
            "min_monthly_jd",
            "max_monthly_jd",
            "has_reappearance",
            "profile_notes",
        ],
        trend_rows,
    )

    with OUTPUT_QUALITY_REPORT.open("w", encoding="utf-8") as f:
        json.dump(quality_report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(quality_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
