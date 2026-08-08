from __future__ import annotations

import re
from dataclasses import dataclass


AGENT_ALGORITHM_JOB = "AI Agent\u7b97\u6cd5\u5de5\u7a0b\u5e08"
AGENT_APPLICATION_JOB = "AI Agent\u5e94\u7528\u5de5\u7a0b\u5e08"
TARGET_REASSIGNMENT_JOBS = {AGENT_ALGORITHM_JOB, AGENT_APPLICATION_JOB}

ALLOWED_SOURCE_JOBS_BY_TARGET = {
    AGENT_APPLICATION_JOB: {
        "\u5927\u6a21\u578b\u5e94\u7528\u5de5\u7a0b\u5e08",
        "AI\u5e94\u7528\u5de5\u7a0b\u5e08",
    },
    AGENT_ALGORITHM_JOB: {
        "\u5927\u6a21\u578b\u7b97\u6cd5\u5de5\u7a0b\u5e08",
        "AIGC\u7b97\u6cd5\u5de5\u7a0b\u5e08",
        "\u7b97\u6cd5\u5de5\u7a0b\u5e08",
        "AI\u5e94\u7528\u5de5\u7a0b\u5e08",
        "\u5927\u6a21\u578b\u5e94\u7528\u5de5\u7a0b\u5e08",
    },
}

NON_ENGINEERING_TITLE_WORDS = (
    "\u4ea7\u54c1\u7ecf\u7406",
    "\u8bbe\u8ba1\u5e08",
    "\u8bad\u7ec3\u5e08",
)

ENGINEERING_TITLE_WORDS = (
    "\u5de5\u7a0b",
    "\u5f00\u53d1",
    "\u7814\u53d1",
    "\u67b6\u6784",
    "\u7b97\u6cd5",
    "\u4e13\u5bb6",
)

ALGORITHM_HINTS = (
    "\u7b97\u6cd5",
    "\u7814\u7a76",
    "\u8bad\u7ec3",
    "\u63a8\u7406",
    "\u89c4\u5212\u7b97\u6cd5",
    "\u5f3a\u5316\u5b66\u4e60",
    "Agent RL",
    "RL",
    "Tool Use",
)

APPLICATION_HINTS = (
    "\u5f00\u53d1",
    "\u7814\u53d1",
    "\u5e94\u7528",
    "\u5e73\u53f0",
    "\u7f16\u6392",
    "\u5de5\u4f5c\u6d41",
    "\u4efb\u52a1\u62c6\u89e3",
    "\u5de5\u5177\u8c03\u7528",
    "Function Calling",
    "MCP",
    "LangChain",
    "LangGraph",
    "AutoGen",
    "Dify",
)


@dataclass(frozen=True)
class StandardJobRule:
    standard_job_title: str
    standard_category: str
    pattern: re.Pattern[str]
    row_order: int


def build_standard_job_rules(standard_rows: list[dict[str, str]]) -> list[StandardJobRule]:
    rules: list[StandardJobRule] = []
    for row_order, row in enumerate(standard_rows):
        title = (row.get("standard_job_title") or "").strip()
        if title not in TARGET_REASSIGNMENT_JOBS:
            continue
        keywords = (row.get("match_keywords") or "").strip()
        if not keywords:
            continue
        rules.append(
            StandardJobRule(
                standard_job_title=title,
                standard_category=(row.get("standard_category") or "").strip(),
                pattern=re.compile(keywords, flags=re.IGNORECASE),
                row_order=row_order,
            )
        )
    return rules


def relabel_standard_job(row: dict[str, str], current_standard_job: str, rules: list[StandardJobRule]) -> str:
    current = (current_standard_job or "").strip()
    if not rules:
        return current

    title = (row.get("job_title") or "").strip()
    if _is_non_engineering_title(title):
        return current

    title_text = " ".join([title, current])
    full_text = " ".join(
        str(row.get(column) or "")
        for column in [
            "job_title",
            "standard_job",
            "job_responsibility",
            "job_requirement",
            "skills",
            "traditional_skills",
            "new_skills",
            "detailed",
            "domain_context",
        ]
    )

    best_rule: StandardJobRule | None = None
    best_score = 0
    for rule in rules:
        if current not in ALLOWED_SOURCE_JOBS_BY_TARGET.get(rule.standard_job_title, set()):
            continue
        score = _rule_score(rule, title_text, full_text)
        if score > best_score:
            best_score = score
            best_rule = rule

    if best_rule is None or best_score < 60:
        return current
    return best_rule.standard_job_title


def _is_non_engineering_title(title: str) -> bool:
    if not any(word in title for word in NON_ENGINEERING_TITLE_WORDS):
        return False
    return not any(word in title for word in ENGINEERING_TITLE_WORDS)


def _rule_score(rule: StandardJobRule, title_text: str, full_text: str) -> int:
    title_match = rule.pattern.search(title_text) is not None
    full_match = rule.pattern.search(full_text) is not None
    if not title_match and not full_match:
        return 0

    score = 80 if title_match else 35
    if full_match:
        score += 20

    if rule.standard_job_title == AGENT_ALGORITHM_JOB:
        score += _hint_score(full_text, ALGORITHM_HINTS)
        if _contains_any(full_text, APPLICATION_HINTS) and not _contains_any(title_text, ALGORITHM_HINTS):
            score -= 15
    elif rule.standard_job_title == AGENT_APPLICATION_JOB:
        score += _hint_score(full_text, APPLICATION_HINTS)
        if _contains_any(full_text, ALGORITHM_HINTS) and _contains_any(title_text, ALGORITHM_HINTS):
            score -= 15

    return score


def _hint_score(text: str, hints: tuple[str, ...]) -> int:
    return min(sum(10 for hint in hints if hint and hint.lower() in text.lower()), 50)


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint.lower() in lowered for hint in hints if hint)
