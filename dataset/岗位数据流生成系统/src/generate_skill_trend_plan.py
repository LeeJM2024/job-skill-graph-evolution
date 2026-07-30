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

from industry_migration_prior import (
    SkillMigrationPrior,
    activation_month,
    load_industry_priors,
    stage_min_probability,
)
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


TREND_STABLE = "\u7a33\u5b9a\u578b"
TREND_RISING = "\u6301\u7eed\u4e0a\u5347"
TREND_DECLINING = "\u6301\u7eed\u4e0b\u964d"
TREND_RISE_THEN_STABLE = "\u5148\u4e0a\u5347\u540e\u7a33\u5b9a"
TREND_RISE_THEN_DECLINE = "\u5148\u4e0a\u5347\u540e\u4e0b\u964d"
TREND_LATE_BURST = "\u540e\u671f\u7a81\u589e"
TREND_INTERMITTENT = "\u95f4\u6b47\u51fa\u73b0"

CORE_SKILL_ROLE = "core"
TREND_SKILL_ROLE = "trend"

SEMANTIC_CORE_SKILLS_BY_JOB = {
    "\u5927\u6a21\u578b\u5e94\u7528\u5de5\u7a0b\u5e08": {
        "Agent",
        "RAG",
        "LLM",
        "prompt\u5de5\u7a0b",
        "LangChain",
        "LangGraph",
        "Tool Use",
        "MCP",
        "\u5927\u6a21\u578b\u5e94\u7528",
    },
    "AI Agent\u5e94\u7528\u5de5\u7a0b\u5e08": {
        "Agent",
        "RAG",
        "LLM",
        "prompt\u5de5\u7a0b",
        "LangChain",
        "LangGraph",
        "Tool Use",
        "MCP",
        "AI\u5de5\u4f5c\u6d41\u8bbe\u8ba1",
    },
    "AI Agent\u7b97\u6cd5\u5de5\u7a0b\u5e08": {
        "Agent",
        "RAG",
        "LLM",
        "Tool Use",
        "\u77e5\u8bc6\u56fe\u8c31",
        "\u63a8\u7406\u4f18\u5316",
        "\u5927\u6a21\u578b\u8bad\u7ec3",
    },
    "\u591a\u6a21\u6001\u7b97\u6cd5\u5de5\u7a0b\u5e08": {
        "\u591a\u6a21\u6001",
        "VLM",
        "AIGC",
        "LLM",
        "NLP",
        "\u8ba1\u7b97\u673a\u89c6\u89c9",
        "\u56fe\u50cf\u56fe\u5f62\u6280\u672f",
        "Diffusion\u6a21\u578b",
    },
    "\u641c\u7d22\u7b97\u6cd5\u5de5\u7a0b\u5e08": {
        "\u641c\u7d22\u7b97\u6cd5",
        "\u4fe1\u606f\u68c0\u7d22",
        "RAG",
        "LLM",
        "NLP",
        "\u673a\u5668\u5b66\u4e60",
    },
}


@dataclass(frozen=True)
class SkillItem:
    standard_job: str
    standard_category: str
    skill: str
    kg_display_skill: str
    skill_stage: str
    source_row_count: int
    traditional_source_row_count: int
    new_source_row_count: int


def read_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


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
                kg_display_skill=(row.get("kg_display_skill") or "").strip(),
                skill_stage=(row.get("skill_stage") or "uncategorized").strip(),
                source_row_count=parse_int(row.get("source_row_count")),
                traditional_source_row_count=parse_int(
                    row.get("traditional_source_row_count")
                ),
                new_source_row_count=parse_int(row.get("new_source_row_count")),
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
    skills: list[SkillItem], planned_total: int, source_jd_count: int, rng: random.Random
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

    core_skills = choose_core_skills(skills, source_jd_count)
    selected: list[SkillItem] = list(core_skills)
    selected_keys = {skill.skill for skill in selected}
    target_traditional = max(
        0,
        target_traditional
        - sum(1 for skill in selected if normalize_stage(skill.skill_stage) == "traditional"),
    )
    target_new = max(
        0,
        target_new
        - sum(1 for skill in selected if normalize_stage(skill.skill_stage) == "new"),
    )
    traditional = [skill for skill in traditional if skill.skill not in selected_keys]
    emerging = [skill for skill in emerging if skill.skill not in selected_keys]
    selected.extend(weighted_sample_skills(traditional, target_traditional, rng))
    selected.extend(weighted_sample_skills(emerging, target_new, rng))

    if len(selected) < target_size:
        selected_keys = {skill.skill for skill in selected}
        remaining = [skill for skill in skills if skill.skill not in selected_keys]
        selected.extend(weighted_sample_skills(remaining, target_size - len(selected), rng))

    selected.sort(key=lambda item: (item.standard_job, normalize_stage(item.skill_stage), -item.source_row_count, item.skill))
    return selected


