from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .skill_lifecycle import LIFECYCLE_COLUMNS, LifecycleRules, build_skill_lifecycle_table


@dataclass(slots=True)
class SkillLifecycleStore:
    skill_lifecycle_path: Path
    rules: LifecycleRules | None = None

    def load(self) -> pd.DataFrame:
        if not self.skill_lifecycle_path.exists():
            return pd.DataFrame(columns=LIFECYCLE_COLUMNS)
        lifecycle = pd.read_csv(self.skill_lifecycle_path, dtype=str, encoding="utf-8-sig").fillna("")
        for column in LIFECYCLE_COLUMNS:
            if column not in lifecycle.columns:
                lifecycle[column] = ""
        return lifecycle[LIFECYCLE_COLUMNS]

    def rebuild(
        self,
        *,
        frequency: pd.DataFrame,
        skill_pool: pd.DataFrame | None = None,
        as_of_month: str | None = None,
        write: bool = True,
    ) -> pd.DataFrame:
        lifecycle = build_skill_lifecycle_table(
            frequency,
            skill_pool,
            as_of_month=as_of_month,
            rules=self.rules,
        )
        if write:
            self.write_lifecycle(lifecycle)
        return lifecycle

    def write_lifecycle(self, lifecycle: pd.DataFrame) -> None:
        self.skill_lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
        lifecycle.to_csv(self.skill_lifecycle_path, index=False, encoding="utf-8-sig")
