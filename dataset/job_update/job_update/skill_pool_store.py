from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .models import JobPosting, NormalizedSkill
from .text import clean_text, split_semicolon


SKILL_POOL_COLUMNS = [
    "normalized_skill",
    "kg_display_skill",
    "skill_type",
    "standard_categories",
    "standard_jobs",
    "first_seen_month",
    "last_seen_month",
    "first_seen_job_id",
    "last_seen_job_id",
    "mention_count",
    "source_job_ids",
    "source_count",
    "sources",
    "updated_at",
]


@dataclass(slots=True)
class SkillPoolStore:
    skill_pool_path: Path

    def load(self) -> pd.DataFrame:
        if not self.skill_pool_path.exists():
            return pd.DataFrame(columns=SKILL_POOL_COLUMNS)
        pool = pd.read_csv(self.skill_pool_path, dtype=str).fillna("")
        for column in SKILL_POOL_COLUMNS:
            if column not in pool.columns:
                pool[column] = ""
        return pool[SKILL_POOL_COLUMNS]

    def update(
        self,
        posting: JobPosting,
        standard_category: str,
        standard_job: str,
        normalized_skills: list[NormalizedSkill],
        write: bool = True,
    ) -> pd.DataFrame:
        pool = self.load()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source = clean_text(posting.metadata.get("source"))

        for skill in normalized_skills:
            name = clean_text(skill.normalized_skill)
            family = clean_text(skill.kg_display_skill)
            if not name or not family:
                raise ValueError(
                    "skill pool update requires normalized_skill and kg_display_skill "
                    f"for job_id={posting.job_id}"
                )

            key = name.casefold()
            if pool.empty:
                matching_indexes: list[int] = []
            else:
                matching_indexes = pool.index[
                    pool["normalized_skill"].astype(str).str.strip().str.casefold() == key
                ].tolist()

            if not matching_indexes:
                pool = pd.concat(
                    [
                        pool,
                        pd.DataFrame(
                            [
                                {
                                    "normalized_skill": name,
                                    "kg_display_skill": family,
                                    "skill_type": clean_text(skill.skill_type),
                                    "standard_categories": clean_text(standard_category),
                                    "standard_jobs": clean_text(standard_job),
                                    "first_seen_month": clean_text(posting.month),
                                    "last_seen_month": clean_text(posting.month),
                                    "first_seen_job_id": clean_text(posting.job_id),
                                    "last_seen_job_id": clean_text(posting.job_id),
                                    "mention_count": "1",
                                    "source_job_ids": clean_text(posting.job_id),
                                    "source_count": "1" if clean_text(posting.job_id) else "0",
                                    "sources": source,
                                    "updated_at": now,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
                continue

            row_index = matching_indexes[0]
            row = pool.loc[row_index]
            current_month = clean_text(posting.month)
            first_seen_month = clean_text(row.get("first_seen_month"))
            last_seen_month = clean_text(row.get("last_seen_month"))

            pool.at[row_index, "kg_display_skill"] = _first_non_empty(row.get("kg_display_skill"), family)
            pool.at[row_index, "skill_type"] = _first_non_empty(row.get("skill_type"), skill.skill_type)
            pool.at[row_index, "standard_categories"] = _join_unique(
                split_semicolon(row.get("standard_categories")),
                [standard_category],
            )
            pool.at[row_index, "standard_jobs"] = _join_unique(
                split_semicolon(row.get("standard_jobs")),
                [standard_job],
            )
            pool.at[row_index, "mention_count"] = str(_int_value(row.get("mention_count")) + 1)
            pool.at[row_index, "source_job_ids"] = _join_unique(
                split_semicolon(row.get("source_job_ids")),
                [posting.job_id],
            )
            pool.at[row_index, "source_count"] = str(
                len(split_semicolon(pool.at[row_index, "source_job_ids"]))
            )
            pool.at[row_index, "sources"] = _join_unique(split_semicolon(row.get("sources")), [source])
            pool.at[row_index, "updated_at"] = now

            if current_month and (not first_seen_month or current_month < first_seen_month):
                pool.at[row_index, "first_seen_month"] = current_month
                pool.at[row_index, "first_seen_job_id"] = clean_text(posting.job_id)
            if current_month and (not last_seen_month or current_month >= last_seen_month):
                pool.at[row_index, "last_seen_month"] = current_month
                pool.at[row_index, "last_seen_job_id"] = clean_text(posting.job_id)

        pool = pool[SKILL_POOL_COLUMNS].sort_values(["normalized_skill"]).reset_index(drop=True)
        if write:
            self.write_pool(pool)
        return pool

    def write_pool(self, pool: pd.DataFrame) -> None:
        self.skill_pool_path.parent.mkdir(parents=True, exist_ok=True)
        pool.to_csv(self.skill_pool_path, index=False, encoding="utf-8-sig")


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def _join_unique(existing: Iterable[object], new_values: Iterable[object]) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *new_values]:
        text = clean_text(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
    return "; ".join(values)


def _int_value(value: object) -> int:
    try:
        return int(float(clean_text(value) or "0"))
    except ValueError:
        return 0
