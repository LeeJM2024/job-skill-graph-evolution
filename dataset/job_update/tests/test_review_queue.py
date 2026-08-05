from __future__ import annotations

import json

from job_update.database import SQLiteJobUpdateStore
from job_update.models import JobPosting, JobRoute, NormalizedSkill, ProcessResult, ScoredCandidate
from job_update.review_queue import create_pending_reviews, serialize_process_result


def test_serialize_process_result_keeps_manual_review_skills() -> None:
    result = _process_result(status="potential_new_job")

    payload = serialize_process_result(result)

    assert payload["review_recommended"] is True
    assert payload["route"]["status"] == "potential_new_job"
    assert payload["skills"][0]["normalized_skill"] == "Python"
    assert payload["updated"] is False


def test_create_pending_reviews_writes_job_and_skill_items_for_manual_mode(tmp_path) -> None:
    store = SQLiteJobUpdateStore(tmp_path / "job_update.db")
    result = _process_result(status="potential_new_job")

    bundle = create_pending_reviews(
        store=store,
        submission_mode="manual",
        input_payload={
            "month": "2026-07",
            "job_title": "测试岗位",
            "responsibility": "写代码",
            "requirement": "会 Python",
            "source": "unit_test",
        },
        result=result,
        skill_pool_path=tmp_path / "skill_pool.csv",
        always_queue_job=True,
    )

    assert bundle["job_review"]["item_type"] == "job"
    assert len(bundle["skill_reviews"]) == 1
    assert bundle["skill_reviews"][0]["payload"]["skill"]["normalized_skill"] == "Python"
    queue_path = tmp_path / "review_queue.jsonl"
    rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    assert [row["item_type"] for row in rows] == ["job", "skill"]
    assert all(row["status"] == "pending" for row in rows)


def test_auto_mode_existing_job_does_not_queue_review(tmp_path) -> None:
    store = SQLiteJobUpdateStore(tmp_path / "job_update.db")
    result = _process_result(status="existing_job")

    bundle = create_pending_reviews(
        store=store,
        submission_mode="auto",
        input_payload={"month": "2026-07", "job_title": "测试岗位"},
        result=result,
    )

    assert bundle["job_review"] is None
    assert bundle["skill_reviews"] == []
    assert not (tmp_path / "review_queue.jsonl").exists()


def _process_result(status: str) -> ProcessResult:
    category = ScoredCandidate("软件研发", 0.9, {"source": "unit"})
    job = ScoredCandidate("Python开发工程师", 0.88, {"category": "软件研发"})
    route = JobRoute(
        status=status,  # type: ignore[arg-type]
        selected_categories=[category],
        selected_jobs=[job],
        best_category=category,
        best_job=job,
        reason="unit test route",
        top_categories=[category],
        top_jobs=[job],
    )
    posting = JobPosting(
        job_id="JOB001",
        month="2026-07",
        job_title="测试岗位",
        routing_job_title="测试岗位",
        job_responsibility="写代码",
        job_requirement="会 Python",
    )
    return ProcessResult(
        route=route,
        posting=posting,
        normalized_skills=[
            NormalizedSkill(
                normalized_skill="Python",
                kg_display_skill="编程语言",
                skill_type="new",
                confidence=0.96,
            )
        ],
    )
