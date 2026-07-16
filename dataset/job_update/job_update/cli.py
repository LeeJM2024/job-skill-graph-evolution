from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .frequency_store import FrequencyStore, rebuild_frequency_table
from .models import JobPosting, SkillMention
from .service import JobUpdateSystem
from .skill_extraction import ExistingSkillExtractAdapter
from .similarity import Text2VecSimilarity
from .taxonomy import JobTaxonomy
from .text import clean_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Existing-job update prototype.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild = subparsers.add_parser("rebuild-frequency", help="Rebuild monthly/cumulative skill frequency CSV.")
    rebuild.add_argument("--event-stream", required=True, type=Path)
    rebuild.add_argument("--output", required=True, type=Path)

    route = subparsers.add_parser("route", help="Route a job title to family and standard job.")
    add_routing_args(route)
    route.add_argument("--job-title", required=True)

    process = subparsers.add_parser("process-one", help="Route and update one posting if it is an existing job.")
    add_routing_args(process)
    process.add_argument("--event-stream", required=True, type=Path)
    process.add_argument("--frequency-output", required=True, type=Path)
    process.add_argument("--job-id", required=True)
    process.add_argument("--month", required=True)
    process.add_argument("--job-title", required=True)
    process.add_argument("--responsibility", default="")
    process.add_argument("--requirement", default="")
    process.add_argument(
        "--skills-json",
        default="[]",
        help="JSON list of extracted skill objects. Each item needs raw_skill or normalized_skill.",
    )
    process.add_argument(
        "--skills",
        default="",
        help="Semicolon-separated skills, used when --skills-json is omitted.",
    )
    process.add_argument("--dry-run", action="store_true")
    process.add_argument(
        "--extract-skills",
        action="store_true",
        help="Use dataset/skill_extract when --skills-json and --skills are empty.",
    )
    process.add_argument("--skill-provider", choices=["deepseek", "gpt"], default="deepseek")
    process.add_argument("--skill-model", default=None)
    process.add_argument("--skill-base-url", default=None)
    process.add_argument("--skill-api-key-env", default=None)
    process.add_argument("--skill-gold", type=Path, default=None)
    process.add_argument("--skill-cache", type=Path, default=None)
    process.add_argument("--skill-timeout", type=int, default=90)
    process.add_argument("--skill-retries", type=int, default=2)

    args = parser.parse_args()
    if args.command == "rebuild-frequency":
        events = pd.read_csv(args.event_stream, dtype=str).fillna("")
        frequency = rebuild_frequency_table(events)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        frequency.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(json.dumps({"rows": len(frequency), "output": str(args.output)}, ensure_ascii=False, indent=2))
        return

    taxonomy = JobTaxonomy.from_csv(args.title_dictionary)
    similarity = build_similarity(args)

    if args.command == "route":
        result = taxonomy.route(
            args.job_title,
            similarity=similarity,
            category_threshold=args.category_threshold,
            job_threshold=args.job_threshold,
            tie_delta=args.tie_delta,
        )
        print(json.dumps(serialize_route(result), ensure_ascii=False, indent=2))
        return

    if args.command == "process-one":
        skills = parse_skills(args.skills_json, args.skills)
        skill_extractor = None
        if args.extract_skills and not skills:
            skill_extractor = build_skill_extractor(args)
        system = JobUpdateSystem(
            taxonomy=taxonomy,
            frequency_store=FrequencyStore(args.event_stream, args.frequency_output),
            similarity=similarity,
            skill_extractor=skill_extractor,
            category_threshold=args.category_threshold,
            job_threshold=args.job_threshold,
            tie_delta=args.tie_delta,
        )
        posting = JobPosting(
            job_id=args.job_id,
            month=args.month,
            job_title=args.job_title,
            job_responsibility=args.responsibility,
            job_requirement=args.requirement,
            skills=skills,
        )
        result = system.process(posting, write=not args.dry_run)
        print(json.dumps(serialize_process_result(result), ensure_ascii=False, indent=2))
        return


