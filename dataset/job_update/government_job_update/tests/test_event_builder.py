from __future__ import annotations

import json

import pandas as pd

from government_job_update.event_builder import build_government_event_stream, clean_government_title
from government_job_update.frequency_store import GovernmentFrequencyStore
from government_job_update.routing import GovernmentStandardJob, GovernmentTaxonomy, build_government_route_review
from government_job_update.skill_lifecycle import build_government_annual_lifecycle
from government_job_update.title_cleaning import apply_government_title_cleaning
from company_job_update.core.models import JobPosting, NormalizedSkill


def test_build_event_stream_preserves_real_publish_time_and_source_identity() -> None:
    raw = {
        "dataset_year": 2024,
        "job_uid": "GOV-2024-001",
        "source_sheet": "test_sheet",
        "original": {
            "用人司局": "信息中心",
            "职位简介": "从事信息系统运行维护工作",
            "专业": "计算机科学与技术",
            "学历": "本科及以上",
            "学位": "学士",
            "招考人数": "2",
        },
    }
    source = pd.DataFrame(
        [
            {
                "source": "government_jobs",
                "source_name": "国家公务员2024招考简章",
                "job_title": "信息管理岗位一级主任科员及以下",
                "company_name": "中央单位",
                "location": "北京市",
                "tags": "computer_software",
                "job_description": "职位简介：从事信息系统运行维护工作",
                "source_url": "https://example.test/001",
                "publish_time": "2023-10-15",
                "raw": json.dumps(raw, ensure_ascii=False),
            }
        ]
    )

    result = build_government_event_stream(source)
    posting = result.normalized_postings.iloc[0]
    event = result.raw_event_stream.iloc[0]

    assert posting["job_id"] == "GOV-2024-001"
    assert posting["month"] == "2023-10"
    assert posting["recruitment_year"] == "2024"
    assert posting["source"] == "government"
    assert posting["job_responsibility"] == "从事信息系统运行维护工作"
    assert "专业：计算机科学与技术" in posting["job_requirement"]
    assert event["standard_job"] == ""
    assert event["skills"] == ""
    assert event["route_status"] == "unprocessed"
    assert result.audit["publish_month_counts"] == {"2023-10": 1}


def test_clean_government_title_removes_rank_suffix_without_erasing_generic_title() -> None:
    assert clean_government_title("信息管理岗位一级主任科员及以下") == "信息管理岗位"
    assert clean_government_title("一级行政执法员（三）") == "一级行政执法员（三）"


class FixedSimilarity:
    def score_many(self, queries, candidates, **kwargs):
        assert queries == ["信息中心岗位"]
        assert candidates == ["政府信息系统运维岗", "政府网络与数据安全岗"]
        return [[0.86, 0.72]]


def test_government_route_review_scores_titles_only_and_never_assigns_formal_route() -> None:
    postings = pd.DataFrame(
        [
            {
                "job_id": "GOV-001",
                "month": "2023-10",
                "publish_time": "2023-10-15",
                "recruitment_year": "2024",
                "source": "government",
                "source_name": "test",
                "source_url": "https://example.test/001",
                "government_agency": "test agency",
                "government_department": "test department",
                "job_title": "信息中心岗位",
                "cleaned_job_title": "信息中心岗位",
                "job_responsibility": "负责信息系统运行维护",
                "job_requirement": "计算机相关专业",
                "routing_text": "岗位名称：信息中心岗位\n职位简介：负责信息系统运行维护\n岗位要求：计算机相关专业",
            }
        ]
    )
    taxonomy = GovernmentTaxonomy(
        [
            GovernmentStandardJob("政府信息系统运维岗", "政务软件与系统", "运行维护|系统维护"),
            GovernmentStandardJob("政府网络与数据安全岗", "网络与安全", "网络安全|信息安全"),
        ]
    )

    review = build_government_route_review(postings, taxonomy=taxonomy, similarity=FixedSimilarity())
    row = review.iloc[0]

    assert row["top1_standard_job"] == "政府信息系统运维岗"
    assert row["route_status"] == "needs_llm_adjudication"
    assert row["selected_standard_job"] == ""
    assert "运行维护" in row["top1_keyword_evidence"]


class FixedGovernmentTitleCleaner:
    def clean(self, job_title):
        assert job_title == "景德镇调查队综合执法科一级科员"
        return {"cleaned_job_title": "调查队综合执法科一级科员", "removed_parts": ["景德镇"], "reason": "remove location"}


def test_government_title_cleaning_uses_llm_result_as_the_only_cleaned_title(tmp_path) -> None:
    postings = pd.DataFrame([{"job_title": "景德镇调查队综合执法科一级科员"}])
    cleaned, audit = apply_government_title_cleaning(
        postings,
        cleaner=FixedGovernmentTitleCleaner(),
        cache_path=tmp_path / "title_cache.jsonl",
    )
    assert cleaned.iloc[0]["cleaned_job_title"] == "调查队综合执法科一级科员"
    assert audit.iloc[0]["removed_parts"] == '["景德镇"]'


def test_government_frequency_store_keeps_provenance_while_reusing_frequency_algorithm(tmp_path) -> None:
    store = GovernmentFrequencyStore(tmp_path / "government_events.csv", tmp_path / "frequency.csv")
    events, frequency = store.append_existing_job(
        JobPosting(
            job_id="GOV-1",
            month="2025-10",
            job_title="信息系统运维岗",
            routing_job_title="信息系统运维岗",
            job_responsibility="负责系统运行维护",
            metadata={
                "source": "government",
                "source_name": "2026 国家公务员招录",
                "publish_time": "2025-10-14",
                "government_agency": "某部信息中心",
            },
        ),
        standard_job="政府信息系统运维岗",
        normalized_skills=[NormalizedSkill("系统运维", "网络与基础设施")],
        write=False,
    )
    assert events.iloc[0]["source"] == "government"
    assert events.iloc[0]["publish_time"] == "2025-10-14"
    assert events.iloc[0]["government_agency"] == "某部信息中心"
    assert frequency.iloc[0]["standard_job"] == "政府信息系统运维岗"


def test_government_lifecycle_uses_observed_annual_cycles_not_missing_months() -> None:
    frequency = pd.DataFrame(
        [
            {"month": "2023-10", "standard_job": "政府信息系统运维岗", "skill": "系统运维", "monthly_skill_count": 3, "monthly_skill_frequency": 0.6, "cumulative_skill_count": 3, "cumulative_skill_frequency": 0.6},
            {"month": "2024-10", "standard_job": "政府信息系统运维岗", "skill": "系统运维", "monthly_skill_count": 4, "monthly_skill_frequency": 0.5, "cumulative_skill_count": 7, "cumulative_skill_frequency": 0.54},
            {"month": "2025-10", "standard_job": "政府信息系统运维岗", "skill": "系统运维", "monthly_skill_count": 5, "monthly_skill_frequency": 0.5, "cumulative_skill_count": 12, "cumulative_skill_frequency": 0.52},
        ]
    )
    lifecycle = build_government_annual_lifecycle(frequency)
    row = lifecycle.iloc[0]
    assert row["lifecycle_status"] == "稳定核心技能"
    assert row["months_since_last_seen"] == 0
    assert "annual recruitment cycles" in row["lifecycle_reason"]
