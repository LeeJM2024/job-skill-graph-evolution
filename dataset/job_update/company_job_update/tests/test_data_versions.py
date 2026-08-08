from __future__ import annotations

from pathlib import Path

from company_job_update.core.data_versions import resolve_company_data_paths


def test_company_versions_resolve_independent_databases() -> None:
    legacy = resolve_company_data_paths("company_base_v1")
    large = resolve_company_data_paths("company_large_v2")

    assert legacy.database.name == "job_update.db"
    assert large.database.name == "job_update.db"
    assert legacy.database != large.database
    assert legacy.event_stream.exists()
    assert large.event_stream.exists()
    assert Path(large.manifest).exists()
