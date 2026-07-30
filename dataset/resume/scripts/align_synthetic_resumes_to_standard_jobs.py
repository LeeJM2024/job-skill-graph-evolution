from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


RESUME_DIR = Path(__file__).resolve().parents[1]
DATASET_DIR = RESUME_DIR.parent
BASE_DATA_DIR = DATASET_DIR / "job_update" / "data" / "base"
DEFAULT_RESUMES = RESUME_DIR / "synthetic_detailed_resumes.csv"
DEFAULT_STANDARD_JOBS = BASE_DATA_DIR / "standard_job_title_dictionary.csv"
DEFAULT_FREQUENCY = BASE_DATA_DIR / "job_skill_monthly_frequency.csv"
DEFAULT_SKILL_POOL = BASE_DATA_DIR / "skill_pool.csv"
DEFAULT_OUTPUT_CSV = RESUME_DIR / "synthetic_detailed_resumes_aligned.csv"
DEFAULT_OUTPUT_JSONL = RESUME_DIR / "synthetic_detailed_resumes_aligned.jsonl"
DEFAULT_REPORT = RESUME_DIR / "synthetic_detailed_resumes_aligned_report.json"


FAMILY_TO_STANDARD_JOBS = {
    "算法工程师": [
        "大模型算法工程师",
        "AI Agent算法工程师",
        "AIGC算法工程师",
        "多模态算法工程师",
        "NLP算法工程师",
        "计算机视觉算法工程师",
        "语音算法工程师",
        "推荐算法工程师",
        "搜索算法工程师",
        "广告算法工程师",
        "风控算法工程师",
        "机器学习算法工程师",
        "数据挖掘算法工程师",
        "算法研究员",
        "算法工程师",
        "控制算法工程师",
        "自动驾驶算法工程师",
        "机器人算法工程师",
    ],
    "后端开发工程师": [
        "后端开发工程师",
        "Java开发工程师",
        "Python开发工程师",
        "Go开发工程师",
        "C++开发工程师",
        "软件开发工程师",
        "软件架构师",
        "大模型应用工程师",
        "AI Agent应用工程师",
    ],
    "前端开发工程师": [
        "前端开发工程师",
        "全栈开发工程师",
        "AI应用工程师",
        "大模型应用工程师",
        "AI Agent应用工程师",
        "软件开发工程师",
    ],
    "全栈开发工程师": [
        "全栈开发工程师",
        "前端开发工程师",
        "后端开发工程师",
        "大模型应用工程师",
        "AI Agent应用工程师",
        "AI应用工程师",
        "软件开发工程师",
        "软件架构师",
    ],
    "数据分析师": [
        "数据分析师",
        "数据挖掘算法工程师",
        "数据治理工程师",
        "数据平台工程师",
        "数据仓库工程师",
        "数据工程师",
    ],
    "数据工程师": [
        "数据工程师",
        "数据开发工程师",
        "大数据开发工程师",
        "数据仓库工程师",
        "数据平台工程师",
        "数据治理工程师",
        "数据库工程师",
    ],
    "测试工程师": [
        "测试工程师",
        "测试开发工程师",
        "质量工程师",
        "大模型测试工程师",
    ],
    "运维工程师": [
        "运维工程师",
        "DevOps工程师",
        "网络工程师",
        "数据库工程师",
        "服务器工程师",
        "技术支持工程师",
        "安全工程师",
        "信息安全工程师",
    ],
    "云计算工程师": [
        "云计算工程师",
        "AI Infra工程师",
        "DevOps工程师",
        "运维工程师",
        "服务器工程师",
        "网络工程师",
        "解决方案工程师",
    ],
    "移动开发工程师": [
        "客户端开发工程师",
        "Android开发工程师",
        "iOS开发工程师",
        "前端开发工程师",
        "全栈开发工程师",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Align synthetic resumes to the standard job-title taxonomy.")
    parser.add_argument("--resumes", type=Path, default=DEFAULT_RESUMES)
    parser.add_argument("--standard-jobs", type=Path, default=DEFAULT_STANDARD_JOBS)
    parser.add_argument("--frequency", type=Path, default=DEFAULT_FREQUENCY)
    parser.add_argument("--skill-pool", type=Path, default=DEFAULT_SKILL_POOL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-skills", type=int, default=24)
    args = parser.parse_args()

    resumes = pd.read_csv(args.resumes, dtype=str, encoding="utf-8-sig").fillna("")
    standard_jobs = pd.read_csv(args.standard_jobs, dtype=str, encoding="utf-8-sig").fillna("")
    frequency = pd.read_csv(args.frequency, dtype=str, encoding="utf-8-sig").fillna("")
    skill_pool = pd.read_csv(args.skill_pool, dtype=str, encoding="utf-8-sig").fillna("")

    category_by_job = dict(zip(standard_jobs["standard_job_title"], standard_jobs["standard_category"]))
    valid_jobs = set(standard_jobs["standard_job_title"])
    job_skills = build_job_skill_profiles(frequency, skill_pool)
    skill_kg = dict(zip(skill_pool["normalized_skill"], skill_pool["kg_display_skill"]))

    aligned_rows: list[dict[str, Any]] = []
    for index, row in resumes.iterrows():
        record = row.to_dict()
        original_family = record.get("target_job_family", "")
        standard_job = choose_standard_job(original_family, int(index), valid_jobs)
        standard_category = category_by_job.get(standard_job, "")
        profile_skills = job_skills.get(standard_job, [])

        original_skills = parse_json_list(record.get("skills_normalized", ""))
        merged_skills = merge_skills(original_skills, profile_skills, args.max_skills)
        skill_levels = update_skill_levels(record.get("skill_levels", ""), merged_skills, profile_skills, record.get("years_experience", ""), int(index))
        keywords_used = merge_skills(parse_json_list(record.get("job_keywords_used", "")), profile_skills, args.max_skills + 8)

        profile_text = update_profile_text(
            str(record.get("profile_text", "")),
            original_family=original_family,
            standard_job=standard_job,
            standard_category=standard_category,
            profile_skills=profile_skills,
        )

        overlap = len(set(original_skills) & set(profile_skills))
        record["original_target_job_family"] = original_family
        record["target_job_family"] = standard_job
        record["standard_job"] = standard_job
        record["standard_job_title"] = standard_job
        record["standard_category"] = standard_category
        record["alignment_method"] = "family_pool_round_robin_with_job_skill_profile"
        record["job_profile_skills"] = json.dumps(profile_skills, ensure_ascii=False)
        record["kg_display_skills"] = json.dumps(
            [{"normalized_skill": skill, "kg_display_skill": skill_kg.get(skill, "")} for skill in merged_skills],
            ensure_ascii=False,
        )
        record["resume_skill_overlap_count"] = str(overlap)
        record["resume_skill_overlap_ratio"] = f"{overlap / max(len(original_skills), 1):.4f}"
        record["job_skill_coverage_ratio"] = f"{len(set(merged_skills) & set(profile_skills)) / max(len(profile_skills), 1):.4f}"
        record["skills_normalized"] = json.dumps(merged_skills, ensure_ascii=False)
        record["skill_levels"] = json.dumps(skill_levels, ensure_ascii=False)
        record["job_keywords_used"] = json.dumps(keywords_used, ensure_ascii=False)
        record["profile_text"] = profile_text
        record["experience"] = rewrite_nested_text(record.get("experience", ""), original_family, standard_job, profile_skills)
        record["projects"] = rewrite_nested_text(record.get("projects", ""), original_family, standard_job, profile_skills)
        aligned_rows.append(record)

    aligned = pd.DataFrame(aligned_rows)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    aligned.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    write_jsonl(aligned_rows, args.output_jsonl)
    write_report(resumes, aligned, standard_jobs, job_skills, args.report)

    print(f"input_rows={len(resumes)}")
    print(f"aligned_rows={len(aligned)}")
    print(f"standard_jobs_used={aligned['standard_job'].nunique()}")
    print(f"standard_categories_used={aligned['standard_category'].nunique()}")
    print(f"output_csv={args.output_csv}")
    print(f"output_jsonl={args.output_jsonl}")
    print(f"report={args.report}")


def build_job_skill_profiles(frequency: pd.DataFrame, skill_pool: pd.DataFrame) -> dict[str, list[str]]:
    if frequency.empty:
        return {}
    work = frequency.copy()
    work["month_rank"] = work["month"].rank(method="dense").astype(int)
    for col in ["cumulative_skill_frequency", "monthly_skill_frequency", "cumulative_skill_count", "monthly_skill_count"]:
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
    work = work.sort_values(
        by=[
            "standard_job",
            "skill",
            "month",
            "cumulative_skill_frequency",
            "cumulative_skill_count",
        ],
        ascending=[True, True, False, False, False],
    )
    latest = work.drop_duplicates(["standard_job", "skill"], keep="first")
    latest = latest.sort_values(
        by=["standard_job", "cumulative_skill_frequency", "monthly_skill_frequency", "cumulative_skill_count"],
        ascending=[True, False, False, False],
    )
    profiles: dict[str, list[str]] = {}
    for job, group in latest.groupby("standard_job"):
        profiles[job] = dedupe([str(skill).strip() for skill in group["skill"].tolist() if str(skill).strip()])[:24]
    augment_profiles_from_skill_pool(profiles, skill_pool)
    fill_missing_profiles_from_aliases(profiles)
    return profiles


def augment_profiles_from_skill_pool(profiles: dict[str, list[str]], skill_pool: pd.DataFrame) -> None:
    if skill_pool.empty or "standard_jobs" not in skill_pool.columns:
        return
    work = skill_pool.copy()
    work["mention_count_num"] = pd.to_numeric(work.get("mention_count", 0), errors="coerce").fillna(0)
    work = work.sort_values(["mention_count_num", "normalized_skill"], ascending=[False, True])
    for _, row in work.iterrows():
        skill = str(row.get("normalized_skill", "")).strip()
        if not skill:
            continue
        jobs = [job.strip() for job in str(row.get("standard_jobs", "")).split(";") if job.strip()]
        for job in jobs:
            current = profiles.setdefault(job, [])
            if skill not in current:
                current.append(skill)
    for job, skills in list(profiles.items()):
        profiles[job] = dedupe(skills)[:24]


def fill_missing_profiles_from_aliases(profiles: dict[str, list[str]]) -> None:
    aliases = {
        "大数据开发工程师": ["数据开发工程师", "数据工程师", "数据平台工程师", "数据仓库工程师"],
    }
    for target_job, source_jobs in aliases.items():
        if profiles.get(target_job):
            continue
        merged: list[str] = []
        for source_job in source_jobs:
            merged.extend(profiles.get(source_job, []))
        profiles[target_job] = dedupe(merged)[:24]


def choose_standard_job(original_family: str, index: int, valid_jobs: set[str]) -> str:
    candidates = [job for job in FAMILY_TO_STANDARD_JOBS.get(original_family, [original_family]) if job in valid_jobs]
    if not candidates:
        return original_family
    return candidates[index % len(candidates)]


def merge_skills(primary: list[str], profile: list[str], max_skills: int) -> list[str]:
    profile_head = profile[:12]
    merged = dedupe(profile_head + primary + profile[12:])
    return merged[:max_skills]


def update_skill_levels(raw_levels: str, skills: list[str], profile_skills: list[str], years_raw: str, seed: int) -> dict[str, str]:
    levels = parse_json_dict(raw_levels)
    years = parse_years(years_raw)
    profile_set = set(profile_skills)
    new_levels: dict[str, str] = {}
    for idx, skill in enumerate(skills):
        if skill in levels:
            new_levels[skill] = str(levels[skill])
            continue
        if skill in profile_set and years >= 5 and idx < 8:
            new_levels[skill] = "精通" if (seed + idx) % 3 == 0 else "熟练"
        elif skill in profile_set and years >= 3:
            new_levels[skill] = "熟练" if idx < 12 else "掌握"
        elif skill in profile_set:
            new_levels[skill] = "掌握" if idx < 10 else "了解"
        else:
            new_levels[skill] = "掌握"
    return new_levels


def update_profile_text(text: str, original_family: str, standard_job: str, standard_category: str, profile_skills: list[str]) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("求职意向："):
        lines[0] = f"求职意向：{standard_job}。"
    profile_line = f"标准岗位：{standard_job}；岗位大族：{standard_category}；岗位系统技能画像：{'、'.join(profile_skills[:10])}。"
    if len(lines) >= 2:
        lines.insert(1, profile_line)
    else:
        lines.append(profile_line)
    replaced = "\n".join(lines)
    if original_family and original_family != standard_job:
        replaced = replaced.replace(f"求职意向：{original_family}。", f"求职意向：{standard_job}。")
    return replaced


def rewrite_nested_text(raw: str, original_family: str, standard_job: str, profile_skills: list[str]) -> str:
    try:
        value = json.loads(raw)
    except Exception:
        return raw
    if isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            for key in ["role", "title"]:
                if key in item and isinstance(item[key], str) and original_family in item[key]:
                    item[key] = item[key].replace(original_family, standard_job)
            if "keywords" in item and isinstance(item["keywords"], list):
                item["keywords"] = merge_skills([str(x) for x in item["keywords"]], profile_skills[:8], 12)
            if "tech_stack" in item and isinstance(item["tech_stack"], list):
                item["tech_stack"] = merge_skills([str(x) for x in item["tech_stack"]], profile_skills[:8], 12)
            if index == 0 and "highlights" in item and isinstance(item["highlights"], list):
                item["highlights"] = [
                    str(h).replace(original_family, standard_job) for h in item["highlights"]
                ]
                item["highlights"].append(f"围绕{standard_job}岗位画像补充{'、'.join(profile_skills[:4])}等核心技能。")
    return json.dumps(value, ensure_ascii=False)


def parse_json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return dedupe([str(item).strip() for item in parsed if str(item).strip()])


def parse_json_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_years(value: str) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return 0


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(
    original: pd.DataFrame,
    aligned: pd.DataFrame,
    standard_jobs: pd.DataFrame,
    job_skills: dict[str, list[str]],
    path: Path,
) -> None:
    report = {
        "input_rows": int(len(original)),
        "aligned_rows": int(len(aligned)),
        "standard_job_dictionary_rows": int(len(standard_jobs)),
        "standard_jobs_used": int(aligned["standard_job"].nunique()),
        "standard_categories_used": int(aligned["standard_category"].nunique()),
        "original_target_job_family_distribution": original["target_job_family"].value_counts().to_dict(),
        "aligned_standard_job_distribution": aligned["standard_job"].value_counts().to_dict(),
        "aligned_standard_category_distribution": aligned["standard_category"].value_counts().to_dict(),
        "jobs_without_frequency_profile": sorted(set(aligned["standard_job"]) - set(job_skills)),
        "new_columns": [
            "original_target_job_family",
            "standard_job",
            "standard_job_title",
            "standard_category",
            "alignment_method",
            "job_profile_skills",
            "kg_display_skills",
            "resume_skill_overlap_count",
            "resume_skill_overlap_ratio",
            "job_skill_coverage_ratio",
        ],
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
