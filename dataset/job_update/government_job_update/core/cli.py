from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from company_job_update.core.frequency_store import FREQUENCY_COLUMNS, rebuild_frequency_table
from company_job_update.core.job_profile import JOB_PROFILE_DIFF_COLUMNS, JOB_PROFILE_SNAPSHOT_COLUMNS
from company_job_update.core.job_profile_store import JobProfileStore
from company_job_update.core.models import JobPosting
from company_job_update.core.review_queue import create_pending_reviews, serialize_process_result
from company_job_update.core.service import JobUpdateSystem
from company_job_update.core.skill_lifecycle import LIFECYCLE_COLUMNS
from company_job_update.core.skill_migration import SKILL_JOB_MONTHLY_SPREAD_COLUMNS, SKILL_MIGRATION_COLUMNS
from company_job_update.core.skill_migration_store import SkillMigrationStore
from company_job_update.core.skill_pool_store import SKILL_POOL_COLUMNS, SkillPoolStore

from .config import (
    DEFAULT_BUILD_AUDIT,
    DEFAULT_CURRENT_PROFILE,
    DEFAULT_DATABASE,
    DEFAULT_EVENT_STREAM,
    DEFAULT_FREQUENCY_OUTPUT,
    DEFAULT_INITIAL_ASSIGNMENT,
    DEFAULT_INITIAL_ASSIGNMENT_REVIEW,
    DEFAULT_JOB_PROFILE_DIFF,
    DEFAULT_JOB_PROFILE_SNAPSHOTS,
    DEFAULT_JOB_DICTIONARY,
    DEFAULT_NORMALIZED_POSTINGS,
    DEFAULT_RAW_EVENT_STREAM,
    DEFAULT_ROUTE_REVIEW,
    DEFAULT_SKILL_EXTRACTION_CACHE,
    DEFAULT_SKILL_EXTRACTION_DICTIONARY,
    DEFAULT_SKILL_JOB_MONTHLY_SPREAD,
    DEFAULT_SKILL_LIFECYCLE,
    DEFAULT_SKILL_MIGRATION,
    DEFAULT_SKILL_NORMALIZATION_CACHE,
    DEFAULT_SKILL_POOL,
    DEFAULT_SOURCE_INPUT,
    DEFAULT_TEXT2VEC_MODEL,
    DEFAULT_TITLE_CLEANED_POSTINGS,
    DEFAULT_TITLE_CLEANING_AUDIT,
    DEFAULT_TITLE_CLEANING_CACHE,
)
from .event_builder import build_government_event_stream, write_government_event_build
from .database import GovernmentSQLiteStore
from .current_profile import GovernmentCurrentProfileStore
from .frequency_store import GOVERNMENT_EVENT_COLUMNS, GovernmentFrequencyStore
from .initial_assignment import build_initial_assignment, build_initial_assignment_review
from .initial_state import build_government_initial_state
from .route_adjudication import GovernmentRouteAdjudicator
from .routing import GovernmentTaxonomy, build_government_route_review
from .review_queue import confirm_existing_review, list_pending_reviews, reject_review, submit_new_job_maintenance
from .skill_extraction import GovernmentSkillExtractAdapter
from .skill_lifecycle import GovernmentAnnualLifecycleStore
from .title_cleaning import GovernmentRoutingTitleCleaner, LLMGovernmentTitleCleaner, apply_government_title_cleaning
from shared.llm_json_client import JsonLLMClient
from shared.similarity import Text2VecSimilarity


