from __future__ import annotations

from dataclasses import asdict, dataclass
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
    BASE_TITLE_DICTIONARY,
    DATASET_ROOT,
    JOB_UPDATE_ROOT,
)

for path in (DATASET_ROOT, JOB_UPDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from job_update.database import SQLiteJobUpdateStore
from job_update.frequency_store import FrequencyStore
from job_update.models import (
    ExistingJobUpdate,
    JobPosting,
    JobRoute,
    NormalizedSkill,
    ProcessResult,
    ScoredCandidate,
)
from job_update.route_adjudication import LLMRouteAdjudicator
from job_update.service import JobUpdateSystem
from job_update.similarity import Text2VecSimilarity
from job_update.skill_extraction import ExistingSkillExtractAdapter
from job_update.skill_normalizer import PassthroughSkillNormalizer
from job_update.skill_pool_store import SkillPoolStore
from job_update.taxonomy import JobTaxonomy
from job_update.text import clean_text
from job_update.title_cleaning import LLMTitleCleaner


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


@dataclass
class ReviewItem:
    item_id: str
    input: dict[str, str]
    result: dict[str, Any]
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""


REVIEW_ITEMS: dict[str, ReviewItem] = {}
ACTIVE_REVIEW_STATUSES = {"pending"}
_SIMILARITY: Text2VecSimilarity | None = None
_TITLE_CLEANER: LLMTitleCleaner | None = None
_ROUTE_ADJUDICATOR: LLMRouteAdjudicator | None = None
_SKILL_EXTRACTOR: ExistingSkillExtractAdapter | None = None
_SKILL_NORMALIZER = PassthroughSkillNormalizer()


def submit_one_dry_run(payload: dict[str, str]) -> dict[str, Any]:
    progress: list[str] = []
    posting = _posting_from_payload(payload, source="web_app_dry_run")
    result = _build_system(progress).process(posting, write=False)
    serialized = _serialize_process_result(result)
    serialized["progress"] = progress
    item = _store_review_item(payload, serialized)
    response = asdict(item)
    response["needs_review"] = serialized["route"]["status"] != "existing_job"
    return response


def import_csv(frame: pd.DataFrame) -> dict[str, Any]:
    normalized = _normalize_import_frame(frame)
    items = [submit_one_dry_run(row) for row in normalized.to_dict(orient="records")]
    return {"count": len(items), "items": items}


def get_review_items() -> list[dict[str, Any]]:
    active_items = [
        item
        for item in REVIEW_ITEMS.values()
        if item.status in ACTIVE_REVIEW_STATUSES
    ]
    return [asdict(item) for item in sorted(active_items, key=lambda value: value.created_at, reverse=True)]


def reject_update(item_id: str) -> dict[str, Any]:
    item = _get_item(item_id)
    item.status = "rejected"
    item.updated_at = _now()
    return asdict(item)


def confirm_existing(item_id: str, merge_database: bool) -> dict[str, Any]:
    item = _get_item(item_id)
    if not merge_database:
        item.status = "confirmed_no_update"
        item.updated_at = _now()
        return asdict(item)

    if item.result.get("route", {}).get("status") != "existing_job":
        raise ValueError("Only existing_job review items can be merged with confirm_existing")

    backup = create_backup(f"confirm existing job {item_id}")
    _ensure_database_initialized()
    result = _write_confirmed_existing_update(item.input, item.result)
    item.status = "merged_existing_job"
    item.updated_at = _now()
    item.result["merge_result"] = result
    item.result["backup"] = backup
    return asdict(item)


def confirm_new_job(
    item_id: str,
    *,
    standard_category: str,
    standard_job_title: str,
    match_keywords: str,
    merge_database: bool,
) -> dict[str, Any]:
    item = _get_item(item_id)
    manual_review = {
        "standard_category": clean_text(standard_category),
        "standard_job_title": clean_text(standard_job_title),
        "match_keywords": clean_text(match_keywords) or clean_text(standard_job_title),
    }
    if not merge_database:
        item.status = "confirmed_new_no_update"
        item.updated_at = _now()
        item.result["manual_review"] = manual_review
        return asdict(item)

    backup = create_backup(f"confirm new job {item_id}")
    _ensure_database_initialized()
    _upsert_standard_job(
        manual_review["standard_job_title"],
        manual_review["standard_category"],
        manual_review["match_keywords"],
    )
    result = _write_human_confirmed_new_job(item.input, item.result, manual_review)
    item.status = "merged_new_job"
    item.updated_at = _now()
    item.result["manual_review"] = manual_review
    item.result["merge_result"] = result
    item.result["backup"] = backup
    return asdict(item)


def _build_system(progress_messages: list[str]) -> JobUpdateSystem:
    return JobUpdateSystem(
        taxonomy=JobTaxonomy.from_csv(BASE_TITLE_DICTIONARY),
        frequency_store=FrequencyStore(BASE_EVENT_STREAM, BASE_FREQUENCY_OUTPUT),
        skill_pool_store=SkillPoolStore(BASE_SKILL_POOL),
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


def _write_confirmed_existing_update(payload: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    route = _route_from_result(result)
    if route.best_job is None:
        raise ValueError("Cannot merge existing job without a selected standard job")
    category = route.best_category.name if route.best_category is not None else ""
    skills = _normalized_skills_from_result(result)
    posting = _posting_from_payload({**payload, "job_id": result.get("job_id", "")}, source="web_app_review")
    posting.routing_job_title = clean_text(result.get("routing_job_title"))
    return _append_confirmed_update(
        posting=posting,
        route=route,
        standard_category=category,
        standard_job=route.best_job.name,
        normalized_skills=skills,
    )


def _write_human_confirmed_new_job(
    payload: dict[str, str],
    result: dict[str, Any],
    manual_review: dict[str, str],
) -> dict[str, Any]:
    posting = _posting_from_payload({**payload, "job_id": result.get("job_id", "")}, source="web_app_new_job_review")
    posting.routing_job_title = manual_review["standard_job_title"]
    mentions = _skill_extractor().extract(posting)
    normalized_skills = _SKILL_NORMALIZER.normalize(posting, mentions)
    category_candidate = ScoredCandidate(manual_review["standard_category"], 1.0, {"source": "human_review"})
    job_candidate = ScoredCandidate(manual_review["standard_job_title"], 1.0, {"source": "human_review"})
    route = JobRoute(
        status="existing_job",
        selected_categories=[category_candidate],
        selected_jobs=[job_candidate],
        best_category=category_candidate,
        best_job=job_candidate,
        reason="human review confirmed a new standard job",
    )
    return _append_confirmed_update(
        posting=posting,
        route=route,
        standard_category=manual_review["standard_category"],
        standard_job=manual_review["standard_job_title"],
        normalized_skills=normalized_skills,
    )


def _append_confirmed_update(
    *,
    posting: JobPosting,
    route: JobRoute,
    standard_category: str,
    standard_job: str,
    normalized_skills: list[NormalizedSkill],
) -> dict[str, Any]:
    if not normalized_skills:
        raise ValueError("No normalized skills were available; refusing to write an empty skill update")

    frequency_store = FrequencyStore(BASE_EVENT_STREAM, BASE_FREQUENCY_OUTPUT)
    skill_pool_store = SkillPoolStore(BASE_SKILL_POOL)
    events, frequency = frequency_store.append_existing_job(
        posting=posting,
        standard_job=standard_job,
        normalized_skills=normalized_skills,
        write=False,
    )
    skill_pool = skill_pool_store.update(
        posting=posting,
        standard_category=standard_category,
        standard_job=standard_job,
        normalized_skills=normalized_skills,
        write=False,
    )
    frequency_store.write_tables(events, frequency)
    skill_pool_store.write_pool(skill_pool)

    monthly_rows = len(
        frequency[
            (frequency["standard_job"] == standard_job)
            & (frequency["month"] == posting.month)
        ]
    )
    update = ExistingJobUpdate(
        standard_job=standard_job,
        month=posting.month,
        normalized_skills=normalized_skills,
        monthly_rows=monthly_rows,
        frequency_rows=len(frequency),
        skill_pool_rows=len(skill_pool),
        event_stream_path=str(BASE_EVENT_STREAM),
        frequency_path=str(BASE_FREQUENCY_OUTPUT),
        skill_pool_path=str(BASE_SKILL_POOL),
    )
    SQLiteJobUpdateStore(BASE_DATABASE).sync_after_process(
        result=ProcessResult(route=route, posting=posting, update=update),
        frequency=frequency,
        skill_pool=skill_pool,
    )
    return {
        "job_id": posting.job_id,
        "standard_category": standard_category,
        "standard_job": standard_job,
        "skill_count": len(normalized_skills),
        "event_rows": len(events),
        "frequency_rows": len(frequency),
        "skill_pool_rows": len(skill_pool),
    }


def _upsert_standard_job(standard_job_title: str, standard_category: str, match_keywords: str) -> None:
    title = clean_text(standard_job_title)
    category = clean_text(standard_category)
    keywords = clean_text(match_keywords) or title
    if not title or not category:
        raise ValueError("standard_category and standard_job_title are required")

    frame = _read_csv(BASE_TITLE_DICTIONARY)
    row = {
        "standard_job_title": title,
        "standard_category": category,
        "match_keywords": keywords,
    }
    if frame.empty:
        frame = pd.DataFrame([row])
    else:
        for column in row:
            if column not in frame.columns:
                frame[column] = ""
        key = frame["standard_job_title"].astype(str).str.strip().str.casefold()
        existing = key == title.casefold()
        if existing.any():
            index = frame.index[existing][0]
            for column, value in row.items():
                frame.at[index, column] = value
        else:
            frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)

    frame[["standard_job_title", "standard_category", "match_keywords"]].to_csv(
        BASE_TITLE_DICTIONARY,
        index=False,
        encoding="utf-8-sig",
    )
    SQLiteJobUpdateStore(BASE_DATABASE).upsert_standard_job(
        standard_job_title=title,
        standard_category=category,
        match_keywords=keywords,
    )


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


def _store_review_item(payload: dict[str, str], result: dict[str, Any]) -> ReviewItem:
    now = _now()
    item = ReviewItem(
        item_id=str(uuid4()),
        input={
            "month": clean_text(payload.get("month")) or datetime.now().strftime("%Y-%m"),
            "job_title": clean_text(payload.get("job_title")),
            "responsibility": clean_text(payload.get("responsibility")),
            "requirement": clean_text(payload.get("requirement")),
        },
        result=result,
        created_at=now,
        updated_at=now,
    )
    REVIEW_ITEMS[item.item_id] = item
    return item


def _get_item(item_id: str) -> ReviewItem:
    if item_id not in REVIEW_ITEMS:
        raise KeyError(f"Review item not found: {item_id}")
    return REVIEW_ITEMS[item_id]


def _serialize_process_result(result: ProcessResult) -> dict[str, Any]:
    skills = []
    if result.update is not None:
        skills = [_skill_to_dict(skill) for skill in result.update.normalized_skills]
    payload: dict[str, Any] = {
        "job_id": result.posting.job_id,
        "job_title": result.posting.job_title,
        "routing_job_title": result.posting.routing_job_title,
        "route": _route_to_dict(result.route),
        "skills": skills,
        "updated": result.update is not None,
    }
    if result.update is not None:
        payload["update"] = {
            "standard_job": result.update.standard_job,
            "month": result.update.month,
            "skills": skills,
            "monthly_rows": result.update.monthly_rows,
            "frequency_rows": result.update.frequency_rows,
            "skill_pool_rows": result.update.skill_pool_rows,
            "event_stream_path": result.update.event_stream_path,
            "frequency_path": result.update.frequency_path,
            "skill_pool_path": result.update.skill_pool_path,
        }
    return payload


def _route_to_dict(route: JobRoute) -> dict[str, Any]:
    return {
        "status": route.status,
        "reason": route.reason,
        "best_category": _candidate_to_dict(route.best_category),
        "best_job": _candidate_to_dict(route.best_job),
        "selected_categories": [_candidate_to_dict(item) for item in route.selected_categories],
        "selected_jobs": [_candidate_to_dict(item) for item in route.selected_jobs],
    }


def _route_from_result(result: dict[str, Any]) -> JobRoute:
    route = result.get("route") or {}
    return JobRoute(
        status=route.get("status") or "potential_new_job",
        reason=clean_text(route.get("reason")),
        best_category=_candidate_from_dict(route.get("best_category")),
        best_job=_candidate_from_dict(route.get("best_job")),
        selected_categories=[
            candidate
            for candidate in (_candidate_from_dict(item) for item in route.get("selected_categories", []))
            if candidate is not None
        ],
        selected_jobs=[
            candidate
            for candidate in (_candidate_from_dict(item) for item in route.get("selected_jobs", []))
            if candidate is not None
        ],
    )


def _candidate_to_dict(candidate: ScoredCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {"name": candidate.name, "score": round(float(candidate.score), 6), "metadata": candidate.metadata}


def _candidate_from_dict(value: Any) -> ScoredCandidate | None:
    if not isinstance(value, dict):
        return None
    name = clean_text(value.get("name"))
    if not name:
        return None
    return ScoredCandidate(
        name=name,
        score=_float_value(value.get("score")),
        metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
    )


def _normalized_skills_from_result(result: dict[str, Any]) -> list[NormalizedSkill]:
    raw_skills = result.get("skills") or result.get("update", {}).get("skills") or []
    skills = [_normalized_skill_from_dict(item) for item in raw_skills if isinstance(item, dict)]
    if not skills:
        raise ValueError("No normalized skills were produced by the formal skill_extract flow")
    return skills


def _normalized_skill_from_dict(item: dict[str, Any]) -> NormalizedSkill:
    name = clean_text(item.get("normalized_skill"))
    family = clean_text(item.get("kg_display_skill"))
    if not name or not family:
        raise ValueError("Each skill must include normalized_skill and kg_display_skill")
    return NormalizedSkill(
        normalized_skill=name,
        kg_display_skill=family,
        skill_type=clean_text(item.get("skill_type")) or None,
        confidence=_optional_float(item.get("confidence")),
        metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {"source": "web_app_review"},
    )


def _skill_to_dict(skill: NormalizedSkill) -> dict[str, Any]:
    return {
        "normalized_skill": skill.normalized_skill,
        "kg_display_skill": skill.kg_display_skill,
        "skill_type": skill.skill_type or "",
        "confidence": skill.confidence,
        "metadata": skill.metadata,
    }


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
    )


def _read_csv(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _generate_job_id(month: str, job_title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    slug = re.sub(r"[^0-9A-Za-z]+", "_", clean_text(job_title)).strip("_").lower()[:24] or "job"
    digest = hashlib.sha1(f"{month}|{job_title}|{timestamp}".encode("utf-8")).hexdigest()[:8]
    return f"web_{clean_text(month).replace('-', '')}_{timestamp}_{slug}_{digest}"


def _progress(messages: list[str], message: str) -> None:
    messages.append(message)
    print(f"[web_job_update] {message}", flush=True)


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
