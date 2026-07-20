from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

from .frequency_store import FrequencyStore
from .models import ExistingJobUpdate, JobPosting, ProcessResult
from .similarity import SimilarityBackend, Text2VecSimilarity
from .skill_extraction import SkillExtractor
from .skill_normalizer import PassthroughSkillNormalizer, SkillNormalizer
from .skill_pool_store import SkillPoolStore
from .taxonomy import JobTaxonomy
from .title_cleaning import TitleCleaner


@dataclass(slots=True)
class JobUpdateSystem:
    taxonomy: JobTaxonomy
    frequency_store: FrequencyStore
    skill_pool_store: SkillPoolStore | None = None
    similarity: SimilarityBackend | None = None
    title_cleaner: TitleCleaner | None = None
    skill_extractor: SkillExtractor | None = None
    skill_normalizer: SkillNormalizer | None = None
    category_threshold: float = 0.6
    job_threshold: float = 0.85
    tie_delta: float = 0.03
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
        route = self.taxonomy.route(
            routing_job_title,
            similarity=similarity,
            category_threshold=self.category_threshold,
            job_threshold=self.job_threshold,
            tie_delta=self.tie_delta,
        )
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
