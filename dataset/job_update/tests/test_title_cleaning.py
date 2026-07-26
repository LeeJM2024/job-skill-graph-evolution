from __future__ import annotations

from job_update.title_cleaning import normalize_technical_title_level


def test_normalize_technical_title_level_to_engineer() -> None:
    assert normalize_technical_title_level("大模型算法实习生") == "大模型算法工程师"
    assert normalize_technical_title_level("音乐大模型算法专家") == "音乐大模型算法工程师"
    assert normalize_technical_title_level("AI Ops研发专家") == "AI Ops研发工程师"
    assert normalize_technical_title_level("算法Leader") == "算法工程师"


def test_normalize_technical_title_level_keeps_non_engineer_roles() -> None:
    assert normalize_technical_title_level("AI产品经理") == "AI产品经理"
    assert normalize_technical_title_level("算法研究员") == "算法研究员"
