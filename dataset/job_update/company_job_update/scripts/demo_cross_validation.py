"""Run a non-destructive cross-validation demonstration.

The script uses a temporary SQLite database only.  It never reads from or
writes to the project's final input dataset, event stream, or production
``job_update.db``.  Its JSON output can be used in a presentation or a manual
acceptance check.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


# When invoked as ``python scripts/demo_cross_validation.py``, make the module
# root available without requiring the user to set PYTHONPATH manually.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.candidate_skill_store import RoleSkillCandidateStore  # noqa: E402
from core.models import JobPosting, NormalizedSkill  # noqa: E402


STANDARD_JOB = "后端开发工程师"
SKILL = NormalizedSkill(
    normalized_skill="MCP",
    kg_display_skill="大模型",
    confidence=0.95,
)
EVIDENCE = {
    "mcp": {
        "field": "requirement",
        "sentence": "熟悉 MCP 协议，能够完成工具调用接入。",
        "confidence": 0.95,
    }
}


def _submit(store: RoleSkillCandidateStore, job_id: str, month: str) -> dict[str, object]:
    decision = store.evaluate(
        posting=JobPosting(job_id=job_id, month=month, job_title=STANDARD_JOB),
        standard_job=STANDARD_JOB,
        skills=[SKILL],
        trusted_skills=set(),
        evidence_by_skill=EVIDENCE,
        persist=True,
    )[0]
    return {
        "input": {
            "job_id": job_id,
            "month": month,
            "standard_job": STANDARD_JOB,
            "normalized_skill": SKILL.normalized_skill,
            "evidence": EVIDENCE["mcp"]["sentence"],
        },
        "output": {
            "status": decision.status,
            "reason": decision.reason,
            "support_job_count": decision.support_job_count,
            "support_month_count": decision.support_month_count,
        },
    }


def _cross_role_confirmation(store: RoleSkillCandidateStore) -> dict[str, object]:
    decision = store.evaluate(
        posting=JobPosting(job_id="demo-cross-role-001", month="2026-08", job_title=STANDARD_JOB),
        standard_job=STANDARD_JOB,
        skills=[SKILL],
        trusted_skills=set(),
        evidence_by_skill=EVIDENCE,
        cross_role_evidence_by_skill={
            "mcp": {
                "eligible": True,
                "peer_job_count": 2,
                "peer_jobs": [
                    {"standard_job": "大模型应用工程师", "similarity": 0.91, "last_seen_month": "2026-07"},
                    {"standard_job": "AI Agent应用工程师", "similarity": 0.86, "last_seen_month": "2026-06"},
                ],
            }
        },
        persist=True,
    )[0]
    return {
        "input": {
            "job_id": "demo-cross-role-001",
            "month": "2026-08",
            "standard_job": STANDARD_JOB,
            "normalized_skill": SKILL.normalized_skill,
            "evidence": EVIDENCE["mcp"]["sentence"],
            "similar_peer_jobs": ["大模型应用工程师", "AI Agent应用工程师"],
        },
        "output": {
            "status": decision.status,
            "confirmation_route": decision.confirmation_route,
            "cross_role_support_job_count": decision.cross_role_support_job_count,
            "reason": decision.reason,
        },
    }


def _ordinary_single_peer_is_held(store: RoleSkillCandidateStore) -> dict[str, object]:
    decision = store.evaluate(
        posting=JobPosting(job_id="demo-cross-role-002", month="2026-08", job_title=STANDARD_JOB),
        standard_job=STANDARD_JOB,
        skills=[SKILL],
        trusted_skills=set(),
        evidence_by_skill=EVIDENCE,
        cross_role_evidence_by_skill={
            "mcp": {
                "eligible": False,
                "peer_job_count": 1,
                "peer_jobs": [{"standard_job": "大模型应用工程师", "similarity": 0.90, "confirmed_cumulative_mentions": 5}],
                "reason": "存在相似岗位技能证据，但确认岗位数或支持强度不足",
            }
        },
        persist=True,
    )[0]
    return {
        "input": {
            "job_id": "demo-cross-role-002",
            "current_jd_evidence": EVIDENCE["mcp"]["sentence"],
            "similar_peer_jobs": ["大模型应用工程师 (similarity=0.90, cumulative_mentions=5)"],
        },
        "expected_output": "candidate",
        "actual_output": {"status": decision.status, "reason": decision.reason},
    }


def _missing_current_jd_evidence_is_held(store: RoleSkillCandidateStore) -> dict[str, object]:
    decision = store.evaluate(
        posting=JobPosting(job_id="demo-cross-role-003", month="2026-08", job_title=STANDARD_JOB),
        standard_job=STANDARD_JOB,
        skills=[SKILL],
        trusted_skills=set(),
        cross_role_evidence_by_skill={
            "mcp": {
                "eligible": True,
                "peer_job_count": 2,
                "peer_jobs": [
                    {"standard_job": "大模型应用工程师", "similarity": 0.91},
                    {"standard_job": "AI Agent应用工程师", "similarity": 0.86},
                ],
            }
        },
        persist=True,
    )[0]
    return {
        "input": {
            "job_id": "demo-cross-role-003",
            "current_jd_evidence": "",
            "similar_peer_jobs": ["大模型应用工程师", "AI Agent应用工程师"],
        },
        "expected_output": "candidate",
        "actual_output": {"status": decision.status, "reason": decision.reason},
    }


def main() -> None:
    with TemporaryDirectory(prefix="cross_validation_demo_") as temporary_directory:
        store = RoleSkillCandidateStore(Path(temporary_directory) / "candidate_demo.db")
        steps = [
            _submit(store, "demo-jd-001", "2026-08"),
            _submit(store, "demo-jd-002", "2026-09"),
            _submit(store, "demo-jd-003", "2026-10"),
        ]
        output = {
            "scenario": "新增技能跨JD、跨自然月交叉验证",
            "isolation": "使用临时SQLite数据库；不修改最终输入数据、事件流或正式job_update.db",
            "confirmation_rule": {
                "min_distinct_job_ids": 2,
                "min_distinct_natural_months": 2,
            },
            "steps": steps,
            "candidate_pool": store.list_candidates(status="confirmed"),
        }
    with TemporaryDirectory(prefix="cross_role_validation_demo_") as temporary_directory:
        store = RoleSkillCandidateStore(Path(temporary_directory) / "cross_role_demo.db")
        output["cross_role_migration_example"] = _cross_role_confirmation(store)
    with TemporaryDirectory(prefix="cross_role_negative_demo_") as temporary_directory:
        output["cross_role_negative_examples"] = {
            "ordinary_single_peer": _ordinary_single_peer_is_held(
                RoleSkillCandidateStore(Path(temporary_directory) / "ordinary_peer.db")
            ),
            "missing_current_jd_evidence": _missing_current_jd_evidence_is_held(
                RoleSkillCandidateStore(Path(temporary_directory) / "missing_evidence.db")
            ),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
