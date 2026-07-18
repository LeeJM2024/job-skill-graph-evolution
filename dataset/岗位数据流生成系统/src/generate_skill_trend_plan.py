"""Generate skill trend and monthly probability plans.

Step 3 assigns trends to a selected subset of skills for each job and creates
monthly skill appearance probabilities. It does not create JD records.
"""

from __future__ import annotations

import csv
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from run_context import get_current_run_dir, relative_to_project


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"

SKILL_TRENDS = [
    "稳定型",
    "持续上升",
    "持续下降",
    "先上升后稳定",
    "先上升后下降",
    "后期突增",
    "间歇出现",
]


@dataclass(frozen=True)
class SkillItem:
    standard_job: str
    standard_category: str
    skill: str
    skill_stage: str
    source_row_count: int
    traditional_source_row_count: int
    new_source_row_count: int
    in_new_skill_dictionary: bool


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


def parse_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return (value or "").strip().lower() in {"yes", "true", "1"}


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


def load_skill_pool(run_dir: Path) -> dict[str, list[SkillItem]]:
    rows = read_csv_dicts(run_dir / "skill_pool_by_job.csv")
    skills_by_job: dict[str, list[SkillItem]] = defaultdict(list)
    for row in rows:
        skill = (row.get("skill") or "").strip()
        job = (row.get("standard_job") or "").strip()
        if not job or not skill:
            continue
        skills_by_job[job].append(
            SkillItem(
                standard_job=job,
                standard_category=(row.get("standard_category") or "").strip(),
                skill=skill,
                skill_stage=(row.get("skill_stage") or "uncategorized").strip(),
                source_row_count=parse_int(row.get("source_row_count")),
                traditional_source_row_count=parse_int(
                    row.get("traditional_source_row_count")
                ),
                new_source_row_count=parse_int(row.get("new_source_row_count")),
                in_new_skill_dictionary=parse_bool(row.get("in_new_skill_dictionary")),
            )
        )
    return skills_by_job


def load_job_plan(run_dir: Path) -> tuple[dict[str, dict[str, int]], dict[str, dict]]:
    monthly_rows = read_csv_dicts(run_dir / "job_demand_monthly_plan.csv")
    trend_rows = read_csv_dicts(run_dir / "job_demand_trend_design.csv")

    monthly_plan: dict[str, dict[str, int]] = defaultdict(dict)
    for row in monthly_rows:
        monthly_plan[(row.get("standard_job") or "").strip()][
            (row.get("month") or "").strip()
        ] = parse_int(row.get("planned_jd_count"))

    trend_by_job = {
        (row.get("standard_job") or "").strip(): row
        for row in trend_rows
        if (row.get("standard_job") or "").strip()
    }
    return monthly_plan, trend_by_job


def normalize_stage(stage: str) -> str:
    if stage == "both":
        return "new"
    if stage == "new_dictionary_only":
        return "new"
    if stage == "uncategorized":
        return "new"
    if stage == "new":
        return "new"
    return "traditional"


def choose_skill_subset(
    skills: list[SkillItem], planned_total: int, rng: random.Random
) -> list[SkillItem]:
    if not skills or planned_total <= 0:
        return []

    traditional = [skill for skill in skills if normalize_stage(skill.skill_stage) == "traditional"]
    emerging = [skill for skill in skills if normalize_stage(skill.skill_stage) == "new"]

    traditional.sort(key=lambda item: (-item.source_row_count, item.skill))
    emerging.sort(key=lambda item: (-item.source_row_count, item.skill))

    pool_size = len(skills)
    target_size = int(round(10 + math.sqrt(pool_size) * 2.2 + math.log1p(planned_total) * 2.5))
    target_size = max(8, min(90, target_size, pool_size))

    target_new = max(2, int(target_size * 0.25)) if emerging else 0
    target_traditional = target_size - target_new
    if not traditional:
        target_new = target_size
        target_traditional = 0

    selected: list[SkillItem] = []
    selected.extend(weighted_sample_skills(traditional, target_traditional, rng))
    selected.extend(weighted_sample_skills(emerging, target_new, rng))

    if len(selected) < target_size:
        selected_keys = {skill.skill for skill in selected}
        remaining = [skill for skill in skills if skill.skill not in selected_keys]
        selected.extend(weighted_sample_skills(remaining, target_size - len(selected), rng))

    selected.sort(key=lambda item: (item.standard_job, normalize_stage(item.skill_stage), -item.source_row_count, item.skill))
    return selected


def weighted_sample_skills(
    skills: list[SkillItem], target_count: int, rng: random.Random
) -> list[SkillItem]:
    if target_count <= 0 or not skills:
        return []
    target_count = min(target_count, len(skills))
    selected: list[SkillItem] = []
    remaining = list(skills)
    for _ in range(target_count):
        weights = [math.log1p(max(item.source_row_count, 1)) for item in remaining]
        picked = rng.choices(remaining, weights=weights, k=1)[0]
        selected.append(picked)
        remaining.remove(picked)
    return selected


