from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import re
import sys
import threading
import time
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
from .skill_extraction import ExistingSkillExtractAdapter, ManualSkillKeywordExtractor, ManualSkillNormalizeAdapter
from .skill_pool_store import SkillPoolStore
from .similarity import Text2VecSimilarity
from .taxonomy import JobTaxonomy
from .text import clean_text
from .title_cleaning import LLMTitleCleaner
from .work_modes import (
    create_manual_workspace,
    resolve_data_stream_inputs,
    resolve_manual_inputs,
    write_manifest,
)


BASE_DATA_DIR = PROJECT_ROOT / "data" / "base"
BASE_TITLE_DICTIONARY = BASE_DATA_DIR / "standard_job_title_dictionary.csv"
BASE_EVENT_STREAM = BASE_DATA_DIR / "job_update_event_stream.csv"
BASE_FREQUENCY_OUTPUT = BASE_DATA_DIR / "job_skill_monthly_frequency.csv"
BASE_SKILL_POOL = BASE_DATA_DIR / "skill_pool.csv"


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
    add_routing_args(route, title_dictionary_required=False, default_title_dictionary=BASE_TITLE_DICTIONARY)
    route.add_argument("--job-title", required=True)

    process = subparsers.add_parser("process-one", help="Route and update one posting if it is an existing job.")
    add_routing_args(process, title_dictionary_required=False, default_title_dictionary=BASE_TITLE_DICTIONARY)
    process.add_argument("--event-stream", type=Path, default=BASE_EVENT_STREAM)
    process.add_argument("--frequency-output", type=Path, default=BASE_FREQUENCY_OUTPUT)
    process.add_argument(
        "--skill-pool",
        type=Path,
        default=BASE_SKILL_POOL,
        help="Skill pool CSV. Defaults to the initialized base skill_pool.csv.",
    )
    process.add_argument("--job-id", default=None, help="Optional. Generated automatically when omitted.")
    process.add_argument("--month", required=True)
    process.add_argument("--job-title", required=True)
    process.add_argument("--responsibility", default="")
    process.add_argument("--requirement", default="")
    process.add_argument("--source", default="manual_cli", help="Source label written to skill_pool.")
    process.add_argument(
        "--skills-json",
        default="[]",
        help="Debug-only JSON list. Each item must include normalized_skill and kg_display_skill.",
    )
    process.add_argument(
        "--skills-json-file",
        type=Path,
        default=None,
        help="Debug-only JSON file. Same schema as --skills-json.",
    )
    process.add_argument(
        "--skills",
        default="",
        help="Semicolon-separated raw skill keywords. They are normalized via skill_extract before use.",
    )
    process.add_argument("--dry-run", action="store_true")
    process.add_argument("--skill-provider", choices=["deepseek", "gpt"], default="deepseek")
    process.add_argument("--skill-model", default=None)
    process.add_argument("--skill-base-url", default=None)
    process.add_argument("--skill-api-key-env", default=None)
    process.add_argument("--skill-gold", type=Path, default=None)
    process.add_argument("--skill-cache", type=Path, default=None)
    process.add_argument("--skill-timeout", type=int, default=90)
    process.add_argument("--skill-retries", type=int, default=2)

    submit = subparsers.add_parser(
        "submit-one",
        help="Submit one real posting to the initialized base dataset.",
    )
    submit.add_argument("--job-title", required=True)
    submit.add_argument("--month", required=True)
    submit.add_argument("--responsibility", default="")
    submit.add_argument("--responsibility-file", type=Path, default=None)
    submit.add_argument("--requirement", default="")
    submit.add_argument("--requirement-file", type=Path, default=None)
    submit.add_argument("--job-id", default=None, help="Optional. Generated automatically when omitted.")
    submit.add_argument("--source", default="user_submission")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--title-dictionary", type=Path, default=BASE_TITLE_DICTIONARY)
    submit.add_argument("--event-stream", type=Path, default=BASE_EVENT_STREAM)
    submit.add_argument("--frequency-output", type=Path, default=BASE_FREQUENCY_OUTPUT)
    submit.add_argument("--skill-pool", type=Path, default=BASE_SKILL_POOL)
    submit.add_argument("--category-threshold", type=float, default=0.6)
    submit.add_argument("--job-threshold", type=float, default=0.85)
    submit.add_argument("--tie-delta", type=float, default=0.03)
    submit.add_argument("--text2vec-model", default="shibing624/text2vec-base-chinese")
    submit.add_argument("--quiet", action="store_true", help="Only print the final JSON result.")
    add_title_cleaning_args(submit)
    submit.add_argument("--skill-provider", choices=["deepseek", "gpt"], default="deepseek")
    submit.add_argument("--skill-model", default=None)
    submit.add_argument("--skill-base-url", default=None)
    submit.add_argument("--skill-api-key-env", default=None)
    submit.add_argument("--skill-gold", type=Path, default=None)
    submit.add_argument("--skill-cache", type=Path, default=None)
    submit.add_argument("--skill-timeout", type=int, default=90)
    submit.add_argument("--skill-retries", type=int, default=2)

    args = parser.parse_args()
    progress = build_progress_logger(args)
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

    if args.command == "submit-one":
        args.responsibility = read_text_arg(args.responsibility, args.responsibility_file)
        args.requirement = read_text_arg(args.requirement, args.requirement_file)
        args.job_id = args.job_id or generate_job_id(args.month, args.job_title)
        progress(f"input: generated job_id={args.job_id}")
    elif args.command == "process-one" and not args.job_id:
        args.job_id = generate_job_id(args.month, args.job_title)
        progress(f"input: generated job_id={args.job_id}")

    progress(f"taxonomy: loading title dictionary from {args.title_dictionary}")
    taxonomy = JobTaxonomy.from_csv(args.title_dictionary)
    progress(
        f"taxonomy: loaded {len(taxonomy.jobs)} standard jobs in "
        f"{len(taxonomy.jobs_by_category)} categories"
    )
    progress(f"text2vec: loading model {args.text2vec_model}")
    similarity = build_similarity(args)
    progress("text2vec: model ready")
    progress(f"title_cleaning: initializing cleaner provider={args.title_clean_provider}")
    title_cleaner = build_title_cleaner(args)
    progress("title_cleaning: cleaner ready")

    if args.command == "route":
        progress(f"title_cleaning: raw={args.job_title}")
        routing_job_title = run_with_heartbeat(
            progress,
            "title_cleaning",
            lambda: title_cleaner.clean(args.job_title),
        )
        progress(f"title_cleaning: cleaned={routing_job_title}")
        progress(f"routing: job_title={routing_job_title}")
        result = taxonomy.route(
            routing_job_title,
            similarity=similarity,
            category_threshold=args.category_threshold,
            job_threshold=args.job_threshold,
            tie_delta=args.tie_delta,
        )
        progress(f"done: route status={result.status}")
        print(
            json.dumps(
                {
                    "job_title": args.job_title,
                    "routing_job_title": routing_job_title,
                    "route": serialize_route(result),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command in {"process-one", "submit-one"}:
        progress(f"input: job_id={args.job_id}, month={args.month}, job_title={args.job_title}")
        skill_pool_path = resolve_skill_pool_path(args)
        progress(f"skill_pool: target={skill_pool_path}")
        skills = parse_skills(read_skills_json_arg(args)) if args.command == "process-one" else []
        raw_skill_keywords = parse_skill_keywords(args.skills) if args.command == "process-one" else []
        if skills and raw_skill_keywords:
            raise ValueError("Use either --skills-json/--skills-json-file or --skills, not both.")
        progress(f"skills: parsed {len(skills)} supplied final normalized skills")
        progress(f"skills: parsed {len(raw_skill_keywords)} supplied raw skill keywords")
        skill_extractor = None
        if raw_skill_keywords:
            progress("skills: raw skill keywords will be normalized after existing-job routing")
            skill_extractor = ManualSkillKeywordExtractor(
                build_manual_skill_normalizer(args),
                raw_skill_keywords,
            )
        elif not skills:
            progress(f"skills: initializing skill_extract adapter provider={args.skill_provider}")
            skill_extractor = build_skill_extractor(args)
            progress("skills: skill_extract adapter ready")
        system = JobUpdateSystem(
            taxonomy=taxonomy,
            frequency_store=FrequencyStore(args.event_stream, args.frequency_output),
            skill_pool_store=SkillPoolStore(skill_pool_path),
            similarity=similarity,
            title_cleaner=title_cleaner,
            skill_extractor=skill_extractor,
            category_threshold=args.category_threshold,
            job_threshold=args.job_threshold,
            tie_delta=args.tie_delta,
            progress=progress,
        )
        posting = JobPosting(
            job_id=args.job_id,
            month=args.month,
            job_title=args.job_title,
            job_responsibility=args.responsibility,
            job_requirement=args.requirement,
            skills=skills,
            metadata={"source": args.source},
        )
        progress(f"process: dry_run={args.dry_run}")
        result = system.process(posting, write=not args.dry_run)
        progress(f"done: {args.command} completed")
        print(json.dumps(serialize_process_result(result), ensure_ascii=False, indent=2))
        return


def add_routing_args(
    parser: argparse.ArgumentParser,
    *,
    title_dictionary_required: bool = True,
    default_title_dictionary: Path | None = None,
) -> None:
    parser.add_argument(
        "--title-dictionary",
        required=title_dictionary_required,
        type=Path,
        default=default_title_dictionary,
    )
    parser.add_argument("--category-threshold", type=float, default=0.6)
    parser.add_argument("--job-threshold", type=float, default=0.85)
    parser.add_argument("--tie-delta", type=float, default=0.03)
    parser.add_argument("--text2vec-model", default="shibing624/text2vec-base-chinese")
    parser.add_argument("--quiet", action="store_true", help="Only print the final JSON result.")
    add_title_cleaning_args(parser)


def add_title_cleaning_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title-clean-provider", choices=["deepseek", "gpt"], default="deepseek")
    parser.add_argument("--title-clean-model", default=None)
    parser.add_argument("--title-clean-base-url", default=None)
    parser.add_argument("--title-clean-api-key-env", default=None)
    parser.add_argument("--title-clean-timeout", type=int, default=60)
    parser.add_argument("--title-clean-retries", type=int, default=2)


def read_text_arg(inline_text: str, file_path: Path | None) -> str:
    if file_path is None:
        return inline_text
    if clean_text(inline_text):
        raise ValueError("Use either inline text or a text file for the same field, not both.")
    return file_path.read_text(encoding="utf-8-sig")


def generate_job_id(month: str, job_title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    title = clean_text(job_title)
    slug = re.sub(r"[^0-9A-Za-z]+", "_", title).strip("_").lower()
    if not slug:
        slug = "job"
    slug = slug[:24]
    digest = hashlib.sha1(f"{month}|{title}|{timestamp}".encode("utf-8")).hexdigest()[:8]
    return f"user_{clean_text(month).replace('-', '')}_{timestamp}_{slug}_{digest}"


def build_similarity(args: argparse.Namespace):
    return Text2VecSimilarity(args.text2vec_model)


def build_title_cleaner(args: argparse.Namespace) -> LLMTitleCleaner:
    return LLMTitleCleaner(
        provider=args.title_clean_provider,
        model=args.title_clean_model,
        base_url=args.title_clean_base_url,
        api_key_env=args.title_clean_api_key_env,
        timeout=args.title_clean_timeout,
        retries=args.title_clean_retries,
    )


def run_with_heartbeat(progress, stage: str, action):
    done = threading.Event()

    def heartbeat() -> None:
        waited_seconds = 0
        while not done.wait(10):
            waited_seconds += 10
            progress(f"{stage}: still waiting for API/model response ({waited_seconds}s elapsed)")

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    started_at = time.perf_counter()
    try:
        return action()
    finally:
        done.set()
        elapsed = time.perf_counter() - started_at
        if elapsed >= 1:
            progress(f"{stage}: stage finished in {elapsed:.1f}s")


def build_progress_logger(args: argparse.Namespace):
    if getattr(args, "quiet", False):
        return lambda message: None

    def progress(message: str) -> None:
        print(f"[job_update] {message}", file=sys.stderr, flush=True)

    return progress


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


def build_manual_skill_normalizer(args: argparse.Namespace) -> ManualSkillNormalizeAdapter:
    return ManualSkillNormalizeAdapter(
        provider=args.skill_provider,
        model=args.skill_model,
        base_url=args.skill_base_url,
        api_key_env=args.skill_api_key_env,
        timeout=args.skill_timeout,
        retries=args.skill_retries,
    )


def resolve_skill_pool_path(args: argparse.Namespace) -> Path:
    if args.skill_pool is not None:
        return args.skill_pool
    return args.frequency_output.parent / "skill_pool.csv"


def read_skills_json_arg(args: argparse.Namespace) -> str:
    if args.skills_json_file is not None:
        return args.skills_json_file.read_text(encoding="utf-8-sig")
    return args.skills_json


def parse_skill_keywords(skills_text: str) -> list[str]:
    return [item.strip() for item in str(skills_text or "").split(";") if item.strip()]


def parse_skills(skills_json: str) -> list[SkillMention]:
    parsed: Any = json.loads(skills_json)
    if not parsed:
        return []
    if not isinstance(parsed, list):
        raise ValueError("--skills-json must be a JSON list")
    return [skill_from_dict(item) for item in parsed]


def skill_from_dict(item: Any) -> SkillMention:
    if not isinstance(item, dict):
        raise ValueError("Each --skills-json item must be an object")
    normalized_skill = clean_text(item.get("normalized_skill"))
    kg_display_skill = clean_text(item.get("kg_display_skill"))
    if not normalized_skill or not kg_display_skill:
        raise ValueError("Each --skills-json item must include normalized_skill and kg_display_skill")
    return SkillMention(
        normalized_skill=normalized_skill,
        kg_display_skill=kg_display_skill,
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
        "routing_job_title": result.posting.routing_job_title,
        "route": serialize_route(result.route),
        "updated": result.update is not None,
    }
    if result.update is not None:
        payload["update"] = {
            "standard_job": result.update.standard_job,
            "month": result.update.month,
            "skills": [
                {
                    "normalized_skill": skill.normalized_skill,
                    "kg_display_skill": skill.kg_display_skill,
                }
                for skill in result.update.normalized_skills
            ],
            "monthly_rows": result.update.monthly_rows,
            "frequency_rows": result.update.frequency_rows,
            "skill_pool_rows": result.update.skill_pool_rows,
            "event_stream_path": result.update.event_stream_path,
            "frequency_path": result.update.frequency_path,
            "skill_pool_path": result.update.skill_pool_path,
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
