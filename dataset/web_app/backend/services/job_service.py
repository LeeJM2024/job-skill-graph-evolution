from __future__ import annotations

from datetime import datetime
import hashlib
import os
import re
import sys
from typing import Any
from uuid import uuid4

import pandas as pd

from .backup_service import create_backup
from .paths import (
    BASE_DATABASE,
    BASE_EVENT_STREAM,
    BASE_FREQUENCY_OUTPUT,
    BASE_SKILL_POOL,
    BASE_SKILL_LIFECYCLE,
    BASE_SKILL_MIGRATION,
    BASE_SKILL_MONTHLY_SPREAD,
    BASE_JOB_PROFILE_DIFF,
    BASE_JOB_PROFILE_SNAPSHOTS,
    BASE_TITLE_DICTIONARY,
    DATASET_ROOT,
    JOB_UPDATE_ROOT,
)

for path in (DATASET_ROOT, JOB_UPDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from company_job_update.core.database import SQLiteJobUpdateStore
from company_job_update.core.frequency_store import FrequencyStore
from company_job_update.core.models import JobPosting, ProcessResult
from company_job_update.core.route_adjudication import LLMRouteAdjudicator
from company_job_update.core.service import JobUpdateSystem
from company_job_update.core.similarity import Text2VecSimilarity
from company_job_update.core.skill_extraction import ExistingSkillExtractAdapter
from company_job_update.core.skill_pool_store import SkillPoolStore
from company_job_update.core.skill_lifecycle_store import SkillLifecycleStore
from company_job_update.core.skill_migration_store import SkillMigrationStore
from company_job_update.core.job_profile_store import JobProfileStore
from company_job_update.core.review_queue import (
    create_pending_reviews,
    serialize_process_result as serialize_review_process_result,
    skill_mentions_from_decisions,
)
from company_job_update.core.taxonomy import JobTaxonomy
from company_job_update.core.text import clean_text
from company_job_update.core.title_cleaning import LLMTitleCleaner


CATEGORY_THRESHOLD = 0.58
JOB_THRESHOLD = 0.82
TIE_DELTA = 0.03
LLM_JOB_FLOOR = 0.58
LLM_TOP_JOBS = 20
LLM_ACCEPT_RANK_LIMIT = 1
LLM_SELECTED_JOB_FLOOR = 0.75
LLM_MIN_CONFIDENCE = 0.80
LLM_UNCERTAIN_TAKE_TOP1_THRESHOLD = 0.82
TEXT2VEC_MODEL = os.getenv("JOB_UPDATE_TEXT2VEC_MODEL", "shibing624/text2vec-base-chinese")


_SIMILARITY: Text2VecSimilarity | None = None
_TITLE_CLEANER: LLMTitleCleaner | None = None
_ROUTE_ADJUDICATOR: LLMRouteAdjudicator | None = None
_SKILL_EXTRACTOR: ExistingSkillExtractAdapter | None = None


def submit_one_dry_run(payload: dict[str, str]) -> dict[str, Any]:
    """Preview a JD, then either merge automatically or create review tasks."""
    progress: list[str] = []
    mode = clean_text(payload.get("processing_mode")).lower() or "auto"
    if mode not in {"auto", "manual"}:
        raise ValueError("processing_mode must be auto or manual")
    _ensure_database_initialized()
    posting = _posting_from_payload(payload, source=f"web_app_{mode}")
    preview = _build_system(progress).process(
        posting,
        write=False,
        collect_skills_for_review=True,
    )
    input_payload = _input_payload(payload, posting)
    store = SQLiteJobUpdateStore(BASE_DATABASE)

    if mode == "auto" and preview.route.status == "existing_job" and preview.route.best_job is not None:
        category = preview.route.best_category.name if preview.route.best_category else ""
        # Evaluate new-skill status before the official write changes skill_pool.
        queued = create_pending_reviews(
            store=store,
            submission_mode=mode,
            input_payload=input_payload,
            result=preview,
            skill_pool_path=BASE_SKILL_POOL,
            always_queue_job=False,
        )
        applied = _build_system(progress).process(
            posting,
            write=True,
            confirmed_standard_job=preview.route.best_job.name,
            confirmed_standard_category=category,
        )
        result_payload = serialize_review_process_result(applied, skill_pool_path=BASE_SKILL_POOL)
        result_payload["progress"] = progress
        result_payload["merge_result"] = _merge_summary(applied)
        item = store.create_review_item(
            review_id=str(uuid4()),
            review_type="job",
            submission_mode=mode,
            status="auto_merged",
            job_id=posting.job_id,
            input_payload=input_payload,
            result_payload=result_payload,
        )
        item["needs_review"] = bool(queued["skill_reviews"])
        item["skill_review_ids"] = [row["item_id"] for row in queued["skill_reviews"]]
        return item

    queued = create_pending_reviews(
        store=store,
        submission_mode=mode,
        input_payload=input_payload,
        result=preview,
        skill_pool_path=BASE_SKILL_POOL,
        always_queue_job=True,
    )
    item = queued["job_review"]
    item["result"]["progress"] = progress
    store.update_review_item(item["item_id"], result_payload=item["result"])
    item["needs_review"] = True
    item["skill_review_ids"] = [row["item_id"] for row in queued["skill_reviews"]]
    return item


def import_csv(frame: pd.DataFrame) -> dict[str, Any]:
    normalized = _normalize_import_frame(frame)
    items = [submit_one_dry_run(row) for row in normalized.to_dict(orient="records")]
    return {"count": len(items), "items": items}


def get_review_items() -> list[dict[str, Any]]:
    _ensure_database_initialized()
    return SQLiteJobUpdateStore(BASE_DATABASE).list_review_items(status="pending")


def reject_update(item_id: str) -> dict[str, Any]:
    return SQLiteJobUpdateStore(BASE_DATABASE).update_review_item(
        item_id,
        status="rejected",
        decision_payload={"action": "reject_update"},
    )


def confirm_existing(
    item_id: str,
    *,
    merge_database: bool,
    standard_job_title: str = "",
    standard_category: str = "",
    skills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item = SQLiteJobUpdateStore(BASE_DATABASE).get_review_item(item_id)
    if item["review_type"] != "job":
        raise ValueError("Only a job review can confirm an existing standard job")
    route = item["result"].get("route") or {}
    selected_job = clean_text(standard_job_title) or clean_text((route.get("best_job") or {}).get("name"))
    category = clean_text(standard_category) or _category_for_job(selected_job, route)
    if not selected_job or not category:
        raise ValueError("Select an existing standard job and its job family before confirming")
    taxonomy = JobTaxonomy.from_csv(BASE_TITLE_DICTIONARY)
    known = {job.title: job.category for job in taxonomy.jobs}
    if selected_job not in known:
        raise ValueError("The selected job is not in the formal dictionary; submit it as a new-job maintenance request")
    category = known[selected_job]
    reviewed_skills = skills or item["result"].get("skills") or []
    mentions = skill_mentions_from_decisions(reviewed_skills)
    posting = _posting_from_payload({**item["input"], "job_id": item["job_id"]}, source="web_app_human_confirmed")
    posting.routing_job_title = clean_text(item["result"].get("routing_job_title"))
    posting.skills = mentions
    backup = create_backup(f"confirm existing job {item_id}")
    applied = _build_system([]).process(
        posting,
        write=True,
        confirmed_standard_job=selected_job,
        confirmed_standard_category=category,
    )
    result_payload = serialize_review_process_result(applied, skill_pool_path=BASE_SKILL_POOL)
    result_payload["merge_result"] = _merge_summary(applied)
    result_payload["backup"] = backup
    return SQLiteJobUpdateStore(BASE_DATABASE).update_review_item(
        item_id,
        status="merged_existing_job",
        decision_payload={
            "action": "confirm_existing",
            "standard_job_title": selected_job,
            "standard_category": category,
            "skills": reviewed_skills,
        },
        result_payload=result_payload,
    )


def confirm_new_job(
    item_id: str,
    *,
    standard_category: str,
    standard_job_title: str,
    match_keywords: str,
    merge_database: bool,
    skills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    store = SQLiteJobUpdateStore(BASE_DATABASE)
    item = store.get_review_item(item_id)
    if item["review_type"] != "job":
        raise ValueError("Only a job review can submit a new job proposal")
    manual_review = {
        "standard_category": clean_text(standard_category),
        "standard_job_title": clean_text(standard_job_title),
        "match_keywords": clean_text(match_keywords) or clean_text(standard_job_title),
    }
    if not manual_review["standard_category"] or not manual_review["standard_job_title"]:
        raise ValueError("standard_category and standard_job_title are required")
    maintenance = store.create_review_item(
        review_id=str(uuid4()),
        review_type="dictionary_maintenance",
        submission_mode=item["submission_mode"],
        job_id=item["job_id"],
        parent_review_id=item_id,
        input_payload=item["input"],
        result_payload={
            "proposal_type": "new_standard_job",
            "proposal": manual_review,
            "skills": skills or item["result"].get("skills") or [],
            "source_job_review_id": item_id,
        },
    )
    result_payload = dict(item["result"])
    result_payload["manual_review"] = manual_review
    result_payload["dictionary_maintenance_review_id"] = maintenance["item_id"]
    return store.update_review_item(
        item_id,
        status="submitted_dictionary_maintenance",
        decision_payload={"action": "submit_new_job_maintenance", **manual_review},
        result_payload=result_payload,
    )


def review_skill(
    item_id: str,
    *,
    decision: str,
    normalized_skill: str,
    kg_display_skill: str,
    skill_type: str,
) -> dict[str, Any]:
    store = SQLiteJobUpdateStore(BASE_DATABASE)
    item = store.get_review_item(item_id)
    if item["review_type"] != "skill":
        raise ValueError("This endpoint only accepts a skill review item")
    skill = dict(item["result"].get("skill") or {})
    if decision == "mapped":
        skill["normalized_skill"] = clean_text(normalized_skill)
        skill["kg_display_skill"] = clean_text(kg_display_skill)
        if not skill["normalized_skill"] or not skill["kg_display_skill"]:
            raise ValueError("A mapped skill needs normalized_skill and kg_display_skill")
    if skill_type:
        skill["skill_type"] = clean_text(skill_type)
    skill["decision"] = decision
    maintenance_id = ""
    if decision == "new_skill":
        maintenance = store.create_review_item(
            review_id=str(uuid4()),
            review_type="dictionary_maintenance",
            submission_mode=item["submission_mode"],
            job_id=item["job_id"],
            parent_review_id=item_id,
            input_payload=item["input"],
            result_payload={"proposal_type": "new_skill", "proposal": skill},
        )
        maintenance_id = maintenance["item_id"]
    item_result = dict(item["result"])
    item_result["skill"] = skill
    if maintenance_id:
        item_result["dictionary_maintenance_review_id"] = maintenance_id
    return store.update_review_item(
        item_id,
        status="reviewed_skill",
        decision_payload={"action": decision, "skill": skill},
        result_payload=item_result,
    )


def _build_system(progress_messages: list[str]) -> JobUpdateSystem:
    return JobUpdateSystem(
        taxonomy=JobTaxonomy.from_csv(BASE_TITLE_DICTIONARY),
        frequency_store=FrequencyStore(BASE_EVENT_STREAM, BASE_FREQUENCY_OUTPUT),
        skill_pool_store=SkillPoolStore(BASE_SKILL_POOL),
        skill_lifecycle_store=SkillLifecycleStore(BASE_SKILL_LIFECYCLE),
        skill_migration_store=SkillMigrationStore(
            BASE_SKILL_MIGRATION,
            BASE_SKILL_MONTHLY_SPREAD,
        ),
        job_profile_store=JobProfileStore(
            BASE_JOB_PROFILE_SNAPSHOTS,
            BASE_JOB_PROFILE_DIFF,
        ),
        database_store=SQLiteJobUpdateStore(BASE_DATABASE),
        similarity=_similarity(),
        route_adjudicator=_route_adjudicator(),
        title_cleaner=_title_cleaner(),
        skill_extractor=_skill_extractor(),
        category_threshold=CATEGORY_THRESHOLD,
        job_threshold=JOB_THRESHOLD,
        tie_delta=TIE_DELTA,
        llm_job_floor=LLM_JOB_FLOOR,
        llm_top_jobs=LLM_TOP_JOBS,
        llm_accept_rank_limit=LLM_ACCEPT_RANK_LIMIT,
        llm_selected_job_floor=LLM_SELECTED_JOB_FLOOR,
        llm_min_confidence=LLM_MIN_CONFIDENCE,
        llm_uncertain_take_top1_threshold=LLM_UNCERTAIN_TAKE_TOP1_THRESHOLD,
        progress=lambda message: _progress(progress_messages, message),
    )


def _posting_from_payload(payload: dict[str, str], *, source: str) -> JobPosting:
    month = clean_text(payload.get("month")) or datetime.now().strftime("%Y-%m")
    job_title = clean_text(payload.get("job_title"))
    if not job_title:
        raise ValueError("job_title is required")
    return JobPosting(
        job_id=clean_text(payload.get("job_id")) or _generate_job_id(month, job_title),
        month=month,
        job_title=job_title,
        job_responsibility=clean_text(payload.get("responsibility")),
        job_requirement=clean_text(payload.get("requirement")),
        metadata={"source": source},
    )


def _input_payload(payload: dict[str, Any], posting: JobPosting) -> dict[str, str]:
    return {
        "job_id": posting.job_id,
        "month": posting.month,
        "job_title": posting.job_title,
        "responsibility": posting.job_responsibility,
        "requirement": posting.job_requirement,
        "source": clean_text(payload.get("source")) or str(posting.metadata.get("source") or ""),
    }


def _category_for_job(job_title: str, route: dict[str, Any]) -> str:
    for candidate in route.get("top_jobs") or route.get("selected_jobs") or []:
        if clean_text(candidate.get("name")) == job_title:
            return clean_text((candidate.get("metadata") or {}).get("category"))
    return clean_text(((route.get("best_category") or {}).get("name")))


def _merge_summary(result: ProcessResult) -> dict[str, Any]:
    update = result.update
    if update is None:
        return {}
    return {
        "job_id": result.posting.job_id,
        "standard_job": update.standard_job,
        "standard_category": result.route.best_category.name if result.route.best_category else "",
        "skill_count": len(update.normalized_skills),
        "event_rows": "updated",
        "frequency_rows": update.frequency_rows,
        "skill_pool_rows": update.skill_pool_rows,
        "lifecycle_rows": update.lifecycle_rows,
        "migration_rows": update.migration_rows,
        "spread_rows": update.spread_rows,
        "profile_snapshot_rows": update.profile_snapshot_rows,
        "profile_diff_rows": update.profile_diff_rows,
    }


def _normalize_import_frame(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "month": ["month", "月份"],
        "job_title": ["job_title", "岗位名称", "职位名称", "title"],
        "responsibility": ["responsibility", "job_responsibility", "岗位职责", "职责"],
        "requirement": ["requirement", "job_requirement", "岗位要求", "要求"],
    }
    output = pd.DataFrame()
    for target, names in aliases.items():
        source = next((name for name in names if name in frame.columns), None)
        output[target] = frame[source].fillna("").astype(str) if source else ""
    if "job_title" not in output or not output["job_title"].astype(str).str.strip().any():
        raise ValueError("CSV must include job_title / 岗位名称 column")
    return output[output["job_title"].astype(str).str.strip() != ""].reset_index(drop=True)


def _similarity() -> Text2VecSimilarity:
    global _SIMILARITY
    if _SIMILARITY is None:
        _SIMILARITY = Text2VecSimilarity(TEXT2VEC_MODEL)
    return _SIMILARITY


def _title_cleaner() -> LLMTitleCleaner:
    global _TITLE_CLEANER
    if _TITLE_CLEANER is None:
        _TITLE_CLEANER = LLMTitleCleaner(
            provider=os.getenv("JOB_UPDATE_TITLE_CLEAN_PROVIDER", "deepseek"),
            model=os.getenv("JOB_UPDATE_TITLE_CLEAN_MODEL") or None,
            base_url=os.getenv("JOB_UPDATE_TITLE_CLEAN_BASE_URL") or None,
            api_key_env=os.getenv("JOB_UPDATE_TITLE_CLEAN_API_KEY_ENV") or None,
            timeout=int(os.getenv("JOB_UPDATE_TITLE_CLEAN_TIMEOUT", "60")),
            retries=int(os.getenv("JOB_UPDATE_TITLE_CLEAN_RETRIES", "2")),
        )
    return _TITLE_CLEANER


def _route_adjudicator() -> LLMRouteAdjudicator:
    global _ROUTE_ADJUDICATOR
    if _ROUTE_ADJUDICATOR is None:
        _ROUTE_ADJUDICATOR = LLMRouteAdjudicator(
            provider=os.getenv("JOB_UPDATE_ROUTE_PROVIDER", "deepseek"),
            model=os.getenv("JOB_UPDATE_ROUTE_MODEL") or None,
            base_url=os.getenv("JOB_UPDATE_ROUTE_BASE_URL") or None,
            api_key_env=os.getenv("JOB_UPDATE_ROUTE_API_KEY_ENV") or None,
            timeout=int(os.getenv("JOB_UPDATE_ROUTE_TIMEOUT", "90")),
            retries=int(os.getenv("JOB_UPDATE_ROUTE_RETRIES", "2")),
        )
    return _ROUTE_ADJUDICATOR


def _skill_extractor() -> ExistingSkillExtractAdapter:
    global _SKILL_EXTRACTOR
    if _SKILL_EXTRACTOR is None:
        overrides: dict[str, Any] = {
            "timeout": int(os.getenv("JOB_UPDATE_SKILL_TIMEOUT", "90")),
            "retries": int(os.getenv("JOB_UPDATE_SKILL_RETRIES", "2")),
        }
        optional_envs = {
            "model": "JOB_UPDATE_SKILL_MODEL",
            "base_url": "JOB_UPDATE_SKILL_BASE_URL",
            "api_key_env": "JOB_UPDATE_SKILL_API_KEY_ENV",
        }
        for key, env_name in optional_envs.items():
            value = os.getenv(env_name)
            if value:
                overrides[key] = value
        _SKILL_EXTRACTOR = ExistingSkillExtractAdapter(
            provider=os.getenv("JOB_UPDATE_SKILL_PROVIDER", "deepseek"),
            **overrides,
        )
    return _SKILL_EXTRACTOR


def _ensure_database_initialized() -> None:
    if BASE_DATABASE.exists():
        SQLiteJobUpdateStore(BASE_DATABASE).migrate()
        return
    SQLiteJobUpdateStore(BASE_DATABASE).initialize_from_csv(
        title_dictionary_path=BASE_TITLE_DICTIONARY,
        event_stream_path=BASE_EVENT_STREAM,
        frequency_path=BASE_FREQUENCY_OUTPUT,
        skill_pool_path=BASE_SKILL_POOL,
        lifecycle_path=BASE_SKILL_LIFECYCLE,
        migration_path=BASE_SKILL_MIGRATION,
        spread_path=BASE_SKILL_MONTHLY_SPREAD,
        profile_snapshot_path=BASE_JOB_PROFILE_SNAPSHOTS,
        profile_diff_path=BASE_JOB_PROFILE_DIFF,
    )


def _generate_job_id(month: str, job_title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    slug = re.sub(r"[^0-9A-Za-z]+", "_", clean_text(job_title)).strip("_").lower()[:24] or "job"
    digest = hashlib.sha1(f"{month}|{job_title}|{timestamp}".encode("utf-8")).hexdigest()[:8]
    return f"web_{clean_text(month).replace('-', '')}_{timestamp}_{slug}_{digest}"


def _progress(messages: list[str], message: str) -> None:
    messages.append(message)
    print(f"[web_job_update] {message}", flush=True)