def choose_skill_trend(skill: SkillItem, job_demand_trend: str, rng: random.Random) -> str:
    stage = normalize_stage(skill.skill_stage)
    if stage == "new":
        weights = {
            "稳定型": 1.2,
            "持续上升": 3.0,
            "持续下降": 0.6,
            "先上升后稳定": 2.4,
            "先上升后下降": 1.3,
            "后期突增": 2.4,
            "间歇出现": 1.0,
        }
    else:
        weights = {
            "稳定型": 3.2,
            "持续上升": 0.9,
            "持续下降": 1.6,
            "先上升后稳定": 1.1,
            "先上升后下降": 0.8,
            "后期突增": 0.25,
            "间歇出现": 0.8,
        }

    if job_demand_trend in {"间歇出现", "消失后再出现"}:
        weights["间歇出现"] += 1.0
    if job_demand_trend == "持续上升":
        weights["持续上升"] += 0.9
        weights["先上升后稳定"] += 0.5
    if job_demand_trend == "持续下降":
        weights["持续下降"] += 0.9

    trends = list(weights)
    return rng.choices(trends, weights=[weights[trend] for trend in trends], k=1)[0]


def probability_curve(
    trend: str, stage: str, source_row_count: int, n: int, rng: random.Random
) -> list[float]:
    base = 0.08 + min(math.log1p(max(source_row_count, 1)) / 20, 0.22)
    if stage == "new":
        low = max(0.03, base * rng.uniform(0.45, 0.8))
        high = min(0.82, base * rng.uniform(1.35, 2.1) + 0.08)
    else:
        low = max(0.05, base * rng.uniform(0.7, 0.95))
        high = min(0.78, base * rng.uniform(1.1, 1.7) + 0.05)

    values: list[float] = []
    peak_index = max(2, min(n - 2, int(n * rng.uniform(0.45, 0.7))))
    plateau_index = max(3, min(n - 1, int(n * rng.uniform(0.45, 0.65))))
    burst_start = rng.randint(max(1, int(n * 0.55)), max(1, n - 4))
    intermittent_period = rng.choice([4, 5, 6])

    for idx in range(n):
        t = idx / max(n - 1, 1)
        if trend == "稳定型":
            value = base * rng.uniform(0.86, 1.14)
        elif trend == "持续上升":
            value = low + (high - low) * (t**1.15)
        elif trend == "持续下降":
            value = high - (high - low) * (t**0.9)
        elif trend == "先上升后稳定":
            if idx <= plateau_index:
                value = low + (high - low) * (idx / plateau_index)
            else:
                value = high * rng.uniform(0.92, 1.08)
        elif trend == "先上升后下降":
            if idx <= peak_index:
                value = low + (high - low) * (idx / peak_index)
            else:
                value = high - (high - low) * 0.75 * (
                    (idx - peak_index) / max(n - peak_index - 1, 1)
                )
        elif trend == "后期突增":
            if idx < burst_start:
                value = low * rng.uniform(0.65, 1.15)
            else:
                value = low + (high - low) * (
                    (idx - burst_start + 1) / max(n - burst_start, 1)
                )
        elif trend == "间歇出现":
            if idx % intermittent_period in (0, 1):
                value = min(high, base * rng.uniform(1.0, 1.8))
            else:
                value = 0.0
        else:
            value = base

        if value > 0:
            value *= rng.uniform(0.92, 1.08)
        values.append(round(max(0.0, min(value, 0.88)), 4))
    return values


def expected_skill_count(probability: float, planned_jd_count: int) -> int:
    if planned_jd_count <= 0 or probability <= 0:
        return 0
    return int(round(probability * planned_jd_count))


