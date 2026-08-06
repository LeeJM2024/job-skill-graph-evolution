from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from company_job_update.core.job_profile_store import JobProfileStore
from company_job_update.core.models import JobPosting
from company_job_update.core.review_queue import skill_mentions_from_decisions
from company_job_update.core.service import JobUpdateSystem
from company_job_update.core.skill_migration_store import SkillMigrationStore
from company_job_update.core.skill_pool_store import SkillPoolStore
from shared.text_utils import clean_text

from .config import (
    DEFAULT_CURRENT_PROFILE,
    DEFAULT_DATABASE,
    DEFAULT_EVENT_STREAM,
    DEFAULT_FREQUENCY_OUTPUT,
    DEFAULT_JOB_PROFILE_DIFF,
    DEFAULT_JOB_PROFILE_SNAPSHOTS,
    DEFAULT_JOB_DICTIONARY,
    DEFAULT_SKILL_JOB_MONTHLY_SPREAD,
    DEFAULT_SKILL_LIFECYCLE,
    DEFAULT_SKILL_MIGRATION,
    DEFAULT_SKILL_POOL,
)
from .current_profile import GovernmentCurrentProfileStore
from .database import GovernmentSQLiteStore
from .frequency_store import GovernmentFrequencyStore
from .routing import GovernmentTaxonomy
from .skill_lifecycle import GovernmentAnnualLifecycleStore


def list_pending_reviews(database_path: Path = DEFAULT_DATABASE) -> list[dict[str, Any]]:
    return GovernmentSQLiteStore(database_path).list_review_items(status="pending")


def reject_review(item_id: str, database_path: Path = DEFAULT_DATABASE) -> dict[str, Any]:
    return GovernmentSQLiteStore(database_path).update_review_item(
        item_id,
        status="rejected",
        decision_payload={"action": "reject_update"},
    )


def confirm_existing_review(
    item_id: str,
    *,
    standard_job_title: str = "",
    skills: list[dict[str, Any]] | None = None,
    database_path: Path = DEFAULT_DATABASE,
) -> dict[str, Any]:
    store = GovernmentSQLiteStore(database_path)
    item = store.get_review_item(item_id)
    if item["review_type"] != "job" or item["status"] != "pending":
        raise ValueError("Only a pending government job review can be confirmed")
    taxonomy = GovernmentTaxonomy.from_csv(DEFAULT_JOB_DICTIONARY)
    categories = {job.title: job.category for job in taxonomy.jobs}
    route = item["result"].get("route") or {}
    selected_job = clean_text(standard_job_title) or clean_text((route.get("best_job") or {}).get("name"))
    if selected_job not in categories:
        raise ValueError("Select an existing government standard job from the formal dictionary")
    reviewed_skills = skills or item["result"].get("skills") or []
    mentions = skill_mentions_from_decisions(reviewed_skills)
    raw = item["input"]
    posting = JobPosting(
        job_id=clean_text(item["job_id"]),
        month=clean_text(raw.get("month")),
        job_title=clean_text(raw.get("job_title")),
        routing_job_title=clean_text(item["result"].get("routing_job_title")),
        job_responsibility=clean_text(raw.get("responsibility")),
        job_requirement=clean_text(raw.get("requirement")),
        skills=mentions,
        metadata={"source": "government_human_confirmed"},
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=GovernmentFrequencyStore(DEFAULT_EVENT_STREAM, DEFAULT_FREQUENCY_OUTPUT),
        skill_pool_store=SkillPoolStore(DEFAULT_SKILL_POOL),
        skill_lifecycle_store=GovernmentAnnualLifecycleStore(DEFAULT_SKILL_LIFECYCLE),
        skill_migration_store=SkillMigrationStore(DEFAULT_SKILL_MIGRATION, DEFAULT_SKILL_JOB_MONTHLY_SPREAD),
        job_profile_store=JobProfileStore(DEFAULT_JOB_PROFILE_SNAPSHOTS, DEFAULT_JOB_PROFILE_DIFF),
        current_profile_store=GovernmentCurrentProfileStore(DEFAULT_CURRENT_PROFILE),
        database_store=store,
    )
    result = system.process(
        posting,
        write=True,
        confirmed_standard_job=selected_job,
        confirmed_standard_category=categories[selected_job],
    )
    return store.update_review_item(
        item_id,
        status="merged_existing_job",
        decision_payload={"action": "confirm_existing", "standard_job_title": selected_job, "skills": reviewed_skills},
        result_payload={**item["result"], "merged_standard_job": selected_job},
    )


def submit_new_job_maintenance(
    item_id: str,
    *,
    standard_category: str,
    standard_job_title: str,
    match_keywords: str = "",
    database_path: Path = DEFAULT_DATABASE,
) -> dict[str, Any]:
    store = GovernmentSQLiteStore(database_path)
    item = store.get_review_item(item_id)
    proposal = {
        "standard_category": clean_text(standard_category),
        "standard_job_title": clean_text(standard_job_title),
        "match_keywords": clean_text(match_keywords) or clean_text(standard_job_title),
    }
    if not proposal["standard_category"] or not proposal["standard_job_title"]:
        raise ValueError("standard_category and standard_job_title are required")
    maintenance = store.create_review_item(
        review_id=str(uuid4()), review_type="dictionary_maintenance", submission_mode=item["submission_mode"],
        job_id=item["job_id"], parent_review_id=item_id, input_payload=item["input"],
        result_payload={"proposal_type": "new_standard_job", "proposal": proposal},
    )
    return store.update_review_item(
        item_id, status="submitted_dictionary_maintenance",
        decision_payload={"action": "submit_new_job_maintenance", **proposal},
        result_payload={**item["result"], "dictionary_maintenance_review_id": maintenance["item_id"]},
    )


def review_skill_item(item_id: str, *, decision: str, normalized_skill: str = "", kg_display_skill: str = "", skill_type: str = "", database_path: Path = DEFAULT_DATABASE) -> dict[str, Any]:
    store = GovernmentSQLiteStore(database_path)
    item = store.get_review_item(item_id)
    if item["review_type"] != "skill" or item["status"] != "pending":
        raise ValueError("Only a pending government skill review can be changed")
    skill = dict(item["result"].get("skill") or {})
    if decision == "mapped":
        skill["normalized_skill"] = clean_text(normalized_skill)
        skill["kg_display_skill"] = clean_text(kg_display_skill)
        if not skill["normalized_skill"] or not skill["kg_display_skill"]:
            raise ValueError("A mapped skill requires normalized_skill and kg_display_skill")
    skill["decision"] = decision
    if skill_type:
        skill["skill_type"] = clean_text(skill_type)
    return store.update_review_item(item_id, status="reviewed_skill", decision_payload={"action": decision, "skill": skill}, result_payload={**item["result"], "skill": skill})
