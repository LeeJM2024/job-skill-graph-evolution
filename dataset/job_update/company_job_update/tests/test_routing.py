from __future__ import annotations

from company_job_update.core.frequency_store import FrequencyStore
from company_job_update.core.models import JobPosting, SkillMention
from company_job_update.core.route_adjudication import RouteAdjudicationDecision
from company_job_update.core.service import JobUpdateSystem
from company_job_update.core.taxonomy import JobTaxonomy, StandardJob
from company_job_update.core.taxonomy_gap_guard import detect_taxonomy_gap


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


class NamedScoreSimilarity:
    def __init__(self, scores):
        self.scores = scores

    def score(self, query: str, candidates):
        return [self.scores.get(candidate, 0.1) for candidate in candidates]


class FakeRouteAdjudicator:
    def __init__(self, decision: RouteAdjudicationDecision):
        self.decision = decision
        self.called = False

    def adjudicate(self, **kwargs):
        self.called = True
        return self.decision


class FixedSkillExtractor:
    def extract(self, posting):
        return [SkillMention(normalized_skill="RAG", kg_display_skill="AI")]


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


def test_process_uses_direct_high_confidence_route_without_llm(tmp_path) -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("AI App Engineer", "AI", "LLM application"),
            StandardJob("AI Agent Engineer", "AI", "agent workflow"),
        ]
    )
    adjudicator = FakeRouteAdjudicator(
        RouteAdjudicationDecision(route_status="potential_new_job", reason="should not be called")
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=NamedScoreSimilarity({"AI App Engineer": 0.86, "AI Agent Engineer": 0.80}),
        route_adjudicator=adjudicator,
    )
    posting = JobPosting(
        job_id="direct",
        month="2026-07",
        job_title="AI App Engineer",
        skills=[SkillMention(normalized_skill="RAG", kg_display_skill="AI")],
    )

    result = system.process(posting, write=False)

    assert result.route.status == "existing_job"
    assert result.route.best_job is not None
    assert result.route.best_job.name == "AI App Engineer"
    assert adjudicator.called is False


def test_process_accepts_middle_zone_llm_top1_decision(tmp_path) -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("AI App Engineer", "AI", "LLM application"),
            StandardJob("AI Agent Engineer", "AI", "agent workflow"),
        ]
    )
    adjudicator = FakeRouteAdjudicator(
        RouteAdjudicationDecision(
            route_status="existing_job",
            selected_standard_job="AI App Engineer",
            selected_category="AI",
            confidence=0.9,
            reason="core work matches",
        )
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=NamedScoreSimilarity({"AI App Engineer": 0.76, "AI Agent Engineer": 0.74}),
        route_adjudicator=adjudicator,
    )
    posting = JobPosting(
        job_id="llm_accept",
        month="2026-07",
        job_title="AI App Engineer",
        skills=[SkillMention(normalized_skill="Prompt", kg_display_skill="AI")],
    )

    result = system.process(posting, write=False)

    assert adjudicator.called is True
    assert result.route.status == "existing_job"
    assert result.route.best_job is not None
    assert result.route.best_job.name == "AI App Engineer"


def test_process_takes_top1_when_llm_is_uncertain_and_score_is_high(tmp_path) -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("AI App Engineer", "AI", "LLM application"),
            StandardJob("AI Agent Engineer", "AI", "agent workflow"),
        ]
    )
    adjudicator = FakeRouteAdjudicator(
        RouteAdjudicationDecision(route_status="potential_new_job", reason="boundary is unclear")
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=NamedScoreSimilarity({"AI App Engineer": 0.83, "AI Agent Engineer": 0.82}),
        route_adjudicator=adjudicator,
    )
    posting = JobPosting(
        job_id="uncertain_high",
        month="2026-07",
        job_title="AI App Engineer",
        skills=[SkillMention(normalized_skill="LLM", kg_display_skill="AI")],
    )

    result = system.process(posting, write=False)

    assert adjudicator.called is True
    assert result.route.status == "existing_job"
    assert result.route.best_job is not None
    assert result.route.best_job.name == "AI App Engineer"
    assert "accepted text2vec top1" in result.route.reason


def test_process_applies_taxonomy_gap_guard(tmp_path) -> None:
    taxonomy = JobTaxonomy(
        [
            StandardJob("大模型算法工程师", "AI算法", "大模型.*算法|LLM.*算法"),
            StandardJob("测试开发工程师", "测试质量", "测试开发|自动化测试"),
        ]
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=FixedSimilarity(),
        use_taxonomy_gap_guard=True,
    )
    posting = JobPosting(
        job_id="job_002",
        month="2026-07",
        job_title="大模型评测工程师",
        skills=[SkillMention(normalized_skill="LLM", kg_display_skill="人工智能")],
    )

    result = system.process(posting, write=False)

    assert result.route.status == "potential_new_job"
    assert "taxonomy gap guard" in result.route.reason
    assert result.update is None


def test_taxonomy_gap_guard_skips_known_standard_job() -> None:
    decision = detect_taxonomy_gap(
        raw_job_title="AIGC算法工程师",
        routing_job_title="AIGC算法工程师",
        current_standard_jobs={"AIGC算法工程师", "大模型算法工程师"},
        current_standard_categories={"AI算法"},
    )

    assert decision is None


def test_manual_review_collects_skills_even_when_route_is_not_existing(tmp_path) -> None:
    taxonomy = JobTaxonomy([StandardJob("Backend Developer", "Software", "Backend")])
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        similarity=NamedScoreSimilarity({"Backend Developer": 0.2}),
        skill_extractor=FixedSkillExtractor(),
    )

    result = system.process(
        JobPosting(job_id="review_001", month="2026-07", job_title="Novel AI Role"),
        write=False,
        collect_skills_for_review=True,
    )

    assert result.route.status == "new_family"
    assert result.update is None
    assert [skill.normalized_skill for skill in result.normalized_skills] == ["RAG"]
