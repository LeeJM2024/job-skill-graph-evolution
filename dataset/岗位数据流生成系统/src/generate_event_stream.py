"""Generate monthly JD event stream.

Step 4 creates concrete JD rows from the demand plan, source JD text, and
skill probability plan. The final event stream intentionally excludes
traditional/new skill helper fields.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from run_context import get_current_run_dir, relative_to_project


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"


@dataclass(frozen=True)
class SourceJD:
    job_title: str
    standard_job: str
    job_responsibility: str
    job_requirement: str
    source_job_id: str


@dataclass(frozen=True)
class SkillProbability:
    skill: str
    skill_stage: str
    skill_trend_type: str
    probability: float


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


def parse_float(value: str | float | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compact_text(value: str | None) -> str:
    if not value:
        return ""
    lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def load_source_jds(source_path: Path) -> dict[str, list[SourceJD]]:
    rows = read_csv_dicts(source_path)
    source_by_job: dict[str, list[SourceJD]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()

    for row in rows:
        standard_job = (row.get("standard_job") or "").strip()
        title = (row.get("job_title") or "").strip()
        responsibility = compact_text(row.get("job_responsibility"))
        requirement = compact_text(row.get("job_requirement"))
        if not standard_job or not title or not responsibility or not requirement:
            continue

        key = (standard_job, title, responsibility[:220], requirement[:220])
        if key in seen:
            continue
        seen.add(key)
        source_by_job[standard_job].append(
            SourceJD(
                job_title=title,
                standard_job=standard_job,
                job_responsibility=responsibility,
                job_requirement=requirement,
                source_job_id=(row.get("job_id") or "").strip(),
            )
        )
    return source_by_job


def load_demand_plan(run_dir: Path) -> list[dict[str, str]]:
    return read_csv_dicts(run_dir / "job_demand_monthly_plan.csv")


def load_skill_probability_plan(
    run_dir: Path,
) -> dict[tuple[str, str], list[SkillProbability]]:
    rows = read_csv_dicts(run_dir / "skill_monthly_probability_plan.csv")
    probability_by_job_month: dict[tuple[str, str], list[SkillProbability]] = defaultdict(list)
    for row in rows:
        planned_jd_count = parse_int(row.get("planned_jd_count"))
        probability = parse_float(row.get("skill_probability"))
        if planned_jd_count <= 0 or probability <= 0:
            continue
        job = (row.get("standard_job") or "").strip()
        month = (row.get("month") or "").strip()
        skill = (row.get("skill") or "").strip()
        if not job or not month or not skill:
            continue
        probability_by_job_month[(job, month)].append(
            SkillProbability(
                skill=skill,
                skill_stage=(row.get("skill_stage") or "").strip(),
                skill_trend_type=(row.get("skill_trend_type") or "").strip(),
                probability=probability,
            )
        )
    return probability_by_job_month


def load_allowed_job_skills(run_dir: Path) -> set[tuple[str, str]]:
    rows = read_csv_dicts(run_dir / "skill_trend_design.csv")
    return {
        ((row.get("standard_job") or "").strip(), (row.get("skill") or "").strip())
        for row in rows
        if (row.get("standard_job") or "").strip()
        and (row.get("skill") or "").strip()
    }


def weighted_sample_without_replacement(
    items: list[SkillProbability], count: int, rng: random.Random
) -> list[SkillProbability]:
    if count <= 0 or not items:
        return []
    count = min(count, len(items))
    selected: list[SkillProbability] = []
    remaining = list(items)
    for _ in range(count):
        weights = [max(item.probability, 0.0001) for item in remaining]
        picked = rng.choices(remaining, weights=weights, k=1)[0]
        selected.append(picked)
        remaining.remove(picked)
    return selected


def target_skill_count(pool_size: int, rng: random.Random) -> int:
    if pool_size <= 0:
        return 0
    lower = min(4, pool_size)
    upper = min(10, pool_size)
    if lower >= upper:
        return lower
    # Center most JDs around 6-8 skills while allowing moderate variation.
    value = int(round(rng.triangular(lower, upper, 7)))
    return max(lower, min(upper, value))


def choose_skills(
    skill_probabilities: list[SkillProbability], rng: random.Random
) -> list[str]:
    if not skill_probabilities:
        return []

    target_count = target_skill_count(len(skill_probabilities), rng)
    chosen = [
        item
        for item in skill_probabilities
        if rng.random() < min(max(item.probability, 0.0), 1.0)
    ]

    if len(chosen) > target_count:
        chosen = weighted_sample_without_replacement(chosen, target_count, rng)
    elif len(chosen) < target_count:
        chosen_keys = {item.skill for item in chosen}
        remaining = [
            item for item in skill_probabilities if item.skill not in chosen_keys
        ]
        chosen.extend(
            weighted_sample_without_replacement(
                remaining, target_count - len(chosen), rng
            )
        )

    chosen.sort(key=lambda item: (-item.probability, item.skill))
    return [item.skill for item in chosen]


def sentence_contains_any_skill(text: str, skills: list[str]) -> bool:
    lowered = text.lower()
    return any(skill.lower() in lowered for skill in skills if skill)


def lightly_adapt_jd_text(
    responsibility: str, requirement: str, skills: list[str], rng: random.Random
) -> tuple[str, str, str]:
    """Apply small deterministic variants so reused JD text can reflect skills."""
    if not skills:
        return responsibility, requirement, "none"

    focus_skills = skills[: min(3, len(skills))]
    focus_text = "、".join(focus_skills)
    adaptation = "none"

    new_responsibility = responsibility
    new_requirement = requirement

    if rng.random() < 0.35 and not sentence_contains_any_skill(
        responsibility, focus_skills[:2]
    ):
        new_responsibility = (
            responsibility
            + f"\n补充职责：结合业务场景推进{focus_text}相关能力建设与落地。"
        )
        adaptation = "responsibility_skill_hint"

    if rng.random() < 0.45 and not sentence_contains_any_skill(requirement, focus_skills[:2]):
        new_requirement = (
            requirement
            + f"\n补充要求：具备{focus_text}相关实践经验者优先。"
        )
        if adaptation == "none":
            adaptation = "requirement_skill_hint"
        else:
            adaptation += "+requirement_skill_hint"

    return new_responsibility, new_requirement, adaptation


def source_jd_sample(
    source_jds: list[SourceJD], usage_counter: Counter[int], rng: random.Random
) -> tuple[SourceJD, int]:
    if not source_jds:
        raise ValueError("Cannot sample from an empty source JD list.")

    # Prefer less-used source rows, but keep randomness for text variety.
    weights = [1 / (1 + usage_counter[idx]) for idx in range(len(source_jds))]
    picked_idx = rng.choices(range(len(source_jds)), weights=weights, k=1)[0]
    usage_counter[picked_idx] += 1
    return source_jds[picked_idx], picked_idx


def generate_event_stream(run_dir: Path) -> tuple[list[dict], dict]:
    config = read_config()
    rng = random.Random(config["seed"] + 4)
    source_path = resolve_project_path(config["source_job_file"])
    output_path = run_dir / Path(config["output_event_stream_file"]).name

    source_by_job = load_source_jds(source_path)
    demand_rows = load_demand_plan(run_dir)
    skill_probability_by_job_month = load_skill_probability_plan(run_dir)
    allowed_job_skills = load_allowed_job_skills(run_dir)

    event_rows: list[dict] = []
    source_usage_by_job: dict[str, Counter[int]] = defaultdict(Counter)
    missing_source_jobs: set[str] = set()
    missing_skill_plan_job_months: set[tuple[str, str]] = set()
    invalid_skill_pairs: set[tuple[str, str]] = set()
    adaptation_counter: Counter[str] = Counter()
    skill_count_counter: Counter[int] = Counter()

    event_index = 1
    for demand in demand_rows:
        job = (demand.get("standard_job") or "").strip()
        month = (demand.get("month") or "").strip()
        planned_count = parse_int(demand.get("planned_jd_count"))
        if planned_count <= 0:
            continue

        source_jds = source_by_job.get(job, [])
        if not source_jds:
            missing_source_jobs.add(job)
            continue

        skill_probabilities = skill_probability_by_job_month.get((job, month), [])
        if not skill_probabilities:
            missing_skill_plan_job_months.add((job, month))

        for _ in range(planned_count):
            source_jd, _source_idx = source_jd_sample(
                source_jds, source_usage_by_job[job], rng
            )
            skills = choose_skills(skill_probabilities, rng)
            for skill in skills:
                if (job, skill) not in allowed_job_skills:
                    invalid_skill_pairs.add((job, skill))

            responsibility, requirement, adaptation = lightly_adapt_jd_text(
                source_jd.job_responsibility,
                source_jd.job_requirement,
                skills,
                rng,
            )
            adaptation_counter[adaptation] += 1
            skill_count_counter[len(skills)] += 1

            event_rows.append(
                {
                    "job_id": f"GEN{event_index:06d}",
                    "month": month,
                    "standard_job": job,
                    "job_title": source_jd.job_title,
                    "job_responsibility": responsibility,
                    "job_requirement": requirement,
                    "skills": "; ".join(skills),
                }
            )
            event_index += 1

    quality_report = {
        "config_seed": config["seed"],
        "event_stream_seed": config["seed"] + 4,
        "run_dir": relative_to_project(PROJECT_ROOT, run_dir),
        "output_event_stream_file": relative_to_project(PROJECT_ROOT, output_path),
        "generated_event_rows": len(event_rows),
        "unique_generated_jobs": len({row["standard_job"] for row in event_rows}),
        "unique_generated_months": len({row["month"] for row in event_rows}),
        "missing_source_jobs": sorted(missing_source_jobs),
        "missing_skill_plan_job_month_count": len(missing_skill_plan_job_months),
        "invalid_skill_pair_count": len(invalid_skill_pairs),
        "min_skills_per_jd": min(skill_count_counter) if skill_count_counter else 0,
        "max_skills_per_jd": max(skill_count_counter) if skill_count_counter else 0,
        "skill_count_distribution": {
            str(count): skill_count_counter[count]
            for count in sorted(skill_count_counter)
        },
        "text_adaptation_distribution": dict(sorted(adaptation_counter.items())),
        "excluded_fields": config.get("excluded_event_stream_fields", []),
    }
    return event_rows, quality_report


def main() -> None:
    config = read_config()
    run_dir = get_current_run_dir(PROJECT_ROOT)
    output_path = run_dir / Path(config["output_event_stream_file"]).name
    event_fields = config["event_stream_fields"]

    event_rows, quality_report = generate_event_stream(run_dir)
    write_csv(output_path, event_fields, event_rows)

    with (run_dir / "event_stream_quality_report.json").open("w", encoding="utf-8") as f:
        json.dump(quality_report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(quality_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

