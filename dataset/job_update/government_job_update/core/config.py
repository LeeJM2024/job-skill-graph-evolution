from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = PACKAGE_ROOT.parents[0]
BASE_DATA_DIR = PACKAGE_ROOT / "data" / "base"
DEFAULT_SOURCE_INPUT = PACKAGE_ROOT / "government_jobs_2024_2026_tech_final.csv"
DEFAULT_NORMALIZED_POSTINGS = BASE_DATA_DIR / "government_job_postings_normalized.csv"
DEFAULT_RAW_EVENT_STREAM = BASE_DATA_DIR / "government_job_event_stream_raw.csv"
DEFAULT_BUILD_AUDIT = BASE_DATA_DIR / "government_event_build_audit.json"
DEFAULT_ROUTE_REVIEW = BASE_DATA_DIR / "government_job_route_review.csv"
DEFAULT_INITIAL_ASSIGNMENT = BASE_DATA_DIR / "government_initial_job_assignment.csv"
DEFAULT_INITIAL_ASSIGNMENT_REVIEW = BASE_DATA_DIR / "government_initial_job_assignment_review.csv"
DEFAULT_JOB_DICTIONARY = BASE_DATA_DIR / "standard_job_title_dictionary.csv"
DEFAULT_TEXT2VEC_MODEL = "shibing624/text2vec-base-chinese"
DEFAULT_TITLE_CLEANED_POSTINGS = BASE_DATA_DIR / "government_job_postings_title_cleaned.csv"
DEFAULT_TITLE_CLEANING_AUDIT = BASE_DATA_DIR / "government_title_cleaning_audit.csv"
DEFAULT_TITLE_CLEANING_CACHE = BASE_DATA_DIR / "cache" / "government_title_cleaning_cache.jsonl"
DEFAULT_SKILL_EXTRACT_DIR = PACKAGE_ROOT / "skill_extract"
DEFAULT_SKILL_EXTRACTION_DICTIONARY = DEFAULT_SKILL_EXTRACT_DIR / "government_skill_dictionary.csv"
DEFAULT_SKILL_EXTRACTION_CACHE = BASE_DATA_DIR / "cache" / "government_skill_extraction_cache.jsonl"
DEFAULT_SKILL_NORMALIZATION_CACHE = BASE_DATA_DIR / "cache" / "government_skill_normalization_cache.jsonl"

# These are the government domain's formal, dynamically updated base state.
# Raw and review files above are deliberately kept separate from this state.
DEFAULT_EVENT_STREAM = BASE_DATA_DIR / "government_job_event_stream.csv"
DEFAULT_FREQUENCY_OUTPUT = BASE_DATA_DIR / "government_job_skill_monthly_frequency.csv"
DEFAULT_SKILL_POOL = BASE_DATA_DIR / "government_skill_pool.csv"
DEFAULT_SKILL_LIFECYCLE = BASE_DATA_DIR / "government_skill_lifecycle.csv"
DEFAULT_SKILL_MIGRATION = BASE_DATA_DIR / "government_skill_migration.csv"
DEFAULT_SKILL_JOB_MONTHLY_SPREAD = BASE_DATA_DIR / "government_skill_job_monthly_spread.csv"
DEFAULT_JOB_PROFILE_SNAPSHOTS = BASE_DATA_DIR / "government_job_profile_snapshots.csv"
DEFAULT_JOB_PROFILE_DIFF = BASE_DATA_DIR / "government_job_profile_diff.csv"
DEFAULT_CURRENT_PROFILE = BASE_DATA_DIR / "government_job_current_profile_system.csv"
DEFAULT_DATABASE = BASE_DATA_DIR / "government_job_update.db"
