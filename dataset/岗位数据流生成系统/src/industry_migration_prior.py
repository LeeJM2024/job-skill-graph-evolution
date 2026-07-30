"""Industry-informed migration priors for emerging technical skills."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillMigrationPrior:
    skill: str
    kg_display_skill: str
    skill_type: str
    industry_origin_month: str
    origin_jobs: tuple[str, ...]
    early_jobs: tuple[str, ...]
    mid_jobs: tuple[str, ...]
    late_jobs: tuple[str, ...]
    notes: str = ""

    @property
    def all_jobs(self) -> tuple[str, ...]:
        seen: set[str] = set()
        jobs: list[str] = []
        for job in [*self.origin_jobs, *self.early_jobs, *self.mid_jobs, *self.late_jobs]:
            if job and job not in seen:
                seen.add(job)
                jobs.append(job)
        return tuple(jobs)

    def stage_for_job(self, standard_job: str) -> str:
        if standard_job in self.origin_jobs:
            return "origin"
        if standard_job in self.early_jobs:
            return "early"
        if standard_job in self.mid_jobs:
            return "mid"
        if standard_job in self.late_jobs:
            return "late"
        return ""


def load_industry_priors(path: Path) -> dict[str, SkillMigrationPrior]:
    if not path.exists():
        raise FileNotFoundError(f"Missing skill industry migration prior file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    priors: dict[str, SkillMigrationPrior] = {}
    for row in rows:
        skill = _clean(row.get("skill"))
        if not skill:
            continue
        prior = SkillMigrationPrior(
            skill=skill,
            kg_display_skill=_clean(row.get("kg_display_skill")),
            skill_type=_clean(row.get("skill_type")) or "new",
            industry_origin_month=_clean(row.get("industry_origin_month")),
            origin_jobs=tuple(_split_jobs(row.get("origin_jobs"))),
            early_jobs=tuple(_split_jobs(row.get("early_jobs"))),
            mid_jobs=tuple(_split_jobs(row.get("mid_jobs"))),
            late_jobs=tuple(_split_jobs(row.get("late_jobs"))),
            notes=_clean(row.get("notes")),
        )
        if not prior.industry_origin_month or not prior.origin_jobs:
            raise ValueError(
                "Each industry prior row must include industry_origin_month and origin_jobs: "
                f"skill={skill}"
            )
        priors[skill.casefold()] = prior
    return priors


def shift_month(month: str, offset: int) -> str:
    year_text, month_text = month.split("-", 1)
    total = int(year_text) * 12 + int(month_text) - 1 + offset
    year = total // 12
    month_index = total % 12
    return f"{year:04d}-{month_index + 1:02d}"


def activation_month(prior: SkillMigrationPrior, standard_job: str) -> str:
    stage = prior.stage_for_job(standard_job)
    if stage == "origin":
        return prior.industry_origin_month
    if stage == "early":
        return shift_month(
            prior.industry_origin_month,
            1 + _stable_offset(prior.skill, standard_job, modulo=2),
        )
    if stage == "mid":
        return shift_month(
            prior.industry_origin_month,
            5 + _stable_offset(prior.skill, standard_job, modulo=4),
        )
    if stage == "late":
        return shift_month(
            prior.industry_origin_month,
            11 + _stable_offset(prior.skill, standard_job, modulo=6),
        )
    return ""


def stage_min_probability(stage: str) -> float:
    if stage == "origin":
        return 0.48
    if stage == "early":
        return 0.34
    if stage == "mid":
        return 0.22
    if stage == "late":
        return 0.13
    return 0.0


def stage_min_source_count(stage: str) -> int:
    if stage == "origin":
        return 90
    if stage == "early":
        return 50
    if stage == "mid":
        return 22
    if stage == "late":
        return 8
    return 0


def _split_jobs(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in (_clean(part) for part in value.split(";")) if item]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _stable_offset(skill: str, standard_job: str, *, modulo: int) -> int:
    if modulo <= 1:
        return 0
    text = f"{skill}|{standard_job}"
    return sum((index + 1) * ord(char) for index, char in enumerate(text)) % modulo
