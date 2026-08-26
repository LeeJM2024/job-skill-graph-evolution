from __future__ import annotations

from pathlib import Path

from core.candidate_skill_store import RoleSkillCandidateStore
from core.models import JobPosting, NormalizedSkill


def _posting(job_id: str, month: str) -> JobPosting:
    return JobPosting(job_id=job_id, month=month, job_title="后端开发工程师")


def _skill(name: str = "MCP") -> NormalizedSkill:
    return NormalizedSkill(normalized_skill=name, kg_display_skill="大模型", confidence=0.95)


def test_existing_profile_skill_is_admitted_without_candidate_record(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")

    decisions = store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill("Java")],
        trusted_skills={"java"},
        persist=True,
    )

    assert decisions[0].status == "verified_existing"
    assert store.list_candidates() == []


def test_candidate_requires_two_jds_in_two_months_before_confirmation(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")
    evidence = {"mcp": {"field": "requirement", "sentence": "熟悉 MCP 协议", "confidence": 0.95}}

    first = store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=evidence,
        persist=True,
    )
    second = store.evaluate(
        posting=_posting("jd-2", "2026-09"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=evidence,
        persist=True,
    )
    later = store.evaluate(
        posting=_posting("jd-3", "2026-10"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=evidence,
        persist=False,
    )

    assert first[0].status == "candidate"
    assert second[0].status == "confirmed_dynamic"
    assert later[0].status == "verified_dynamic"
    row = store.list_candidates(status="confirmed")[0]
    assert row["support_job_count"] == 2
    assert row["support_month_count"] == 2
    assert row["evidence"][0]["sentence"] == "熟悉 MCP 协议"


def test_candidate_expires_when_no_new_time_window_evidence(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")
    store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        persist=True,
    )

    assert store.expire_stale("2026-11") == 1
    assert store.list_candidates(status="expired")[0]["skill"] == "MCP"


def test_cross_role_evidence_confirms_on_the_first_directly_evidenced_jd(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")
    cross_role_evidence = {
        "mcp": {
            "eligible": True,
            "peer_job_count": 2,
            "peer_jobs": [
                {"standard_job": "大模型应用工程师", "similarity": 0.91},
                {"standard_job": "AI Agent应用工程师", "similarity": 0.86},
            ],
        }
    }
    direct_evidence = {"mcp": {"field": "requirement", "sentence": "熟悉 MCP 协议", "confidence": 0.95}}

    first = store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=direct_evidence,
        cross_role_evidence_by_skill=cross_role_evidence,
        persist=True,
    )
    later = store.evaluate(
        posting=_posting("jd-2", "2026-09"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        persist=False,
    )

    assert first[0].status == "confirmed_cross_role"
    assert first[0].confirmation_route == "cross_role_migration"
    assert first[0].cross_role_support_job_count == 2
    assert later[0].status == "verified_cross_role"
    row = store.list_candidates(status="confirmed")[0]
    assert row["confirmation_route"] == "cross_role_migration"
    assert row["cross_role_support_job_count"] == 2


def test_cross_role_evidence_cannot_bypass_current_jd_original_text(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")

    decisions = store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        cross_role_evidence_by_skill={"mcp": {"eligible": True, "peer_job_count": 2}},
        persist=True,
    )

    assert decisions[0].status == "candidate"


def test_same_role_temporal_confirmation_takes_precedence_over_cross_role_evidence(tmp_path: Path) -> None:
    store = RoleSkillCandidateStore(tmp_path / "candidates.db")
    direct_evidence = {"mcp": {"field": "requirement", "sentence": "熟悉 MCP 协议"}}
    store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=direct_evidence,
        persist=True,
    )

    second = store.evaluate(
        posting=_posting("jd-2", "2026-09"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        evidence_by_skill=direct_evidence,
        cross_role_evidence_by_skill={"mcp": {"eligible": True, "peer_job_count": 2}},
        persist=True,
    )

    assert second[0].status == "confirmed_dynamic"
    assert second[0].confirmation_route == "same_role_temporal"


def test_database_connection_is_released_after_each_operation(tmp_path: Path) -> None:
    database_path = tmp_path / "candidates.db"
    store = RoleSkillCandidateStore(database_path)

    store.evaluate(
        posting=_posting("jd-1", "2026-08"),
        standard_job="后端开发工程师",
        skills=[_skill()],
        trusted_skills=set(),
        persist=True,
    )
    store.list_candidates()

    # This also protects the Windows demo path: the SQLite file must no longer
    # be held open after an operation completes.
    database_path.unlink()
    assert not database_path.exists()