def add_routing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title-dictionary", required=True, type=Path)
    parser.add_argument("--category-threshold", type=float, default=0.6)
    parser.add_argument("--job-threshold", type=float, default=0.85)
    parser.add_argument("--tie-delta", type=float, default=0.03)
    parser.add_argument("--text2vec-model", default="shibing624/text2vec-base-chinese")


def build_similarity(args: argparse.Namespace):
    return Text2VecSimilarity(args.text2vec_model)


def build_skill_extractor(args: argparse.Namespace) -> ExistingSkillExtractAdapter:
    overrides: dict[str, Any] = {
        "timeout": args.skill_timeout,
        "retries": args.skill_retries,
    }
    if args.skill_model:
        overrides["model"] = args.skill_model
    if args.skill_base_url:
        overrides["base_url"] = args.skill_base_url
    if args.skill_api_key_env:
        overrides["api_key_env"] = args.skill_api_key_env
    if args.skill_gold:
        overrides["gold_path"] = args.skill_gold
    if args.skill_cache:
        overrides["cache_path"] = args.skill_cache
    return ExistingSkillExtractAdapter(provider=args.skill_provider, **overrides)


def parse_skills(skills_json: str, skills_text: str) -> list[SkillMention]:
    parsed: Any = json.loads(skills_json)
    if parsed:
        if not isinstance(parsed, list):
            raise ValueError("--skills-json must be a JSON list")
        return [skill_from_dict(item) for item in parsed]
    return [SkillMention(raw_skill=item.strip()) for item in skills_text.split(";") if item.strip()]


def skill_from_dict(item: Any) -> SkillMention:
    if isinstance(item, str):
        return SkillMention(raw_skill=item)
    if not isinstance(item, dict):
        raise ValueError("Each skill item must be a string or object")
    raw_skill = clean_text(item.get("raw_skill") or item.get("skill") or item.get("name"))
    normalized_skill = clean_text(item.get("normalized_skill")) or None
    if not raw_skill and not normalized_skill:
        raise ValueError("Each skill object needs raw_skill, skill, name, or normalized_skill")
    return SkillMention(
        raw_skill=raw_skill or normalized_skill or "",
        normalized_skill=normalized_skill,
        category=clean_text(item.get("category")) or None,
        skill_type=clean_text(item.get("skill_type")) or None,
        confidence=_optional_float(item.get("confidence")),
        evidence_field=clean_text(item.get("evidence_field")) or None,
        evidence_sentence=clean_text(item.get("evidence_sentence")) or None,
        span_text=clean_text(item.get("span_text")) or None,
        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
    )


def serialize_route(route) -> dict[str, Any]:
    return {
        "status": route.status,
        "reason": route.reason,
        "best_category": serialize_candidate(route.best_category),
        "best_job": serialize_candidate(route.best_job),
        "selected_categories": [serialize_candidate(item) for item in route.selected_categories],
        "selected_jobs": [serialize_candidate(item) for item in route.selected_jobs],
    }


def serialize_process_result(result) -> dict[str, Any]:
    payload = {
        "job_id": result.posting.job_id,
        "job_title": result.posting.job_title,
        "route": serialize_route(result.route),
        "updated": result.update is not None,
    }
    if result.update is not None:
        payload["update"] = {
            "standard_job": result.update.standard_job,
            "month": result.update.month,
            "normalized_skills": [skill.normalized_skill for skill in result.update.normalized_skills],
            "monthly_rows": result.update.monthly_rows,
            "frequency_rows": result.update.frequency_rows,
            "event_stream_path": result.update.event_stream_path,
            "frequency_path": result.update.frequency_path,
        }
    return payload


def serialize_candidate(candidate) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {"name": candidate.name, "score": round(candidate.score, 6), "metadata": candidate.metadata}


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
