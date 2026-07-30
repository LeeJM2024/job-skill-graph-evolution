from __future__ import annotations

import sqlite3

import pandas as pd

from job_update.database import SQLiteJobUpdateStore
from job_update.frequency_store import FrequencyStore, rebuild_frequency_table
from job_update.job_profile import build_job_profile_tables
from job_update.job_profile_store import JobProfileStore
from job_update.models import JobPosting, SkillMention
from job_update.route_adjudication import RouteAdjudicationDecision
from job_update.service import JobUpdateSystem
from job_update.skill_lifecycle import build_skill_lifecycle_table
from job_update.skill_lifecycle_store import SkillLifecycleStore
from job_update.skill_migration import build_skill_migration_tables
from job_update.skill_migration_store import SkillMigrationStore
from job_update.skill_pool_store import SkillPoolStore
from job_update.taxonomy import JobTaxonomy, StandardJob


class FixedSimilarity:
    def score(self, query: str, candidates):
        return [0.86 if candidate == "AI App Engineer" else 0.80 for candidate in candidates]


class UnusedAdjudicator:
    def adjudicate(self, **kwargs):
        return RouteAdjudicationDecision(route_status="potential_new_job")


def test_sqlite_store_initializes_and_exports_base_csvs(tmp_path) -> None:
    title_dictionary = tmp_path / "standard_job_title_dictionary.csv"
    event_stream = tmp_path / "job_update_event_stream.csv"
    frequency_output = tmp_path / "job_skill_monthly_frequency.csv"
    skill_pool = tmp_path / "skill_pool.csv"
    skill_lifecycle = tmp_path / "skill_lifecycle.csv"
    skill_migration = tmp_path / "skill_migration.csv"
    skill_job_monthly_spread = tmp_path / "skill_job_monthly_spread.csv"
    profile_snapshots = tmp_path / "job_profile_snapshots.csv"
    profile_diff = tmp_path / "job_profile_diff.csv"
    database = tmp_path / "job_update.db"

    pd.DataFrame(
        [
            {
                "standard_job_title": "AI App Engineer",
                "standard_category": "AI",
                "match_keywords": "LLM",
            }
        ]
    ).to_csv(title_dictionary, index=False, encoding="utf-8-sig")
    events = pd.DataFrame(
        [
            {
                "job_id": "base_001",
                "month": "2026-07",
                "standard_job": "AI App Engineer",
                "job_title": "AI App Engineer",
                "job_responsibility": "Build apps",
                "job_requirement": "Know LLM",
                "skills": "LLM",
            }
        ]
    )
    events.to_csv(event_stream, index=False, encoding="utf-8-sig")
    frequency = rebuild_frequency_table(events)
    frequency.to_csv(frequency_output, index=False, encoding="utf-8-sig")
    skill_pool_frame = pd.DataFrame(
        [
            {
                "normalized_skill": "LLM",
                "kg_display_skill": "AI",
                "skill_type": "",
                "standard_categories": "AI",
                "standard_jobs": "AI App Engineer",
                "first_seen_month": "2026-07",
                "last_seen_month": "2026-07",
                "first_seen_job_id": "base_001",
                "last_seen_job_id": "base_001",
                "mention_count": "1",
                "source_job_ids": "base_001",
                "source_count": "1",
                "sources": "base_csv",
                "updated_at": "2026-07-26T00:00:00+00:00",
            }
        ]
    )
    skill_pool_frame.to_csv(skill_pool, index=False, encoding="utf-8-sig")
    build_skill_lifecycle_table(frequency, skill_pool_frame).to_csv(
        skill_lifecycle,
        index=False,
        encoding="utf-8-sig",
    )
    migration, spread = build_skill_migration_tables(frequency, skill_pool_frame)
    migration.to_csv(skill_migration, index=False, encoding="utf-8-sig")
    spread.to_csv(skill_job_monthly_spread, index=False, encoding="utf-8-sig")
    snapshots, diffs = build_job_profile_tables(frequency, skill_pool_frame)
    snapshots.to_csv(profile_snapshots, index=False, encoding="utf-8-sig")
    diffs.to_csv(profile_diff, index=False, encoding="utf-8-sig")

    counts = SQLiteJobUpdateStore(database).initialize_from_csv(
        title_dictionary_path=title_dictionary,
        event_stream_path=event_stream,
        frequency_path=frequency_output,
        skill_pool_path=skill_pool,
        lifecycle_path=skill_lifecycle,
        migration_path=skill_migration,
        spread_path=skill_job_monthly_spread,
        profile_snapshot_path=profile_snapshots,
        profile_diff_path=profile_diff,
    )

    assert counts["standard_jobs"] == 1
    assert counts["job_postings"] == 1
    assert counts["skill_lifecycle"] == 1
    assert counts["skill_migration"] == 1
    assert counts["skill_job_monthly_spread"] == 1
    assert counts["job_profile_snapshots"] == 1
    assert counts["job_profile_diff"] == 0

    export_dir = tmp_path / "export"
    exported = SQLiteJobUpdateStore(database).export_to_csv(
        title_dictionary_path=export_dir / "standard_job_title_dictionary.csv",
        event_stream_path=export_dir / "job_update_event_stream.csv",
        frequency_path=export_dir / "job_skill_monthly_frequency.csv",
        skill_pool_path=export_dir / "skill_pool.csv",
        lifecycle_path=export_dir / "skill_lifecycle.csv",
        migration_path=export_dir / "skill_migration.csv",
        spread_path=export_dir / "skill_job_monthly_spread.csv",
        profile_snapshot_path=export_dir / "job_profile_snapshots.csv",
        profile_diff_path=export_dir / "job_profile_diff.csv",
    )

    assert exported["job_postings"] == 1
    exported_events = pd.read_csv(export_dir / "job_update_event_stream.csv", dtype=str).fillna("")
    exported_lifecycle = pd.read_csv(export_dir / "skill_lifecycle.csv", dtype=str).fillna("")
    exported_migration = pd.read_csv(export_dir / "skill_migration.csv", dtype=str).fillna("")
    exported_snapshots = pd.read_csv(export_dir / "job_profile_snapshots.csv", dtype=str).fillna("")
    assert exported_events.iloc[0]["job_title"] == "AI App Engineer"
    assert exported_events.iloc[0]["skills"] == "LLM"
    assert exported_lifecycle.iloc[0]["skill"] == "LLM"
    assert exported_migration.iloc[0]["skill"] == "LLM"
    assert exported_snapshots.iloc[0]["skill"] == "LLM"

    with sqlite3.connect(database) as conn:
        view_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view'"
            ).fetchall()
        }
        trend_count = conn.execute("SELECT COUNT(*) FROM job_skill_trend").fetchone()[0]
        conn.execute("UPDATE skill_lifecycle SET lifecycle_status = '新兴技能'")
        emerging_count = conn.execute("SELECT COUNT(*) FROM emerging_skill_alerts").fetchone()[0]
        conn.execute("UPDATE skill_lifecycle SET lifecycle_status = '废弃技能'")
        deprecated_count = conn.execute("SELECT COUNT(*) FROM deprecated_skill_alerts").fetchone()[0]

    assert {"job_skill_trend", "emerging_skill_alerts", "deprecated_skill_alerts"} <= view_names
    assert trend_count == 1
    assert emerging_count == 1
    assert deprecated_count == 1


