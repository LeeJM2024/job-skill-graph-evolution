from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from .frequency_store import FREQUENCY_COLUMNS
from .job_profile import JOB_PROFILE_DIFF_COLUMNS, JOB_PROFILE_SNAPSHOT_COLUMNS
from .models import JobPosting, JobRoute, NormalizedSkill, ProcessResult
from .skill_lifecycle import LIFECYCLE_COLUMNS
from .skill_migration import SKILL_JOB_MONTHLY_SPREAD_COLUMNS, SKILL_MIGRATION_COLUMNS
from .skill_pool_store import SKILL_POOL_COLUMNS
from .text import clean_text


STANDARD_JOB_COLUMNS = ["standard_job_title", "standard_category", "match_keywords"]
EVENT_EXPORT_COLUMNS = [
    "job_id",
    "month",
    "standard_job",
    "job_title",
    "job_responsibility",
    "job_requirement",
    "skills",
]


@dataclass(slots=True)
class SQLiteJobUpdateStore:
    database_path: Path

    def initialize_from_csv(
        self,
        *,
        title_dictionary_path: Path,
        event_stream_path: Path,
        frequency_path: Path,
        skill_pool_path: Path,
        lifecycle_path: Path,
        migration_path: Path,
        spread_path: Path,
        profile_snapshot_path: Path | None = None,
        profile_diff_path: Path | None = None,
    ) -> dict[str, int]:
        self.migrate()
        standard_jobs = _read_csv(title_dictionary_path, STANDARD_JOB_COLUMNS)
        events = _read_csv(event_stream_path, EVENT_EXPORT_COLUMNS)
        frequency = _read_csv(frequency_path, FREQUENCY_COLUMNS)
        skill_pool = _read_csv(skill_pool_path, SKILL_POOL_COLUMNS)
        lifecycle = _read_csv(lifecycle_path, LIFECYCLE_COLUMNS)
        migration = _read_csv(migration_path, SKILL_MIGRATION_COLUMNS)
        spread = _read_csv(spread_path, SKILL_JOB_MONTHLY_SPREAD_COLUMNS)
        profile_snapshots = _read_optional_csv(profile_snapshot_path, JOB_PROFILE_SNAPSHOT_COLUMNS)
        profile_diffs = _read_optional_csv(profile_diff_path, JOB_PROFILE_DIFF_COLUMNS)

        with self._connect() as conn:
            self._replace_standard_jobs(conn, standard_jobs)
            self._replace_existing_job_postings(conn, events)
            self._replace_dataframe(conn, "job_skill_monthly_frequency", frequency, FREQUENCY_COLUMNS)
            self._replace_dataframe(conn, "skill_pool", skill_pool, SKILL_POOL_COLUMNS)
            self._replace_dataframe(conn, "skill_lifecycle", lifecycle, LIFECYCLE_COLUMNS)
            self._replace_dataframe(conn, "skill_migration", migration, SKILL_MIGRATION_COLUMNS)
            self._replace_dataframe(conn, "skill_job_monthly_spread", spread, SKILL_JOB_MONTHLY_SPREAD_COLUMNS)
            self._replace_dataframe(conn, "job_profile_snapshots", profile_snapshots, JOB_PROFILE_SNAPSHOT_COLUMNS)
            self._replace_dataframe(conn, "job_profile_diff", profile_diffs, JOB_PROFILE_DIFF_COLUMNS)
            conn.execute("DELETE FROM job_routes")
            conn.execute("DELETE FROM skill_mentions")
            conn.commit()
        return {
            "standard_jobs": len(standard_jobs),
            "job_postings": len(events),
            "job_skill_monthly_frequency": len(frequency),
            "skill_pool": len(skill_pool),
            "skill_lifecycle": len(lifecycle),
            "skill_migration": len(migration),
            "skill_job_monthly_spread": len(spread),
            "job_profile_snapshots": len(profile_snapshots),
            "job_profile_diff": len(profile_diffs),
        }

    def export_to_csv(
        self,
        *,
        title_dictionary_path: Path,
        event_stream_path: Path,
        frequency_path: Path,
        skill_pool_path: Path,
        lifecycle_path: Path,
        migration_path: Path,
        spread_path: Path,
        profile_snapshot_path: Path | None = None,
        profile_diff_path: Path | None = None,
    ) -> dict[str, int]:
        self.migrate()
        title_dictionary_path.parent.mkdir(parents=True, exist_ok=True)
        event_stream_path.parent.mkdir(parents=True, exist_ok=True)
        frequency_path.parent.mkdir(parents=True, exist_ok=True)
        skill_pool_path.parent.mkdir(parents=True, exist_ok=True)
        lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
        migration_path.parent.mkdir(parents=True, exist_ok=True)
        spread_path.parent.mkdir(parents=True, exist_ok=True)
        if profile_snapshot_path is not None:
            profile_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        if profile_diff_path is not None:
            profile_diff_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            standard_jobs = pd.read_sql_query(
                """
                SELECT standard_job_title, standard_category, match_keywords
                FROM standard_jobs
                ORDER BY row_order, standard_job_title
                """,
                conn,
            )
            events = pd.read_sql_query(
                """
                SELECT
                    job_id,
                    month,
                    standard_job,
                    raw_job_title AS job_title,
                    job_responsibility,
                    job_requirement,
                    skills
                FROM job_postings
                WHERE is_existing_event = 1
                ORDER BY row_order, job_id
                """,
                conn,
            )
            frequency = pd.read_sql_query(
                """
                SELECT month, standard_job, skill, monthly_jd_count, monthly_skill_count,
                       monthly_skill_frequency, cumulative_jd_count, cumulative_skill_count,
                       cumulative_skill_frequency
                FROM job_skill_monthly_frequency
                ORDER BY standard_job, skill, month
                """,
                conn,
            )
            skill_pool = pd.read_sql_query(
                f"SELECT {', '.join(SKILL_POOL_COLUMNS)} FROM skill_pool ORDER BY normalized_skill",
                conn,
            )
            lifecycle = pd.read_sql_query(
                f"SELECT {', '.join(LIFECYCLE_COLUMNS)} FROM skill_lifecycle ORDER BY standard_job, skill",
                conn,
            )
            migration = pd.read_sql_query(
                f"SELECT {', '.join(SKILL_MIGRATION_COLUMNS)} FROM skill_migration ORDER BY skill",
                conn,
            )
            spread = pd.read_sql_query(
                f"""
                SELECT {', '.join(SKILL_JOB_MONTHLY_SPREAD_COLUMNS)}
                FROM skill_job_monthly_spread
                ORDER BY skill, standard_job, month
                """,
                conn,
            )
            profile_snapshots = pd.read_sql_query(
                f"""
                SELECT {', '.join(JOB_PROFILE_SNAPSHOT_COLUMNS)}
                FROM job_profile_snapshots
                ORDER BY standard_job, month, skill
                """,
                conn,
            )
            profile_diffs = pd.read_sql_query(
                f"""
                SELECT {', '.join(JOB_PROFILE_DIFF_COLUMNS)}
                FROM job_profile_diff
                ORDER BY standard_job, from_month, to_month, change_type, skill
                """,
                conn,
            )

        standard_jobs.to_csv(title_dictionary_path, index=False, encoding="utf-8-sig")
        events.to_csv(event_stream_path, index=False, encoding="utf-8-sig")
        frequency.to_csv(frequency_path, index=False, encoding="utf-8-sig")
        skill_pool.to_csv(skill_pool_path, index=False, encoding="utf-8-sig")
        lifecycle.to_csv(lifecycle_path, index=False, encoding="utf-8-sig")
        migration.to_csv(migration_path, index=False, encoding="utf-8-sig")
        spread.to_csv(spread_path, index=False, encoding="utf-8-sig")
        if profile_snapshot_path is not None:
            profile_snapshots.to_csv(profile_snapshot_path, index=False, encoding="utf-8-sig")
        if profile_diff_path is not None:
            profile_diffs.to_csv(profile_diff_path, index=False, encoding="utf-8-sig")
        return {
            "standard_jobs": len(standard_jobs),
            "job_postings": len(events),
            "job_skill_monthly_frequency": len(frequency),
            "skill_pool": len(skill_pool),
            "skill_lifecycle": len(lifecycle),
            "skill_migration": len(migration),
            "skill_job_monthly_spread": len(spread),
            "job_profile_snapshots": len(profile_snapshots),
            "job_profile_diff": len(profile_diffs),
        }

    def sync_after_process(
        self,
        *,
        result: ProcessResult,
        frequency: pd.DataFrame | None = None,
        skill_pool: pd.DataFrame | None = None,
        lifecycle: pd.DataFrame | None = None,
        migration: pd.DataFrame | None = None,
        spread: pd.DataFrame | None = None,
        profile_snapshots: pd.DataFrame | None = None,
        profile_diffs: pd.DataFrame | None = None,
    ) -> None:
        self.migrate()
        with self._connect() as conn:
            self._upsert_processed_posting(conn, result)
            self._insert_route(conn, result.route, result.posting)
            if result.update is not None:
                self._replace_skill_mentions(conn, result.posting.job_id, result.update.normalized_skills)
            if frequency is not None:
                self._replace_dataframe(conn, "job_skill_monthly_frequency", frequency, FREQUENCY_COLUMNS)
            if skill_pool is not None:
                self._replace_dataframe(conn, "skill_pool", skill_pool, SKILL_POOL_COLUMNS)
            if lifecycle is not None:
                self._replace_dataframe(conn, "skill_lifecycle", lifecycle, LIFECYCLE_COLUMNS)
            if migration is not None:
                self._replace_dataframe(conn, "skill_migration", migration, SKILL_MIGRATION_COLUMNS)
            if spread is not None:
                self._replace_dataframe(conn, "skill_job_monthly_spread", spread, SKILL_JOB_MONTHLY_SPREAD_COLUMNS)
            if profile_snapshots is not None:
                self._replace_dataframe(conn, "job_profile_snapshots", profile_snapshots, JOB_PROFILE_SNAPSHOT_COLUMNS)
            if profile_diffs is not None:
                self._replace_dataframe(conn, "job_profile_diff", profile_diffs, JOB_PROFILE_DIFF_COLUMNS)
            conn.commit()

    def upsert_standard_job(
        self,
        *,
        standard_job_title: str,
        standard_category: str,
        match_keywords: str,
    ) -> None:
        self.migrate()
        title = clean_text(standard_job_title)
        category = clean_text(standard_category)
        keywords = clean_text(match_keywords) or title
        if not title or not category:
            raise ValueError("standard_job_title and standard_category are required")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT row_order FROM standard_jobs WHERE standard_job_title = ?",
                (title,),
            ).fetchone()
            row_order = (
                int(existing["row_order"])
                if existing is not None
                else int(
                    conn.execute(
                        "SELECT COALESCE(MAX(row_order), -1) + 1 AS next_order FROM standard_jobs"
                    ).fetchone()["next_order"]
                )
            )
            conn.execute(
                """
                INSERT INTO standard_jobs
                (standard_job_title, standard_category, match_keywords, row_order, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(standard_job_title) DO UPDATE SET
                    standard_category = excluded.standard_category,
                    match_keywords = excluded.match_keywords,
                    updated_at = excluded.updated_at
                """,
                (title, category, keywords, row_order, _now()),
            )
            conn.commit()

    def migrate(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS standard_jobs (
                    standard_job_title TEXT PRIMARY KEY,
                    standard_category TEXT NOT NULL,
                    match_keywords TEXT NOT NULL DEFAULT '',
                    row_order INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_postings (
                    job_id TEXT PRIMARY KEY,
                    month TEXT NOT NULL,
                    standard_job TEXT NOT NULL DEFAULT '',
                    raw_job_title TEXT NOT NULL DEFAULT '',
                    cleaned_job_title TEXT NOT NULL DEFAULT '',
                    job_responsibility TEXT NOT NULL DEFAULT '',
                    job_requirement TEXT NOT NULL DEFAULT '',
                    skills TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    is_existing_event INTEGER NOT NULL DEFAULT 0,
                    row_order INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_routes (
                    route_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    route_status TEXT NOT NULL,
                    selected_standard_job TEXT NOT NULL DEFAULT '',
                    selected_category TEXT NOT NULL DEFAULT '',
                    best_category TEXT NOT NULL DEFAULT '',
                    best_category_score REAL NOT NULL DEFAULT 0,
                    best_job TEXT NOT NULL DEFAULT '',
                    best_job_score REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    route_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_mentions (
                    mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    normalized_skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL,
                    skill_type TEXT NOT NULL DEFAULT '',
                    confidence REAL,
                    evidence_field TEXT NOT NULL DEFAULT '',
                    evidence_sentence TEXT NOT NULL DEFAULT '',
                    span_text TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS job_skill_monthly_frequency (
                    month TEXT NOT NULL,
                    standard_job TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    monthly_jd_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    cumulative_jd_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (month, standard_job, skill)
                );

                CREATE TABLE IF NOT EXISTS skill_pool (
                    normalized_skill TEXT PRIMARY KEY,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    skill_type TEXT NOT NULL DEFAULT '',
                    standard_categories TEXT NOT NULL DEFAULT '',
                    standard_jobs TEXT NOT NULL DEFAULT '',
                    first_seen_month TEXT NOT NULL DEFAULT '',
                    last_seen_month TEXT NOT NULL DEFAULT '',
                    first_seen_job_id TEXT NOT NULL DEFAULT '',
                    last_seen_job_id TEXT NOT NULL DEFAULT '',
                    mention_count INTEGER NOT NULL DEFAULT 0,
                    source_job_ids TEXT NOT NULL DEFAULT '',
                    source_count INTEGER NOT NULL DEFAULT 0,
                    sources TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS skill_lifecycle (
                    month TEXT NOT NULL,
                    standard_job TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    lifecycle_status TEXT NOT NULL DEFAULT '',
                    first_seen_month TEXT NOT NULL DEFAULT '',
                    last_seen_month TEXT NOT NULL DEFAULT '',
                    age_months INTEGER NOT NULL DEFAULT 0,
                    months_since_last_seen INTEGER NOT NULL DEFAULT 0,
                    current_monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    current_monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    recent_3m_skill_count INTEGER NOT NULL DEFAULT 0,
                    recent_6m_skill_count INTEGER NOT NULL DEFAULT 0,
                    recent_3m_active_months INTEGER NOT NULL DEFAULT 0,
                    recent_6m_active_months INTEGER NOT NULL DEFAULT 0,
                    prev_3m_skill_count INTEGER NOT NULL DEFAULT 0,
                    prev_6m_skill_count INTEGER NOT NULL DEFAULT 0,
                    mom_frequency_change REAL NOT NULL DEFAULT 0,
                    recent_3m_vs_prev_3m_change REAL NOT NULL DEFAULT 0,
                    recent_6m_frequency_stddev REAL NOT NULL DEFAULT 0,
                    covered_job_count INTEGER NOT NULL DEFAULT 0,
                    recent_3m_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    prev_3m_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    recent_3m_covered_job_count_change INTEGER NOT NULL DEFAULT 0,
                    lifecycle_reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (month, standard_job, skill)
                );

                CREATE TABLE IF NOT EXISTS skill_migration (
                    skill TEXT PRIMARY KEY,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    skill_type TEXT NOT NULL DEFAULT '',
                    first_seen_month TEXT NOT NULL DEFAULT '',
                    first_seen_standard_jobs TEXT NOT NULL DEFAULT '',
                    first_seen_job_count INTEGER NOT NULL DEFAULT 0,
                    is_left_censored INTEGER NOT NULL DEFAULT 0,
                    migration_confidence TEXT NOT NULL DEFAULT '',
                    migration_interpretation TEXT NOT NULL DEFAULT '',
                    latest_seen_month TEXT NOT NULL DEFAULT '',
                    latest_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    spread_job_count INTEGER NOT NULL DEFAULT 0,
                    spread_standard_jobs TEXT NOT NULL DEFAULT '',
                    all_standard_jobs TEXT NOT NULL DEFAULT '',
                    peak_monthly_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    peak_monthly_covered_job_month TEXT NOT NULL DEFAULT '',
                    total_skill_mentions INTEGER NOT NULL DEFAULT 0,
                    migration_path TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS skill_job_monthly_spread (
                    month TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    standard_job TEXT NOT NULL,
                    monthly_jd_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    cumulative_jd_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    job_first_seen_month TEXT NOT NULL DEFAULT '',
                    skill_first_seen_month TEXT NOT NULL DEFAULT '',
                    months_since_skill_first_seen INTEGER NOT NULL DEFAULT 0,
                    is_first_seen_job INTEGER NOT NULL DEFAULT 0,
                    is_new_job_for_skill INTEGER NOT NULL DEFAULT 0,
                    covered_job_count_this_month INTEGER NOT NULL DEFAULT 0,
                    cumulative_covered_job_count INTEGER NOT NULL DEFAULT 0,
                    monthly_frequency_change REAL NOT NULL DEFAULT 0,
                    cumulative_frequency_change REAL NOT NULL DEFAULT 0,
                    is_left_censored INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (month, skill, standard_job)
                );

                CREATE TABLE IF NOT EXISTS job_profile_snapshots (
                    month TEXT NOT NULL,
                    standard_job TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    monthly_jd_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    cumulative_jd_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    snapshot_skill_status TEXT NOT NULL DEFAULT '',
                    is_core_skill INTEGER NOT NULL DEFAULT 0,
                    rank_in_month TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (month, standard_job, skill)
                );

                CREATE TABLE IF NOT EXISTS job_profile_diff (
                    standard_job TEXT NOT NULL,
                    from_month TEXT NOT NULL,
                    to_month TEXT NOT NULL,
                    skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    change_type TEXT NOT NULL DEFAULT '',
                    from_monthly_jd_count INTEGER NOT NULL DEFAULT 0,
                    to_monthly_jd_count INTEGER NOT NULL DEFAULT 0,
                    from_monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    to_monthly_skill_count INTEGER NOT NULL DEFAULT 0,
                    from_monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    to_monthly_skill_frequency REAL NOT NULL DEFAULT 0,
                    frequency_delta REAL NOT NULL DEFAULT 0,
                    frequency_delta_ratio REAL NOT NULL DEFAULT 0,
                    from_cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    to_cumulative_skill_count INTEGER NOT NULL DEFAULT 0,
                    from_cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    to_cumulative_skill_frequency REAL NOT NULL DEFAULT 0,
                    is_stable_core INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (standard_job, from_month, to_month, skill, change_type)
                );
                """
            )
            _ensure_columns(conn, "skill_migration", SKILL_MIGRATION_COLUMNS)
            _ensure_columns(conn, "skill_job_monthly_spread", SKILL_JOB_MONTHLY_SPREAD_COLUMNS)
            _ensure_columns(conn, "job_profile_snapshots", JOB_PROFILE_SNAPSHOT_COLUMNS)
            _ensure_columns(conn, "job_profile_diff", JOB_PROFILE_DIFF_COLUMNS)
            _create_read_model_indexes(conn)
            _create_read_model_views(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _replace_standard_jobs(self, conn: sqlite3.Connection, frame: pd.DataFrame) -> None:
        conn.execute("DELETE FROM standard_jobs")
        now = _now()
        rows = [
            (
                clean_text(row["standard_job_title"]),
                clean_text(row["standard_category"]),
                clean_text(row.get("match_keywords")),
                index,
                now,
            )
            for index, row in frame.iterrows()
        ]
        conn.executemany(
            """
            INSERT INTO standard_jobs
            (standard_job_title, standard_category, match_keywords, row_order, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _replace_existing_job_postings(self, conn: sqlite3.Connection, frame: pd.DataFrame) -> None:
        conn.execute("DELETE FROM job_postings")
        now = _now()
        rows = [
            (
                clean_text(row["job_id"]),
                clean_text(row["month"]),
                clean_text(row["standard_job"]),
                clean_text(row.get("job_title")),
                "",
                clean_text(row.get("job_responsibility")),
                clean_text(row.get("job_requirement")),
                clean_text(row.get("skills")),
                "base_csv",
                1,
                index,
                now,
            )
            for index, row in frame.iterrows()
        ]
        conn.executemany(
            """
            INSERT INTO job_postings
            (job_id, month, standard_job, raw_job_title, cleaned_job_title,
             job_responsibility, job_requirement, skills, source, is_existing_event,
             row_order, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _replace_dataframe(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        frame: pd.DataFrame,
        columns: list[str],
    ) -> None:
        normalized = frame.copy().fillna("")
        for column in columns:
            if column not in normalized.columns:
                normalized[column] = ""
        normalized = normalized[columns]
        conn.execute(f"DELETE FROM {table_name}")
        if normalized.empty:
            return
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        rows = [tuple(row[column] for column in columns) for _, row in normalized.iterrows()]
        conn.executemany(
            f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
            rows,
        )

    def _upsert_processed_posting(self, conn: sqlite3.Connection, result: ProcessResult) -> None:
        posting = result.posting
        update = result.update
        now = _now()
        standard_job = update.standard_job if update is not None else ""
        skills = (
            "; ".join(skill.normalized_skill for skill in update.normalized_skills if skill.normalized_skill)
            if update is not None
            else ""
        )
        conn.execute(
            """
            INSERT INTO job_postings
            (job_id, month, standard_job, raw_job_title, cleaned_job_title,
             job_responsibility, job_requirement, skills, source, is_existing_event,
             row_order, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                month = excluded.month,
                standard_job = excluded.standard_job,
                raw_job_title = excluded.raw_job_title,
                cleaned_job_title = excluded.cleaned_job_title,
                job_responsibility = excluded.job_responsibility,
                job_requirement = excluded.job_requirement,
                skills = excluded.skills,
                source = excluded.source,
                is_existing_event = excluded.is_existing_event,
                updated_at = excluded.updated_at
            """,
            (
                clean_text(posting.job_id),
                clean_text(posting.month),
                clean_text(standard_job),
                clean_text(posting.job_title),
                clean_text(posting.routing_job_title),
                clean_text(posting.job_responsibility),
                clean_text(posting.job_requirement),
                skills,
                clean_text(posting.metadata.get("source")),
                1 if update is not None else 0,
                self._next_row_order(conn),
                now,
            ),
        )

    def _insert_route(self, conn: sqlite3.Connection, route: JobRoute, posting: JobPosting) -> None:
        best_category = route.best_category
        best_job = route.best_job
        conn.execute(
            """
            INSERT INTO job_routes
            (job_id, route_status, selected_standard_job, selected_category,
             best_category, best_category_score, best_job, best_job_score,
             reason, route_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_text(posting.job_id),
                clean_text(route.status),
                best_job.name if route.status == "existing_job" and best_job is not None else "",
                best_category.name if best_category is not None else "",
                best_category.name if best_category is not None else "",
                best_category.score if best_category is not None else 0.0,
                best_job.name if best_job is not None else "",
                best_job.score if best_job is not None else 0.0,
                clean_text(route.reason),
                json.dumps(serialize_route(route), ensure_ascii=False),
                _now(),
            ),
        )

    def _replace_skill_mentions(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        skills: list[NormalizedSkill],
    ) -> None:
        conn.execute("DELETE FROM skill_mentions WHERE job_id = ?", (clean_text(job_id),))
        now = _now()
        rows = [
            (
                clean_text(job_id),
                clean_text(skill.normalized_skill),
                clean_text(skill.kg_display_skill),
                clean_text(skill.skill_type),
                skill.confidence,
                "",
                "",
                "",
                json.dumps(skill.metadata, ensure_ascii=False),
                now,
            )
            for skill in skills
        ]
        conn.executemany(
            """
            INSERT INTO skill_mentions
            (job_id, normalized_skill, kg_display_skill, skill_type, confidence,
             evidence_field, evidence_sentence, span_text, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _next_row_order(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(row_order), -1) + 1 AS next_order FROM job_postings").fetchone()
        return int(row["next_order"])


def serialize_route(route: JobRoute) -> dict[str, Any]:
    return {
        "status": route.status,
        "reason": route.reason,
        "best_category": serialize_candidate(route.best_category),
        "best_job": serialize_candidate(route.best_job),
        "selected_categories": [serialize_candidate(candidate) for candidate in route.selected_categories],
        "selected_jobs": [serialize_candidate(candidate) for candidate in route.selected_jobs],
    }


def serialize_candidate(candidate: Any) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "name": candidate.name,
        "score": round(float(candidate.score), 6),
        "metadata": candidate.metadata,
    }


def _read_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for column in columns:
        if column not in frame.columns:
            frame[column] = ""
    return frame[columns]


def _read_optional_csv(path: Path | None, columns: list[str]) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=columns)
    return _read_csv(path, columns)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: list[str]) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column in columns:
        if column in existing:
            continue
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _create_read_model_views(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS job_skill_trend;
        DROP VIEW IF EXISTS emerging_skill_alerts;
        DROP VIEW IF EXISTS deprecated_skill_alerts;

        CREATE VIEW job_skill_trend AS
        SELECT
            l.month AS as_of_month,
            l.standard_job,
            l.skill,
            l.kg_display_skill,
            l.lifecycle_status,
            l.first_seen_month,
            l.last_seen_month,
            l.age_months,
            l.months_since_last_seen,
            l.current_monthly_skill_count,
            l.current_monthly_skill_frequency,
            l.cumulative_skill_count,
            l.cumulative_skill_frequency,
            l.recent_3m_skill_count,
            l.recent_6m_skill_count,
            l.recent_3m_active_months,
            l.recent_6m_active_months,
            l.mom_frequency_change,
            l.recent_3m_vs_prev_3m_change,
            l.covered_job_count,
            l.recent_3m_covered_job_count,
            l.recent_3m_covered_job_count_change,
            m.first_seen_standard_jobs AS migration_origin_jobs,
            m.spread_standard_jobs AS migration_spread_jobs,
            m.latest_covered_job_count AS migration_latest_covered_job_count,
            m.cumulative_covered_job_count AS migration_cumulative_covered_job_count,
            m.migration_path,
            m.total_skill_mentions,
            l.lifecycle_reason,
            l.updated_at
        FROM skill_lifecycle AS l
        LEFT JOIN skill_migration AS m
            ON lower(l.skill) = lower(m.skill);

        CREATE VIEW emerging_skill_alerts AS
        SELECT
            as_of_month,
            standard_job,
            skill,
            kg_display_skill,
            lifecycle_status AS alert_type,
            current_monthly_skill_count,
            current_monthly_skill_frequency,
            recent_3m_skill_count,
            recent_6m_skill_count,
            recent_3m_covered_job_count,
            recent_3m_covered_job_count_change,
            cumulative_skill_count,
            cumulative_skill_frequency,
            migration_origin_jobs,
            migration_path,
            lifecycle_reason,
            updated_at
        FROM job_skill_trend
        WHERE lifecycle_status = '新兴技能';

        CREATE VIEW deprecated_skill_alerts AS
        SELECT
            as_of_month,
            standard_job,
            skill,
            kg_display_skill,
            lifecycle_status AS alert_type,
            current_monthly_skill_count,
            current_monthly_skill_frequency,
            months_since_last_seen,
            recent_3m_skill_count,
            recent_6m_skill_count,
            cumulative_skill_count,
            cumulative_skill_frequency,
            migration_origin_jobs,
            migration_path,
            lifecycle_reason,
            updated_at
        FROM job_skill_trend
        WHERE lifecycle_status IN ('衰退技能', '废弃技能');
        """
    )


def _create_read_model_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_job_profile_snapshots_job_month
            ON job_profile_snapshots (standard_job, month);
        CREATE INDEX IF NOT EXISTS idx_job_profile_snapshots_skill
            ON job_profile_snapshots (skill);
        CREATE INDEX IF NOT EXISTS idx_job_profile_diff_job_month_pair
            ON job_profile_diff (standard_job, from_month, to_month);
        CREATE INDEX IF NOT EXISTS idx_job_profile_diff_change_type
            ON job_profile_diff (change_type);
        CREATE INDEX IF NOT EXISTS idx_skill_lifecycle_status
            ON skill_lifecycle (lifecycle_status);
        CREATE INDEX IF NOT EXISTS idx_skill_migration_skill
            ON skill_migration (skill);
        """
    )
