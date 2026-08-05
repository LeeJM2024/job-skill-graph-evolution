from __future__ import annotations

from pathlib import Path


DATASET_ROOT = Path(__file__).resolve().parents[3]
WEB_APP_ROOT = DATASET_ROOT / "web_app"
FRONTEND_ROOT = WEB_APP_ROOT / "frontend"
JOB_UPDATE_ROOT = DATASET_ROOT / "job_update"
JOB_UPDATE_PACKAGE_ROOT = JOB_UPDATE_ROOT / "job_update"
DATA_STREAM_ROOT = DATASET_ROOT / "岗位数据流生成系统"
SKILL_EXTRACT_ROOT = DATASET_ROOT / "skill_extract"

BASE_DATA_DIR = JOB_UPDATE_ROOT / "data" / "base"
BASE_DATABASE = BASE_DATA_DIR / "job_update.db"
BASE_TITLE_DICTIONARY = BASE_DATA_DIR / "standard_job_title_dictionary.csv"
BASE_EVENT_STREAM = BASE_DATA_DIR / "job_update_event_stream.csv"
BASE_FREQUENCY_OUTPUT = BASE_DATA_DIR / "job_skill_monthly_frequency.csv"
BASE_SKILL_POOL = BASE_DATA_DIR / "skill_pool.csv"
BASE_SKILL_LIFECYCLE = BASE_DATA_DIR / "skill_lifecycle.csv"
BASE_SKILL_MIGRATION = BASE_DATA_DIR / "skill_migration.csv"
BASE_SKILL_MONTHLY_SPREAD = BASE_DATA_DIR / "skill_job_monthly_spread.csv"
BASE_JOB_PROFILE_DIFF = BASE_DATA_DIR / "job_profile_diff.csv"
BASE_JOB_PROFILE_SNAPSHOTS = BASE_DATA_DIR / "job_profile_snapshots.csv"
BASE_CURRENT_PROFILE = BASE_DATA_DIR / "job_current_profile_system.csv"
SKILL_ALIAS_DICTIONARY = SKILL_EXTRACT_ROOT / "泛抽取级词典.csv"
SKILL_NORMALIZED_DICTIONARY = SKILL_EXTRACT_ROOT / "归一化级词典.csv"
SKILL_DISPLAY_DICTIONARY = SKILL_EXTRACT_ROOT / "展示级词典.csv"
DATA_STREAM_TITLE_DICTIONARY = DATA_STREAM_ROOT / "data" / "input" / "standard_job_title_dictionary.csv"
DATA_STREAM_SKILL_DICTIONARY = DATA_STREAM_ROOT / "data" / "input" / "泛抽取级词典_传统新兴分类.csv"

BACKUP_ROOT = WEB_APP_ROOT / "backups"
RUN_FULL_SCRIPT = DATASET_ROOT / "run_full_pipeline.py"
