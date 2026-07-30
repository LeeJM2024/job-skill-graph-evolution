from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .job_profile import (
    JOB_PROFILE_DIFF_COLUMNS,
    JOB_PROFILE_SNAPSHOT_COLUMNS,
    JobProfileRules,
    build_job_profile_tables,
)


@dataclass(slots=True)
class JobProfileStore:
    snapshot_path: Path
    diff_path: Path
    rules: JobProfileRules | None = None

    def load_snapshots(self) -> pd.DataFrame:
        return _load_table(self.snapshot_path, JOB_PROFILE_SNAPSHOT_COLUMNS)

    def load_diffs(self) -> pd.DataFrame:
        return _load_table(self.diff_path, JOB_PROFILE_DIFF_COLUMNS)

    def rebuild(
        self,
        *,
        frequency: pd.DataFrame,
        skill_pool: pd.DataFrame | None = None,
        write: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        snapshots, diffs = build_job_profile_tables(
            frequency,
            skill_pool,
            rules=self.rules,
        )
        if write:
            self.write_tables(snapshots, diffs)
        return snapshots, diffs

    def write_tables(self, snapshots: pd.DataFrame, diffs: pd.DataFrame) -> None:
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        self.diff_path.parent.mkdir(parents=True, exist_ok=True)
        snapshots.to_csv(self.snapshot_path, index=False, encoding="utf-8-sig")
        diffs.to_csv(self.diff_path, index=False, encoding="utf-8-sig")


def _load_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]
