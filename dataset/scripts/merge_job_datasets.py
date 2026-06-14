"""Merge enterprise and government job JSONL files into one indexed dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_INPUTS = (
    Path("cleaned/enterprise_jobs_3000_normalized.jsonl"),
    Path("cleaned/government_jobs_2026_normalized.jsonl"),
)
DEFAULT_JSONL = Path("cleaned/all_jobs_23714_normalized.jsonl")
DEFAULT_CSV = Path("cleaned/all_jobs_23714_normalized.csv")

OUTPUT_FIELDS = (
    "job_id",
    "source_type",
    "source",
    "source_name",
    "keyword",
    "city",
    "crawl_time",
    "job_title",
    "company_name",
    "salary_text",
    "location",
    "tags",
    "job_description",
    "source_url",
    "publish_time",
    "content_hash",
    "is_content_duplicate",
    "duplicate_of",
    "raw",
)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def digest(parts: Iterable[Any], length: int = 20) -> str:
    payload = "\x1f".join(normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def source_type(source: str) -> str:
    return "government" if source == "government_jobs" else "enterprise"


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    source = str(record.get("source", ""))
    identity_hash = digest(
        (
            source,
            record.get("source_url"),
            record.get("job_title"),
            record.get("company_name"),
            record.get("location"),
        )
    )
    content_hash = digest(
        (
            record.get("job_title"),
            record.get("company_name"),
            record.get("location"),
            record.get("job_description"),
        )
    )

    merged = {field: record.get(field, "") for field in OUTPUT_FIELDS}
    merged.update(
        {
            "job_id": f"job_{identity_hash}",
            "source_type": source_type(source),
            "content_hash": content_hash,
            "is_content_duplicate": False,
            "duplicate_of": "",
            "tags": record.get("tags") if isinstance(record.get("tags"), list) else [],
            "raw": record.get("raw", {}),
        }
    )
    return merged


def merge_records(input_paths: list[Path]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    first_by_content: dict[str, str] = {}

    for input_path in input_paths:
        for record in read_jsonl(input_path):
            item = normalize_record(record)
            first_job_id = first_by_content.get(item["content_hash"])
            if first_job_id:
                item["is_content_duplicate"] = True
                item["duplicate_of"] = first_job_id
            else:
                first_by_content[item["content_hash"]] = item["job_id"]
            merged.append(item)

    return merged


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def csv_value(field: str, value: Any) -> Any:
    if field == "tags":
        return ";".join(str(tag) for tag in value)
    if field == "raw":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(
                {field: csv_value(field, record.get(field, "")) for field in OUTPUT_FIELDS}
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument("--jsonl-output", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    missing = [path for path in args.inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing input files: {', '.join(map(str, missing))}")

    records = merge_records(args.inputs)
    write_jsonl(args.jsonl_output, records)
    write_csv(args.csv_output, records)

    source_counts: dict[str, int] = {}
    for record in records:
        key = record["source_type"]
        source_counts[key] = source_counts.get(key, 0) + 1

    duplicate_count = sum(record["is_content_duplicate"] for record in records)
    print(f"Merged records: {len(records)}")
    print(f"Source counts: {source_counts}")
    print(f"Content duplicates marked: {duplicate_count}")
    print(f"JSONL: {args.jsonl_output}")
    print(f"CSV: {args.csv_output}")


if __name__ == "__main__":
    main()
