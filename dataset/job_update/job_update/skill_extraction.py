from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Protocol

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
            normalized_skill = str(row.get("normalized_skill") or "").strip()
            kg_display_skill = str(row.get("kg_display_skill") or "").strip()
            if not normalized_skill or not kg_display_skill:
                raise ValueError(
                    "skill_extract result must include normalized_skill and kg_display_skill "
                    f"for job_id={posting.job_id}: {row}"
                )
            evidence = row.get("evidence") or []
            first_evidence = evidence[0] if evidence else {}
            skills.append(
                SkillMention(
                    normalized_skill=normalized_skill,
                    kg_display_skill=kg_display_skill,
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
                        "skill_keyword": row.get("skill_keyword"),
                        "extractor_provider": result.provider,
                        "extractor_model": result.model,
                        "extractor_stats": result.stats,
                    },
                )
            )
        return skills


class ManualSkillNormalizeAdapter:
    """Normalize manually supplied skill keywords through skill_extract.normalizer."""

    def __init__(
        self,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout: int = 90,
        retries: int = 2,
        temperature: float = 0.0,
        batch_size: int = 80,
        allow_new_skills: bool = True,
        load_env: bool = True,
        **normalizer_overrides,
    ) -> None:
        dataset_dir = Path(__file__).resolve().parents[2]
        if str(dataset_dir) not in sys.path:
            sys.path.insert(0, str(dataset_dir))

        from skill_extract import extract_job_skills_api as extract_api
        from skill_extract.normalizer import DEFAULT_CACHE, SkillNormalizer

        if load_env:
            extract_api.load_env_file()
        self.normalizer = SkillNormalizer(**normalizer_overrides)
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self.batch_size = batch_size
        self.allow_new_skills = allow_new_skills
        self.cache_path = DEFAULT_CACHE

    def normalize(self, posting: JobPosting, skill_keywords: list[str]) -> list[SkillMention]:
        rows = self._rows(posting, skill_keywords)
        normalized_rows, stats = self.normalizer.normalize_rows(rows)
        normalized_rows, api_stats = self.normalizer.normalize_unknowns_with_api(
            normalized_rows,
            provider=self.provider,
            model=self.model,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
            cache_path=self.cache_path,
            timeout=self.timeout,
            retries=self.retries,
            temperature=self.temperature,
            batch_size=self.batch_size,
            allow_new_skills=self.allow_new_skills,
        )
        stats.update({f"api_{key}": value for key, value in api_stats.items()})
        invalid_rows = [
            row
            for row in normalized_rows
            if not str(row.get("normalized_skill") or "").strip()
            or not str(row.get("kg_display_skill") or "").strip()
        ]
        if invalid_rows:
            raise ValueError(
                "Manual skills must be normalized by skill_extract before job_update can use them. "
                f"Unresolved rows: {invalid_rows[:3]}"
            )
        return [self._skill_from_row(row, dict(stats)) for row in normalized_rows]

    def _rows(self, posting: JobPosting, skill_keywords: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        evidence_sentence = posting.job_requirement or posting.job_responsibility or posting.job_title
        for skill in skill_keywords:
            value = str(skill or "").strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "job_id": posting.job_id,
                    "job_title": posting.job_title,
                    "source_type": str(posting.metadata.get("source_type") or "job_update"),
                    "source_name": str(posting.metadata.get("source_name") or "manual_skill_input"),
                    "skill_keyword": value,
                    "span_text": value,
                    "evidence_sentence": evidence_sentence,
                    "evidence_field": "manual_skill",
                    "skill_type": "required",
                    "max_confidence": 1.0,
                    "mention_count": 1,
                    "evidence_count": 1,
                    "evidence_sentences": [evidence_sentence],
                    "evidence_fields": ["manual_skill"],
                    "span_texts": [value],
                    "match_methods": ["manual_input"],
                }
            )
        return rows

    @staticmethod
    def _skill_from_row(row: dict[str, Any], stats: dict[str, int]) -> SkillMention:
        return SkillMention(
            normalized_skill=str(row.get("normalized_skill") or "").strip(),
            kg_display_skill=str(row.get("kg_display_skill") or "").strip(),
            skill_type=str(row.get("skill_type") or "").strip() or None,
            confidence=_optional_float(row.get("normalization_confidence"))
            or _optional_float(row.get("max_confidence")),
            evidence_field=_first_value(row.get("evidence_fields"))
            or str(row.get("evidence_field") or "").strip()
            or None,
            evidence_sentence=_first_value(row.get("evidence_sentences"))
            or str(row.get("evidence_sentence") or "").strip()
            or None,
            span_text=_first_value(row.get("span_texts")) or str(row.get("span_text") or "").strip() or None,
            metadata={
                "skill_keyword": row.get("skill_keyword"),
                "normalization_method": row.get("normalization_method"),
                "normalization_status": row.get("normalization_status"),
                "needs_review": row.get("needs_review"),
                "manual_normalization_stats": stats,
            },
        )


class ManualSkillKeywordExtractor:
    """SkillExtractor wrapper for raw skill keywords supplied by the user."""

    def __init__(self, normalizer: ManualSkillNormalizeAdapter, skill_keywords: list[str]) -> None:
        self.normalizer = normalizer
        self.skill_keywords = skill_keywords

    def extract(self, posting: JobPosting) -> list[SkillMention]:
        return self.normalizer.normalize(posting, self.skill_keywords)


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
