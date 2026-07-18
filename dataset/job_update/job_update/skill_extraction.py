from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from .models import JobPosting, SkillMention


class SkillExtractor(Protocol):
    def extract(self, posting: JobPosting) -> list[SkillMention]:
        ...


class ExistingSkillExtractAdapter:
    """Adapter from dataset/skill_extract to final job_update SkillMention objects."""

    def __init__(self, provider: str = "deepseek", **config_overrides: Any) -> None:
        _ensure_dataset_on_path()

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
            source_name=str(posting.metadata.get("source") or "existing_job_update"),
        )
        skills = [_skill_from_extract_row(row, result=result) for row in result.job_skills]
        if not skills:
            raise ValueError(f"skill_extract returned no normalized skills for job_id={posting.job_id}")
        return skills


class ManualSkillNormalizeAdapter:
    """Normalize manually supplied raw skill keywords through skill_extract.normalizer."""

    def __init__(
        self,
        *,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout: int = 90,
        retries: int = 2,
        temperature: float = 0.0,
        allow_new_skills: bool = True,
    ) -> None:
        _ensure_dataset_on_path()

        from skill_extract import extract_job_skills_api as api
        from skill_extract.normalizer import DEFAULT_CACHE, SkillNormalizer

        api.load_env_file()
        provider_config = api.PROVIDERS[provider]
        self.provider = provider
        self.model = model or os.getenv(provider_config["model_env"], provider_config["default_model"])
        self.base_url = base_url or os.getenv(provider_config["base_url_env"], provider_config["default_base_url"])
        self.api_key_env = api_key_env or provider_config["api_key_env"]
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self.allow_new_skills = allow_new_skills
        self.cache_path = DEFAULT_CACHE
        self.normalizer = SkillNormalizer()

    def normalize_keywords(self, posting: JobPosting, keywords: list[str]) -> list[SkillMention]:
        rows = [
            {
                "job_id": posting.job_id,
                "job_title": posting.job_title,
                "skill_keyword": keyword,
                "span_text": keyword,
                "normalized_skill_candidate": "",
                "evidence_field": "manual_skills",
                "evidence_sentence": "",
            }
            for keyword in keywords
            if str(keyword).strip()
        ]
        if not rows:
            return []

        normalized_rows, _ = self.normalizer.normalize_rows(rows)
        unresolved = [
            row for row in normalized_rows if str(row.get("normalization_status")) == "unresolved"
        ]
        if unresolved:
            normalized_rows, _ = self.normalizer.normalize_unknowns_with_api(
                normalized_rows,
                provider=self.provider,
                model=self.model,
                base_url=self.base_url,
                api_key_env=self.api_key_env,
                cache_path=self.cache_path,
                timeout=self.timeout,
                retries=self.retries,
                temperature=self.temperature,
                allow_new_skills=self.allow_new_skills,
            )

        invalid_rows = [
            row
            for row in normalized_rows
            if not str(row.get("normalized_skill") or "").strip()
            or not str(row.get("kg_display_skill") or "").strip()
        ]
        if invalid_rows:
            sample = invalid_rows[:3]
            raise RuntimeError(
                "Manual skill normalization did not produce normalized_skill and kg_display_skill "
                f"for {len(invalid_rows)} rows. Sample: {sample}"
            )

        return [_skill_from_normalized_row(row) for row in normalized_rows]


class ManualSkillKeywordExtractor:
    """SkillExtractor wrapper for route-first manual skill normalization."""

    def __init__(self, normalizer: ManualSkillNormalizeAdapter, raw_keywords: list[str]) -> None:
        self.normalizer = normalizer
        self.raw_keywords = raw_keywords

    def extract(self, posting: JobPosting) -> list[SkillMention]:
        return self.normalizer.normalize_keywords(posting, self.raw_keywords)


def _ensure_dataset_on_path() -> None:
    dataset_dir = Path(__file__).resolve().parents[2]
    if str(dataset_dir) not in sys.path:
        sys.path.insert(0, str(dataset_dir))


def _skill_from_extract_row(row: dict[str, Any], *, result: Any) -> SkillMention:
    skill = _skill_from_normalized_row(row)
    skill.metadata.update(
        {
            "mention_count": row.get("mention_count"),
            "evidence_count": row.get("evidence_count"),
            "match_methods": row.get("match_methods"),
            "extractor_provider": result.provider,
            "extractor_model": result.model,
            "extractor_stats": result.stats,
        }
    )
    return skill


def _skill_from_normalized_row(row: dict[str, Any]) -> SkillMention:
    normalized_skill = str(row.get("normalized_skill") or "").strip()
    kg_display_skill = str(row.get("kg_display_skill") or "").strip()
    if not normalized_skill or not kg_display_skill:
        raise ValueError(
            "skill_extract output must include normalized_skill and kg_display_skill. "
            f"Row: {row}"
        )
    evidence = row.get("evidence") or []
    first_evidence = evidence[0] if evidence else {}
    return SkillMention(
        normalized_skill=normalized_skill,
        kg_display_skill=kg_display_skill,
        skill_type=str(row.get("skill_type") or "").strip() or None,
        confidence=_optional_float(row.get("max_confidence") or row.get("normalization_confidence")),
        evidence_field=_first_value(row.get("evidence_fields")) or first_evidence.get("evidence_field"),
        evidence_sentence=_first_value(row.get("evidence_sentences"))
        or first_evidence.get("evidence_sentence"),
        span_text=_first_value(row.get("span_texts"))
        or first_evidence.get("span_text")
        or str(row.get("span_text") or "").strip()
        or str(row.get("skill_keyword") or "").strip()
        or None,
        metadata={
            "normalization_method": row.get("normalization_method"),
            "normalization_status": row.get("normalization_status"),
            "needs_review": row.get("needs_review"),
            "normalization_reason": row.get("normalization_reason"),
        },
    )


def _first_value(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str) and value:
        return value
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
