from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .skill_migration import (
    SKILL_JOB_MONTHLY_SPREAD_COLUMNS,
    SKILL_MIGRATION_COLUMNS,
    build_skill_migration_tables,
)


@dataclass(slots=True)
class SkillMigrationStore:
    skill_migration_path: Path
    skill_job_monthly_spread_path: Path

    def load_migration(self) -> pd.DataFrame:
        return _load_table(self.skill_migration_path, SKILL_MIGRATION_COLUMNS)

    def load_spread(self) -> pd.DataFrame:
        return _load_table(self.skill_job_monthly_spread_path, SKILL_JOB_MONTHLY_SPREAD_COLUMNS)

    def rebuild(
        self,
        *,
        frequency: pd.DataFrame,
        skill_pool: pd.DataFrame | None = None,
        write: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        migration, spread = build_skill_migration_tables(frequency, skill_pool)
        if write:
            self.write_tables(migration, spread)
        return migration, spread

    def write_tables(self, migration: pd.DataFrame, spread: pd.DataFrame) -> None:
        self.skill_migration_path.parent.mkdir(parents=True, exist_ok=True)
        self.skill_job_monthly_spread_path.parent.mkdir(parents=True, exist_ok=True)
        migration.to_csv(self.skill_migration_path, index=False, encoding="utf-8-sig")
        spread.to_csv(self.skill_job_monthly_spread_path, index=False, encoding="utf-8-sig")


def _load_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]
