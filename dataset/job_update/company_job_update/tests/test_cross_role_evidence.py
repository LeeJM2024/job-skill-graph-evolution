from __future__ import annotations

import pandas as pd

from core.cross_role_evidence import CrossRoleEvidenceResolver
from core.models import ScoredCandidate


class _FakeTaxonomy:
    def __init__(self, peers: list[tuple[str, float]]) -> None:
        self.peers = peers

    def score_jobs(self, job_title: str, similarity: object) -> list[ScoredCandidate]:
        return [
            ScoredCandidate("后端开发工程师", 1.0, {"category": "研发"}),
            *[
                ScoredCandidate(name, score, {"category": "研发"})
                for name, score in self.peers
            ],
            ScoredCandidate("产品经理", 0.99, {"category": "产品"}),
        ]


def _spread(*rows: tuple[str, int, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "skill": "MCP",
                "standard_job": job,
                "month": month,
                "monthly_skill_count": 1,
                "cumulative_skill_count": cumulative,
            }
            for job, cumulative, month in rows
        ]
    )


def _resolver(peers: list[tuple[str, float]], spread: pd.DataFrame) -> CrossRoleEvidenceResolver:
    return CrossRoleEvidenceResolver(
        taxonomy=_FakeTaxonomy(peers),  # type: ignore[arg-type]
        similarity=object(),  # type: ignore[arg-type]
        migration=pd.DataFrame(
            [{"skill": "MCP", "migration_confidence": "high", "confirmed_cumulative_covered_job_count": 2}]
        ),
        spread=spread,
    )


def test_two_recent_confirmed_similar_jobs_confirm_cross_role_evidence() -> None:
    resolver = _resolver(
        [("大模型应用工程师", 0.91), ("AI Agent应用工程师", 0.86)],
        _spread(("大模型应用工程师", 2, "2026-07"), ("AI Agent应用工程师", 2, "2026-06")),
    )

    evidence = resolver.resolve(
        standard_job="后端开发工程师",
        skill="MCP",
        observed_month="2026-08",
    )

    assert evidence["eligible"] is True
    assert evidence["peer_job_count"] == 2
    assert evidence["peer_jobs"][0]["standard_job"] == "大模型应用工程师"


def test_one_ordinary_peer_is_insufficient_but_one_strong_peer_can_confirm() -> None:
    ordinary = _resolver(
        [("大模型应用工程师", 0.90)],
        _spread(("大模型应用工程师", 5, "2026-07")),
    ).resolve(standard_job="后端开发工程师", skill="MCP", observed_month="2026-08")
    strong = _resolver(
        [("大模型应用工程师", 0.93)],
        _spread(("大模型应用工程师", 3, "2026-07")),
    ).resolve(standard_job="后端开发工程师", skill="MCP", observed_month="2026-08")

    assert ordinary["eligible"] is False
    assert strong["eligible"] is True


def test_stale_or_different_family_skill_evidence_does_not_confirm() -> None:
    resolver = _resolver(
        [("大模型应用工程师", 0.90)],
        _spread(("大模型应用工程师", 4, "2025-12")),
    )

    evidence = resolver.resolve(
        standard_job="后端开发工程师",
        skill="MCP",
        observed_month="2026-08",
    )

    assert evidence["eligible"] is False
    assert evidence["peer_job_count"] == 0
