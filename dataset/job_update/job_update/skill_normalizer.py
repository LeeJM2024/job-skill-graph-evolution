from __future__ import annotations

from typing import Protocol

from .models import JobPosting, NormalizedSkill, SkillMention
from .text import clean_text


class SkillNormalizer(Protocol):
    def normalize(self, posting: JobPosting, skills: list[SkillMention]) -> list[NormalizedSkill]:
        ...


class PassthroughSkillNormalizer:
    """Placeholder for later rule-based and LLM-assisted normalization.

    Expected input shape for each extracted skill:
    {
      "raw_skill": "大语言模型",
      "normalized_skill": "LLM",        # optional for now
      "category": "AI算法",             # optional
      "skill_type": "required",         # optional: required/preferred/etc.
      "confidence": 0.92,               # optional
      "evidence_field": "requirement",  # optional
      "evidence_sentence": "...",       # optional
      "span_text": "大语言模型",         # optional
      "metadata": {...}                 # optional
    }

    Later you can replace this class with:
    1. manual forced normalization rules,
    2. ontology lookup,
    3. LLM/API assisted disambiguation.
    """

    def normalize(self, posting: JobPosting, skills: list[SkillMention]) -> list[NormalizedSkill]:
        normalized: list[NormalizedSkill] = []
        seen: set[str] = set()
        for skill in skills:
            name = clean_text(skill.normalized_skill) or clean_text(skill.raw_skill)
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                NormalizedSkill(
                    normalized_skill=name,
                    raw_skill=clean_text(skill.raw_skill) or None,
                    category=clean_text(skill.category) or None,
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

