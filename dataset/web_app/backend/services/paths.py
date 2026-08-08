from __future__ import annotations

from pathlib import Path
import sys


DATASET_ROOT = Path(__file__).resolve().parents[3]
WEB_APP_ROOT = DATASET_ROOT / "web_app"
FRONTEND_ROOT = WEB_APP_ROOT / "frontend"
JOB_UPDATE_ROOT = DATASET_ROOT / "job_update" / "company_job_update"
JOB_UPDATE_PACKAGE_ROOT = JOB_UPDATE_ROOT / "core"
JOB_UPDATE_GROUP_ROOT = DATASET_ROOT / "job_update"
if str(JOB_UPDATE_GROUP_ROOT) not in sys.path:
    sys.path.insert(0, str(JOB_UPDATE_GROUP_ROOT))
from company_job_update.core.data_versions import resolve_company_data_paths

COMPANY_DATA_PATHS = resolve_company_data_paths()
DATA_STREAM_ROOT = DATASET_ROOT / "岗位数据流生成系统"
SKILL_EXTRACT_ROOT = JOB_UPDATE_ROOT / "skill_extract"

BASE_DATA_DIR = COMPANY_DATA_PATHS.data_dir
BASE_DATABASE = COMPANY_DATA_PATHS.database
BASE_TITLE_DICTIONARY = COMPANY_DATA_PATHS.title_dictionary
BASE_EVENT_STREAM = COMPANY_DATA_PATHS.event_stream
BASE_FREQUENCY_OUTPUT = COMPANY_DATA_PATHS.frequency
BASE_SKILL_POOL = COMPANY_DATA_PATHS.skill_pool
BASE_SKILL_LIFECYCLE = COMPANY_DATA_PATHS.lifecycle
BASE_SKILL_MIGRATION = COMPANY_DATA_PATHS.migration
BASE_SKILL_MONTHLY_SPREAD = COMPANY_DATA_PATHS.spread
BASE_JOB_PROFILE_DIFF = COMPANY_DATA_PATHS.profile_diff
BASE_JOB_PROFILE_SNAPSHOTS = COMPANY_DATA_PATHS.profile_snapshots
BASE_CURRENT_PROFILE = COMPANY_DATA_PATHS.current_profile
SKILL_ALIAS_DICTIONARY = SKILL_EXTRACT_ROOT / "company_skill_dictionary.csv"
# The broad extraction dictionary is the sole maintained skill ontology.
SKILL_NORMALIZED_DICTIONARY = SKILL_ALIAS_DICTIONARY
SKILL_DISPLAY_DICTIONARY = SKILL_ALIAS_DICTIONARY
DATA_STREAM_TITLE_DICTIONARY = DATA_STREAM_ROOT / "data" / "input" / "standard_job_title_dictionary.csv"
DATA_STREAM_SKILL_DICTIONARY = DATA_STREAM_ROOT / "data" / "input" / "company_skill_dictionary_with_type.csv"

GOVERNMENT_JOB_UPDATE_ROOT = DATASET_ROOT / "job_update" / "government_job_update"
GOVERNMENT_BASE_DATA_DIR = GOVERNMENT_JOB_UPDATE_ROOT / "data" / "base"
GOVERNMENT_BASE_DATABASE = GOVERNMENT_BASE_DATA_DIR / "government_job_update.db"
GOVERNMENT_BASE_TITLE_DICTIONARY = GOVERNMENT_BASE_DATA_DIR / "standard_job_title_dictionary.csv"
GOVERNMENT_BASE_EVENT_STREAM = GOVERNMENT_BASE_DATA_DIR / "government_job_event_stream.csv"
GOVERNMENT_BASE_FREQUENCY_OUTPUT = GOVERNMENT_BASE_DATA_DIR / "government_job_skill_monthly_frequency.csv"
GOVERNMENT_BASE_SKILL_POOL = GOVERNMENT_BASE_DATA_DIR / "government_skill_pool.csv"
GOVERNMENT_BASE_SKILL_LIFECYCLE = GOVERNMENT_BASE_DATA_DIR / "government_skill_lifecycle.csv"
GOVERNMENT_BASE_SKILL_MIGRATION = GOVERNMENT_BASE_DATA_DIR / "government_skill_migration.csv"
GOVERNMENT_BASE_SKILL_MONTHLY_SPREAD = GOVERNMENT_BASE_DATA_DIR / "government_skill_job_monthly_spread.csv"
GOVERNMENT_BASE_JOB_PROFILE_DIFF = GOVERNMENT_BASE_DATA_DIR / "government_job_profile_diff.csv"
GOVERNMENT_BASE_JOB_PROFILE_SNAPSHOTS = GOVERNMENT_BASE_DATA_DIR / "government_job_profile_snapshots.csv"
GOVERNMENT_BASE_CURRENT_PROFILE = GOVERNMENT_BASE_DATA_DIR / "government_job_current_profile_system.csv"


def resolve_domain(domain: str) -> str:
    value = str(domain or "company").strip().lower()
    if value not in {"company", "government"}:
        raise ValueError("domain must be company or government")
    return value


def domain_file(domain: str, name: str) -> Path:
    domain = resolve_domain(domain)
    files = {
        "company": {
            "frequency": BASE_FREQUENCY_OUTPUT, "lifecycle": BASE_SKILL_LIFECYCLE,
            "migration": BASE_SKILL_MIGRATION, "spread": BASE_SKILL_MONTHLY_SPREAD,
            "snapshot": BASE_JOB_PROFILE_SNAPSHOTS, "diff": BASE_JOB_PROFILE_DIFF, "current": BASE_CURRENT_PROFILE,
        },
        "government": {
            "frequency": GOVERNMENT_BASE_FREQUENCY_OUTPUT, "lifecycle": GOVERNMENT_BASE_SKILL_LIFECYCLE,
            "migration": GOVERNMENT_BASE_SKILL_MIGRATION, "spread": GOVERNMENT_BASE_SKILL_MONTHLY_SPREAD,
            "snapshot": GOVERNMENT_BASE_JOB_PROFILE_SNAPSHOTS, "diff": GOVERNMENT_BASE_JOB_PROFILE_DIFF, "current": GOVERNMENT_BASE_CURRENT_PROFILE,
        },
    }
    return files[domain][name]

BACKUP_ROOT = WEB_APP_ROOT / "backups"
RUN_FULL_SCRIPT = DATASET_ROOT / "run_full_pipeline.py"
