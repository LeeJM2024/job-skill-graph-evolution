from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from company_job_update.core.current_profile import CURRENT_PROFILE_COLUMNS, build_current_profile


@dataclass(slots=True)
class GovernmentCurrentProfileStore:
    current_profile_path: Path

    def rebuild(self, *, snapshots: pd.DataFrame, write: bool = True) -> pd.DataFrame:
        profile = build_current_profile(snapshots)
        if write:
            self.write(profile)
        return profile

    def write(self, profile: pd.DataFrame) -> None:
        self.current_profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile.to_csv(self.current_profile_path, index=False, encoding="utf-8-sig")

    def load(self) -> pd.DataFrame:
        if not self.current_profile_path.exists():
            return pd.DataFrame(columns=CURRENT_PROFILE_COLUMNS)
        frame = pd.read_csv(self.current_profile_path, dtype=str, encoding="utf-8-sig").fillna("")
        for column in CURRENT_PROFILE_COLUMNS:
            if column not in frame.columns:
                frame[column] = ""
        return frame[CURRENT_PROFILE_COLUMNS]
