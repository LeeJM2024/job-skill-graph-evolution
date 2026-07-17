from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .frequency_store import FrequencyStore
from .models import ExistingJobUpdate, JobPosting, ProcessResult
from .similarity import SimilarityBackend, Text2VecSimilarity
from .skill_extraction import SkillExtractor
from .skill_normalizer import PassthroughSkillNormalizer, SkillNormalizer
from .taxonomy import JobTaxonomy


@dataclass(slots=True)
class JobUpdateSystem:
    taxonomy: JobTaxonomy
    frequency_store: FrequencyStore
    similarity: SimilarityBackend | None = None
    skill_extractor: SkillExtractor | None = None
    skill_normalizer: SkillNormalizer | None = None
    category_threshold: float = 0.6
    job_threshold: float = 0.85
    tie_delta: float = 0.03
    progress: Callable[[str], None] | None = None

    def process(self, posting: JobPosting, write: bool = True) -> ProcessResult:
        similarity = self.similarity or Text2VecSimilarity()
        normalizer = self.skill_normalizer or PassthroughSkillNormalizer()
        self._progress("routing: comparing job title with standard categories and jobs")
        route = self.taxonomy.route(
            posting.job_title,
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
            self._progress("done: not an existing job, frequency table will not be updated")
            return ProcessResult(route=route, posting=posting, update=None)

        if not posting.skills:
            if self.skill_extractor is None:
                raise ValueError("process-one requires skill_extract output; no skill_extractor was configured")
            self._progress("skills: calling configured skill provider")
            posting.skills.extend(self.skill_extractor.extract(posting))
            self._progress(f"skills: extracted {len(posting.skills)} final normalized skills")
        elif posting.skills:
            self._progress(f"skills: using {len(posting.skills)} supplied final normalized skills")

        self._progress("skills: validating final normalized skills")
        normalized_skills = normalizer.normalize(posting, posting.skills)
        self._progress(f"skills: accepted {len(normalized_skills)} unique normalized skills")
        mode = "dry-run rebuild" if not write else "append and write"
        self._progress(f"frequency: loading event stream and rebuilding monthly/cumulative table ({mode})")
        events, frequency = self.frequency_store.append_existing_job(
            posting=posting,
            standard_job=route.best_job.name,
            normalized_skills=normalized_skills,
            write=write,
        )
        self._progress(
            f"frequency: event_rows={len(events)}, frequency_rows={len(frequency)}, write={write}"
        )
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
            event_stream_path=str(self.frequency_store.event_stream_path),
            frequency_path=str(self.frequency_store.frequency_path)
            if self.frequency_store.frequency_path is not None
            else None,
        )
        return ProcessResult(route=route, posting=posting, update=update)

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)
