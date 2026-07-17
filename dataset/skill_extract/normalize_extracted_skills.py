"""CLI for normalizing skill extraction outputs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from skill_extract import extract_job_skills_api as extract_api
    from skill_extract.normalizer import (
        DEFAULT_CACHE,
        DEFAULT_DISPLAY_DICTIONARY,
        DEFAULT_EXTRACTION_DICTIONARY,
        DEFAULT_NORMALIZED_DICTIONARY,
        SkillNormalizer,
    )
else:
    from . import extract_job_skills_api as extract_api
    from .normalizer import (
        DEFAULT_CACHE,
        DEFAULT_DISPLAY_DICTIONARY,
        DEFAULT_EXTRACTION_DICTIONARY,
        DEFAULT_NORMALIZED_DICTIONARY,
        SkillNormalizer,
    )


DEFAULT_INPUT = extract_api.DEFAULT_OUTPUT_DIR / "job_skill_mentions_deepseek.csv"
DEFAULT_OUTPUT = extract_api.DEFAULT_OUTPUT_DIR / "job_skill_mentions_deepseek_normalized.csv"


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return list(extract_api.read_jsonl(path))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["normalized_skill", "kg_display_skill"]
    if path.suffix.lower() == ".jsonl":
        extract_api.write_jsonl(path, rows)
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def final_output_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        normalized_skill = SkillNormalizer.clean(row.get("normalized_skill"))
        kg_display_skill = SkillNormalizer.clean(row.get("kg_display_skill"))
        if not normalized_skill:
            continue
        key = (normalized_skill.casefold(), kg_display_skill.casefold())
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "normalized_skill": normalized_skill,
                "kg_display_skill": kg_display_skill,
            }
        )
    return sorted(output, key=lambda row: (row["kg_display_skill"].casefold(), row["normalized_skill"].casefold()))


def append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize extracted JD skill candidates.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--extraction-dictionary", type=Path, default=DEFAULT_EXTRACTION_DICTIONARY)
    parser.add_argument("--normalized-dictionary", type=Path, default=DEFAULT_NORMALIZED_DICTIONARY)
    parser.add_argument("--display-dictionary", type=Path, default=DEFAULT_DISPLAY_DICTIONARY)
    parser.add_argument("--no-api-for-unknown", action="store_true")
    parser.add_argument("--disallow-new-skills", action="store_true")
    parser.add_argument("--provider", choices=sorted(extract_api.PROVIDERS), default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--batch-size", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extract_api.load_env_file()
    normalizer = SkillNormalizer(
        extraction_dictionary=args.extraction_dictionary,
        normalized_dictionary=args.normalized_dictionary,
        display_dictionary=args.display_dictionary,
    )
    source_rows = read_rows(args.input)
    normalized_rows, stats = normalizer.normalize_rows(source_rows)
    api_stats: Counter[str] = Counter()
    if not args.no_api_for_unknown:
        normalized_rows, api_stats = normalizer.normalize_unknowns_with_api(
            normalized_rows,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            cache_path=args.cache,
            timeout=args.timeout,
            retries=args.retries,
            temperature=args.temperature,
            batch_size=args.batch_size,
            allow_new_skills=not args.disallow_new_skills,
        )

    final_rows = final_output_rows(normalized_rows)
    write_rows(args.output, final_rows)
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "rows": len(source_rows),
        "output_rows": len(final_rows),
        "unresolved_rows": sum(1 for row in normalized_rows if not row.get("normalized_skill")),
        "local_stats": dict(stats),
        "api_stats": dict(api_stats),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