def test_process_writes_sqlite_database_when_enabled(tmp_path) -> None:
    database = tmp_path / "job_update.db"
    taxonomy = JobTaxonomy(
        [
            StandardJob("AI App Engineer", "AI", "LLM"),
            StandardJob("AI Agent Engineer", "AI", "Agent"),
        ]
    )
    system = JobUpdateSystem(
        taxonomy=taxonomy,
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        skill_pool_store=SkillPoolStore(tmp_path / "skill_pool.csv"),
        skill_lifecycle_store=SkillLifecycleStore(tmp_path / "skill_lifecycle.csv"),
        skill_migration_store=SkillMigrationStore(
            tmp_path / "skill_migration.csv",
            tmp_path / "skill_job_monthly_spread.csv",
        ),
        job_profile_store=JobProfileStore(
            tmp_path / "job_profile_snapshots.csv",
            tmp_path / "job_profile_diff.csv",
        ),
        database_store=SQLiteJobUpdateStore(database),
        similarity=FixedSimilarity(),
        route_adjudicator=UnusedAdjudicator(),
    )
    posting = JobPosting(
        job_id="job_001",
        month="2026-07",
        job_title="AI App Engineer",
        job_responsibility="Build apps",
        job_requirement="Know LLM",
        skills=[SkillMention(normalized_skill="LLM", kg_display_skill="AI")],
        metadata={"source": "test"},
    )

    result = system.process(posting, write=True)

    assert result.update is not None
    with sqlite3.connect(database) as conn:
        posting_count = conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
        route_count = conn.execute("SELECT COUNT(*) FROM job_routes").fetchone()[0]
        skill_count = conn.execute("SELECT COUNT(*) FROM skill_mentions").fetchone()[0]
        frequency_count = conn.execute("SELECT COUNT(*) FROM job_skill_monthly_frequency").fetchone()[0]
        pool_count = conn.execute("SELECT COUNT(*) FROM skill_pool").fetchone()[0]
        lifecycle_count = conn.execute("SELECT COUNT(*) FROM skill_lifecycle").fetchone()[0]
        migration_count = conn.execute("SELECT COUNT(*) FROM skill_migration").fetchone()[0]
        spread_count = conn.execute("SELECT COUNT(*) FROM skill_job_monthly_spread").fetchone()[0]
        profile_snapshot_count = conn.execute("SELECT COUNT(*) FROM job_profile_snapshots").fetchone()[0]
        profile_diff_count = conn.execute("SELECT COUNT(*) FROM job_profile_diff").fetchone()[0]
        trend_count = conn.execute("SELECT COUNT(*) FROM job_skill_trend").fetchone()[0]

    assert posting_count == 1
    assert route_count == 1
    assert skill_count == 1
    assert frequency_count == 1
    assert pool_count == 1
    assert lifecycle_count == 1
    assert migration_count == 1
    assert spread_count == 1
    assert profile_snapshot_count == 1
    assert profile_diff_count == 0
    assert trend_count == 1


