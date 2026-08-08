from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_ROOT = PROJECT_ROOT / "data" / "versions"
DATASET_ROOT = PROJECT_ROOT.parents[1]
LEGACY_BASE_DIR = DATASET_ROOT / "岗位数据流生成与评测系统" / "data" / "reference" / "company_base_v1"
COMPANY_DATA_VERSION_ENV = "COMPANY_DATA_VERSION"
DEFAULT_COMPANY_DATA_VERSION = "company_large_v2"


@dataclass(frozen=True, slots=True)
class CompanyDataPaths:
    version: str
    data_dir: Path
    title_dictionary: Path
    event_stream: Path
    frequency: Path
    skill_pool: Path
    lifecycle: Path
    migration: Path
    spread: Path
    profile_snapshots: Path
    profile_diff: Path
    current_profile: Path
    database: Path
    manifest: Path


def resolve_company_data_paths(version: str | None = None) -> CompanyDataPaths:
    selected = (version or os.getenv(COMPANY_DATA_VERSION_ENV) or DEFAULT_COMPANY_DATA_VERSION).strip()
    if not selected or any(part in {"", ".", ".."} for part in Path(selected).parts):
        raise ValueError(f"Invalid {COMPANY_DATA_VERSION_ENV}: {selected!r}")
    data_dir = VERSION_ROOT / selected
    if not data_dir.is_dir():
        raise FileNotFoundError(
            f"Company data version {selected!r} does not exist at {data_dir}. "
            f"Set {COMPANY_DATA_VERSION_ENV} to an available version."
        )
    return CompanyDataPaths(
        version=selected,
        data_dir=data_dir,
        title_dictionary=data_dir / "standard_job_title_dictionary.csv",
        event_stream=data_dir / "job_update_event_stream.csv",
        frequency=data_dir / "job_skill_monthly_frequency.csv",
        skill_pool=data_dir / "skill_pool.csv",
        lifecycle=data_dir / "skill_lifecycle.csv",
        migration=data_dir / "skill_migration.csv",
        spread=data_dir / "skill_job_monthly_spread.csv",
        profile_snapshots=data_dir / "job_profile_snapshots.csv",
        profile_diff=data_dir / "job_profile_diff.csv",
        current_profile=data_dir / "job_current_profile_system.csv",
        database=data_dir / "job_update.db",
        manifest=data_dir / "version_manifest.json",
    )


def list_company_data_versions() -> list[str]:
    if not VERSION_ROOT.exists():
        return []
    return sorted(path.name for path in VERSION_ROOT.iterdir() if path.is_dir())
