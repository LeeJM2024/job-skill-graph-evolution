from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from company_job_update.core.skill_extraction import ExistingSkillExtractAdapter
from government_job_update.skill_extraction import (
    GOVERNMENT_EXTRACTION_PROMPT_APPENDIX,
    GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX,
    GovernmentSkillExtractAdapter,
)
from skill_extract.normalizer import normalization_cache_key


def test_government_skill_prompts_exclude_administrative_duties() -> None:
    assert "Never extract administrative work" in GOVERNMENT_EXTRACTION_PROMPT_APPENDIX
    assert "Reject administrative" in GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX
    assert "electronic forensics" in GOVERNMENT_EXTRACTION_PROMPT_APPENDIX


def test_normalization_cache_is_scoped_by_domain_prompt() -> None:
    batch = [{"skill_keyword": "数据目录", "span_text": "建设数据目录"}]
    normalized_skills = {"数据治理": "数据治理"}
    display_map = {"数据治理": "数据与统计"}

    company_key = normalization_cache_key(batch, normalized_skills, display_map, True)
    government_key = normalization_cache_key(
        batch,
        normalized_skills,
        display_map,
        True,
        GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX,
    )

    assert company_key != government_key


def test_government_adapter_injects_government_domain_prompts() -> None:
    with patch.object(ExistingSkillExtractAdapter, "__init__", return_value=None) as parent_init:
        GovernmentSkillExtractAdapter(
            extraction_dictionary=Path("extract.csv"),
            cache_path=Path("extract.cache.jsonl"),
            normalization_cache_path=Path("normalize.cache.jsonl"),
        )

    assert parent_init.call_args.kwargs["system_prompt_appendix"] == GOVERNMENT_EXTRACTION_PROMPT_APPENDIX
    assert parent_init.call_args.kwargs["normalization_prompt_appendix"] == GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX
