from __future__ import annotations

from dataclasses import dataclass

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

    def process(self, posting: JobPosting, write: bool = True) -> ProcessResult:
        similarity = self.similarity or Text2VecSimilarity()
        normalizer = self.skill_normalizer or PassthroughSkillNormalizer()
        route = self.taxonomy.route(
            posting.job_title,
            similarity=similarity,
            category_threshold=self.category_threshold,
            job_threshold=self.job_threshold,
            tie_delta=self.tie_delta,
        )
        if route.status != "existing_job" or route.best_job is None:
            return ProcessResult(route=route, posting=posting, update=None)

        if not posting.skills and self.skill_extractor is not None:
            posting.skills.extend(self.skill_extractor.extract(posting))
        normalized_skills = normalizer.normalize(posting, posting.skills)
        events, frequency = self.frequency_store.append_existing_job(
            posting=posting,
            standard_job=route.best_job.name,
            normalized_skills=normalized_skills,
            write=write,
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
