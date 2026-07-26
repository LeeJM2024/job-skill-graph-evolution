from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
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
from job_update.models import JobPosting, NormalizedSkill, ScoredCandidate
from job_update.skill_pool_store import SkillPoolStore
from job_update.taxonomy import JobTaxonomy
from job_update.text import clean_text


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


class LocalSimilarity:
    def score(self, query: str, candidates: list[str]) -> list[float]:
        query_clean = clean_text(query).casefold()
        scores: list[float] = []
        for candidate in candidates:
            candidate_clean = clean_text(candidate).casefold()
            ratio = SequenceMatcher(None, query_clean, candidate_clean).ratio()
            if candidate_clean and candidate_clean in query_clean:
                ratio = max(ratio, 0.96)
            if query_clean and query_clean in candidate_clean:
                ratio = max(ratio, 0.88)
            scores.append(round(float(ratio), 6))
        return scores


def submit_one_dry_run(payload: dict[str, str]) -> dict[str, Any]:
    result = _classify_and_extract(payload)
    item = _store_review_item(payload, result)
    response = asdict(item)
    response["needs_review"] = result["route"]["status"] != "existing_job"
    return response


def import_csv(frame: pd.DataFrame) -> dict[str, Any]:
    normalized = _normalize_import_frame(frame)
    items = []
    for row in normalized.to_dict(orient="records"):
        items.append(submit_one_dry_run(row))
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
    backup = create_backup(f"confirm existing job {item_id}")
    result = _write_existing_job(item.input, item.result)
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
    if not merge_database:
        item.status = "confirmed_new_no_update"
        item.updated_at = _now()
        item.result["manual_review"] = {
            "standard_category": standard_category,
            "standard_job_title": standard_job_title,
            "match_keywords": match_keywords or standard_job_title,
        }
        return asdict(item)
    backup = create_backup(f"confirm new job {item_id}")
    result = _write_new_job(
        item.input,
        item.result,
        standard_category=standard_category,
        standard_job_title=standard_job_title,
        match_keywords=match_keywords or standard_job_title,
    )
    item.status = "merged_new_job"
    item.updated_at = _now()
    item.result["merge_result"] = result
    item.result["backup"] = backup
    return asdict(item)


def _classify_and_extract(payload: dict[str, str]) -> dict[str, Any]:
    taxonomy = JobTaxonomy.from_csv(BASE_TITLE_DICTIONARY)
    title = clean_text(payload.get("job_title"))
    route = _route_locally(taxonomy, title)
    skills = _extract_skills(payload, route)
    return {
        "job_id": _generate_job_id(clean_text(payload.get("month")) or datetime.now().strftime("%Y-%m"), title),
        "job_title": title,
        "routing_job_title": title,
        "route": route,
        "skills": skills,
        "updated": False,
    }


def _route_locally(taxonomy: JobTaxonomy, title: str) -> dict[str, Any]:
    similarity = LocalSimilarity()
    category_scores = taxonomy.score_categories(title, similarity)
    all_jobs = taxonomy.score_jobs(title, similarity, taxonomy.jobs)
    best_category = category_scores[0] if category_scores else None
    best_job = all_jobs[0] if all_jobs else None
    status = "new_family"
    reason = "best category score is too low for the local router"
    selected_categories = category_scores[:3]
    selected_jobs = all_jobs[:5]
    if best_category is not None and best_category.score >= 0.35:
        status = "potential_new_job"
        reason = "local router found a related family but no high-confidence standard job"
    if best_job is not None and (best_job.score >= 0.55 or _contains_job_title(title, best_job.name)):
        status = "existing_job"
        reason = "matched existing standard job with local similarity"
    return {
        "status": status,
        "reason": reason,
        "best_category": _candidate(best_category),
        "best_job": _candidate(best_job),
        "selected_categories": [_candidate(item) for item in selected_categories],
        "selected_jobs": [_candidate(item) for item in selected_jobs],
    }


def _extract_skills(payload: dict[str, str], route: dict[str, Any]) -> list[dict[str, Any]]:
    text = " ".join(
        [
            clean_text(payload.get("job_title")),
            clean_text(payload.get("responsibility")),
            clean_text(payload.get("requirement")),
        ]
    ).casefold()
    pool = _read_csv(BASE_SKILL_POOL)
    found: list[dict[str, Any]] = []
    if not pool.empty and "normalized_skill" in pool.columns:
        for _, row in pool.iterrows():
            skill = clean_text(row.get("normalized_skill"))
            if not skill:
                continue
            if skill.casefold() in text:
                found.append(_skill_payload(row, "text_match", 0.92))
    if found:
        return _dedupe_skills(found)[:20]

    best_job = ((route.get("best_job") or {}).get("name") or "").strip()
    frequency = _read_csv(BASE_FREQUENCY_OUTPUT)
    if best_job and not frequency.empty and {"standard_job", "skill", "cumulative_skill_count"}.issubset(frequency.columns):
        subset = frequency[frequency["standard_job"].astype(str) == best_job].copy()
        subset["score"] = pd.to_numeric(subset["cumulative_skill_count"], errors="coerce").fillna(0)
        subset = subset.sort_values("score", ascending=False).drop_duplicates("skill").head(12)
        for _, row in subset.iterrows():
            found.append(
                {
                    "normalized_skill": clean_text(row.get("skill")),
                    "kg_display_skill": _lookup_skill_family(pool, clean_text(row.get("skill"))),
                    "skill_type": "",
                    "confidence": 0.66,
                    "source": "historical_frequency",
                }
            )
    return _dedupe_skills(found)[:12]


