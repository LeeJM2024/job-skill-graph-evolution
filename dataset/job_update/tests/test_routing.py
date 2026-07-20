from __future__ import annotations

from job_update.frequency_store import FrequencyStore
from job_update.models import JobPosting, SkillMention
from job_update.service import JobUpdateSystem
from job_update.taxonomy import JobTaxonomy, StandardJob


class FixedSimilarity:
    def score(self, query: str, candidates):
        return [1.0 if "大模型算法工程师" in candidate else 0.1 for candidate in candidates]


def test_route_existing_job_by_exact_title() -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("大模型算法工程师", "AI算法", "大模型.*算法|LLM.*算法"),
            StandardJob("后端开发工程师", "软件研发", "后端|服务端"),
        ]
    )

    route = taxonomy.route(
        "大模型算法工程师",
        similarity=FixedSimilarity(),
        category_threshold=0.6,
        job_threshold=0.85,
    )

    assert route.status == "existing_job"
    assert route.best_job is not None
    assert route.best_job.name == "大模型算法工程师"


class QueryAwareSimilarity:
    def score(self, query: str, candidates):
        if query == "Frontend Developer":
            return [1.0 if "Frontend Developer" in candidate else 0.1 for candidate in candidates]
        return [0.1 for _ in candidates]


class FixedTitleCleaner:
    def clean(self, job_title: str) -> str:
        assert job_title == "Game Project - Frontend Developer"
        return "Frontend Developer"


def test_process_routes_with_cleaned_title_and_keeps_raw_title(tmp_path) -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("Frontend Developer", "Software", "Frontend"),
            StandardJob("Backend Developer", "Software", "Backend"),
        ]
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=QueryAwareSimilarity(),
        title_cleaner=FixedTitleCleaner(),
    )
    posting = JobPosting(
        job_id="job_001",
        month="2026-07",
        job_title="Game Project - Frontend Developer",
        skills=[SkillMention(normalized_skill="JavaScript", kg_display_skill="编程语言")],
    )

    result = system.process(posting, write=False)

    assert result.route.status == "existing_job"
    assert result.route.best_job is not None
    assert result.route.best_job.name == "Frontend Developer"
    assert result.posting.job_title == "Game Project - Frontend Developer"
    assert result.posting.routing_job_title == "Frontend Developer"
