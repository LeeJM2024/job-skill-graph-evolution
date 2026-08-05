from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import SQLiteJobUpdateStore
from .models import JobRoute, NormalizedSkill, ProcessResult, ScoredCandidate
from .text import clean_text


REVIEW_QUEUE_FILE = "review_queue.jsonl"


def serialize_process_result(result: ProcessResult, *, skill_pool_path: Path | None = None) -> dict[str, Any]:
    """Serialize a process result for CLI manual review output.

    This mirrors the CLI's automatic-output shape, but keeps normalized skills
    even when the posting was not written to the frequency tables.
    """

    skills = [_skill_to_dict(skill) for skill in _result_skills(result)]
    payload: dict[str, Any] = {
        "job_id": result.posting.job_id,
        "job_title": result.posting.job_title,
        "routing_job_title": result.posting.routing_job_title,
        "route": _route_to_dict(result.route),
        "skills": skills,
        "updated": result.update is not None,
        "review_recommended": result.route.status != "existing_job",
    }
    if skill_pool_path is not None:
        payload["skill_pool_path"] = str(skill_pool_path)
    if result.update is not None:
        payload["update"] = {
            "standard_job": result.update.standard_job,
            "month": result.update.month,
            "skills": [_skill_to_dict(skill) for skill in result.update.normalized_skills],
            "monthly_rows": result.update.monthly_rows,
            "frequency_rows": result.update.frequency_rows,
            "skill_pool_rows": result.update.skill_pool_rows,
            "lifecycle_rows": result.update.lifecycle_rows,
            "migration_rows": result.update.migration_rows,
            "spread_rows": result.update.spread_rows,
            "profile_snapshot_rows": result.update.profile_snapshot_rows,
            "profile_diff_rows": result.update.profile_diff_rows,
            "current_profile_rows": result.update.current_profile_rows,
            "event_stream_path": result.update.event_stream_path,
            "frequency_path": result.update.frequency_path,
            "skill_pool_path": result.update.skill_pool_path,
            "lifecycle_path": result.update.lifecycle_path,
            "migration_path": result.update.migration_path,
            "spread_path": result.update.spread_path,
            "profile_snapshot_path": result.update.profile_snapshot_path,
            "profile_diff_path": result.update.profile_diff_path,
            "current_profile_path": result.update.current_profile_path,
        }
    return payload


def create_pending_reviews(
    *,
    store: SQLiteJobUpdateStore,
    submission_mode: str,
    input_payload: dict[str, Any],
    result: ProcessResult,
    skill_pool_path: Path | None = None,
    always_queue_job: bool = False,
) -> dict[str, Any]:
    """Append pending job/skill review items to a JSONL queue file.

    The repository currently has no SQLite review table. A JSONL queue keeps the
    CLI usable and gives later Web/DB integration a stable record format to
    import from.
    """

    queue_path = _queue_path(store)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    now = _now()
    serialized = serialize_process_result(result, skill_pool_path=skill_pool_path)
    job_review = None
    skill_reviews: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []

    if always_queue_job or result.route.status != "existing_job":
        job_review = _review_item(
            item_type="job",
            submission_mode=submission_mode,
            input_payload=input_payload,
            result=serialized,
            now=now,
            payload={
                "route_status": result.route.status,
                "best_category": _candidate_to_dict(result.route.best_category),
                "best_job": _candidate_to_dict(result.route.best_job),
                "reason": result.route.reason,
            },
        )
        records.append(job_review)

    if submission_mode == "manual":
        for index, skill in enumerate(_result_skills(result), start=1):
            item = _review_item(
                item_type="skill",
                submission_mode=submission_mode,
                input_payload=input_payload,
                result=serialized,
                now=now,
                payload={
                    "row_order": index,
                    "skill": _skill_to_dict(skill),
                    "skill_pool_path": str(skill_pool_path) if skill_pool_path is not None else "",
                },
            )
            skill_reviews.append(item)
            records.append(item)

    if records:
        with queue_path.open("a", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "queue_path": str(queue_path),
        "job_review": job_review,
        "skill_reviews": skill_reviews,
    }


def _queue_path(store: SQLiteJobUpdateStore) -> Path:
    database_path = Path(store.database_path)
    return database_path.with_name(REVIEW_QUEUE_FILE)


def _review_item(
    *,
    item_type: str,
    submission_mode: str,
    input_payload: dict[str, Any],
    result: dict[str, Any],
    now: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "item_id": str(uuid4()),
        "item_type": item_type,
        "submission_mode": submission_mode,
        "status": "pending",
        "input": _clean_input(input_payload),
        "result": result,
        "payload": payload,
        "created_at": now,
        "updated_at": now,
    }


def _clean_input(input_payload: dict[str, Any]) -> dict[str, str]:
    return {
        "month": clean_text(input_payload.get("month")),
        "job_title": clean_text(input_payload.get("job_title")),
        "responsibility": clean_text(input_payload.get("responsibility")),
        "requirement": clean_text(input_payload.get("requirement")),
        "source": clean_text(input_payload.get("source")),
    }


def _result_skills(result: ProcessResult) -> list[NormalizedSkill]:
    if result.update is not None:
        return result.update.normalized_skills
    return result.normalized_skills


def _route_to_dict(route: JobRoute) -> dict[str, Any]:
    return {
        "status": route.status,
        "reason": route.reason,
        "best_category": _candidate_to_dict(route.best_category),
        "best_job": _candidate_to_dict(route.best_job),
        "selected_categories": [_candidate_to_dict(item) for item in route.selected_categories],
        "selected_jobs": [_candidate_to_dict(item) for item in route.selected_jobs],
        "top_categories": [_candidate_to_dict(item) for item in route.top_categories],
        "top_jobs": [_candidate_to_dict(item) for item in route.top_jobs],
        "adjudication": route.adjudication,
    }


def _candidate_to_dict(candidate: ScoredCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "name": candidate.name,
        "score": round(float(candidate.score), 6),
        "metadata": candidate.metadata,
    }


def _skill_to_dict(skill: NormalizedSkill) -> dict[str, Any]:
    return {
        "normalized_skill": skill.normalized_skill,
        "kg_display_skill": skill.kg_display_skill,
        "skill_type": skill.skill_type or "",
        "confidence": skill.confidence,
        "metadata": skill.metadata,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