def test_upsert_standard_job_preserves_route_and_skill_history(tmp_path) -> None:
    database = tmp_path / "job_update.db"
    store = SQLiteJobUpdateStore(database)
    store.migrate()

    result = JobUpdateSystem(
        taxonomy=JobTaxonomy([StandardJob("AI App Engineer", "AI", "LLM")]),
        frequency_store=FrequencyStore(tmp_path / "events.csv", tmp_path / "frequency.csv"),
        skill_pool_store=SkillPoolStore(tmp_path / "skill_pool.csv"),
        skill_lifecycle_store=SkillLifecycleStore(tmp_path / "skill_lifecycle.csv"),
        database_store=store,
        similarity=FixedSimilarity(),
        route_adjudicator=UnusedAdjudicator(),
    ).process(
        JobPosting(
            job_id="job_001",
            month="2026-07",
            job_title="AI App Engineer",
            skills=[SkillMention(normalized_skill="LLM", kg_display_skill="AI")],
            metadata={"source": "test"},
        ),
        write=True,
    )

    assert result.update is not None
    store.upsert_standard_job(
        standard_job_title="AI Agent Engineer",
        standard_category="AI",
        match_keywords="Agent",
    )

    with sqlite3.connect(database) as conn:
        standard_job_count = conn.execute("SELECT COUNT(*) FROM standard_jobs").fetchone()[0]
        route_count = conn.execute("SELECT COUNT(*) FROM job_routes").fetchone()[0]
        skill_count = conn.execute("SELECT COUNT(*) FROM skill_mentions").fetchone()[0]

    assert standard_job_count == 1
    assert route_count == 1
    assert skill_count == 1