def generate_skill_plan(run_dir: Path) -> tuple[list[dict], list[dict], dict]:
    config = read_config()
    rng = random.Random(config["seed"] + 3)
    months = month_sequence(config["month_start"], config["month_end"])
    skills_by_job = load_skill_pool(run_dir)
    monthly_plan, trend_by_job = load_job_plan(run_dir)

    trend_rows: list[dict] = []
    probability_rows: list[dict] = []
    selected_skill_count_by_job: dict[str, int] = {}

    for job, trend_info in trend_by_job.items():
        total_planned = parse_int(trend_info.get("total_planned_jd_count"))
        source_jd_count = parse_int(trend_info.get("source_jd_count"))
        has_source_data = (trend_info.get("has_source_data") or "").strip() == "yes"
        if total_planned <= 0 or not has_source_data:
            selected_skill_count_by_job[job] = 0
            continue

        job_skills = skills_by_job.get(job, [])
        selected_skills = choose_skill_subset(job_skills, total_planned, rng)
        selected_skill_count_by_job[job] = len(selected_skills)
        job_demand_trend = (trend_info.get("demand_trend_type") or "").strip()

        for skill_item in selected_skills:
            skill_stage = normalize_stage(skill_item.skill_stage)
            skill_trend = choose_skill_trend(skill_item, job_demand_trend, rng)
            probabilities = probability_curve(
                skill_trend,
                skill_stage,
                skill_item.source_row_count,
                len(months),
                rng,
            )
            active_probabilities = [
                probability
                for month, probability in zip(months, probabilities)
                if monthly_plan[job].get(month, 0) > 0 and probability > 0
            ]
            average_probability = (
                round(sum(active_probabilities) / len(active_probabilities), 4)
                if active_probabilities
                else 0.0
            )
            max_probability = max(active_probabilities) if active_probabilities else 0.0

            trend_rows.append(
                {
                    "standard_job": job,
                    "standard_category": skill_item.standard_category,
                    "skill": skill_item.skill,
                    "skill_stage": skill_stage,
                    "skill_trend_type": skill_trend,
                    "job_demand_trend_type": job_demand_trend,
                    "source_jd_count": source_jd_count,
                    "source_skill_row_count": skill_item.source_row_count,
                    "planned_job_jd_count": total_planned,
                    "average_active_month_probability": average_probability,
                    "max_active_month_probability": max_probability,
                    "in_new_skill_dictionary": "yes"
                    if skill_item.in_new_skill_dictionary
                    else "no",
                }
            )

            for idx, (month, probability) in enumerate(zip(months, probabilities), start=1):
                planned_jd_count = monthly_plan[job].get(month, 0)
                if planned_jd_count <= 0:
                    effective_probability = 0.0
                else:
                    effective_probability = probability
                probability_rows.append(
                    {
                        "standard_job": job,
                        "standard_category": skill_item.standard_category,
                        "month": month,
                        "month_index": idx,
                        "skill": skill_item.skill,
                        "skill_stage": skill_stage,
                        "skill_trend_type": skill_trend,
                        "planned_jd_count": planned_jd_count,
                        "skill_probability": f"{effective_probability:.4f}",
                        "expected_skill_count": expected_skill_count(
                            effective_probability, planned_jd_count
                        ),
                    }
                )

    trend_type_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    for row in trend_rows:
        trend_type_counts[row["skill_trend_type"]] = (
            trend_type_counts.get(row["skill_trend_type"], 0) + 1
        )
        stage_counts[row["skill_stage"]] = stage_counts.get(row["skill_stage"], 0) + 1

    jobs_without_skill_plan = [
        job
        for job in trend_by_job
        if selected_skill_count_by_job.get(job, 0) == 0
    ]

    quality_report = {
        "config_seed": config["seed"],
        "skill_plan_seed": config["seed"] + 3,
        "run_dir": relative_to_project(PROJECT_ROOT, run_dir),
        "month_start": config["month_start"],
        "month_end": config["month_end"],
        "month_count": len(months),
        "jobs_in_demand_plan": len(trend_by_job),
        "jobs_with_skill_plan": sum(
            1 for count in selected_skill_count_by_job.values() if count > 0
        ),
        "jobs_without_skill_plan": jobs_without_skill_plan,
        "selected_job_skill_pairs": len(trend_rows),
        "skill_probability_rows": len(probability_rows),
        "skill_stage_counts": stage_counts,
        "skill_trend_type_counts": trend_type_counts,
        "min_selected_skills_per_generated_job": min(
            count
            for count in selected_skill_count_by_job.values()
            if count > 0
        ),
        "max_selected_skills_per_generated_job": max(
            selected_skill_count_by_job.values()
        ),
    }
    return trend_rows, probability_rows, quality_report


def main() -> None:
    run_dir = get_current_run_dir(PROJECT_ROOT)
    trend_rows, probability_rows, quality_report = generate_skill_plan(run_dir)

    write_csv(
        run_dir / "skill_trend_design.csv",
        [
            "standard_job",
            "standard_category",
            "skill",
            "skill_stage",
            "skill_trend_type",
            "job_demand_trend_type",
            "source_jd_count",
            "source_skill_row_count",
            "planned_job_jd_count",
            "average_active_month_probability",
            "max_active_month_probability",
            "in_new_skill_dictionary",
        ],
        trend_rows,
    )
    write_csv(
        run_dir / "skill_monthly_probability_plan.csv",
        [
            "standard_job",
            "standard_category",
            "month",
            "month_index",
            "skill",
            "skill_stage",
            "skill_trend_type",
            "planned_jd_count",
            "skill_probability",
            "expected_skill_count",
        ],
        probability_rows,
    )

    with (run_dir / "skill_trend_quality_report.json").open("w", encoding="utf-8") as f:
        json.dump(quality_report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(quality_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

