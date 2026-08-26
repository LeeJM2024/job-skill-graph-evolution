"""Cross-role evidence for admitting a newly observed job-skill relation.

This module deliberately consumes the existing migration and monthly-spread
outputs.  It does not change how the skill-evolution pipeline calculates those
tables; it only turns confirmed, recent diffusion in similar jobs into an
additional admission signal for a new JD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .similarity import SimilarityBackend
from .taxonomy import JobTaxonomy
from .text import clean_text


@dataclass(slots=True)
class CrossRoleEvidenceResolver:
    taxonomy: JobTaxonomy
    similarity: SimilarityBackend
    migration: pd.DataFrame
    spread: pd.DataFrame
    similarity_threshold: float = 0.85
    strong_similarity_threshold: float = 0.92
    min_peer_jobs: int = 2
    min_confirmed_mentions: int = 2
    min_strong_peer_mentions: int = 3
    recent_months: int = 6

    def resolve(
        self,
        *,
        standard_job: str,
        skill: str,
        observed_month: str,
    ) -> dict[str, object]:
        target_job = clean_text(standard_job)
        normalized_skill = clean_text(skill)
        base = {
            "route": "cross_role_migration",
            "eligible": False,
            "peer_job_count": 0,
            "peer_jobs": [],
            "similarity_threshold": self.similarity_threshold,
            "recent_months": self.recent_months,
        }
        if not target_job or not normalized_skill or not _is_month(observed_month):
            return {**base, "reason": "缺少有效岗位、技能或事件时间，无法进行跨岗位迁移验证"}

        candidates = self.taxonomy.score_jobs(target_job, self.similarity)
        target = next((item for item in candidates if item.name == target_job), None)
        if target is None:
            return {**base, "reason": "标准岗位未找到可比较的相似岗位集合"}
        target_category = clean_text(target.metadata.get("category"))
        peer_scores = {
            item.name: float(item.score)
            for item in candidates
            if item.name != target_job
            and clean_text(item.metadata.get("category")) == target_category
            and float(item.score) >= self.similarity_threshold
        }
        if not peer_scores:
            return {**base, "reason": "同岗位大类内未找到达到相似度阈值的岗位"}

        skill_rows = _skill_rows(self.spread, normalized_skill)
        peer_evidence = _confirmed_recent_peer_evidence(
            skill_rows,
            peer_scores=peer_scores,
            observed_month=observed_month,
            min_confirmed_mentions=self.min_confirmed_mentions,
            recent_months=self.recent_months,
        )
        migration_summary = _migration_summary(self.migration, normalized_skill)
        regular_confirmation = len(peer_evidence) >= self.min_peer_jobs
        strong_peer_confirmation = any(
            item["similarity"] >= self.strong_similarity_threshold
            and item["confirmed_cumulative_mentions"] >= self.min_strong_peer_mentions
            for item in peer_evidence
        )
        eligible = regular_confirmation or strong_peer_confirmation
        if eligible:
            reason = (
                "已获得多个相似岗位的近期确认迁移证据"
                if regular_confirmation
                else "已获得极高相似岗位的增强迁移证据"
            )
        elif peer_evidence:
            reason = "存在相似岗位技能证据，但确认岗位数或支持强度不足"
        else:
            reason = "相似岗位中没有满足近期性和累计确认门槛的技能证据"
        return {
            **base,
            "eligible": eligible,
            "reason": reason,
            "peer_job_count": len(peer_evidence),
            "peer_jobs": peer_evidence,
            "migration_summary": migration_summary,
        }


def _skill_rows(frame: pd.DataFrame, skill: str) -> pd.DataFrame:
    if frame.empty or "skill" not in frame.columns:
        return pd.DataFrame()
    output = frame.copy()
    output["skill"] = output["skill"].map(clean_text)
    output = output[output["skill"].str.casefold() == skill.casefold()].copy()
    for column in ("monthly_skill_count", "cumulative_skill_count"):
        output[column] = pd.to_numeric(output.get(column, 0), errors="coerce").fillna(0).astype(int)
    output["month"] = output.get("month", "").map(clean_text)
    output["standard_job"] = output.get("standard_job", "").map(clean_text)
    return output[(output["month"] != "") & (output["standard_job"] != "")]


def _confirmed_recent_peer_evidence(
    rows: pd.DataFrame,
    *,
    peer_scores: dict[str, float],
    observed_month: str,
    min_confirmed_mentions: int,
    recent_months: int,
) -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for job, group in rows.groupby("standard_job", sort=True):
        if job not in peer_scores:
            continue
        active = group[group["monthly_skill_count"] > 0].sort_values("month")
        confirmed = group[group["cumulative_skill_count"] >= min_confirmed_mentions].sort_values("month")
        if active.empty or confirmed.empty:
            continue
        last_seen_month = clean_text(active.iloc[-1]["month"])
        age = _month_distance(last_seen_month, observed_month)
        if age < 0 or age > recent_months:
            continue
        evidence.append(
            {
                "standard_job": job,
                "similarity": round(peer_scores[job], 6),
                "confirmed_cumulative_mentions": int(confirmed.iloc[-1]["cumulative_skill_count"]),
                "last_seen_month": last_seen_month,
                "months_since_last_seen": age,
            }
        )
    return sorted(evidence, key=lambda item: (-float(item["similarity"]), str(item["standard_job"])))


def _migration_summary(frame: pd.DataFrame, skill: str) -> dict[str, object]:
    if frame.empty or "skill" not in frame.columns:
        return {}
    rows = frame[frame["skill"].map(clean_text).str.casefold() == skill.casefold()]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "migration_confidence": clean_text(row.get("migration_confidence")),
        "confirmed_covered_job_count": _as_int(row.get("confirmed_cumulative_covered_job_count")),
        "confirmed_spread_job_count": _as_int(row.get("confirmed_spread_job_count")),
        "latest_seen_month": clean_text(row.get("latest_seen_month")),
    }


def _as_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _is_month(value: str) -> bool:
    try:
        year, month = clean_text(value).split("-", 1)
        return int(year) >= 2000 and 1 <= int(month) <= 12
    except (TypeError, ValueError):
        return False


def _month_distance(start: str, end: str) -> int:
    start_year, start_month = (int(part) for part in start.split("-", 1))
    end_year, end_month = (int(part) for part in end.split("-", 1))
    return (end_year - start_year) * 12 + end_month - start_month
