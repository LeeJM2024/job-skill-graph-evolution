from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .analysis import (
    analyze_event_stream,
    read_events,
    read_skill_universe,
    write_analysis_outputs,
)
from .comparison import compare_answer_tables, write_comparison_outputs
from .frequency_store import FrequencyStore, rebuild_frequency_table
from .models import JobPosting, SkillMention
from .output_runs import PROJECT_ROOT, resolve_run_output_dir, write_current_run_marker
from .service import JobUpdateSystem
from .skill_extraction import ExistingSkillExtractAdapter
from .similarity import Text2VecSimilarity
from .taxonomy import JobTaxonomy
from .text import clean_text
from .work_modes import (
    create_manual_workspace,
    resolve_data_stream_inputs,
    resolve_manual_inputs,
    write_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Existing-job update prototype.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild = subparsers.add_parser("rebuild-frequency", help="Rebuild monthly/cumulative skill frequency CSV.")
    rebuild.add_argument("--event-stream", required=True, type=Path)
    rebuild.add_argument("--output", required=True, type=Path)

    analyze = subparsers.add_parser(
        "analyze-event-stream",
        help="Analyze job demand and skill frequencies from an event stream.",
    )
    analyze.add_argument("--event-stream", required=True, type=Path)
    analyze.add_argument("--title-dictionary", required=True, type=Path)
    analyze.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to outputs/analysis_runs/<run_id> when omitted.",
    )
    analyze.add_argument(
        "--run-id",
        default=None,
        help="Optional run id used for the default output directory.",
    )
    analyze.add_argument("--month-start", default=None)
    analyze.add_argument("--month-end", default=None)
    analyze.add_argument(
        "--skill-universe",
        type=Path,
        default=None,
        help="Optional CSV with standard_job and skill columns; used to include zero-only skills.",
    )

    compare = subparsers.add_parser(
        "compare-answer",
        help="Compare analysis CSVs against generated answer CSVs.",
    )
    compare.add_argument("--actual-job-demand", required=True, type=Path)
    compare.add_argument("--expected-job-demand", required=True, type=Path)
    compare.add_argument("--actual-skill-frequency", required=True, type=Path)
    compare.add_argument("--expected-skill-frequency", required=True, type=Path)
    compare.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to outputs/comparison_runs/<run_id> when omitted.",
    )
    compare.add_argument(
        "--run-id",
        default=None,
        help="Optional run id used for the default output directory.",
    )
    compare.add_argument("--frequency-tolerance", type=float, default=0.0001)
    compare.add_argument(
        "--pass-threshold",
        type=float,
        default=0.9,
        help="Row match rate must be greater than this value for both tables. Default: 0.9.",
    )

    data_stream = subparsers.add_parser(
        "run-data-stream",
        help="Run analysis and optional answer comparison for a generated data-stream run.",
    )
    data_stream.add_argument("--run-dir", required=True, type=Path)
    data_stream.add_argument("--title-dictionary", type=Path, default=None)
    data_stream.add_argument("--month-start", default="2024-12")
    data_stream.add_argument("--month-end", default="2026-07")
    data_stream.add_argument("--skip-compare", action="store_true")
    data_stream.add_argument(
        "--pass-threshold",
        type=float,
        default=0.9,
        help="Row match rate must be greater than this value for both tables. Default: 0.9.",
    )

    init_manual = subparsers.add_parser(
        "init-manual-workspace",
        help="Create folders for manual input files.",
    )
    init_manual.add_argument("--workspace", required=True, type=Path)

    manual = subparsers.add_parser(
        "run-manual",
        help="Run analysis and optional comparison from a manual input workspace.",
    )
    manual.add_argument("--workspace", required=True, type=Path)
    manual.add_argument("--month-start", default=None)
    manual.add_argument("--month-end", default=None)
    manual.add_argument(
        "--pass-threshold",
        type=float,
        default=0.9,
        help="Row match rate must be greater than this value for both tables. Default: 0.9.",
    )

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

    if args.command == "analyze-event-stream":
        taxonomy = JobTaxonomy.from_csv(args.title_dictionary)
        skill_universe = (
            read_skill_universe(args.skill_universe)
            if args.skill_universe is not None
            else None
        )
        result = analyze_event_stream(
            read_events(args.event_stream),
            taxonomy=taxonomy,
            month_start=args.month_start,
            month_end=args.month_end,
            skill_universe=skill_universe,
        )
        output_dir, output_run_id = resolve_run_output_dir(
            explicit_output_dir=args.output_dir,
            run_id=args.run_id,
            source_paths=[args.event_stream],
            run_group="analysis_runs",
        )
        write_current_run_marker("analysis_runs", output_run_id)
        outputs = write_analysis_outputs(result, output_dir)
        print(
            json.dumps(
                {
                    **result.quality_report,
                    "output_run_id": output_run_id,
                    "outputs": outputs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "compare-answer":
        result = compare_answer_tables(
            actual_job_demand_path=args.actual_job_demand,
            expected_job_demand_path=args.expected_job_demand,
            actual_skill_frequency_path=args.actual_skill_frequency,
            expected_skill_frequency_path=args.expected_skill_frequency,
            frequency_tolerance=args.frequency_tolerance,
            pass_threshold=args.pass_threshold,
        )
        output_dir, output_run_id = resolve_run_output_dir(
            explicit_output_dir=args.output_dir,
            run_id=args.run_id,
            source_paths=[
                args.expected_job_demand,
                args.expected_skill_frequency,
                args.actual_job_demand,
                args.actual_skill_frequency,
            ],
            run_group="comparison_runs",
        )
        write_current_run_marker("comparison_runs", output_run_id)
        outputs = write_comparison_outputs(result, output_dir)
        print(
            json.dumps(
                {
                    **result.report,
                    "output_run_id": output_run_id,
                    "outputs": outputs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "run-data-stream":
        inputs = resolve_data_stream_inputs(
            run_dir=args.run_dir,
            title_dictionary=args.title_dictionary,
        )
        analysis_result = analyze_event_stream(
            read_events(inputs.event_stream),
            taxonomy=JobTaxonomy.from_csv(inputs.title_dictionary),
            month_start=args.month_start,
            month_end=args.month_end,
            skill_universe=read_skill_universe(inputs.skill_universe),
        )
        analysis_dir = PROJECT_ROOT / "outputs" / "analysis_runs" / inputs.run_id
        write_current_run_marker("analysis_runs", inputs.run_id)
        analysis_outputs = write_analysis_outputs(analysis_result, analysis_dir)
        comparison_outputs = None
        comparison_report = None
        if (
            not args.skip_compare
            and inputs.expected_job_demand is not None
            and inputs.expected_skill_frequency is not None
        ):
            comparison_result = compare_answer_tables(
                actual_job_demand_path=analysis_outputs["job_demand"],
                expected_job_demand_path=inputs.expected_job_demand,
                actual_skill_frequency_path=analysis_outputs["skill_frequency"],
                expected_skill_frequency_path=inputs.expected_skill_frequency,
                pass_threshold=args.pass_threshold,
            )
            write_current_run_marker("comparison_runs", inputs.run_id)
            comparison_outputs = write_comparison_outputs(
                comparison_result,
                PROJECT_ROOT / "outputs" / "comparison_runs" / inputs.run_id,
            )
            comparison_report = comparison_result.report
        print(
            json.dumps(
                {
                    "mode": "data_stream",
                    "run_id": inputs.run_id,
                    "analysis": analysis_result.quality_report,
                    "analysis_outputs": analysis_outputs,
                    "comparison": comparison_report,
                    "comparison_outputs": comparison_outputs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "init-manual-workspace":
        folders = create_manual_workspace(args.workspace)
        print(json.dumps({"workspace": str(args.workspace), "folders": folders}, ensure_ascii=False, indent=2))
        return

    if args.command == "run-manual":
        inputs = resolve_manual_inputs(args.workspace)
        analysis_result = analyze_event_stream(
            read_events(inputs.event_stream),
            taxonomy=JobTaxonomy.from_csv(inputs.title_dictionary),
            month_start=args.month_start,
            month_end=args.month_end,
            skill_universe=read_skill_universe(inputs.skill_universe)
            if inputs.skill_universe is not None
            else None,
        )
        analysis_dir = inputs.output_dir / "analysis"
        comparison_dir = inputs.output_dir / "comparison"
        analysis_outputs = write_analysis_outputs(analysis_result, analysis_dir)
        comparison_outputs = None
        comparison_report = None
        if (
            inputs.expected_job_demand is not None
            and inputs.expected_skill_frequency is not None
        ):
            comparison_result = compare_answer_tables(
                actual_job_demand_path=analysis_outputs["job_demand"],
                expected_job_demand_path=inputs.expected_job_demand,
                actual_skill_frequency_path=analysis_outputs["skill_frequency"],
                expected_skill_frequency_path=inputs.expected_skill_frequency,
                pass_threshold=args.pass_threshold,
            )
            comparison_outputs = write_comparison_outputs(
                comparison_result,
                comparison_dir,
            )
            comparison_report = comparison_result.report
        manifest_path = write_manifest(
            inputs.output_dir,
            {
                "mode": "manual",
                "manual_run_id": inputs.manual_run_id,
                "workspace": str(inputs.workspace),
                "event_stream": str(inputs.event_stream),
                "title_dictionary": str(inputs.title_dictionary),
                "skill_universe": str(inputs.skill_universe)
                if inputs.skill_universe is not None
                else None,
                "expected_job_demand": str(inputs.expected_job_demand)
                if inputs.expected_job_demand is not None
                else None,
                "expected_skill_frequency": str(inputs.expected_skill_frequency)
                if inputs.expected_skill_frequency is not None
                else None,
                "analysis_outputs": analysis_outputs,
                "comparison_outputs": comparison_outputs,
            },
        )
        manual_marker_path = PROJECT_ROOT / "outputs" / "current_manual_run_id.txt"
        manual_marker_path.parent.mkdir(parents=True, exist_ok=True)
        manual_marker_path.write_text(inputs.manual_run_id + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "mode": "manual",
                    "manual_run_id": inputs.manual_run_id,
                    "output_dir": str(inputs.output_dir),
                    "manifest": str(manifest_path),
                    "analysis": analysis_result.quality_report,
                    "analysis_outputs": analysis_outputs,
                    "comparison": comparison_report,
                    "comparison_outputs": comparison_outputs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
