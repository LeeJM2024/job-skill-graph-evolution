from __future__ import annotations

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