def enforce_prior_skill_selection(
    job: str,
    job_skills: list[SkillItem],
    selected_skills: list[SkillItem],
    industry_priors: dict[str, SkillMigrationPrior],
) -> list[SkillItem]:
    selected_by_skill = {skill.skill.casefold(): skill for skill in selected_skills}
    for skill in job_skills:
        prior = industry_priors.get(skill.skill.casefold())
        if prior is None or prior.stage_for_job(job) == "":
            continue
        selected_by_skill.setdefault(skill.skill.casefold(), skill)
    return sorted(
        selected_by_skill.values(),
        key=lambda item: (
            item.standard_job,
            normalize_stage(item.skill_stage),
            -item.source_row_count,
            item.skill,
        ),
    )


def choose_core_skills(skills: list[SkillItem], source_jd_count: int) -> list[SkillItem]:
    if not skills or source_jd_count <= 0:
        return []

    sorted_skills = sorted(skills, key=lambda item: (-item.source_row_count, item.skill))
    semantic_core = SEMANTIC_CORE_SKILLS_BY_JOB.get(sorted_skills[0].standard_job, set())
    core: list[SkillItem] = []
    seen: set[str] = set()

    for rank, skill in enumerate(sorted_skills, start=1):
        share = skill.source_row_count / max(source_jd_count, 1)
        is_statistical_core = (
            rank <= 8
            or skill.source_row_count >= 30
            or (skill.source_row_count >= 8 and share >= 0.08)
        )
        is_semantic_core = skill.skill in semantic_core and skill.source_row_count >= 2
        if not is_statistical_core and not is_semantic_core:
            continue
        if skill.skill in seen:
            continue
        seen.add(skill.skill)
        core.append(skill)
        if len(core) >= 18:
            break
    return core


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


def choose_skill_trend_for_role(
    skill: SkillItem,
    job_demand_trend: str,
    rng: random.Random,
    *,
    is_core: bool,
) -> str:
    stage = normalize_stage(skill.skill_stage)
    if is_core and stage == "new":
        weights = {
            TREND_STABLE: 2.0,
            TREND_RISING: 2.8,
            TREND_DECLINING: 0.15,
            TREND_RISE_THEN_STABLE: 3.0,
            TREND_RISE_THEN_DECLINE: 0.35,
            TREND_LATE_BURST: 1.0,
            TREND_INTERMITTENT: 0.05,
        }
    elif is_core:
        weights = {
            TREND_STABLE: 4.0,
            TREND_RISING: 1.2,
            TREND_DECLINING: 0.35,
            TREND_RISE_THEN_STABLE: 2.0,
            TREND_RISE_THEN_DECLINE: 0.45,
            TREND_LATE_BURST: 0.2,
            TREND_INTERMITTENT: 0.05,
        }
    elif stage == "new":
        weights = {
            TREND_STABLE: 1.2,
            TREND_RISING: 3.0,
            TREND_DECLINING: 0.6,
            TREND_RISE_THEN_STABLE: 2.4,
            TREND_RISE_THEN_DECLINE: 1.3,
            TREND_LATE_BURST: 2.4,
            TREND_INTERMITTENT: 1.0,
        }
    else:
        weights = {
            TREND_STABLE: 3.2,
            TREND_RISING: 0.9,
            TREND_DECLINING: 1.6,
            TREND_RISE_THEN_STABLE: 1.1,
            TREND_RISE_THEN_DECLINE: 0.8,
            TREND_LATE_BURST: 0.25,
            TREND_INTERMITTENT: 0.8,
        }

    if job_demand_trend in {"\u95f4\u6b47\u51fa\u73b0", "\u6d88\u5931\u540e\u518d\u51fa\u73b0"}:
        weights[TREND_INTERMITTENT] += 0.2 if is_core else 1.0
    if job_demand_trend == TREND_RISING:
        weights[TREND_RISING] += 0.9
        weights[TREND_RISE_THEN_STABLE] += 0.5
    if job_demand_trend == TREND_DECLINING:
        weights[TREND_DECLINING] += 0.25 if is_core else 0.9

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


def strengthen_core_probabilities(
    probabilities: list[float],
    *,
    source_skill_row_count: int,
    source_jd_count: int,
    monthly_plan: dict[str, int],
    months: list[str],
) -> list[float]:
    if source_jd_count <= 0:
        return probabilities

    source_share = source_skill_row_count / source_jd_count
    minimum = 0.34 + min(source_share * 0.85, 0.28)
    if source_skill_row_count >= 100:
        minimum = max(minimum, 0.56)
    elif source_skill_row_count >= 30:
        minimum = max(minimum, 0.46)
    else:
        minimum = max(minimum, 0.38)
    minimum = min(minimum, 0.72)

    strengthened: list[float] = []
    for month, probability in zip(months, probabilities):
        if monthly_plan.get(month, 0) <= 0:
            strengthened.append(0.0)
        else:
            strengthened.append(round(max(probability, minimum), 4))
    return strengthened


