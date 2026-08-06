from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import SQLiteJobUpdateStore
from .models import NormalizedSkill, ProcessResult, SkillMention
from .skill_pool_store import SkillPoolStore


LOW_CONFIDENCE_THRESHOLD = 0.80


def serialize_process_result(result: ProcessResult, *, skill_pool_path: Path | None = None) -> dict[str, Any]:
    """Create the read-only result shown to a reviewer before any write."""
    known_skills = _known_skills(skill_pool_path)
    mentions = {skill.normalized_skill.casefold(): skill for skill in result.posting.skills}
    skills = [
        _serialize_skill(skill, mentions.get(skill.normalized_skill.casefold()), known_skills)
        for skill in result.normalized_skills
    ]
    return {
        "job_id": result.posting.job_id,
        "job_title": result.posting.job_title,
        "routing_job_title": result.posting.routing_job_title,
        "route": _serialize_route(result),
        "skills": skills,
        "updated": result.update is not None,
        "update": _serialize_update(result),
    }


def create_pending_reviews(
    *,
    store: SQLiteJobUpdateStore,
    submission_mode: str,
    input_payload: dict[str, Any],
    result: ProcessResult,
    skill_pool_path: Path | None,
    always_queue_job: bool,
) -> dict[str, Any]:
    """Queue the job decision and risky skill decisions without writing base data."""
    review_result = serialize_process_result(result, skill_pool_path=skill_pool_path)
    job_id = result.posting.job_id
    job_review: dict[str, Any] | None = None
    if always_queue_job or result.route.status != "existing_job":
        job_review = store.create_review_item(
            review_id=str(uuid4()),
            review_type="job",
            submission_mode=submission_mode,
            job_id=job_id,
            input_payload=input_payload,
            result_payload=review_result,
        )

    skill_reviews: list[dict[str, Any]] = []
    for skill in review_result["skills"]:
        if not (skill["is_new_skill_candidate"] or skill["is_low_confidence"]):
            continue
        skill_reviews.append(
            store.create_review_item(
                review_id=str(uuid4()),
                review_type="skill",
                submission_mode=submission_mode,
                job_id=job_id,
                parent_review_id=job_review["item_id"] if job_review else "",
                input_payload=input_payload,
                result_payload={"skill": skill, "job_result": review_result},
            )
        )
    return {"job_review": job_review, "skill_reviews": skill_reviews, "result": review_result}


def skill_mentions_from_decisions(raw_skills: list[dict[str, Any]]) -> list[SkillMention]:
    """Apply reviewer edits. Skills marked invalid are deliberately omitted."""
    mentions: list[SkillMention] = []
    for raw in raw_skills:
        if str(raw.get("decision") or "").strip() == "invalid":
            continue
        name = str(raw.get("normalized_skill") or "").strip()
        family = str(raw.get("kg_display_skill") or "").strip()
        if not name or not family:
            raise ValueError("Each confirmed skill needs normalized_skill and kg_display_skill")
        mentions.append(
            SkillMention(
                normalized_skill=name,
                kg_display_skill=family,
                skill_type=str(raw.get("skill_type") or "").strip() or None,
                confidence=_number(raw.get("confidence")),
                span_text=str(raw.get("raw_skill") or raw.get("span_text") or "").strip() or None,
                metadata={
                    "normalization_method": raw.get("normalization_method"),
                    "normalization_status": raw.get("normalization_status"),
                    "review_decision": raw.get("decision") or "confirmed",
                },
            )
        )
    if not mentions:
        raise ValueError("At least one valid skill is required before updating the base dataset")
    return mentions


def _serialize_route(result: ProcessResult) -> dict[str, Any]:
    route = result.route
    return {
        "status": route.status,
        "reason": route.reason,
        "best_category": _candidate(route.best_category),
        "best_job": _candidate(route.best_job),
        "selected_categories": [_candidate(item) for item in route.selected_categories],
        "selected_jobs": [_candidate(item) for item in route.selected_jobs],
        "top_categories": [_candidate(item) for item in route.top_categories],
        "top_jobs": [_candidate(item) for item in route.top_jobs],
        "adjudication": route.adjudication,
    }


def _serialize_update(result: ProcessResult) -> dict[str, Any] | None:
    update = result.update
    if update is None:
        return None
    return {
        "standard_job": update.standard_job,
        "month": update.month,
        "monthly_rows": update.monthly_rows,
        "frequency_rows": update.frequency_rows,
        "skill_pool_rows": update.skill_pool_rows,
        "lifecycle_rows": update.lifecycle_rows,
        "migration_rows": update.migration_rows,
        "spread_rows": update.spread_rows,
        "profile_snapshot_rows": update.profile_snapshot_rows,
        "profile_diff_rows": update.profile_diff_rows,
        "current_profile_rows": update.current_profile_rows,
    }


def _serialize_skill(
    skill: NormalizedSkill,
    mention: SkillMention | None,
    known_skills: set[str],
) -> dict[str, Any]:
    metadata = skill.metadata or {}
    status = str(metadata.get("normalization_status") or "").strip()
    needs_review = _truthy(metadata.get("needs_review"))
    confidence = skill.confidence
    is_low_confidence = needs_review or status in {"unresolved", "uncertain"} or (
        confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD
    )
    return {
        "raw_skill": (mention.span_text if mention else "") or metadata.get("span_text") or skill.normalized_skill,
        "normalized_skill": skill.normalized_skill,
        "kg_display_skill": skill.kg_display_skill,
        "skill_type": skill.skill_type or "",
        "confidence": confidence,
        "normalization_method": metadata.get("normalization_method") or "",
        "normalization_status": status,
        "normalization_reason": metadata.get("normalization_reason") or "",
        "is_new_skill_candidate": skill.normalized_skill.casefold() not in known_skills,
        "is_low_confidence": is_low_confidence,
        "needs_review": is_low_confidence or skill.normalized_skill.casefold() not in known_skills,
        "decision": "confirmed",
    }


def _known_skills(skill_pool_path: Path | None) -> set[str]:
    if skill_pool_path is None:
        return set()
    return {
        str(value).strip().casefold()
        for value in SkillPoolStore(skill_pool_path).load().get("normalized_skill", [])
        if str(value).strip()
    }


def _candidate(candidate: Any) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {"name": candidate.name, "score": round(float(candidate.score), 6), "metadata": candidate.metadata}


def _truthy(value: Any) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
