from __future__ import annotations

from pydantic import BaseModel, Field


class JobInput(BaseModel):
    month: str = Field(default="")
    job_title: str
    responsibility: str = ""
    requirement: str = ""


class ExistingReviewInput(BaseModel):
    merge_database: bool = False


class NewJobReviewInput(BaseModel):
    standard_category: str
    standard_job_title: str
    match_keywords: str = ""
    merge_database: bool = False


class RunExistingInput(BaseModel):
    run_id: str
    pass_threshold: float = 0.9
    month_start: str = "2024-12"
    month_end: str = "2026-07"


class RunFullInput(BaseModel):
    pass_threshold: float = 0.9
    month_start: str = "2024-12"
    month_end: str = "2026-07"
