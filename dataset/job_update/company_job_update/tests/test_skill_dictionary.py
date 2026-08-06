from __future__ import annotations

from pathlib import Path

from company_job_update.skill_extract import extract_job_skills_api as api
from company_job_update.skill_extract.normalizer import SkillNormalizer


def test_common_backend_and_agent_skills_are_dictionary_normalized() -> None:
    dictionary = Path(__file__).parents[1] / "skill_extract" / "泛抽取级词典.csv"
    normalizer = SkillNormalizer(extraction_dictionary=dictionary)
    ontology = api.load_extraction_dictionary(dictionary)
    text = "Function Calling、LangChain、FastAPI、MySQL、Redis、Kubernetes"
    mentions = api.build_dictionary_mentions([{"sentence_id": "test", "text": text}], ontology)

    assert {item["skill_keyword"] for item in mentions} == {
        "Function Calling", "LangChain", "FastAPI", "MySQL", "Redis", "Kubernetes"
    }
    for item in mentions:
        decision = normalizer.normalize_one(item)
        assert decision.status == "normalized"
        assert decision.normalized_skill

    decisions = {
        item["skill_keyword"]: normalizer.normalize_one(item)
        for item in mentions
    }
    assert decisions["Function Calling"].normalized_skill == "Agent"
    assert decisions["Function Calling"].kg_display_skill == "Agent"
    assert decisions["LangChain"].normalized_skill == "LangChain"
    assert decisions["FastAPI"].normalized_skill == "FastAPI"
    assert decisions["MySQL"].normalized_skill == "MySQL"
    assert decisions["Redis"].normalized_skill == "Redis"
    assert decisions["Kubernetes"].normalized_skill == "Kubernetes"
