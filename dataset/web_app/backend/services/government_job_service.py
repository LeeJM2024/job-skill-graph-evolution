from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pandas as pd

from government_job_update.config import DEFAULT_DATABASE, DEFAULT_SKILL_POOL
from government_job_update.database import GovernmentSQLiteStore
from government_job_update.review_queue import (
    confirm_existing_review,
    list_pending_reviews,
    reject_review,
    submit_new_job_maintenance,
    review_skill_item,
)
from government_job_update.cli import _build_update_system
from company_job_update.core.models import JobPosting
from company_job_update.core.review_queue import create_pending_reviews, serialize_process_result
from shared.text_utils import clean_text


def submit_one_dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    mode = clean_text(payload.get("processing_mode")).lower() or "auto"
    if mode not in {"auto", "manual"}:
        raise ValueError("processing_mode must be auto or manual")
    store = GovernmentSQLiteStore(DEFAULT_DATABASE)
    store.migrate()
    posting = JobPosting(
        job_id=clean_text(payload.get("job_id")) or f"GOV-WEB-{uuid4().hex[:12]}",
        month=clean_text(payload.get("month")), job_title=clean_text(payload.get("job_title")),
        job_responsibility=clean_text(payload.get("responsibility")),
        job_requirement=clean_text(payload.get("requirement")), metadata={"source": "government_web"},
    )
    if not posting.job_title or not posting.month:
        raise ValueError("month and job_title are required")
    args = SimpleNamespace(
        provider="deepseek", model=None, base_url=None, api_key_env=None, timeout=90, retries=2,
        text2vec_model="shibing624/text2vec-base-chinese", category_threshold=0.58, job_threshold=0.82,
        tie_delta=0.03, llm_job_floor=0.58, llm_top_jobs=10, llm_accept_rank_limit=1,
        llm_selected_job_floor=0.75, llm_min_confidence=0.80, llm_uncertain_take_top1_threshold=0.82,
    )
    system = _build_update_system(args, store)
    preview = system.process(posting, write=False, collect_skills_for_review=True)
    input_payload = {"month": posting.month, "job_title": posting.job_title, "responsibility": posting.job_responsibility, "requirement": posting.job_requirement, "source": "government_web"}
    if mode == "auto" and preview.route.status == "existing_job" and preview.route.best_job is not None:
        applied = system.process(posting, write=True, confirmed_standard_job=preview.route.best_job.name, confirmed_standard_category=preview.route.best_category.name if preview.route.best_category else "")
        return {"status": "auto_merged", "result": serialize_process_result(applied, skill_pool_path=DEFAULT_SKILL_POOL)}
    bundle = create_pending_reviews(store=store, submission_mode=mode, input_payload=input_payload, result=preview, skill_pool_path=DEFAULT_SKILL_POOL, always_queue_job=True)
    return {"status": "pending", "item": bundle["job_review"], "skill_reviews": bundle["skill_reviews"], "result": bundle["result"]}


def import_csv(frame: pd.DataFrame) -> dict[str, Any]:
    aliases = {"month": ["month", "月份"], "job_title": ["job_title", "岗位名称", "职位名称"], "responsibility": ["responsibility", "job_responsibility", "岗位职责"], "requirement": ["requirement", "job_requirement", "岗位要求"]}
    rows = []
    for _, raw in frame.fillna("").iterrows():
        row = {target: clean_text(next((raw.get(name) for name in names if name in raw.index), "")) for target, names in aliases.items()}
        if row["job_title"]:
            rows.append(submit_one_dry_run(row))
    return {"count": len(rows), "items": rows}


def get_review_items() -> list[dict[str, Any]]:
    return list_pending_reviews()


def reject_update(item_id: str) -> dict[str, Any]:
    return reject_review(item_id)


def confirm_existing(item_id: str, *, standard_job_title: str = "", skills: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return confirm_existing_review(item_id, standard_job_title=standard_job_title, skills=skills)


def confirm_new_job(item_id: str, *, standard_category: str, standard_job_title: str, match_keywords: str = "") -> dict[str, Any]:
    return submit_new_job_maintenance(item_id, standard_category=standard_category, standard_job_title=standard_job_title, match_keywords=match_keywords)


def review_skill(item_id: str, *, decision: str, normalized_skill: str = "", kg_display_skill: str = "", skill_type: str = "") -> dict[str, Any]:
    return review_skill_item(item_id, decision=decision, normalized_skill=normalized_skill, kg_display_skill=kg_display_skill, skill_type=skill_type)
