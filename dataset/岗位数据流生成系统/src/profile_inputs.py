"""Profile input data for the job event stream generator.

Step 1 only reads and validates source files. It does not generate synthetic
events or trend plans.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from run_context import relative_to_project, start_new_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"

SKILL_SPLIT_RE = re.compile(r"[;；\n\r、,，]+")


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


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_skills(value: str | None) -> list[str]:
    if not value:
        return []
    skills: list[str] = []
    seen: set[str] = set()
    for part in SKILL_SPLIT_RE.split(value):
        skill = part.strip()
        if not skill or skill in seen:
            continue
        seen.add(skill)
        skills.append(skill)
    return skills


def joined_sample(values: Iterable[str], limit: int = 5) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return " | ".join(cleaned)


def build_profile() -> tuple[list[dict], list[dict], dict]:
    config = read_config()
    standard_path = resolve_project_path(config["standard_job_file"])
    source_path = resolve_project_path(config["source_job_file"])
    new_skill_path = resolve_project_path(config["new_skill_file"])

    standard_rows = read_csv_dicts(standard_path)
    source_rows = read_csv_dicts(source_path)
    new_skill_rows = read_csv_dicts(new_skill_path)

    standard_jobs: list[str] = []
    standard_categories: dict[str, str] = {}
    duplicate_standard_jobs: list[str] = []
    seen_standard_jobs: set[str] = set()

    for row in standard_rows:
        job = (row.get("standard_job_title") or "").strip()
        if not job:
            continue
        if job in seen_standard_jobs:
            duplicate_standard_jobs.append(job)
            continue
        seen_standard_jobs.add(job)
        standard_jobs.append(job)
        standard_categories[job] = (row.get("standard_category") or "").strip()

    allowed_jobs = set(standard_jobs)
    new_skill_dictionary = {
        (row.get("new_skill") or "").strip()
        for row in new_skill_rows
        if (row.get("new_skill") or "").strip()
    }

    jd_count_by_job: Counter[str] = Counter()
    row_with_skills_by_job: Counter[str] = Counter()
    job_title_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    skill_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    traditional_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    new_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)

    rows_outside_dictionary = 0
    rows_without_standard_job = 0
    rows_without_skills = 0

    for row in source_rows:
        standard_job = (row.get("standard_job") or "").strip()
        if not standard_job:
            rows_without_standard_job += 1
            continue
        if standard_job not in allowed_jobs:
            rows_outside_dictionary += 1
            continue

        jd_count_by_job[standard_job] += 1
        title = (row.get("job_title") or "").strip()
        if title:
            job_title_by_job[standard_job][title] += 1

        row_skills = split_skills(row.get("skills"))
        row_traditional_skills = split_skills(row.get("traditional_skills"))
        row_new_skills = split_skills(row.get("new_skills"))

        if row_skills or row_traditional_skills or row_new_skills:
            row_with_skills_by_job[standard_job] += 1
        else:
            rows_without_skills += 1

        for skill in row_skills:
            skill_counter_by_job[standard_job][skill] += 1
        for skill in row_traditional_skills:
            traditional_counter_by_job[standard_job][skill] += 1
            skill_counter_by_job[standard_job][skill] += 0
        for skill in row_new_skills:
            new_counter_by_job[standard_job][skill] += 1
            skill_counter_by_job[standard_job][skill] += 0

    input_profile_rows: list[dict] = []
    skill_pool_rows: list[dict] = []

    for job in standard_jobs:
        all_skills = set(skill_counter_by_job[job])
        traditional_skills = set(traditional_counter_by_job[job])
        new_skills = set(new_counter_by_job[job])
        staged_skills = traditional_skills | new_skills
        overlap_skills = traditional_skills & new_skills
        unstaged_skills = all_skills - staged_skills

        jd_count = jd_count_by_job[job]
        rows_with_skills = row_with_skills_by_job[job]
        rows_without_job_skills = max(jd_count - rows_with_skills, 0)

        notes: list[str] = []
        if jd_count == 0:
            notes.append("无可用真实JD样本")
        elif jd_count < 10:
            notes.append("真实JD样本较少")
        if not all_skills:
            notes.append("无技能池")
        elif len(all_skills) < 5:
            notes.append("技能池较小")
        if unstaged_skills:
            notes.append("存在未分阶段技能")
        if overlap_skills:
            notes.append("存在传统/新兴重复归类技能")

        input_profile_rows.append(
            {
                "standard_job": job,
                "standard_category": standard_categories.get(job, ""),
                "source_jd_count": jd_count,
                "unique_job_title_count": len(job_title_by_job[job]),
                "unique_skill_count": len(all_skills),
                "traditional_skill_count": len(traditional_skills),
                "new_skill_count": len(new_skills),
                "dictionary_new_skill_count": len(all_skills & new_skill_dictionary),
                "overlap_skill_stage_count": len(overlap_skills),
                "skills_without_stage_count": len(unstaged_skills),
                "source_rows_with_skills": rows_with_skills,
                "source_rows_without_skills": rows_without_job_skills,
                "sample_job_titles": joined_sample(job_title_by_job[job].keys()),
                "sample_skills": joined_sample(
                    skill for skill, _count in skill_counter_by_job[job].most_common(8)
                ),
                "notes": "；".join(notes),
            }
        )

        for skill, count in sorted(
            skill_counter_by_job[job].items(), key=lambda item: (-item[1], item[0])
        ):
            in_traditional = traditional_counter_by_job[job][skill]
            in_new = new_counter_by_job[job][skill]
            if in_traditional and in_new:
                stage = "both"
            elif in_new:
                stage = "new"
            elif in_traditional:
                stage = "traditional"
            elif skill in new_skill_dictionary:
                stage = "new_dictionary_only"
            else:
                stage = "uncategorized"

            skill_pool_rows.append(
                {
                    "standard_job": job,
                    "standard_category": standard_categories.get(job, ""),
                    "skill": skill,
                    "skill_stage": stage,
                    "source_row_count": count,
                    "traditional_source_row_count": in_traditional,
                    "new_source_row_count": in_new,
                    "in_new_skill_dictionary": "yes"
                    if skill in new_skill_dictionary
                    else "no",
                }
            )

    quality_report = {
        "standard_job_count": len(standard_jobs),
        "duplicate_standard_jobs": duplicate_standard_jobs,
        "source_row_count": len(source_rows),
        "source_rows_used": sum(jd_count_by_job.values()),
        "source_rows_without_standard_job": rows_without_standard_job,
        "source_rows_outside_standard_dictionary": rows_outside_dictionary,
        "source_rows_without_any_skill": rows_without_skills,
        "jobs_with_source_jd": sum(1 for job in standard_jobs if jd_count_by_job[job] > 0),
        "jobs_without_source_jd": [
            job for job in standard_jobs if jd_count_by_job[job] == 0
        ],
        "jobs_with_skill_pool": sum(
            1 for job in standard_jobs if len(skill_counter_by_job[job]) > 0
        ),
        "jobs_without_skill_pool": [
            job for job in standard_jobs if len(skill_counter_by_job[job]) == 0
        ],
        "total_job_skill_pairs": len(skill_pool_rows),
        "unique_skills_across_jobs": len(
            {row["skill"] for row in skill_pool_rows if row.get("skill")}
        ),
        "new_skill_dictionary_count": len(new_skill_dictionary),
    }

    return input_profile_rows, skill_pool_rows, quality_report


def main() -> None:
    config = read_config()
    output_dir = start_new_run(PROJECT_ROOT, config)

    input_profile_rows, skill_pool_rows, quality_report = build_profile()

    write_csv(
        output_dir / "input_profile.csv",
        [
            "standard_job",
            "standard_category",
            "source_jd_count",
            "unique_job_title_count",
            "unique_skill_count",
            "traditional_skill_count",
            "new_skill_count",
            "dictionary_new_skill_count",
            "overlap_skill_stage_count",
            "skills_without_stage_count",
            "source_rows_with_skills",
            "source_rows_without_skills",
            "sample_job_titles",
            "sample_skills",
            "notes",
        ],
        input_profile_rows,
    )
    write_csv(
        output_dir / "skill_pool_by_job.csv",
        [
            "standard_job",
            "standard_category",
            "skill",
            "skill_stage",
            "source_row_count",
            "traditional_source_row_count",
            "new_source_row_count",
            "in_new_skill_dictionary",
        ],
        skill_pool_rows,
    )

    quality_report["config_seed"] = config.get("seed")
    quality_report["run_dir"] = relative_to_project(PROJECT_ROOT, output_dir)
    quality_report_path = output_dir / "input_quality_report.json"
    with quality_report_path.open("w", encoding="utf-8") as f:
        json.dump(quality_report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(quality_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

