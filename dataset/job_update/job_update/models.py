from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RouteStatus = Literal["existing_job", "potential_new_job", "new_family"]


@dataclass(slots=True)
class SkillMention:
    """Skill extraction input before project-level normalization.

    Required field:
    - raw_skill: the extracted skill keyword/span.

    Optional fields are preserved for later normalization, audit, and graph import.
    If normalized_skill is already supplied by an upstream extractor, the default
    normalizer will use it directly.
    """

    raw_skill: str
    normalized_skill: str | None = None
    category: str | None = None
    skill_type: str | None = None
    confidence: float | None = None
    evidence_field: str | None = None
    evidence_sentence: str | None = None
    span_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedSkill:
    """Project-level normalized skill used by the frequency updater."""

    normalized_skill: str
    raw_skill: str | None = None
    category: str | None = None
    skill_type: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JobPosting:
    job_id: str
    month: str
    job_title: str
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
    event_stream_path: str | None = None
    frequency_path: str | None = None


@dataclass(slots=True)
class ProcessResult:
    route: JobRoute
    posting: JobPosting
    update: ExistingJobUpdate | None = None

