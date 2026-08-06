from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from company_job_update.core.database import SQLiteJobUpdateStore
from company_job_update.core.models import ProcessResult
from shared.text_utils import clean_text

from .frequency_store import GOVERNMENT_EVENT_COLUMNS


GOVERNMENT_METADATA_COLUMNS = [
    "source_name",
    "publish_time",
    "recruitment_year",
    "source_url",
    "government_agency",
    "government_department",
    "location",
    "event_time_type",
    "source_time_granularity",
]


class GovernmentSQLiteStore(SQLiteJobUpdateStore):
    """Government-owned SQLite state with provenance retained beside shared tables."""

    def migrate(self) -> None:
        super().migrate()
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS government_posting_metadata (
                    job_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL DEFAULT '',
                    publish_time TEXT NOT NULL DEFAULT '',
                    recruitment_year TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    government_agency TEXT NOT NULL DEFAULT '',
                    government_department TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    event_time_type TEXT NOT NULL DEFAULT 'published',
                    source_time_granularity TEXT NOT NULL DEFAULT 'annual_recruitment_cycle'
                )
                """
            )
            conn.commit()

    def initialize_from_csv(self, **paths: Path) -> dict[str, int]:
        counts = super().initialize_from_csv(**paths)
        event_stream_path = Path(paths["event_stream_path"])
        events = pd.read_csv(event_stream_path, dtype=str, encoding="utf-8-sig").fillna("")
        self.migrate()
        with self._connect() as conn:
            conn.execute("DELETE FROM government_posting_metadata")
            for _, row in events.iterrows():
                self._upsert_metadata(conn, clean_text(row.get("job_id")), row)
                conn.execute(
                    """
                    UPDATE job_postings
                    SET source = ?, cleaned_job_title = ?
                    WHERE job_id = ?
                    """,
                    (
                        clean_text(row.get("source")) or "government",
                        clean_text(row.get("cleaned_job_title")),
                        clean_text(row.get("job_id")),
                    ),
                )
            conn.commit()
        counts["government_posting_metadata"] = len(events)
        return counts

    def sync_after_process(self, *, result: ProcessResult, **tables: Any) -> None:
        super().sync_after_process(result=result, **tables)
        self.migrate()
        with self._connect() as conn:
            self._upsert_metadata(conn, result.posting.job_id, result.posting.metadata)
            conn.commit()

    def export_to_csv(self, **paths: Path) -> dict[str, int]:
        counts = super().export_to_csv(**paths)
        event_stream_path = Path(paths["event_stream_path"])
        self.migrate()
        with self._connect() as conn:
            events = pd.read_sql_query(
                """
                SELECT p.job_id, p.month, p.standard_job, p.raw_job_title AS job_title,
                       p.job_responsibility, p.job_requirement, p.skills, p.source,
                       m.source_name, m.publish_time, m.recruitment_year, m.source_url,
                       m.government_agency, m.government_department, m.location,
                       p.cleaned_job_title, COALESCE(r.route_status, 'existing_job') AS route_status,
                       COALESCE(m.event_time_type, 'published') AS event_time_type,
                       COALESCE(m.source_time_granularity, 'annual_recruitment_cycle') AS source_time_granularity
                FROM job_postings AS p
                LEFT JOIN government_posting_metadata AS m ON m.job_id = p.job_id
                LEFT JOIN job_routes AS r ON r.job_id = p.job_id
                WHERE p.is_existing_event = 1
                ORDER BY p.row_order, p.job_id
                """,
                conn,
            )
        for column in GOVERNMENT_EVENT_COLUMNS:
            if column not in events.columns:
                events[column] = ""
        events[GOVERNMENT_EVENT_COLUMNS].to_csv(event_stream_path, index=False, encoding="utf-8-sig")
        counts["government_posting_metadata"] = len(events)
        return counts

    @staticmethod
    def _upsert_metadata(conn: Any, job_id: str, values: Any) -> None:
        if not job_id:
            return
        row = [clean_text(values.get(column)) for column in GOVERNMENT_METADATA_COLUMNS]
        row[-2] = row[-2] or "published"
        row[-1] = row[-1] or "annual_recruitment_cycle"
        conn.execute(
            """
            INSERT INTO government_posting_metadata
            (job_id, source_name, publish_time, recruitment_year, source_url,
             government_agency, government_department, location,
             event_time_type, source_time_granularity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                source_name = excluded.source_name,
                publish_time = excluded.publish_time,
                recruitment_year = excluded.recruitment_year,
                source_url = excluded.source_url,
                government_agency = excluded.government_agency,
                government_department = excluded.government_department,
                location = excluded.location,
                event_time_type = excluded.event_time_type,
                source_time_granularity = excluded.source_time_granularity
            """,
            (job_id, *row),
        )
