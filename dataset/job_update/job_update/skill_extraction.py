from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

from .models import JobPosting, SkillMention


class SkillExtractor(Protocol):
    def extract(self, posting: JobPosting) -> list[SkillMention]:
        ...


class ExistingSkillExtractAdapter:
    """Adapter from dataset/skill_extract to job_update SkillMention objects."""

    def __init__(self, provider: str = "deepseek", **config_overrides) -> None:
        dataset_dir = Path(__file__).resolve().parents[2]
        if str(dataset_dir) not in sys.path:
            sys.path.insert(0, str(dataset_dir))

        from skill_extract import JobSkillExtractor, SkillExtractionConfig

        config = SkillExtractionConfig(provider=provider, **config_overrides)
        self.extractor = JobSkillExtractor(config)

    def extract(self, posting: JobPosting) -> list[SkillMention]:
        result = self.extractor.extract(
            job_id=posting.job_id,
            job_title=posting.job_title,
            requirements=posting.job_requirement,
            responsibility=posting.job_responsibility,
            source_type=str(posting.metadata.get("source_type") or "job_update"),
            source_name=str(posting.metadata.get("source_name") or "existing_job_update"),
        )
        skills: list[SkillMention] = []
        for row in result.job_skills:
            evidence = row.get("evidence") or []
            first_evidence = evidence[0] if evidence else {}
            skills.append(
                SkillMention(
                    raw_skill=_first_value(row.get("span_texts")) or row.get("normalized_skill", ""),
                    normalized_skill=row.get("normalized_skill"),
                    category=row.get("category"),
                    skill_type=row.get("skill_type"),
                    confidence=_optional_float(row.get("max_confidence")),
                    evidence_field=_first_value(row.get("evidence_fields"))
                    or first_evidence.get("evidence_field"),
                    evidence_sentence=_first_value(row.get("evidence_sentences"))
                    or first_evidence.get("evidence_sentence"),
                    span_text=_first_value(row.get("span_texts")) or first_evidence.get("span_text"),
                    metadata={
                        "mention_count": row.get("mention_count"),
                        "evidence_count": row.get("evidence_count"),
                        "match_methods": row.get("match_methods"),
                        "extractor_provider": result.provider,
                        "extractor_model": result.model,
                        "extractor_stats": result.stats,
                    },
                )
            )
        return skills


def _first_value(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value:
        return value
    return None


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