def _write_existing_job(payload: dict[str, str], result: dict[str, Any]) -> dict[str, Any]:
    best_job = (result.get("route", {}).get("best_job") or {}).get("name")
    best_category = (result.get("route", {}).get("best_category") or {}).get("name") or ""
    if not best_job:
        raise ValueError("Cannot merge existing job without a best_job")
    skills = [_to_normalized_skill(item) for item in result.get("skills", []) if item.get("normalized_skill")]
    return _append_posting_and_sync(payload, result, best_category, best_job, skills)


def _write_new_job(
    payload: dict[str, str],
    result: dict[str, Any],
    *,
    standard_category: str,
    standard_job_title: str,
    match_keywords: str,
) -> dict[str, Any]:
    _upsert_standard_job(standard_job_title, standard_category, match_keywords)
    skills = [_to_normalized_skill(item) for item in result.get("skills", []) if item.get("normalized_skill")]
    return _append_posting_and_sync(payload, result, standard_category, standard_job_title, skills)


def _append_posting_and_sync(
    payload: dict[str, str],
    result: dict[str, Any],
    standard_category: str,
    standard_job: str,
    skills: list[NormalizedSkill],
) -> dict[str, Any]:
    if not skills:
        skills = [NormalizedSkill(normalized_skill="待补充技能", kg_display_skill="待补充")]
    posting = JobPosting(
        job_id=result.get("job_id") or _generate_job_id(payload.get("month", ""), payload.get("job_title", "")),
        month=clean_text(payload.get("month")) or datetime.now().strftime("%Y-%m"),
        job_title=clean_text(payload.get("job_title")),
        job_responsibility=clean_text(payload.get("responsibility")),
        job_requirement=clean_text(payload.get("requirement")),
        metadata={"source": "web_app_review"},
    )
    events, frequency = FrequencyStore(BASE_EVENT_STREAM, BASE_FREQUENCY_OUTPUT).append_existing_job(
        posting=posting,
        standard_job=standard_job,
        normalized_skills=skills,
        write=False,
    )
    pool = SkillPoolStore(BASE_SKILL_POOL).update(
        posting=posting,
        standard_category=standard_category,
        standard_job=standard_job,
        normalized_skills=skills,
        write=False,
    )
    FrequencyStore(BASE_EVENT_STREAM, BASE_FREQUENCY_OUTPUT).write_tables(events, frequency)
    SkillPoolStore(BASE_SKILL_POOL).write_pool(pool)
    SQLiteJobUpdateStore(BASE_DATABASE).initialize_from_csv(
        title_dictionary_path=BASE_TITLE_DICTIONARY,
        event_stream_path=BASE_EVENT_STREAM,
        frequency_path=BASE_FREQUENCY_OUTPUT,
        skill_pool_path=BASE_SKILL_POOL,
    )
    return {
        "job_id": posting.job_id,
        "standard_category": standard_category,
        "standard_job": standard_job,
        "skill_count": len(skills),
        "event_rows": len(events),
        "frequency_rows": len(frequency),
        "skill_pool_rows": len(pool),
    }


def _upsert_standard_job(standard_job_title: str, standard_category: str, match_keywords: str) -> None:
    frame = _read_csv(BASE_TITLE_DICTIONARY)
    row = {
        "standard_job_title": clean_text(standard_job_title),
        "standard_category": clean_text(standard_category),
        "match_keywords": clean_text(match_keywords) or clean_text(standard_job_title),
    }
    if frame.empty:
        frame = pd.DataFrame([row])
    else:
        key = frame["standard_job_title"].astype(str).str.strip().str.casefold()
        existing = key == row["standard_job_title"].casefold()
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


def _candidate(candidate: ScoredCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {"name": candidate.name, "score": round(float(candidate.score), 6), "metadata": candidate.metadata}


def _contains_job_title(query: str, job_title: str) -> bool:
    q = clean_text(query).casefold()
    j = clean_text(job_title).casefold()
    return bool(j and (j in q or q in j))


def _skill_payload(row: pd.Series, source: str, confidence: float) -> dict[str, Any]:
    return {
        "normalized_skill": clean_text(row.get("normalized_skill")),
        "kg_display_skill": clean_text(row.get("kg_display_skill")),
        "skill_type": clean_text(row.get("skill_type")),
        "confidence": confidence,
        "source": source,
    }


def _lookup_skill_family(pool: pd.DataFrame, skill: str) -> str:
    if pool.empty or "normalized_skill" not in pool.columns:
        return ""
    matched = pool[pool["normalized_skill"].astype(str).str.strip().str.casefold() == skill.casefold()]
    if matched.empty:
        return ""
    return clean_text(matched.iloc[0].get("kg_display_skill"))


def _dedupe_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in skills:
        name = clean_text(skill.get("normalized_skill"))
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        skill["normalized_skill"] = name
        output.append(skill)
    return output


def _to_normalized_skill(item: dict[str, Any]) -> NormalizedSkill:
    return NormalizedSkill(
        normalized_skill=clean_text(item.get("normalized_skill")),
        kg_display_skill=clean_text(item.get("kg_display_skill")) or "未分类",
        skill_type=clean_text(item.get("skill_type")) or None,
        confidence=float(item["confidence"]) if item.get("confidence") not in (None, "") else None,
        metadata={"source": item.get("source", "web_app")},
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


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
