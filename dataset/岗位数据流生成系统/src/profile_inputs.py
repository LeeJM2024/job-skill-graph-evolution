"""Profile input data for the job event stream generator.

Step 1 reads source files, normalizes skill names with the supplied skill
dictionary, and builds per-job skill pools. It does not generate synthetic
events or trend plans.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from industry_migration_prior import (
    SkillMigrationPrior,
    load_industry_priors,
    stage_min_source_count,
)
from run_context import relative_to_project, start_new_run
from source_relabeling import build_standard_job_rules, relabel_standard_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"

SKILL_SPLIT_RE = re.compile(r"[;；\n\r、,，]+")


@dataclass(frozen=True)
class SkillDictionaryItem:
    normalized_skill: str
    kg_display_skill: str
    skill_stage: str


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


def clean_stage(value: str | None) -> str:
    text = (value or "").strip()
    if text == "新兴技能":
        return "new"
    if text == "传统技能":
        return "traditional"
    if text in {"new", "traditional", "both", "uncategorized"}:
        return text
    return ""


def load_skill_dictionary(rows: list[dict[str, str]]) -> tuple[dict[str, SkillDictionaryItem], dict[str, SkillDictionaryItem]]:
    by_keyword: dict[str, SkillDictionaryItem] = {}
    by_normalized: dict[str, SkillDictionaryItem] = {}

    for row in rows:
        keyword = (row.get("skill_keyword") or "").strip()
        normalized = (row.get("normalized_skill") or "").strip()
        display = (row.get("kg_display_skill") or "").strip()
        stage = clean_stage(row.get("技能类型"))
        if not normalized:
            continue
        item = SkillDictionaryItem(
            normalized_skill=normalized,
            kg_display_skill=display,
            skill_stage=stage,
        )
        by_normalized.setdefault(normalized.casefold(), item)
        if keyword:
            by_keyword.setdefault(keyword.casefold(), item)
        by_keyword.setdefault(normalized.casefold(), item)

    return by_keyword, by_normalized


def normalize_skill(
    skill: str,
    dictionary_by_keyword: dict[str, SkillDictionaryItem],
    dictionary_by_normalized: dict[str, SkillDictionaryItem],
) -> SkillDictionaryItem:
    text = (skill or "").strip()
    if not text:
        return SkillDictionaryItem("", "", "")
    item = dictionary_by_keyword.get(text.casefold()) or dictionary_by_normalized.get(text.casefold())
    if item is not None:
        return item
    return SkillDictionaryItem(text, "", "")


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
    skill_dictionary_path = resolve_project_path(config["skill_dictionary_file"])
    industry_prior_path = resolve_project_path(config["skill_industry_migration_prior_file"])

    standard_rows = read_csv_dicts(standard_path)
    source_rows = read_csv_dicts(source_path)
    skill_dictionary_rows = read_csv_dicts(skill_dictionary_path)
    industry_priors = load_industry_priors(industry_prior_path)
    dictionary_by_keyword, dictionary_by_normalized = load_skill_dictionary(skill_dictionary_rows)
    standard_job_rules = build_standard_job_rules(standard_rows)

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

    jd_count_by_job: Counter[str] = Counter()
    row_with_skills_by_job: Counter[str] = Counter()
    job_title_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    skill_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    traditional_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    new_counter_by_job: dict[str, Counter[str]] = defaultdict(Counter)
    dictionary_stage_by_skill: dict[str, str] = {}
    display_by_skill: dict[str, str] = {}

    rows_outside_dictionary = 0
    rows_without_standard_job = 0
    rows_without_skills = 0
    raw_skill_mentions = 0
    normalized_skill_mentions = 0
    unmapped_skill_mentions = 0
    unmapped_skill_counter: Counter[str] = Counter()
    relabeled_standard_job_counter: Counter[tuple[str, str]] = Counter()

    def normalize_and_record(raw_skill: str) -> SkillDictionaryItem:
        nonlocal raw_skill_mentions, normalized_skill_mentions, unmapped_skill_mentions
        raw_skill_mentions += 1
        item = normalize_skill(raw_skill, dictionary_by_keyword, dictionary_by_normalized)
        if item.kg_display_skill:
            normalized_skill_mentions += 1
        else:
            unmapped_skill_mentions += 1
            unmapped_skill_counter[raw_skill] += 1
        if item.normalized_skill:
            if item.kg_display_skill:
                display_by_skill.setdefault(item.normalized_skill, item.kg_display_skill)
            if item.skill_stage:
                dictionary_stage_by_skill.setdefault(item.normalized_skill, item.skill_stage)
        return item

    for row in source_rows:
        original_standard_job = (row.get("standard_job") or "").strip()
        standard_job = relabel_standard_job(row, original_standard_job, standard_job_rules)
        if not standard_job:
            rows_without_standard_job += 1
            continue
        if standard_job != original_standard_job:
            relabeled_standard_job_counter[(original_standard_job, standard_job)] += 1
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

        for raw_skill in row_skills:
            item = normalize_and_record(raw_skill)
            if item.normalized_skill and item.kg_display_skill:
                skill_counter_by_job[standard_job][item.normalized_skill] += 1
        for raw_skill in row_traditional_skills:
            item = normalize_and_record(raw_skill)
            if item.normalized_skill and item.kg_display_skill:
                traditional_counter_by_job[standard_job][item.normalized_skill] += 1
                skill_counter_by_job[standard_job][item.normalized_skill] += 0
        for raw_skill in row_new_skills:
            item = normalize_and_record(raw_skill)
            if item.normalized_skill and item.kg_display_skill:
                new_counter_by_job[standard_job][item.normalized_skill] += 1
                skill_counter_by_job[standard_job][item.normalized_skill] += 0

    prior_adjustment_report = apply_industry_migration_priors(
        industry_priors=industry_priors,
        allowed_jobs=allowed_jobs,
        skill_counter_by_job=skill_counter_by_job,
        traditional_counter_by_job=traditional_counter_by_job,
        new_counter_by_job=new_counter_by_job,
        dictionary_stage_by_skill=dictionary_stage_by_skill,
        display_by_skill=display_by_skill,
    )

    input_profile_rows: list[dict] = []
    skill_pool_rows: list[dict] = []

    for job in standard_jobs:
        all_skills = set(skill_counter_by_job[job])
        traditional_skills = set(traditional_counter_by_job[job])
        new_skills = set(new_counter_by_job[job])
        dictionary_new_skills = {
            skill for skill in all_skills if dictionary_stage_by_skill.get(skill) == "new"
        }
        dictionary_traditional_skills = {
            skill for skill in all_skills if dictionary_stage_by_skill.get(skill) == "traditional"
        }
        staged_skills = traditional_skills | new_skills | dictionary_new_skills | dictionary_traditional_skills
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
                "traditional_skill_count": len(dictionary_traditional_skills | traditional_skills),
                "new_skill_count": len(dictionary_new_skills | new_skills),
                "dictionary_new_skill_count": len(dictionary_new_skills),
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
            dictionary_stage = dictionary_stage_by_skill.get(skill, "")
            if dictionary_stage:
                stage = dictionary_stage
            elif in_traditional and in_new:
                stage = "both"
            elif in_new:
                stage = "new"
            elif in_traditional:
                stage = "traditional"
            else:
                stage = "uncategorized"

            skill_pool_rows.append(
                {
                    "standard_job": job,
                    "standard_category": standard_categories.get(job, ""),
                    "skill": skill,
                    "kg_display_skill": display_by_skill.get(skill, ""),
                    "skill_stage": stage,
                    "source_row_count": count,
                    "traditional_source_row_count": in_traditional,
                    "new_source_row_count": in_new,
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
        "skill_dictionary_keyword_count": len(dictionary_by_keyword),
        "skill_dictionary_normalized_count": len(dictionary_by_normalized),
        "dictionary_new_skill_count": sum(
            1 for item in dictionary_by_normalized.values() if item.skill_stage == "new"
        ),
        "raw_skill_mentions": raw_skill_mentions,
        "normalized_skill_mentions": normalized_skill_mentions,
        "ignored_unmapped_skill_mentions": unmapped_skill_mentions,
        "ignored_unmapped_skill_coverage": round(
            unmapped_skill_mentions / raw_skill_mentions, 6
        )
        if raw_skill_mentions
        else 0.0,
        "top_unmapped_skills": [
            {"skill": skill, "count": count}
            for skill, count in unmapped_skill_counter.most_common(20)
        ],
        "relabeled_standard_job_rows": sum(relabeled_standard_job_counter.values()),
        "relabeled_standard_job_pairs": [
            {"from": source, "to": target, "count": count}
            for (source, target), count in relabeled_standard_job_counter.most_common()
        ],
        "industry_prior_skill_count": len(industry_priors),
        "industry_prior_adjustment": prior_adjustment_report,
    }

    return input_profile_rows, skill_pool_rows, quality_report


def apply_industry_migration_priors(
    *,
    industry_priors: dict[str, SkillMigrationPrior],
    allowed_jobs: set[str],
    skill_counter_by_job: dict[str, Counter[str]],
    traditional_counter_by_job: dict[str, Counter[str]],
    new_counter_by_job: dict[str, Counter[str]],
    dictionary_stage_by_skill: dict[str, str],
    display_by_skill: dict[str, str],
) -> dict[str, int]:
    removed_pairs = 0
    injected_pairs = 0
    boosted_pairs = 0

    for prior in industry_priors.values():
        missing_jobs = sorted(job for job in prior.all_jobs if job not in allowed_jobs)
        if missing_jobs:
            raise ValueError(
                f"Industry migration prior references jobs outside the standard dictionary: "
                f"skill={prior.skill}, jobs={'; '.join(missing_jobs)}"
            )

        allowed_prior_jobs = set(prior.all_jobs)
        dictionary_stage_by_skill[prior.skill] = prior.skill_type or "new"
        display_by_skill[prior.skill] = prior.kg_display_skill

        for job in list(skill_counter_by_job):
            if job in allowed_prior_jobs:
                continue
            if prior.skill in skill_counter_by_job[job]:
                del skill_counter_by_job[job][prior.skill]
                removed_pairs += 1
            traditional_counter_by_job[job].pop(prior.skill, None)
            new_counter_by_job[job].pop(prior.skill, None)

        for job in prior.all_jobs:
            stage = prior.stage_for_job(job)
            minimum = stage_min_source_count(stage)
            if minimum <= 0:
                continue
            old_count = skill_counter_by_job[job][prior.skill]
            if old_count <= 0:
                injected_pairs += 1
            elif old_count < minimum:
                boosted_pairs += 1
            skill_counter_by_job[job][prior.skill] = max(old_count, minimum)
            new_counter_by_job[job][prior.skill] = max(new_counter_by_job[job][prior.skill], minimum)
            traditional_counter_by_job[job].pop(prior.skill, None)

    return {
        "removed_unrealistic_job_skill_pairs": removed_pairs,
        "injected_missing_prior_pairs": injected_pairs,
        "boosted_prior_pairs": boosted_pairs,
    }


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
            "kg_display_skill",
            "skill_stage",
            "source_row_count",
            "traditional_source_row_count",
            "new_source_row_count",
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
