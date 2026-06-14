"""Anonymize and normalize the structured Chinese resume dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


SKILL_GROUPS = (
    ("编程语言", "编程语言熟练度", "programming_language"),
    ("前端技术", "前端技术熟练度", "frontend"),
    ("后端技术", "后端技术熟练度", "backend"),
    ("数据库", "数据库熟练度", "database"),
    ("云计算/运维", "云计算/运维熟练度", "cloud_devops"),
    ("数据与算法", "数据与算法熟练度", "data_ai"),
    ("移动开发", "移动开发熟练度", "mobile"),
    ("测试工具", "测试工具熟练度", "testing"),
)

EXPERIENCE_FIELDS = (
    ("小型企业工作经验", "small_company"),
    ("中型企业工作经验", "medium_company"),
    ("大型企业工作经验", "large_company"),
)

PROJECT_FIELDS = (
    ("小规模项目", "small"),
    ("中规模项目", "medium"),
    ("大规模项目", "large"),
)

OUTPUT_COLUMNS = (
    "resume_id",
    "profile_hash",
    "dataset_version",
    "split",
    "target_job_family",
    "education",
    "school_category",
    "major",
    "english_level",
    "experience",
    "projects",
    "skills_raw",
    "skills_normalized",
    "skill_levels",
    "profile_text",
    "screening_label",
    "screening_label_original",
    "screening_label_revised",
    "label_disagreement",
)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def split_values(value: Any) -> list[str]:
    text = clean(value)
    return [part.strip() for part in text.split(",") if part.strip()] if text else []


def stable_id(original_id: Any) -> str:
    digest = hashlib.sha256(f"chinese-resume-v1:{clean(original_id)}".encode()).hexdigest()
    return f"resume_{digest[:16]}"


def stable_bucket(group_key: str) -> int:
    return int(hashlib.sha256(group_key.encode()).hexdigest()[:8], 16) % 100


def split_name(group_key: str) -> str:
    bucket = stable_bucket(group_key)
    if bucket < 60:
        return "train"
    if bucket < 80:
        return "dev"
    return "test"


def load_aliases(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_skills(
    row: pd.Series, aliases: dict[str, list[str]]
) -> tuple[dict[str, list[str]], list[str], dict[str, str], list[str]]:
    raw_groups: dict[str, list[str]] = {}
    normalized: list[str] = []
    levels: dict[str, str] = {}
    warnings: list[str] = []

    for skill_column, level_column, group_name in SKILL_GROUPS:
        raw_skills = split_values(row.get(skill_column))
        raw_levels = split_values(row.get(level_column))
        raw_groups[group_name] = raw_skills

        if raw_skills and len(raw_skills) != len(raw_levels):
            warnings.append(group_name)

        for index, raw_skill in enumerate(raw_skills):
            level = raw_levels[index] if index < len(raw_levels) else "未标注"
            expanded = aliases.get(raw_skill, [raw_skill])
            for skill in expanded:
                if skill not in normalized:
                    normalized.append(skill)
                previous = levels.get(skill)
                if not previous or previous == "未标注":
                    levels[skill] = level

    return raw_groups, normalized, levels, warnings


def build_experience(row: pd.Series) -> list[dict[str, str]]:
    return [
        {"company_size": key, "duration": value}
        for column, key in EXPERIENCE_FIELDS
        if (value := clean(row.get(column)))
    ]


def build_projects(row: pd.Series) -> dict[str, int]:
    projects: dict[str, int] = {}
    for column, key in PROJECT_FIELDS:
        value = clean(row.get(column))
        projects[key] = int(float(value)) if value else 0
    return projects


def build_profile_text(record: dict[str, Any]) -> str:
    skill_text = "、".join(
        f"{skill}（{record['skill_levels'].get(skill, '未标注')}）"
        for skill in record["skills_normalized"]
    )
    experience_text = "；".join(
        f"{item['company_size']}企业经验：{item['duration']}"
        for item in record["experience"]
    )
    projects = record["projects"]
    project_text = (
        f"小型项目{projects['small']}个，中型项目{projects['medium']}个，"
        f"大型项目{projects['large']}个"
    )
    parts = (
        f"意向岗位：{record['target_job_family']}",
        f"学历：{record['education']}",
        f"专业：{record['major']}",
        f"英语水平：{record['english_level']}",
        f"技能：{skill_text}",
        f"工作经验：{experience_text or '未填写'}",
        f"项目经验：{project_text}",
    )
    return "。".join(parts) + "。"


def contains_pii(text: str) -> bool:
    phone = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    return bool(phone.search(text) or email.search(text))


def process(
    original_path: Path, revised_path: Path, aliases_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    original = pd.read_csv(original_path, encoding="utf-8-sig")
    revised = pd.read_csv(revised_path, encoding="utf-8-sig")
    if list(original.columns) != list(revised.columns):
        raise ValueError("Original and revised resume columns do not match")
    if len(original) != len(revised):
        raise ValueError("Original and revised resume row counts do not match")

    aliases = load_aliases(aliases_path)
    records: list[dict[str, Any]] = []
    alignment_warnings: Counter[str] = Counter()

    for index, row in revised.iterrows():
        original_row = original.iloc[index]
        if clean(row["简历编号"]) != clean(original_row["简历编号"]):
            raise ValueError(f"Resume ID mismatch at row {index + 2}")

        skills_raw, skills_normalized, skill_levels, warnings = extract_skills(row, aliases)
        alignment_warnings.update(warnings)
        original_label = clean(original_row["筛选结果"])
        revised_label = clean(row["筛选结果"])
        resume_id = stable_id(row["简历编号"])

        record: dict[str, Any] = {
            "resume_id": resume_id,
            "profile_hash": "",
            "dataset_version": "revised_with_original_label_audit",
            "split": "",
            "target_job_family": clean(row["意向岗位"]),
            "education": clean(row["学历层次"]),
            "school_category": clean(row["院校类别"]),
            "major": clean(row["专业类别"]),
            "english_level": clean(row["英语水平"]),
            "experience": build_experience(row),
            "projects": build_projects(row),
            "skills_raw": skills_raw,
            "skills_normalized": skills_normalized,
            "skill_levels": skill_levels,
            "screening_label": revised_label,
            "screening_label_original": original_label,
            "screening_label_revised": revised_label,
            "label_disagreement": original_label != revised_label,
        }
        record["profile_text"] = build_profile_text(record)
        record["profile_hash"] = hashlib.sha256(
            record["profile_text"].encode("utf-8")
        ).hexdigest()[:20]
        record["split"] = split_name(record["profile_hash"])
        records.append(record)

    pii_count = 0
    for record in records:
        content_fields = {
            key: value
            for key, value in record.items()
            if key not in {"resume_id", "profile_hash"}
        }
        pii_count += contains_pii(json.dumps(content_fields, ensure_ascii=False))
    split_counts = Counter(record["split"] for record in records)
    job_counts = Counter(record["target_job_family"] for record in records)
    skill_counts = Counter(
        skill for record in records for skill in record["skills_normalized"]
    )
    label_counts = Counter(record["screening_label"] for record in records)
    profile_counts = Counter(record["profile_hash"] for record in records)
    profile_splits: dict[str, set[str]] = {}
    for record in records:
        profile_splits.setdefault(record["profile_hash"], set()).add(record["split"])
    quality = {
        "input_rows": len(revised),
        "output_rows": len(records),
        "unique_resume_ids": len({record["resume_id"] for record in records}),
        "pii_matches_in_output": pii_count,
        "empty_profile_text": sum(not record["profile_text"] for record in records),
        "empty_skill_lists": sum(not record["skills_normalized"] for record in records),
        "unique_profile_texts": len(profile_counts),
        "duplicate_profile_rows": sum(count - 1 for count in profile_counts.values()),
        "cross_split_profile_leakage": sum(
            len(splits) > 1 for splits in profile_splits.values()
        ),
        "label_disagreements": sum(record["label_disagreement"] for record in records),
        "split_counts": dict(split_counts),
        "screening_label_counts": dict(label_counts),
        "target_job_family_counts": dict(job_counts),
        "top_skills": skill_counts.most_common(30),
        "skill_level_alignment_warnings": dict(alignment_warnings),
        "excluded_sensitive_fields": ["姓名", "性别", "年龄", "电话", "邮箱"],
    }
    return records, quality


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        row = {}
        for column in OUTPUT_COLUMNS:
            value = record[column]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            row[column] = value
        rows.append(row)
    pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_csv(
        path, index=False, encoding="utf-8-sig"
    )


def write_split_manifests(output_dir: Path, records: list[dict[str, Any]]) -> None:
    benchmark_dir = output_dir.parent / "benchmark"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "dev", "test"):
        items = [
            {
                "resume_id": record["resume_id"],
                "target_job_family": record["target_job_family"],
                "split": split,
            }
            for record in records
            if record["split"] == split
        ]
        write_jsonl(benchmark_dir / f"resume_{split}_manifest.jsonl", items)


def write_pilot_sample(output_dir: Path, records: list[dict[str, Any]]) -> None:
    annotation_dir = output_dir.parent / "annotations"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["target_job_family"], []).append(record)

    sample = []
    for job_family in sorted(groups):
        selected = []
        seen_profiles = set()
        for item in sorted(groups[job_family], key=lambda value: value["resume_id"]):
            if item["profile_hash"] in seen_profiles:
                continue
            selected.append(item)
            seen_profiles.add(item["profile_hash"])
            if len(selected) == 3:
                break
        sample.extend(
            {
                "resume_id": item["resume_id"],
                "target_job_family": item["target_job_family"],
                "profile_text": item["profile_text"],
                "candidate_generation_status": "pending_bm25_index",
            }
            for item in selected
        )
    write_jsonl(annotation_dir / "pilot_resumes_30.jsonl", sample)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--original", type=Path, default=Path("resume/Chinese_resume_data.csv")
    )
    parser.add_argument(
        "--revised", type=Path, default=Path("resume/revise_Chinese_resume_data.csv")
    )
    parser.add_argument(
        "--aliases", type=Path, default=Path("config/skill_aliases.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("processed"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, quality = process(args.original, args.revised, args.aliases)
    jsonl_path = args.output_dir / "resumes_anonymized.jsonl"
    csv_path = args.output_dir / "resumes_anonymized.csv"
    quality_path = args.output_dir / "resume_quality_report.json"

    write_jsonl(jsonl_path, records)
    write_csv(csv_path, records)
    write_split_manifests(args.output_dir, records)
    write_pilot_sample(args.output_dir, records)
    quality_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Processed resumes: {len(records)}")
    print(f"Label disagreements: {quality['label_disagreements']}")
    print(f"PII matches in output: {quality['pii_matches_in_output']}")
    print(f"Split counts: {quality['split_counts']}")
    print(f"JSONL: {jsonl_path}")
    print(f"CSV: {csv_path}")
    print(f"Quality report: {quality_path}")


if __name__ == "__main__":
    main()