def main() -> None:
    parser = argparse.ArgumentParser(description="Government technical-job update system.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-event-stream", help="Build the real-time government raw event stream.")
    build.add_argument("--input", type=Path, default=DEFAULT_SOURCE_INPUT)
    build.add_argument("--normalized-output", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    build.add_argument("--event-output", type=Path, default=DEFAULT_RAW_EVENT_STREAM)
    build.add_argument("--audit-output", type=Path, default=DEFAULT_BUILD_AUDIT)
    route = subparsers.add_parser("route-postings", help=argparse.SUPPRESS)
    route.add_argument("--postings", type=Path, default=DEFAULT_TITLE_CLEANED_POSTINGS)
    route.add_argument("--title-dictionary", type=Path, default=DEFAULT_JOB_DICTIONARY)
    route.add_argument("--output", type=Path, default=DEFAULT_ROUTE_REVIEW)
    route.add_argument("--top-k", type=int, default=5)
    route.add_argument("--candidate-floor", type=float, default=0.45)
    route.add_argument("--text2vec-model", default=DEFAULT_TEXT2VEC_MODEL)
    initial_assignment = subparsers.add_parser(
        "build-initial-assignment",
        help="Build the historical government job mapping from seed taxonomy rules, without text2vec.",
    )
    initial_assignment.add_argument("--postings", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    initial_assignment.add_argument("--title-dictionary", type=Path, default=DEFAULT_JOB_DICTIONARY)
    initial_assignment.add_argument("--output", type=Path, default=DEFAULT_INITIAL_ASSIGNMENT)
    assignment_review = subparsers.add_parser(
        "export-initial-assignment-review",
        help="Export low-confidence government initial job mappings for human audit.",
    )
    assignment_review.add_argument("--postings", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    assignment_review.add_argument("--assignment", type=Path, default=DEFAULT_INITIAL_ASSIGNMENT)
    assignment_review.add_argument("--output", type=Path, default=DEFAULT_INITIAL_ASSIGNMENT_REVIEW)
    bootstrap = subparsers.add_parser(
        "bootstrap-initial-state",
        help="Build all government base CSV and SQLite state from seed assignments and seed skill dictionaries.",
    )
    bootstrap.add_argument("--postings", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    bootstrap.add_argument("--assignment", type=Path, default=DEFAULT_INITIAL_ASSIGNMENT)
    bootstrap.add_argument("--skill-dictionary", type=Path, default=DEFAULT_SKILL_EXTRACTION_DICTIONARY)
    clean_titles = subparsers.add_parser("clean-titles", help=argparse.SUPPRESS)
    clean_titles.add_argument("--postings", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    clean_titles.add_argument("--output", type=Path, default=DEFAULT_TITLE_CLEANED_POSTINGS)
    clean_titles.add_argument("--audit-output", type=Path, default=DEFAULT_TITLE_CLEANING_AUDIT)
    clean_titles.add_argument("--cache", type=Path, default=DEFAULT_TITLE_CLEANING_CACHE)
    clean_titles.add_argument("--provider", choices=["deepseek", "gpt"], default="deepseek")
    clean_titles.add_argument("--model", default=None)
    clean_titles.add_argument("--base-url", default=None)
    clean_titles.add_argument("--api-key-env", default=None)
    clean_titles.add_argument("--timeout", type=int, default=90)
    clean_titles.add_argument("--retries", type=int, default=2)
    clean_titles.add_argument("--workers", type=int, default=8)
    submit = subparsers.add_parser("submit-one", help="Process one government JD through the full update workflow.")
    submit.add_argument("--job-id", default=None, help="Optional. Generated automatically when omitted.")
    submit.add_argument("--month", required=True, help="Real publication month, YYYY-MM.")
    submit.add_argument("--job-title", required=True)
    submit.add_argument("--responsibility", default="")
    submit.add_argument("--requirement", default="")
    submit.add_argument("--source", default="government_user_submission")
    submit.add_argument("--source-name", default="")
    submit.add_argument("--publish-time", default="")
    submit.add_argument("--recruitment-year", default="")
    submit.add_argument("--source-url", default="")
    submit.add_argument("--government-agency", default="")
    submit.add_argument("--government-department", default="")
    submit.add_argument("--location", default="")
    submit.add_argument("--mode", choices=["auto", "manual"], default="auto")
    submit.add_argument("--dry-run", action="store_true")
    submit.add_argument("--category-threshold", type=float, default=0.58)
    submit.add_argument("--job-threshold", type=float, default=0.82)
    submit.add_argument("--tie-delta", type=float, default=0.03)
    submit.add_argument("--llm-job-floor", type=float, default=0.58)
    submit.add_argument("--llm-top-jobs", type=int, default=10)
    submit.add_argument("--llm-accept-rank-limit", type=int, default=1)
    submit.add_argument("--llm-selected-job-floor", type=float, default=0.75)
    submit.add_argument("--llm-min-confidence", type=float, default=0.80)
    submit.add_argument("--llm-uncertain-take-top1-threshold", type=float, default=0.82)
    submit.add_argument("--text2vec-model", default=DEFAULT_TEXT2VEC_MODEL)
    _add_llm_args(submit)
    init_db = subparsers.add_parser("init-db", help="Initialize the independent government SQLite database.")
    init_db.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    export_csv = subparsers.add_parser("export-csv", help="Export government SQLite state to government CSV files.")
    export_csv.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    rebuild = subparsers.add_parser("rebuild-analytics", help="Rebuild government frequency, lifecycle, migration, and profiles.")
    rebuild.add_argument("--event-stream", type=Path, default=DEFAULT_EVENT_STREAM)
    rebuild.add_argument("--frequency-output", type=Path, default=DEFAULT_FREQUENCY_OUTPUT)
    review_list = subparsers.add_parser("list-reviews", help="List pending government manual review items.")
    review_list.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    review_reject = subparsers.add_parser("reject-review", help="Reject a pending government review item.")
    review_reject.add_argument("--review-id", required=True)
    review_reject.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    review_existing = subparsers.add_parser("confirm-existing-review", help="Confirm an existing government job and write all updates.")
    review_existing.add_argument("--review-id", required=True)
    review_existing.add_argument("--standard-job", default="")
    review_existing.add_argument("--skills-json-file", type=Path, default=None)
    review_existing.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    review_new = subparsers.add_parser("submit-new-job-review", help="Submit a government new-job dictionary maintenance proposal.")
    review_new.add_argument("--review-id", required=True)
    review_new.add_argument("--standard-category", required=True)
    review_new.add_argument("--standard-job", required=True)
    review_new.add_argument("--match-keywords", default="")
    review_new.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    ingest = subparsers.add_parser("ingest-history", help=argparse.SUPPRESS)
    ingest.add_argument("--postings", type=Path, default=DEFAULT_NORMALIZED_POSTINGS)
    ingest.add_argument("--assignment", type=Path, default=DEFAULT_INITIAL_ASSIGNMENT)
    ingest.add_argument("--limit", type=int, default=None, help="Optional row limit for a controlled trial.")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--category-threshold", type=float, default=0.58)
    ingest.add_argument("--job-threshold", type=float, default=0.82)
    ingest.add_argument("--tie-delta", type=float, default=0.03)
    ingest.add_argument("--llm-job-floor", type=float, default=0.58)
    ingest.add_argument("--llm-top-jobs", type=int, default=10)
    ingest.add_argument("--llm-accept-rank-limit", type=int, default=1)
    ingest.add_argument("--llm-selected-job-floor", type=float, default=0.75)
    ingest.add_argument("--llm-min-confidence", type=float, default=0.80)
    ingest.add_argument("--llm-uncertain-take-top1-threshold", type=float, default=0.82)
    _add_llm_args(ingest)
    # Historical initialization is rule-mapped; legacy batch-routing commands
    # are deliberately removed from the public CLI.
    for legacy_command in ("route-postings", "clean-titles", "ingest-history"):
        subparsers.choices.pop(legacy_command, None)
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions
        if action.dest not in {"route-postings", "clean-titles", "ingest-history"}
    ]
    args = parser.parse_args()

    if args.command == "build-event-stream":
        source = pd.read_csv(args.input, dtype=str, encoding="utf-8-sig").fillna("")
        result = build_government_event_stream(source)
        write_government_event_build(
            result,
            normalized_postings_path=args.normalized_output,
            raw_event_stream_path=args.event_output,
            audit_path=args.audit_output,
        )
        print(
            json.dumps(
                {
                    **result.audit,
                    "input": str(args.input),
                    "normalized_output": str(args.normalized_output),
                    "event_output": str(args.event_output),
                    "audit_output": str(args.audit_output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "init-db":
        _ensure_government_base_files()
        counts = GovernmentSQLiteStore(args.database).initialize_from_csv(**_database_paths())
        print(json.dumps({"database": str(args.database), "initialized": counts}, ensure_ascii=False, indent=2))
        return

    if args.command == "export-csv":
        _ensure_government_base_files()
        counts = GovernmentSQLiteStore(args.database).export_to_csv(**_database_paths())
        print(json.dumps({"database": str(args.database), "exported": counts}, ensure_ascii=False, indent=2))
        return

    if args.command == "rebuild-analytics":
        events = GovernmentFrequencyStore(args.event_stream, args.frequency_output).load_events()
        frequency = rebuild_frequency_table(events)
        pool = SkillPoolStore(DEFAULT_SKILL_POOL).load()
        GovernmentFrequencyStore(args.event_stream, args.frequency_output).write_tables(events, frequency)
        lifecycle = GovernmentAnnualLifecycleStore(DEFAULT_SKILL_LIFECYCLE).rebuild(
            frequency=frequency, skill_pool=pool, write=True
        )
        migration, spread = SkillMigrationStore(
            DEFAULT_SKILL_MIGRATION, DEFAULT_SKILL_JOB_MONTHLY_SPREAD
        ).rebuild(frequency=frequency, skill_pool=pool, write=True)
        snapshots, diffs = JobProfileStore(
            DEFAULT_JOB_PROFILE_SNAPSHOTS, DEFAULT_JOB_PROFILE_DIFF
        ).rebuild(frequency=frequency, skill_pool=pool, write=True)
        current_profile = GovernmentCurrentProfileStore(DEFAULT_CURRENT_PROFILE).rebuild(snapshots=snapshots, write=True)
        print(json.dumps({"event_rows": len(events), "frequency_rows": len(frequency), "lifecycle_rows": len(lifecycle), "migration_rows": len(migration), "spread_rows": len(spread), "profile_snapshot_rows": len(snapshots), "profile_diff_rows": len(diffs), "current_profile_rows": len(current_profile)}, ensure_ascii=False, indent=2))
        return

    if args.command == "list-reviews":
        print(json.dumps(list_pending_reviews(args.database), ensure_ascii=False, indent=2))
        return

    if args.command == "reject-review":
        print(json.dumps(reject_review(args.review_id, args.database), ensure_ascii=False, indent=2))
        return

    if args.command == "confirm-existing-review":
        skills = None
        if args.skills_json_file is not None:
            skills = json.loads(args.skills_json_file.read_text(encoding="utf-8"))
        print(json.dumps(confirm_existing_review(args.review_id, standard_job_title=args.standard_job, skills=skills, database_path=args.database), ensure_ascii=False, indent=2))
        return

    if args.command == "submit-new-job-review":
        print(json.dumps(submit_new_job_maintenance(args.review_id, standard_category=args.standard_category, standard_job_title=args.standard_job, match_keywords=args.match_keywords, database_path=args.database), ensure_ascii=False, indent=2))
        return

    if args.command == "submit-one":
        _submit_one(args)
        return

    if args.command == "ingest-history":
        _ingest_history(args)
        return

    if args.command == "route-postings":
        postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
        taxonomy = GovernmentTaxonomy.from_csv(args.title_dictionary)
        print(f"text2vec: loading model {args.text2vec_model}", flush=True)
        similarity = Text2VecSimilarity(args.text2vec_model)
        print(f"routing: scoring {len(postings)} government postings against {len(taxonomy.jobs)} standard jobs", flush=True)
        review = build_government_route_review(
            postings,
            taxonomy=taxonomy,
            similarity=similarity,
            top_k=args.top_k,
            candidate_floor=args.candidate_floor,
            progress=lambda completed, total: print(
                f"routing: text2vec encoded {completed}/{total} government postings", flush=True
            ),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        review.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(
            json.dumps(
                {
                    "rows": len(review),
                    "route_status_counts": review["route_status"].value_counts().to_dict(),
                    "output": str(args.output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "build-initial-assignment":
        postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
        print(f"initial_assignment: applying seed taxonomy rules to {len(postings)} government postings", flush=True)
        assignment = build_initial_assignment(postings, args.title_dictionary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        assignment.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(
            json.dumps(
                {
                    "rows": len(assignment),
                    "status_counts": assignment["assignment_status"].value_counts().to_dict(),
                    "standard_job_counts": assignment["assigned_standard_job"].value_counts().to_dict(),
                    "output": str(args.output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "export-initial-assignment-review":
        postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
        assignments = pd.read_csv(args.assignment, dtype=str, encoding="utf-8-sig").fillna("")
        review = build_initial_assignment_review(postings, assignments)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        review.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(json.dumps({"rows": len(review), "output": str(args.output)}, ensure_ascii=False, indent=2))
        return

    if args.command == "bootstrap-initial-state":
        postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
        assignments = pd.read_csv(args.assignment, dtype=str, encoding="utf-8-sig").fillna("")
        skill_dictionary = pd.read_csv(args.skill_dictionary, dtype=str, encoding="utf-8-sig").fillna("")
        print(f"bootstrap: building all government base state from {len(postings)} seed-mapped postings", flush=True)
        summary = build_government_initial_state(
            postings=postings,
            assignments=assignments,
            skill_dictionary=skill_dictionary,
            event_stream_path=DEFAULT_EVENT_STREAM,
            frequency_path=DEFAULT_FREQUENCY_OUTPUT,
            skill_pool_path=DEFAULT_SKILL_POOL,
            lifecycle_path=DEFAULT_SKILL_LIFECYCLE,
            migration_path=DEFAULT_SKILL_MIGRATION,
            spread_path=DEFAULT_SKILL_JOB_MONTHLY_SPREAD,
            snapshot_path=DEFAULT_JOB_PROFILE_SNAPSHOTS,
            diff_path=DEFAULT_JOB_PROFILE_DIFF,
            current_profile_path=DEFAULT_CURRENT_PROFILE,
            database_path=DEFAULT_DATABASE,
            title_dictionary_path=DEFAULT_JOB_DICTIONARY,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.command == "clean-titles":
        postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
        print(f"title_cleaning: processing {postings['job_title'].nunique()} unique government titles", flush=True)
        cleaner = LLMGovernmentTitleCleaner(
            JsonLLMClient(
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                api_key_env=args.api_key_env,
                timeout=args.timeout,
                retries=args.retries,
            )
        )
        cleaned, audit = apply_government_title_cleaning(
            postings,
            cleaner=cleaner,
            cache_path=args.cache,
            workers=args.workers,
            progress=lambda completed, total: (
                print(
                    f"title_cleaning: completed {completed}/{total} unique government titles",
                    flush=True,
                )
                if completed == 1 or completed == total or completed % 25 == 0
                else None
            ),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        cleaned.to_csv(args.output, index=False, encoding="utf-8-sig")
        audit.to_csv(args.audit_output, index=False, encoding="utf-8-sig")
        print(
            json.dumps(
                {
                    "rows": len(cleaned),
                    "unique_titles": len(audit),
                    "output": str(args.output),
                    "audit_output": str(args.audit_output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["deepseek", "gpt"], default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)


def _database_paths() -> dict[str, Path]:
    return {
        "title_dictionary_path": DEFAULT_JOB_DICTIONARY,
        "event_stream_path": DEFAULT_EVENT_STREAM,
        "frequency_path": DEFAULT_FREQUENCY_OUTPUT,
        "skill_pool_path": DEFAULT_SKILL_POOL,
        "lifecycle_path": DEFAULT_SKILL_LIFECYCLE,
        "migration_path": DEFAULT_SKILL_MIGRATION,
        "spread_path": DEFAULT_SKILL_JOB_MONTHLY_SPREAD,
        "profile_snapshot_path": DEFAULT_JOB_PROFILE_SNAPSHOTS,
        "profile_diff_path": DEFAULT_JOB_PROFILE_DIFF,
    }


def _ensure_government_base_files() -> None:
    files = {
        DEFAULT_EVENT_STREAM: GOVERNMENT_EVENT_COLUMNS,
        DEFAULT_FREQUENCY_OUTPUT: FREQUENCY_COLUMNS,
        DEFAULT_SKILL_POOL: SKILL_POOL_COLUMNS,
        DEFAULT_SKILL_LIFECYCLE: LIFECYCLE_COLUMNS,
        DEFAULT_SKILL_MIGRATION: SKILL_MIGRATION_COLUMNS,
        DEFAULT_SKILL_JOB_MONTHLY_SPREAD: SKILL_JOB_MONTHLY_SPREAD_COLUMNS,
        DEFAULT_JOB_PROFILE_SNAPSHOTS: JOB_PROFILE_SNAPSHOT_COLUMNS,
        DEFAULT_JOB_PROFILE_DIFF: JOB_PROFILE_DIFF_COLUMNS,
    }
    for path, columns in files.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def _submit_one(args: argparse.Namespace) -> None:
    _ensure_government_base_files()
    job_id = args.job_id or f"GOV-SUB-{args.month.replace('-', '')}-{uuid4().hex[:10]}"
    print(f"input: job_id={job_id}, month={args.month}, title={args.job_title}", flush=True)
    database = GovernmentSQLiteStore(DEFAULT_DATABASE)
    system = _build_update_system(args, database)
    posting = JobPosting(
        job_id=job_id,
        month=args.month,
        job_title=args.job_title,
        job_responsibility=args.responsibility,
        job_requirement=args.requirement,
        metadata={
            "source": args.source,
            "source_name": args.source_name,
            "publish_time": args.publish_time,
            "recruitment_year": args.recruitment_year,
            "source_url": args.source_url,
            "government_agency": args.government_agency,
            "government_department": args.government_department,
            "location": args.location,
        },
    )
    if not args.dry_run:
        database.initialize_from_csv(**_database_paths())
    result = system.process(
        posting,
        write=not args.dry_run and args.mode == "auto",
        collect_skills_for_review=args.mode == "manual",
    )
    review = None
    if not args.dry_run and (args.mode == "manual" or result.route.status != "existing_job"):
        print("review_queue: writing government pending review items", flush=True)
        review = create_pending_reviews(
            store=database,
            submission_mode=args.mode,
            input_payload={
                "month": args.month,
                "job_title": args.job_title,
                "responsibility": args.responsibility,
                "requirement": args.requirement,
                "source": args.source,
            },
            result=result,
            skill_pool_path=DEFAULT_SKILL_POOL,
            always_queue_job=args.mode == "manual",
        )
    output = serialize_process_result(result, skill_pool_path=DEFAULT_SKILL_POOL)
    if review is not None:
        output["review_queue"] = {
            "job_review_id": review["job_review"]["item_id"] if review["job_review"] else "",
            "skill_review_ids": [item["item_id"] for item in review["skill_reviews"]],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _build_update_system(
    args: argparse.Namespace,
    database: GovernmentSQLiteStore,
    *,
    load_similarity: bool = True,
) -> JobUpdateSystem:
    taxonomy = GovernmentTaxonomy.from_csv(DEFAULT_JOB_DICTIONARY)
    print(f"taxonomy: loaded {len(taxonomy.jobs)} government standard jobs", flush=True)
    similarity = None
    if load_similarity:
        print(f"text2vec: loading model {args.text2vec_model}", flush=True)
        similarity = Text2VecSimilarity(args.text2vec_model)
        print("text2vec: model ready", flush=True)
    client = JsonLLMClient(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        timeout=args.timeout,
        retries=args.retries,
    )
    return JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=GovernmentFrequencyStore(DEFAULT_EVENT_STREAM, DEFAULT_FREQUENCY_OUTPUT),
        skill_pool_store=SkillPoolStore(DEFAULT_SKILL_POOL),
        skill_lifecycle_store=GovernmentAnnualLifecycleStore(DEFAULT_SKILL_LIFECYCLE),
        skill_migration_store=SkillMigrationStore(DEFAULT_SKILL_MIGRATION, DEFAULT_SKILL_JOB_MONTHLY_SPREAD),
        job_profile_store=JobProfileStore(DEFAULT_JOB_PROFILE_SNAPSHOTS, DEFAULT_JOB_PROFILE_DIFF),
        current_profile_store=GovernmentCurrentProfileStore(DEFAULT_CURRENT_PROFILE),
        database_store=database,
        similarity=similarity,
        route_adjudicator=GovernmentRouteAdjudicator(client),
        title_cleaner=GovernmentRoutingTitleCleaner(LLMGovernmentTitleCleaner(client)),
        skill_extractor=GovernmentSkillExtractAdapter(
            extraction_dictionary=DEFAULT_SKILL_EXTRACTION_DICTIONARY,
            cache_path=DEFAULT_SKILL_EXTRACTION_CACHE,
            normalization_cache_path=DEFAULT_SKILL_NORMALIZATION_CACHE,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            timeout=args.timeout,
            retries=args.retries,
        ),
        category_threshold=args.category_threshold,
        job_threshold=args.job_threshold,
        tie_delta=args.tie_delta,
        llm_job_floor=args.llm_job_floor,
        llm_top_jobs=args.llm_top_jobs,
        llm_accept_rank_limit=args.llm_accept_rank_limit,
        llm_selected_job_floor=args.llm_selected_job_floor,
        llm_min_confidence=args.llm_min_confidence,
        llm_uncertain_take_top1_threshold=args.llm_uncertain_take_top1_threshold,
        progress=lambda message: print(message, flush=True),
    )


def _ingest_history(args: argparse.Namespace) -> None:
    _ensure_government_base_files()
    if not args.postings.exists():
        raise FileNotFoundError(
            f"Missing normalized government postings: {args.postings}. Run build-event-stream first."
        )
    if not args.assignment.exists():
        raise FileNotFoundError(
            f"Missing initial job assignment: {args.assignment}. Run build-initial-assignment first."
        )
    postings = pd.read_csv(args.postings, dtype=str, encoding="utf-8-sig").fillna("")
    assignments = pd.read_csv(args.assignment, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"job_id", "month", "job_title"}
    missing = sorted(required.difference(postings.columns))
    if missing:
        raise ValueError(f"Normalized government postings missing columns: {missing}")
    assignment_required = {"job_id", "assigned_standard_category", "assigned_standard_job"}
    assignment_missing = sorted(assignment_required.difference(assignments.columns))
    if assignment_missing:
        raise ValueError(f"Initial assignment missing columns: {assignment_missing}")
    postings = postings.merge(assignments[list(assignment_required)], on="job_id", how="left", validate="one_to_one")
    if (postings["assigned_standard_job"].astype(str).str.strip() == "").any():
        raise ValueError("Initial assignment does not cover every normalized government posting.")
    if args.limit is not None:
        postings = postings.head(args.limit)
    print(f"history: processing {len(postings)} seed-mapped government postings without title routing", flush=True)
    database = GovernmentSQLiteStore(DEFAULT_DATABASE)
    if not args.dry_run:
        database.initialize_from_csv(**_database_paths())
    system = _build_update_system(args, database, load_similarity=False)
    existing_ids = set(GovernmentFrequencyStore(DEFAULT_EVENT_STREAM).load_events()["job_id"].astype(str))
    counts = {"processed": 0, "skipped_existing": 0, "existing_job": 0, "potential_new_job": 0, "new_family": 0, "queued_reviews": 0}
    for index, (_, row) in enumerate(postings.iterrows(), start=1):
        job_id = str(row.get("job_id") or "").strip()
        if job_id in existing_ids:
            counts["skipped_existing"] += 1
            continue
        posting = JobPosting(
            job_id=job_id,
            month=str(row.get("month") or "").strip(),
            job_title=str(row.get("job_title") or "").strip(),
            job_responsibility=str(row.get("job_responsibility") or "").strip(),
            job_requirement=str(row.get("job_requirement") or "").strip(),
            metadata={
                "source": str(row.get("source") or "government"),
                "source_name": str(row.get("source_name") or ""),
                "publish_time": str(row.get("publish_time") or ""),
                "recruitment_year": str(row.get("recruitment_year") or ""),
                "source_url": str(row.get("source_url") or ""),
                "government_agency": str(row.get("government_agency") or ""),
                "government_department": str(row.get("government_department") or ""),
                "location": str(row.get("location") or ""),
            },
        )
        result = system.process(
            posting,
            write=not args.dry_run,
            confirmed_standard_job=str(row.get("assigned_standard_job") or "").strip(),
            confirmed_standard_category=str(row.get("assigned_standard_category") or "").strip(),
        )
        counts["processed"] += 1
        counts[result.route.status] += 1
        if result.update is not None:
            existing_ids.add(job_id)
        if index == 1 or index == len(postings) or index % 25 == 0:
            print(f"history: completed {index}/{len(postings)} postings", flush=True)
    print(json.dumps({**counts, "dry_run": args.dry_run, "formal_event_stream": str(DEFAULT_EVENT_STREAM), "database": str(DEFAULT_DATABASE)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
