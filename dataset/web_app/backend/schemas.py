from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class JobInput(BaseModel):
    month: str = Field(default="")
    job_title: str
    responsibility: str = ""
    requirement: str = ""
    processing_mode: Literal["auto", "manual"] = "auto"


class ExistingReviewInput(BaseModel):
    merge_database: bool = False
    standard_job_title: str = ""
    standard_category: str = ""
    skills: list[dict[str, Any]] = Field(default_factory=list)


class NewJobReviewInput(BaseModel):
    standard_category: str
    standard_job_title: str
    match_keywords: str = ""
    merge_database: bool = False
    skills: list[dict[str, Any]] = Field(default_factory=list)


class SkillReviewInput(BaseModel):
    decision: Literal["confirmed", "mapped", "invalid", "new_skill"] = "confirmed"
    normalized_skill: str = ""
    kg_display_skill: str = ""
    skill_type: str = ""


class ProfileOverrideInput(BaseModel):
    standard_job: str
    changes: list[dict[str, Any]] = Field(default_factory=list)


class RunExistingInput(BaseModel):
    run_id: str
    pass_threshold: float = 0.9
    month_start: str = "2024-12"
    month_end: str = "2026-07"


class RunFullInput(BaseModel):
    pass_threshold: float = 0.9
    month_start: str = "2024-12"
    month_end: str = "2026-07"
