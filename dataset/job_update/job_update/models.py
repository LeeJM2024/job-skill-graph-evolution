from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RouteStatus = Literal["existing_job", "potential_new_job", "new_family"]


@dataclass(slots=True)
class SkillMention:
    """Final normalized skill emitted by skill_extract."""

    normalized_skill: str
    kg_display_skill: str
    skill_type: str | None = None
    confidence: float | None = None
    evidence_field: str | None = None
    evidence_sentence: str | None = None
    span_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedSkill:
    """Final skill used by the frequency updater and carried to graph layers."""

    normalized_skill: str
    kg_display_skill: str
    skill_type: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobPosting:
    job_id: str
    month: str
    job_title: str
    routing_job_title: str = ""
    job_responsibility: str = ""
    job_requirement: str = ""
    skills: list[SkillMention] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoredCandidate:
    name: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobRoute:
    status: RouteStatus
    selected_categories: list[ScoredCandidate]
    selected_jobs: list[ScoredCandidate]
    best_category: ScoredCandidate | None = None
    best_job: ScoredCandidate | None = None
    reason: str = ""


@dataclass(slots=True)
class ExistingJobUpdate:
    standard_job: str
    month: str
    normalized_skills: list[NormalizedSkill]
    monthly_rows: int
    frequency_rows: int
    skill_pool_rows: int = 0
    lifecycle_rows: int = 0
    migration_rows: int = 0
    spread_rows: int = 0
    profile_snapshot_rows: int = 0
    profile_diff_rows: int = 0
    event_stream_path: str | None = None
    frequency_path: str | None = None
    skill_pool_path: str | None = None
    lifecycle_path: str | None = None
    migration_path: str | None = None
    spread_path: str | None = None
    profile_snapshot_path: str | None = None
    profile_diff_path: str | None = None


@dataclass(slots=True)
class ProcessResult:
    route: JobRoute
    posting: JobPosting
    update: ExistingJobUpdate | None = None

