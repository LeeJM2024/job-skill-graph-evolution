from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

from .database import SQLiteJobUpdateStore
from .current_profile_store import CurrentProfileStore
from .frequency_store import FrequencyStore
from .job_profile_store import JobProfileStore
from .models import ExistingJobUpdate, JobPosting, JobRoute, NormalizedSkill, ProcessResult, ScoredCandidate
from .route_adjudication import RouteAdjudicator
from .similarity import SimilarityBackend, Text2VecSimilarity
from .skill_extraction import SkillExtractor
from .skill_lifecycle_store import SkillLifecycleStore
from .skill_migration_store import SkillMigrationStore
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
    skill_lifecycle_store: SkillLifecycleStore | None = None
    skill_migration_store: SkillMigrationStore | None = None
    job_profile_store: JobProfileStore | None = None
    current_profile_store: CurrentProfileStore | None = None
    database_store: SQLiteJobUpdateStore | None = None
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

    def process(
        self,
        posting: JobPosting,
        write: bool = True,
        *,
        collect_skills_for_review: bool = False,
        confirmed_standard_job: str = "",
        confirmed_standard_category: str = "",
    ) -> ProcessResult:
        """Process a posting, optionally applying a human-confirmed route.

        Human review uses the same write path as automatic processing.  The
        only difference is that the selected route is supplied by a reviewer
        instead of inferred again from the title.
        """
        normalizer = self.skill_normalizer or PassthroughSkillNormalizer()
        routing_job_title = posting.routing_job_title.strip() or posting.job_title
        if confirmed_standard_job:
            routing_job_title = posting.routing_job_title.strip() or posting.job_title
            category_candidate = ScoredCandidate(
                confirmed_standard_category,
                1.0,
                {"source": "human_review"},
            )
            job_candidate = ScoredCandidate(
                confirmed_standard_job,
                1.0,
                {"category": confirmed_standard_category, "source": "human_review"},
            )
            route = JobRoute(
                status="existing_job",
                selected_categories=[category_candidate],
                selected_jobs=[job_candidate],
                best_category=category_candidate,
                best_job=job_candidate,
                reason="human review confirmed standard job",
                top_categories=[category_candidate],
                top_jobs=[job_candidate],
            )
            posting.routing_job_title = routing_job_title
            self._progress(
                f"routing: using human-confirmed route {confirmed_standard_category} / {confirmed_standard_job}"
            )
        else:
            route = None
        if route is None and self.title_cleaner is not None and not posting.routing_job_title.strip():
            self._progress("title_cleaning: calling configured LLM title cleaner")
            routing_job_title = self._run_with_heartbeat(
                "title_cleaning",
                lambda: self.title_cleaner.clean(posting.job_title),
            )
            self._progress(f"title_cleaning: raw={posting.job_title}, cleaned={routing_job_title}")
        posting.routing_job_title = routing_job_title
        if route is None:
            similarity = self.similarity or Text2VecSimilarity()
            self._progress("routing: comparing cleaned job title with standard categories and jobs")
            route = self._route_posting(posting, routing_job_title, similarity)
            # The automatic decision may use a narrower candidate set, while
            # reviewers need to see the globally ranked Top-K alternatives.
            route.top_categories = self.taxonomy.score_categories(routing_job_title, similarity)[:5]
            route.top_jobs = self.taxonomy.score_jobs(routing_job_title, similarity)[:10]
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
        should_collect_skills = route.status == "existing_job" or collect_skills_for_review
        normalized_skills: list[NormalizedSkill] = []
        if should_collect_skills:
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

        if route.status != "existing_job" or route.best_job is None:
            self._progress("done: not an existing job, frequency and skill pool will not be updated")
            result = ProcessResult(
                route=route,
                posting=posting,
                update=None,
                normalized_skills=normalized_skills,
            )
            if write and self.database_store is not None:
                self._progress("database: writing route log")
                self.database_store.sync_after_process(result=result)
            return result

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

        lifecycle_rows = 0
        lifecycle = None
        if self.skill_lifecycle_store is not None:
            mode = "dry-run rebuild" if not write else "calculate update"
            self._progress(f"lifecycle: rebuilding skill lifecycle table ({mode})")
            lifecycle = self.skill_lifecycle_store.rebuild(
                frequency=frequency,
                skill_pool=skill_pool,
                as_of_month=posting.month,
                write=False,
            )
            lifecycle_rows = len(lifecycle)
            self._progress(f"lifecycle: rows={lifecycle_rows}")
        else:
            self._progress("lifecycle: no lifecycle path configured, skipped")

        migration_rows = 0
        spread_rows = 0
        migration = None
        spread = None
        if self.skill_migration_store is not None:
            mode = "dry-run rebuild" if not write else "calculate update"
            self._progress(f"migration: rebuilding skill migration and monthly spread tables ({mode})")
            migration, spread = self.skill_migration_store.rebuild(
                frequency=frequency,
                skill_pool=skill_pool,
                write=False,
            )
            migration_rows = len(migration)
            spread_rows = len(spread)
            self._progress(f"migration: migration_rows={migration_rows}, spread_rows={spread_rows}")
        else:
            self._progress("migration: no migration path configured, skipped")

        profile_snapshot_rows = 0
        profile_diff_rows = 0
        profile_snapshots = None
        profile_diffs = None
        current_profile_rows = 0
        current_profile = None
        if self.job_profile_store is not None:
            mode = "dry-run rebuild" if not write else "calculate update"
            self._progress(f"job_profile: rebuilding profile snapshots and diffs ({mode})")
            profile_snapshots, profile_diffs = self.job_profile_store.rebuild(
                frequency=frequency,
                skill_pool=skill_pool,
                write=False,
            )
            profile_snapshot_rows = len(profile_snapshots)
            profile_diff_rows = len(profile_diffs)
            self._progress(
                f"job_profile: snapshot_rows={profile_snapshot_rows}, diff_rows={profile_diff_rows}"
            )
        else:
            self._progress("job_profile: no profile path configured, skipped")

        if self.current_profile_store is not None and profile_snapshots is not None:
            mode = "dry-run rebuild" if not write else "calculate update"
            self._progress(f"current_profile: rebuilding current system profile ({mode})")
            current_profile = self.current_profile_store.rebuild(
                snapshots=profile_snapshots,
                write=False,
            )
            current_profile_rows = len(current_profile)
            self._progress(f"current_profile: rows={current_profile_rows}")
        elif self.current_profile_store is not None:
            self._progress("current_profile: profile snapshots unavailable, skipped")

        if write:
            self._progress("write: writing event stream and frequency table")
            self.frequency_store.write_tables(events, frequency)
            if self.skill_pool_store is not None and skill_pool is not None:
                self._progress("write: writing skill pool")
                self.skill_pool_store.write_pool(skill_pool)
            if self.skill_lifecycle_store is not None and lifecycle is not None:
                self._progress("write: writing skill lifecycle")
                self.skill_lifecycle_store.write_lifecycle(lifecycle)
            if self.skill_migration_store is not None and migration is not None and spread is not None:
                self._progress("write: writing skill migration and monthly spread")
                self.skill_migration_store.write_tables(migration, spread)
            if self.job_profile_store is not None and profile_snapshots is not None and profile_diffs is not None:
                self._progress("write: writing job profile snapshots and diffs")
                self.job_profile_store.write_tables(profile_snapshots, profile_diffs)
            if self.current_profile_store is not None and current_profile is not None:
                self._progress("write: writing current system job profile")
                self.current_profile_store.write(current_profile)
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
            lifecycle_rows=lifecycle_rows,
            migration_rows=migration_rows,
            spread_rows=spread_rows,
            profile_snapshot_rows=profile_snapshot_rows,
            profile_diff_rows=profile_diff_rows,
            current_profile_rows=current_profile_rows,
            event_stream_path=str(self.frequency_store.event_stream_path),
            frequency_path=str(self.frequency_store.frequency_path)
            if self.frequency_store.frequency_path is not None
            else None,
            skill_pool_path=str(self.skill_pool_store.skill_pool_path)
            if self.skill_pool_store is not None
            else None,
            lifecycle_path=str(self.skill_lifecycle_store.skill_lifecycle_path)
            if self.skill_lifecycle_store is not None
            else None,
            migration_path=str(self.skill_migration_store.skill_migration_path)
            if self.skill_migration_store is not None
            else None,
            spread_path=str(self.skill_migration_store.skill_job_monthly_spread_path)
            if self.skill_migration_store is not None
            else None,
            profile_snapshot_path=str(self.job_profile_store.snapshot_path)
            if self.job_profile_store is not None
            else None,
            profile_diff_path=str(self.job_profile_store.diff_path)
            if self.job_profile_store is not None
            else None,
            current_profile_path=str(self.current_profile_store.current_profile_path)
            if self.current_profile_store is not None
            else None,
        )
        result = ProcessResult(
            route=route,
            posting=posting,
            update=update,
            normalized_skills=normalized_skills,
        )
        if write and self.database_store is not None:
            self._progress(
                "database: syncing processed posting, route, skills, frequency, "
                "skill pool, lifecycle, migration, and job profile"
            )
            self.database_store.sync_after_process(
                result=result,
                frequency=frequency,
                skill_pool=skill_pool,
                lifecycle=lifecycle,
                migration=migration,
                spread=spread,
                profile_snapshots=profile_snapshots,
                profile_diffs=profile_diffs,
            )
        return result

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
        adjudication = {
            "route_status": decision.route_status,
            "selected_standard_job": decision.selected_standard_job,
            "selected_category": decision.selected_category,
            "confidence": decision.confidence,
            "evidence": decision.evidence,
            "reason": decision.reason,
        }
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
                    adjudication=adjudication,
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
                adjudication=adjudication,
            )

        return JobRoute(
            status=decision.route_status,
            selected_categories=selected_categories,
            selected_jobs=selected_jobs,
            best_category=best_category,
            best_job=best_job,
            reason=decision.reason or "LLM adjudication did not accept an existing job",
            adjudication=adjudication,
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
