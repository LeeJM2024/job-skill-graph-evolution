"""Normalize extracted JD skill candidates after skill extraction.

This layer consumes extractor outputs such as `skill_keyword` and `span_text`.
It maps them to the curated normalization/display dictionaries when possible.
Unknown skills are kept for review instead of being silently forced into the
wrong normalized node.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import extract_job_skills_api as extract_api


DATASET_DICT_DIR = extract_api.SKILL_EXTRACT_DIR
DEFAULT_EXTRACTION_DICTIONARY = DATASET_DICT_DIR / "\u6cdb\u62bd\u53d6\u7ea7\u8bcd\u5178.csv"
DEFAULT_NORMALIZED_DICTIONARY = DATASET_DICT_DIR / "\u5f52\u4e00\u5316\u7ea7\u8bcd\u5178.csv"
DEFAULT_DISPLAY_DICTIONARY = DATASET_DICT_DIR / "\u5c55\u793a\u7ea7\u8bcd\u5178.csv"
DEFAULT_CACHE = extract_api.SKILL_EXTRACT_DIR / "cache" / "skill_normalization_api_cache.jsonl"


@dataclass(frozen=True, slots=True)
class NormalizationDecision:
    normalized_skill: str
    kg_display_skill: str
    method: str
    confidence: float
    status: str
    needs_review: bool
    reason: str = ""
    proposed_normalized_skill: str = ""


class SkillNormalizer:
    def __init__(
        self,
        *,
        extraction_dictionary: Path = DEFAULT_EXTRACTION_DICTIONARY,
        normalized_dictionary: Path = DEFAULT_NORMALIZED_DICTIONARY,
        display_dictionary: Path = DEFAULT_DISPLAY_DICTIONARY,
    ) -> None:
        self.extraction_dictionary = extraction_dictionary
        self.normalized_dictionary = normalized_dictionary
        self.display_dictionary = display_dictionary
        self.keyword_map = self._load_extraction_dictionary(extraction_dictionary)
        self.normalized_skills = self._load_normalized_dictionary(normalized_dictionary)
        self.display_map = self._load_display_dictionary(display_dictionary)

    @staticmethod
    def clean(value: Any) -> str:
        return extract_api.clean_text(value)

    def _load_extraction_dictionary(self, path: Path) -> dict[str, dict[str, str]]:
        mapping: dict[str, dict[str, str]] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                keyword = self.clean(row.get("skill_keyword"))
                normalized = self.clean(row.get("normalized_skill"))
                display = self.clean(row.get("kg_display_skill"))
                if not keyword or not normalized:
                    continue
                mapping.setdefault(
                    keyword.casefold(),
                    {
                        "skill_keyword": keyword,
                        "normalized_skill": normalized,
                        "kg_display_skill": display,
                    },
                )
        return mapping

    def _load_normalized_dictionary(self, path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                skill = self.clean(row.get("skill"))
                if skill:
                    result[skill.casefold()] = skill
        return result

    def _load_display_dictionary(self, path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                skill = self.clean(row.get("skill"))
                display = self.clean(row.get("kg_display_skill"))
                if skill:
                    result[skill.casefold()] = display
        return result

    def normalize_one(self, row: dict[str, Any]) -> NormalizationDecision:
        candidate = self.clean(row.get("normalized_skill_candidate"))
        if candidate and candidate.casefold() in self.normalized_skills:
            skill = self.normalized_skills[candidate.casefold()]
            return self._known(skill, "extractor_candidate", 1.0)

        for field in ("dictionary_skill_keyword", "skill_keyword", "span_text"):
            value = self.clean(row.get(field))
            if not value:
                continue
            mapped = self.keyword_map.get(value.casefold())
            if mapped and mapped["normalized_skill"].casefold() in self.normalized_skills:
                skill = self.normalized_skills[mapped["normalized_skill"].casefold()]
                display = mapped["kg_display_skill"] or self.display_map.get(skill.casefold(), "")
                return NormalizationDecision(
                    normalized_skill=skill,
                    kg_display_skill=display,
                    method=f"{field}_dictionary_exact",
                    confidence=1.0,
                    status="normalized",
                    needs_review=False,
                    reason="exact dictionary match",
                )
            if value.casefold() in self.normalized_skills:
                skill = self.normalized_skills[value.casefold()]
                return self._known(skill, f"{field}_already_normalized", 0.98)

        skill_keyword = self.clean(row.get("skill_keyword")) or self.clean(row.get("span_text"))
        return NormalizationDecision(
            normalized_skill="",
            kg_display_skill="",
            method="unresolved_local",
            confidence=0.0,
            status="unresolved",
            needs_review=True,
            reason=f"no exact dictionary match for {skill_keyword}",
            proposed_normalized_skill=skill_keyword,
        )

    def _known(self, skill: str, method: str, confidence: float) -> NormalizationDecision:
        return NormalizationDecision(
            normalized_skill=skill,
            kg_display_skill=self.display_map.get(skill.casefold(), ""),
            method=method,
            confidence=confidence,
            status="normalized",
            needs_review=False,
            reason="known normalized skill",
        )

    def normalize_rows(self, rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
        output: list[dict[str, Any]] = []
        stats: Counter[str] = Counter()
        for row in rows:
            decision = self.normalize_one(row)
            stats[decision.status] += 1
            stats[decision.method] += 1
            output.append(apply_decision(row, decision))
        return output, stats

    def normalize_unknowns_with_api(
        self,
        rows: list[dict[str, Any]],
        *,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        cache_path: Path = DEFAULT_CACHE,
        timeout: int = 90,
        retries: int = 2,
        temperature: float = 0.0,
        batch_size: int = 80,
        allow_new_skills: bool = False,
    ) -> tuple[list[dict[str, Any]], Counter[str]]:
        unresolved = [row for row in rows if str(row.get("normalization_status")) == "unresolved"]
        if not unresolved:
            return rows, Counter()

        provider_config = _provider_config(provider, model, base_url, api_key_env)
        api_key = os.getenv(provider_config["api_key_env"])
        if not api_key:
            raise RuntimeError(f"Missing API key. Set ${provider_config['api_key_env']} first.")

        cache = extract_api.load_cache(cache_path)
        updated_by_key: dict[tuple[str, str], NormalizationDecision] = {}
        stats: Counter[str] = Counter()
        unique_items = unique_unresolved_items(unresolved)

        for batch in batched(unique_items, batch_size):
            cache_key = normalization_cache_key(batch, self.normalized_skills, self.display_map, allow_new_skills)
            if cache_key in cache:
                result = cache[cache_key]["result"]
                stats["api_cache_hit"] += 1
            else:
                result = call_normalization_api(
                    api_key=api_key,
                    model=provider_config["model"],
                    base_url=provider_config["base_url"],
                    batch=batch,
                    normalizer=self,
                    allow_new_skills=allow_new_skills,
                    timeout=timeout,
                    retries=retries,
                    temperature=temperature,
                )
                extract_api.append_cache(
                    cache_path,
                    {
                        "cache_key": cache_key,
                        "provider": provider,
                        "model": provider_config["model"],
                        "base_url": provider_config["base_url"],
                        "result": result,
                    },
                )
                stats["api_call"] += 1

            for item in result.get("items", []):
                key = (self.clean(item.get("skill_keyword")).casefold(), self.clean(item.get("span_text")).casefold())
                decision = self._decision_from_api_item(item, allow_new_skills)
                updated_by_key[key] = decision
                stats[decision.status] += 1

        output: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("normalization_status")) != "unresolved":
                output.append(row)
                continue
            key = (self.clean(row.get("skill_keyword")).casefold(), self.clean(row.get("span_text")).casefold())
            decision = updated_by_key.get(key)
            output.append(apply_decision(row, decision) if decision else row)
        return output, stats

    def _decision_from_api_item(self, item: dict[str, Any], allow_new_skills: bool) -> NormalizationDecision:
        decision = self.clean(item.get("decision")).lower()
        normalized = self.clean(item.get("normalized_skill"))
        proposed = self.clean(item.get("proposed_normalized_skill")) or normalized
        reason = self.clean(item.get("reason"))
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        if decision == "existing" and normalized.casefold() in self.normalized_skills:
            skill = self.normalized_skills[normalized.casefold()]
            return NormalizationDecision(
                normalized_skill=skill,
                kg_display_skill=self.display_map.get(skill.casefold(), ""),
                method="llm_existing_skill",
                confidence=confidence,
                status="normalized",
                needs_review=confidence < 0.75,
                reason=reason,
            )
        if decision == "new" and allow_new_skills and proposed:
            return NormalizationDecision(
                normalized_skill=proposed,
                kg_display_skill=self.clean(item.get("kg_display_skill")),
                method="llm_new_skill",
                confidence=confidence,
                status="new_skill_candidate",
                needs_review=True,
                reason=reason,
                proposed_normalized_skill=proposed,
            )
        return NormalizationDecision(
            normalized_skill="",
            kg_display_skill="",
            method="llm_reject_or_unresolved",
            confidence=confidence,
            status="unresolved",
            needs_review=True,
            reason=reason or "LLM did not map to an existing normalized skill",
            proposed_normalized_skill=proposed,
        )


def apply_decision(row: dict[str, Any], decision: NormalizationDecision | None) -> dict[str, Any]:
    if decision is None:
        return dict(row)
    output = dict(row)
    output.update(
        {
            "normalized_skill": decision.normalized_skill,
            "kg_display_skill": decision.kg_display_skill,
            "normalization_method": decision.method,
            "normalization_confidence": f"{decision.confidence:.4f}",
            "normalization_status": decision.status,
            "needs_review": "true" if decision.needs_review else "false",
            "normalization_reason": decision.reason,
            "proposed_normalized_skill": decision.proposed_normalized_skill,
        }
    )
    return output


def unique_unresolved_items(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        skill_keyword = SkillNormalizer.clean(row.get("skill_keyword")) or SkillNormalizer.clean(row.get("span_text"))
        span_text = SkillNormalizer.clean(row.get("span_text"))
        if not skill_keyword and not span_text:
            continue
        key = (skill_keyword.casefold(), span_text.casefold())
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "skill_keyword": skill_keyword,
                "span_text": span_text,
                "evidence_sentence": SkillNormalizer.clean(row.get("evidence_sentence"))[:220],
            }
        )
    return output


def batched(items: list[dict[str, str]], batch_size: int) -> Iterable[list[dict[str, str]]]:
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


def normalization_cache_key(
    batch: list[dict[str, str]],
    normalized_skills: dict[str, str],
    display_map: dict[str, str],
    allow_new_skills: bool,
) -> str:
    payload = {
        "version": "skill_normalization_v1_2026_07_17",
        "batch": batch,
        "normalized_skills": sorted(normalized_skills.values()),
        "display_map": display_map,
        "allow_new_skills": allow_new_skills,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _provider_config(
    provider: str,
    model: str | None,
    base_url: str | None,
    api_key_env: str | None,
) -> dict[str, str]:
    if provider not in extract_api.PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    config = extract_api.PROVIDERS[provider]
    return {
        "model": model or os.getenv(config["model_env"], config["default_model"]),
        "base_url": base_url or os.getenv(config["base_url_env"], config["default_base_url"]),
        "api_key_env": api_key_env or config["api_key_env"],
    }


def call_normalization_api(
    *,
    api_key: str,
    model: str,
    base_url: str,
    batch: list[dict[str, str]],
    normalizer: SkillNormalizer,
    allow_new_skills: bool,
    timeout: int,
    retries: int,
    temperature: float,
) -> dict[str, Any]:
    normalized_nodes = [
        {
            "normalized_skill": skill,
            "kg_display_skill": normalizer.display_map.get(skill.casefold(), ""),
        }
        for skill in sorted(normalizer.normalized_skills.values(), key=str.casefold)
    ]
    display_categories = sorted({value for value in normalizer.display_map.values() if value}, key=str.casefold)
    system_prompt = (
        "You normalize extracted JD skill candidates after extraction. This API call is part of the required "
        "normalization layer, not an optional audit. Map each item to one existing normalized_skill when it is "
        "semantically the same skill. If no existing node fits but the item is clearly a resume/JD technical skill, "
        "return decision='new' and create a concise normalized skill name. For new skills, choose kg_display_skill "
        "from the provided display_categories. Do not invent broad business skills, product scenarios, vague "
        "responsibilities, or common-sense skills not supported by the evidence sentence. "
        f"allow_new_skills={str(allow_new_skills).lower()}. "
        "Return JSON only: {\"items\":[{\"skill_keyword\":\"...\",\"span_text\":\"...\","
        "\"decision\":\"existing|new|reject\",\"normalized_skill\":\"...\","
        "\"kg_display_skill\":\"...\",\"proposed_normalized_skill\":\"...\","
        "\"confidence\":0.0,\"reason\":\"...\"}]}"
    )
    user_payload = {
        "items": batch,
        "existing_normalized_nodes": normalized_nodes,
        "display_categories": display_categories,
    }
    return extract_api.call_chat_api(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_payload=user_payload,
        timeout=timeout,
        retries=retries,
        temperature=temperature,
    )
