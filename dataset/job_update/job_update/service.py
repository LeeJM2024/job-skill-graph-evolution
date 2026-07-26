from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

from .frequency_store import FrequencyStore
from .models import ExistingJobUpdate, JobPosting, JobRoute, ProcessResult, ScoredCandidate
from .route_adjudication import RouteAdjudicator
from .similarity import SimilarityBackend, Text2VecSimilarity
from .skill_extraction import SkillExtractor
from .skill_normalizer import PassthroughSkillNormalizer, SkillNormalizer
from .skill_pool_store import SkillPoolStore
from .taxonomy import JobTaxonomy
from .taxonomy_gap_guard import detect_taxonomy_gap
from .title_cleaning import TitleCleaner


@dataclass(slots=True)
class JobUpdateSystem:
    taxonomy: JobTaxonomy
    frequency_store: FrequencyStore
    skill_pool_store: SkillPoolStore | None = None
    similarity: SimilarityBackend | None = None
    route_adjudicator: RouteAdjudicator | None = None
    title_cleaner: TitleCleaner | None = None
    skill_extractor: SkillExtractor | None = None
    skill_normalizer: SkillNormalizer | None = None
    category_threshold: float = 0.58
    job_threshold: float = 0.82
    tie_delta: float = 0.03
    llm_job_floor: float = 0.58
    llm_top_jobs: int = 20
    llm_accept_rank_limit: int = 1
    llm_selected_job_floor: float = 0.75
    llm_min_confidence: float = 0.80
    llm_uncertain_take_top1_threshold: float = 0.82
    use_taxonomy_gap_guard: bool = False
    progress: Callable[[str], None] | None = None

    def process(self, posting: JobPosting, write: bool = True) -> ProcessResult:
        similarity = self.similarity or Text2VecSimilarity()
        normalizer = self.skill_normalizer or PassthroughSkillNormalizer()
        routing_job_title = posting.routing_job_title.strip() or posting.job_title
        if self.title_cleaner is not None and not posting.routing_job_title.strip():
            self._progress("title_cleaning: calling configured LLM title cleaner")
            routing_job_title = self._run_with_heartbeat(
                "title_cleaning",
                lambda: self.title_cleaner.clean(posting.job_title),
            )
            self._progress(f"title_cleaning: raw={posting.job_title}, cleaned={routing_job_title}")
        posting.routing_job_title = routing_job_title
        self._progress("routing: comparing cleaned job title with standard categories and jobs")
        route = self._route_posting(posting, routing_job_title, similarity)
        if self.use_taxonomy_gap_guard:
            gap_decision = detect_taxonomy_gap(
                raw_job_title=posting.job_title,
                routing_job_title=routing_job_title,
                job_responsibility=posting.job_responsibility,
                job_requirement=posting.job_requirement,
                current_standard_jobs={job.title for job in self.taxonomy.jobs},
                current_standard_categories=set(self.taxonomy.jobs_by_category),
            )
            if gap_decision is not None:
                self._progress(
                    "routing: "
                    f"{gap_decision.status} forced by taxonomy gap guard ({gap_decision.reason})"
                )
                route.status = gap_decision.status
                route.reason = gap_decision.reason
        best_category = route.best_category.name if route.best_category else "none"
        best_category_score = route.best_category.score if route.best_category else 0.0
        best_job = route.best_job.name if route.best_job else "none"
        best_job_score = route.best_job.score if route.best_job else 0.0
        self._progress(
            "routing: "
            f"status={route.status}, best_category={best_category}({best_category_score:.4f}), "
            f"best_job={best_job}({best_job_score:.4f})"
        )
        if route.status != "existing_job" or route.best_job is None:
            self._progress("done: not an existing job, frequency and skill pool will not be updated")
            return ProcessResult(route=route, posting=posting, update=None)

        if not posting.skills:
            if self.skill_extractor is None:
                raise ValueError("process-one requires skill_extract output; no skill_extractor was configured")
            self._progress("skills: calling configured skill provider")
            posting.skills.extend(
                self._run_with_heartbeat(
                    "skills",
                    lambda: self.skill_extractor.extract(posting),
                )
            )
            self._progress(f"skills: extracted {len(posting.skills)} final normalized skills")
        else:
            self._progress(f"skills: using {len(posting.skills)} supplied final normalized skills")

        self._progress("skills: validating final normalized skills")
        normalized_skills = normalizer.normalize(posting, posting.skills)
        self._progress(f"skills: accepted {len(normalized_skills)} unique normalized skills")

        mode = "dry-run rebuild" if not write else "calculate update"
        self._progress(f"frequency: loading event stream and rebuilding monthly/cumulative table ({mode})")
        events, frequency = self.frequency_store.append_existing_job(
            posting=posting,
            standard_job=route.best_job.name,
            normalized_skills=normalized_skills,
            write=False,
        )
        self._progress(f"frequency: event_rows={len(events)}, frequency_rows={len(frequency)}")

        skill_pool_rows = 0
        skill_pool = None
        if self.skill_pool_store is not None:
            standard_category = route.best_category.name if route.best_category else ""
            mode = "dry-run update" if not write else "calculate update"
            self._progress(f"skill_pool: loading and updating discovered skills ({mode})")
            skill_pool = self.skill_pool_store.update(
                posting=posting,
                standard_category=standard_category,
                standard_job=route.best_job.name,
                normalized_skills=normalized_skills,
                write=False,
            )
            skill_pool_rows = len(skill_pool)
            self._progress(f"skill_pool: rows={skill_pool_rows}")
        else:
            self._progress("skill_pool: no skill pool path configured, skipped")

        if write:
            self._progress("write: writing event stream and frequency table")
            self.frequency_store.write_tables(events, frequency)
            if self.skill_pool_store is not None and skill_pool is not None:
                self._progress("write: writing skill pool")
                self.skill_pool_store.write_pool(skill_pool)
        else:
            self._progress("write: dry-run, no files were written")

        monthly_rows = len(
            frequency[
                (frequency["standard_job"] == route.best_job.name)
                & (frequency["month"] == posting.month)
            ]
        )
        update = ExistingJobUpdate(
            standard_job=route.best_job.name,
            month=posting.month,
            normalized_skills=normalized_skills,
            monthly_rows=monthly_rows,
            frequency_rows=len(frequency),
            skill_pool_rows=skill_pool_rows,
            event_stream_path=str(self.frequency_store.event_stream_path),
            frequency_path=str(self.frequency_store.frequency_path)
            if self.frequency_store.frequency_path is not None
            else None,
            skill_pool_path=str(self.skill_pool_store.skill_pool_path)
            if self.skill_pool_store is not None
            else None,
        )
        return ProcessResult(route=route, posting=posting, update=update)

    def _route_posting(
        self,
        posting: JobPosting,
        routing_job_title: str,
        similarity: SimilarityBackend,
    ) -> JobRoute:
        category_scores = self.taxonomy.score_categories(routing_job_title, similarity)
        best_category = category_scores[0] if category_scores else None
        if best_category is None or best_category.score < self.category_threshold:
            return JobRoute(
                status="new_family",
                selected_categories=[],
                selected_jobs=[],
                best_category=best_category,
                reason=f"best category score is below {self.category_threshold}",
            )

        selected_categories = [
            candidate
            for candidate in category_scores
            if candidate.score >= self.category_threshold
            and best_category.score - candidate.score <= self.tie_delta
        ][:3]
        job_candidates = [
            job
            for category in selected_categories
            for job in self.taxonomy.jobs_by_category.get(category.name, [])
        ]
        selected_jobs = self.taxonomy.score_jobs(routing_job_title, similarity, job_candidates)
        all_jobs = self.taxonomy.score_jobs(routing_job_title, similarity, self.taxonomy.jobs)
        best_job = selected_jobs[0] if selected_jobs else None
        second_job = selected_jobs[1] if len(selected_jobs) > 1 else None
        margin = best_job.score - second_job.score if best_job is not None and second_job is not None else 1.0

        if best_job is None:
            return JobRoute(
                status="potential_new_job",
                selected_categories=selected_categories,
                selected_jobs=[],
                best_category=best_category,
                reason="no standard job candidate was available",
            )

        if best_job.score < self.llm_job_floor:
            return JobRoute(
                status="potential_new_job",
                selected_categories=selected_categories,
                selected_jobs=selected_jobs,
                best_category=best_category,
                best_job=best_job,
                reason=f"best job score is below {self.llm_job_floor}",
            )

        if best_job.score >= self.job_threshold and margin >= self.tie_delta:
            return JobRoute(
                status="existing_job",
                selected_categories=selected_categories,
                selected_jobs=[best_job],
                best_category=best_category,
                best_job=best_job,
                reason="direct high-confidence text2vec route",
            )

        if self.route_adjudicator is None:
            raise RuntimeError("route adjudication is required for middle-zone routing, but no route_adjudicator was configured")

        self._progress(
            "routing: middle-zone candidate, calling LLM adjudicator "
            f"(best_job={best_job.name}, score={best_job.score:.4f}, margin={margin:.4f})"
        )
        decision = self._run_with_heartbeat(
            "routing_adjudication",
            lambda: self.route_adjudicator.adjudicate(
                posting=posting,
                routing_job_title=routing_job_title,
                text2vec_summary=self._text2vec_summary(best_category, best_job, second_job, margin),
                candidate_jobs=all_jobs[: self.llm_top_jobs],
            ),
        )
        self._progress(
            "routing: LLM adjudication "
            f"status={decision.route_status}, selected={decision.selected_standard_job or 'none'}, "
            f"confidence={decision.confidence:.2f}"
        )
        accepted_job = self._accepted_llm_job(decision.selected_standard_job, all_jobs)
        if decision.route_status == "existing_job" and accepted_job is not None:
            accepted_rank = all_jobs.index(accepted_job) + 1
            if (
                accepted_rank <= self.llm_accept_rank_limit
                and accepted_job.score >= self.llm_selected_job_floor
                and decision.confidence >= self.llm_min_confidence
            ):
                return JobRoute(
                    status="existing_job",
                    selected_categories=selected_categories,
                    selected_jobs=[accepted_job],
                    best_category=best_category,
                    best_job=accepted_job,
                    reason=f"LLM adjudication accepted: {decision.reason}",
                )

        if decision.route_status in {"potential_new_job", "new_family"} and best_job.score >= self.llm_uncertain_take_top1_threshold:
            return JobRoute(
                status="existing_job",
                selected_categories=selected_categories,
                selected_jobs=[best_job],
                best_category=best_category,
                best_job=best_job,
                reason=(
                    "LLM uncertain, accepted text2vec top1 because "
                    f"best_job_score={best_job.score:.4f} >= {self.llm_uncertain_take_top1_threshold}"
                ),
            )

        return JobRoute(
            status=decision.route_status,
            selected_categories=selected_categories,
            selected_jobs=selected_jobs,
            best_category=best_category,
            best_job=best_job,
            reason=decision.reason or "LLM adjudication did not accept an existing job",
        )

    @staticmethod
    def _text2vec_summary(
        best_category: ScoredCandidate,
        best_job: ScoredCandidate,
        second_job: ScoredCandidate | None,
        margin: float,
    ) -> dict[str, object]:
        return {
            "best_category": best_category.name,
            "best_category_score": round(best_category.score, 6),
            "best_job": best_job.name,
            "best_job_score": round(best_job.score, 6),
            "second_job": second_job.name if second_job is not None else "",
            "second_job_score": round(second_job.score, 6) if second_job is not None else 0.0,
            "top1_margin": round(margin, 6),
        }

    @staticmethod
    def _accepted_llm_job(selected_standard_job: str, candidates: list[ScoredCandidate]) -> ScoredCandidate | None:
        selected = selected_standard_job.strip()
        if not selected:
            return None
        for candidate in candidates:
            if candidate.name == selected:
                return candidate
        return None

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _run_with_heartbeat(self, stage: str, action):
        if self.progress is None:
            return action()

        done = threading.Event()

        def heartbeat() -> None:
            waited_seconds = 0
            while not done.wait(10):
                waited_seconds += 10
                self._progress(f"{stage}: still waiting for API/model response ({waited_seconds}s elapsed)")

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        started_at = time.perf_counter()
        try:
            return action()
        finally:
            done.set()
            elapsed = time.perf_counter() - started_at
            if elapsed >= 1:
                self._progress(f"{stage}: stage finished in {elapsed:.1f}s")
