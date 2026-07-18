from __future__ import annotations

from pathlib import Path

from job_update.output_runs import derive_run_id_from_path, resolve_run_output_dir
from job_update.work_modes import create_manual_workspace, resolve_manual_inputs


def test_derive_run_id_from_data_stream_path() -> None:
    path = Path("system") / "outputs" / "runs" / "run_001" / "event.csv"

    assert derive_run_id_from_path(path) == "run_001"


def test_resolve_run_output_dir_uses_matching_run_id() -> None:
    output_dir, run_id = resolve_run_output_dir(
        explicit_output_dir=None,
        run_id=None,
        source_paths=[Path("system") / "outputs" / "runs" / "run_001" / "event.csv"],
        run_group="analysis_runs",
    )

    assert run_id == "run_001"
    assert output_dir.parts[-3:] == ("outputs", "analysis_runs", "run_001")


def test_resolve_run_output_dir_preserves_explicit_dir() -> None:
    output_dir, run_id = resolve_run_output_dir(
        explicit_output_dir=Path("custom"),
        run_id="run_002",
        source_paths=[],
        run_group="analysis_runs",
    )

    assert output_dir == Path("custom")
    assert run_id == "run_002"


def test_create_manual_workspace_and_resolve_inputs(tmp_path) -> None:
    workspace = tmp_path / "manual_inputs"
    create_manual_workspace(workspace)
    (workspace / "event_stream" / "events.csv").write_text(
        "job_id,month,standard_job,skills\n",
        encoding="utf-8",
    )
    (workspace / "title_dictionary" / "titles.csv").write_text(
        "standard_job_title,standard_category\n",
        encoding="utf-8",
    )

    inputs = resolve_manual_inputs(workspace)

    assert inputs.event_stream.name == "events.csv"
    assert inputs.title_dictionary.name == "titles.csv"
    assert inputs.manual_run_id.startswith("manual_")
    assert inputs.output_dir.parts[-2] == "manual_runs"
