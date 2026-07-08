"""Anonymize and normalize the detailed synthetic Chinese resume dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


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

PUBLIC_SCHEMA_REQUIRED_COLUMNS = {
    "resume_id",
    "name",
    "gender",
    "age",
    "phone",
    "email",
    "split",
    "target_job_family",
    "education",
    "school_category",
    "major",
    "english_level",
    "experience",
    "projects",
    "skills_normalized",
    "skill_levels",
    "profile_text",
}


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def parse_json_cell(value: Any, column: str) -> Any:
    text = clean(value)
    if not text:
        raise ValueError(f"Column {column} contains an empty JSON value.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Column {column} contains invalid JSON: {text[:120]}") from exc


def contains_pii(text: str) -> bool:
    phone = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    return bool(phone.search(text) or email.search(text))


def process(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    missing = sorted(PUBLIC_SCHEMA_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(
            "New resume CSV schema is missing required columns: "
            + ", ".join(missing)
        )

    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        profile_text = clean(row["profile_text"])
        skills_normalized = parse_json_cell(row.get("skills_normalized"), "skills_normalized")
        skill_levels = parse_json_cell(row.get("skill_levels"), "skill_levels")
        record = {
            "resume_id": clean(row["resume_id"]),
            "profile_hash": hashlib.sha256(profile_text.encode("utf-8")).hexdigest()[:20],
            "dataset_version": "detailed_resume_v2_public_schema",
            "split": clean(row["split"]),
            "target_job_family": clean(row["target_job_family"]),
            "education": clean(row["education"]),
            "school_category": clean(row["school_category"]),
            "major": clean(row["major"]),
            "english_level": clean(row["english_level"]),
            "experience": parse_json_cell(row.get("experience"), "experience"),
            "projects": parse_json_cell(row.get("projects"), "projects"),
            "skills_raw": {},
            "skills_normalized": skills_normalized if isinstance(skills_normalized, list) else [],
            "skill_levels": skill_levels if isinstance(skill_levels, dict) else {},
            "profile_text": profile_text,
            "screening_label": "",
            "screening_label_original": "",
            "screening_label_revised": "",
            "label_disagreement": False,
        }
        records.append(record)

    return records, build_quality_report(
        records,
        input_rows=len(frame),
        label_disagreements=0,
        input_schema="detailed_resume_v2_public_schema",
    )


def build_quality_report(
    records: list[dict[str, Any]],
    input_rows: int,
    label_disagreements: int,
    input_schema: str,
) -> dict[str, Any]:
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
    return {
        "input_schema": input_schema,
        "input_rows": input_rows,
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
        "label_disagreements": label_disagreements,
        "split_counts": dict(split_counts),
        "screening_label_counts": dict(label_counts),
        "target_job_family_counts": dict(job_counts),
        "top_skills": skill_counts.most_common(30),
        "excluded_sensitive_fields": ["name", "gender", "age", "phone", "email"],
    }


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
        "--input",
        type=Path,
        default=Path("resume/synthetic_detailed_resumes.csv"),
        help="Public-schema detailed resume CSV.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("processed"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, quality = process(args.input)
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
