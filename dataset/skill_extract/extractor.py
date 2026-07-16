from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import extract_job_skills_api as api


@dataclass(slots=True)
class SkillExtractionConfig:
    provider: str = "deepseek"
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    gold_path: Path = api.DEFAULT_GOLD
    cache_path: Path = api.DEFAULT_CACHE
    max_sentences_per_job: int = 40
    max_ontology_skills: int = 260
    max_gold_examples: int = 50
    timeout: int = 90
    retries: int = 2
    temperature: float = 0.0
    load_env: bool = True


@dataclass(slots=True)
class SkillExtractionResult:
    job_id: str
    job_title: str
    mentions: list[dict[str, Any]]
    job_skills: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    stats: dict[str, int]
    provider: str
    model: str
    base_url: str
    prompt_version: str = api.PROMPT_VERSION


class JobSkillExtractor:
    """Programmatic interface over the existing API-based skill extraction pipeline.

    This class intentionally reuses the functions in extract_job_skills_api.py
    instead of duplicating prompt, cache, ontology, normalization, and aggregation
    behavior. job_update should depend on this class rather than on the CLI.
    """

    def __init__(self, config: SkillExtractionConfig | None = None) -> None:
        self.config = config or SkillExtractionConfig()
        if self.config.provider not in api.PROVIDERS:
            raise ValueError(f"Unsupported provider: {self.config.provider}")
        if self.config.load_env:
            api.load_env_file()

        provider = api.PROVIDERS[self.config.provider]
        self.provider = self.config.provider
        self.model = self.config.model or os.getenv(provider["model_env"], provider["default_model"])
        self.base_url = self.config.base_url or os.getenv(provider["base_url_env"], provider["default_base_url"])
        self.api_key_env = self.config.api_key_env or provider["api_key_env"]

        self.ontology = api.load_gold_ontology(
            self.config.gold_path,
            max_examples=self.config.max_gold_examples,
        )
        self.ontology_digest = hashlib.sha256(
            json.dumps(self.ontology, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        self.system_prompt = api.build_system_prompt(self.ontology, self.config.max_ontology_skills)
        self.cache = api.load_cache(self.config.cache_path)

    def extract(
        self,
        *,
        job_id: str,
        job_title: str,
        job_description: str = "",
        requirements: str = "",
        responsibility: str = "",
        qualification: str = "",
        source_type: str = "job_update",
        source_name: str = "existing_job_update",
    ) -> SkillExtractionResult:
        job = {
            "job_id": api.clean_text(job_id),
            "job_title": api.clean_text(job_title),
            "source_type": api.clean_text(source_type),
            "source_name": api.clean_text(source_name),
            "job_description": api.clean_text(job_description),
            "requirements": api.clean_text(requirements),
            "responsibility": api.clean_text(responsibility),
            "qualification": api.clean_text(qualification),
        }
        return self.extract_job(job)

    def extract_job(self, job: dict[str, Any]) -> SkillExtractionResult:
        units = api.build_units(job, self.config.max_sentences_per_job)
        stats: Counter[str] = Counter()
        mentions: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if not units:
            return self._result(job, mentions, [], rejected, stats)

        result = self._call_or_load_cache(job, units, stats)
        pipeline_stats = result.get("pipeline_stats", {})
        stats["first_pass_mentions"] += int(pipeline_stats.get("first_pass_mentions", 0))
        stats["pipeline_net_new_mentions"] += int(pipeline_stats.get("net_new_mentions", 0))
        stats["mandatory_rule_new_mentions"] += int(pipeline_stats.get("mandatory_rule_new_mentions", 0))
        stats["boundary_filtered_mentions"] += int(pipeline_stats.get("boundary_filtered_mentions", 0))

        unit_by_id = {unit["sentence_id"]: unit for unit in units}
        for mention in result.get("mentions", []):
            row, error = api.normalize_mention(mention, unit_by_id, job)
            if error:
                rejected.append(
                    {
                        "job_id": api.clean_text(job.get("job_id")),
                        "job_title": api.clean_text(job.get("job_title")),
                        "mention": mention,
                        "error": error,
                    }
                )
                stats["rejected"] += 1
                continue
            mentions.append(row)
            stats["accepted"] += 1

        mentions = api.dedupe_mentions(mentions)
        job_skills = api.aggregate_job_skills(mentions)
        stats["mentions"] = len(mentions)
        stats["job_skill_pairs"] = len(job_skills)
        return self._result(job, mentions, job_skills, rejected, stats)

    def _call_or_load_cache(
        self,
        job: dict[str, Any],
        units: list[dict[str, str]],
        stats: Counter[str],
    ) -> dict[str, Any]:
        key = api.cache_key(self.model, self.base_url, units, self.ontology_digest)
        if key in self.cache:
            stats["cache_hit"] += 1
            return self.cache[key]["result"]

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key. Set ${self.api_key_env} first.")

        payload = {
            "job": {
                "job_id": api.clean_text(job.get("job_id")),
                "job_title": api.clean_text(job.get("job_title")),
                "source_type": api.clean_text(job.get("source_type")),
                "source_name": api.clean_text(job.get("source_name")) or api.clean_text(job.get("source")),
            },
            "sentences": units,
        }
        result = api.call_skill_extraction(
            api_key=api_key,
            model=self.model,
            base_url=self.base_url,
            system_prompt=self.system_prompt,
            user_payload=payload,
            timeout=self.config.timeout,
            retries=self.config.retries,
            temperature=self.config.temperature,
            literal_skills=(item["normalized_skill"] for item in self.ontology["skills"]),
        )
        cache_item = {
            "cache_key": key,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "result": result,
        }
        api.append_cache(self.config.cache_path, cache_item)
        self.cache[key] = cache_item
        stats["api_call"] += 1
        return result

    def _result(
        self,
        job: dict[str, Any],
        mentions: list[dict[str, Any]],
        job_skills: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        stats: Counter[str],
    ) -> SkillExtractionResult:
        return SkillExtractionResult(
            job_id=api.clean_text(job.get("job_id")),
            job_title=api.clean_text(job.get("job_title")),
            mentions=mentions,
            job_skills=job_skills,
            rejected=rejected,
            stats=dict(stats),
            provider=self.provider,
            model=self.model,
            base_url=self.base_url,
        )