def apply_industry_prior_schedule(
    probabilities: list[float],
    *,
    job: str,
    prior: SkillMigrationPrior,
    months: list[str],
    monthly_plan: dict[str, int],
) -> list[float]:
    stage = prior.stage_for_job(job)
    first_active_month = activation_month(prior, job)
    minimum = stage_min_probability(stage)
    if not first_active_month or minimum <= 0:
        return [0.0 for _ in probabilities]

    scheduled: list[float] = []
    for month, probability in zip(months, probabilities):
        if monthly_plan.get(month, 0) <= 0 or month < first_active_month:
            scheduled.append(0.0)
            continue
        months_after_activation = _month_distance(first_active_month, month)
        ramp = min(1.0, 0.65 + months_after_activation * 0.08)
        floor = minimum * ramp
        scheduled.append(round(max(probability, floor), 4))
    return scheduled


def choose_prior_trend(stage: str) -> str:
    if stage in {"origin", "early"}:
        return TREND_RISE_THEN_STABLE
    if stage == "mid":
        return TREND_RISING
    if stage == "late":
        return TREND_LATE_BURST
    return TREND_RISING


def _month_distance(start_month: str, end_month: str) -> int:
    start_year, start_month_index = [int(part) for part in start_month.split("-")]
    end_year, end_month_index = [int(part) for part in end_month.split("-")]
    return (end_year * 12 + end_month_index) - (start_year * 12 + start_month_index)


def generate_skill_plan(run_dir: Path) -> tuple[list[dict], list[dict], dict]:
    config = read_config()
    rng = random.Random(config["seed"] + 3)
    months = month_sequence(config["month_start"], config["month_end"])
    skills_by_job = load_skill_pool(run_dir)
    monthly_plan, trend_by_job = load_job_plan(run_dir)
    industry_priors = load_industry_priors(
        resolve_project_path(config["skill_industry_migration_prior_file"])
    )

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
        selected_skills = choose_skill_subset(job_skills, total_planned, source_jd_count, rng)
        selected_skills = enforce_prior_skill_selection(
            job,
            job_skills,
            selected_skills,
            industry_priors,
        )
        selected_skill_count_by_job[job] = len(selected_skills)
        job_demand_trend = (trend_info.get("demand_trend_type") or "").strip()
        core_skill_keys = {
            skill.skill for skill in choose_core_skills(job_skills, source_jd_count)
        }

        for skill_item in selected_skills:
            skill_stage = normalize_stage(skill_item.skill_stage)
            prior = industry_priors.get(skill_item.skill.casefold())
            prior_stage = prior.stage_for_job(job) if prior is not None else ""
            role = CORE_SKILL_ROLE if skill_item.skill in core_skill_keys else TREND_SKILL_ROLE
            if prior_stage:
                skill_trend = choose_prior_trend(prior_stage)
            else:
                skill_trend = choose_skill_trend_for_role(
                    skill_item,
                    job_demand_trend,
                    rng,
                    is_core=role == CORE_SKILL_ROLE,
                )
            probabilities = probability_curve(
                skill_trend,
                skill_stage,
                skill_item.source_row_count,
                len(months),
                rng,
            )
            if role == CORE_SKILL_ROLE:
                probabilities = strengthen_core_probabilities(
                    probabilities,
                    source_skill_row_count=skill_item.source_row_count,
                    source_jd_count=source_jd_count,
                    monthly_plan=monthly_plan[job],
                    months=months,
                )
            if prior is not None:
                probabilities = apply_industry_prior_schedule(
                    probabilities,
                    job=job,
                    prior=prior,
                    months=months,
                    monthly_plan=monthly_plan[job],
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
                    "kg_display_skill": skill_item.kg_display_skill,
                    "skill_stage": skill_stage,
                    "skill_plan_role": role,
                    "skill_trend_type": skill_trend,
                    "job_demand_trend_type": job_demand_trend,
                    "source_jd_count": source_jd_count,
                    "source_skill_row_count": skill_item.source_row_count,
                    "planned_job_jd_count": total_planned,
                    "average_active_month_probability": average_probability,
                    "max_active_month_probability": max_probability,
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
                        "kg_display_skill": skill_item.kg_display_skill,
                        "skill_stage": skill_stage,
                        "skill_plan_role": role,
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
        "industry_prior_skill_count": len(industry_priors),
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
            "kg_display_skill",
            "skill_stage",
            "skill_plan_role",
            "skill_trend_type",
            "job_demand_trend_type",
            "source_jd_count",
            "source_skill_row_count",
            "planned_job_jd_count",
            "average_active_month_probability",
            "max_active_month_probability",
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
            "kg_display_skill",
            "skill_stage",
            "skill_plan_role",
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

