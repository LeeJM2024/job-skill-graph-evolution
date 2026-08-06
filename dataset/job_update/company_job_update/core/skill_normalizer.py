from __future__ import annotations

from typing import Protocol

from .models import JobPosting, NormalizedSkill, SkillMention
from .text import clean_text


class SkillNormalizer(Protocol):
    def normalize(self, posting: JobPosting, skills: list[SkillMention]) -> list[NormalizedSkill]:
        ...


class PassthroughSkillNormalizer:
    """Validate and deduplicate final skill_extract output.

    job_update does not normalize skills. It only accepts final
    normalized_skill + kg_display_skill pairs emitted by skill_extract.
    """

    def normalize(self, posting: JobPosting, skills: list[SkillMention]) -> list[NormalizedSkill]:
        normalized: list[NormalizedSkill] = []
        seen: set[str] = set()
        for skill in skills:
            name = clean_text(skill.normalized_skill)
            family = clean_text(skill.kg_display_skill)
            if not name or not family:
                raise ValueError(
                    "skill_extract output must include normalized_skill and kg_display_skill "
                    f"for job_id={posting.job_id}"
                )
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                NormalizedSkill(
                    normalized_skill=name,
                    kg_display_skill=family,
                    skill_type=clean_text(skill.skill_type) or None,
                    confidence=skill.confidence,
                    metadata={
                        **skill.metadata,
                        "evidence_field": clean_text(skill.evidence_field),
                        "evidence_sentence": clean_text(skill.evidence_sentence),
                        "span_text": clean_text(skill.span_text),
                    },
                )
            )
        return normalized
