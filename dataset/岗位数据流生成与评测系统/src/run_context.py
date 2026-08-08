"""Run directory management for generated outputs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def outputs_dir(project_root: Path) -> Path:
    return project_root / "outputs"


def runs_dir(project_root: Path) -> Path:
    return outputs_dir(project_root) / "runs"


def current_run_file(project_root: Path) -> Path:
    return outputs_dir(project_root) / "current_run_id.txt"


def make_run_id(seed: int | str | None) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    seed_part = f"_seed_{seed}" if seed is not None else ""
    return f"run_{timestamp}{seed_part}"


def start_new_run(project_root: Path, config: dict) -> Path:
    """Create a new run folder and mark it as the current run."""
    base_outputs = outputs_dir(project_root)
    base_runs = runs_dir(project_root)
    base_outputs.mkdir(parents=True, exist_ok=True)
    base_runs.mkdir(parents=True, exist_ok=True)

    requested_run_id = os.environ.get("JOB_STREAM_RUN_ID") or make_run_id(
        config.get("seed")
    )
    run_id = requested_run_id
    run_path = base_runs / run_id
    suffix = 2
    while run_path.exists() and not os.environ.get("JOB_STREAM_RUN_ID"):
        run_id = f"{requested_run_id}_{suffix:02d}"
        run_path = base_runs / run_id
        suffix += 1

    run_path.mkdir(parents=True, exist_ok=True)
    current_run_file(project_root).write_text(run_id + "\n", encoding="utf-8")

    metadata = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "seed": config.get("seed"),
        "month_start": config.get("month_start"),
        "month_end": config.get("month_end"),
    }
    with (run_path / "run_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return run_path


def get_current_run_dir(project_root: Path) -> Path:
    """Return the active run folder created by step 1."""
    env_run_id = os.environ.get("JOB_STREAM_RUN_ID")
    if env_run_id:
        run_path = runs_dir(project_root) / env_run_id
        if not run_path.exists():
            raise FileNotFoundError(
                f"Run folder does not exist: {run_path}. Run step 1 first."
            )
        return run_path

    marker = current_run_file(project_root)
    if not marker.exists():
        raise FileNotFoundError(
            "No current run found. Run `python src\\profile_inputs.py` first."
        )
    run_id = marker.read_text(encoding="utf-8").strip()
    if not run_id:
        raise ValueError("Current run marker is empty. Run step 1 again.")
    run_path = runs_dir(project_root) / run_id
    if not run_path.exists():
        raise FileNotFoundError(
            f"Current run folder does not exist: {run_path}. Run step 1 again."
        )
    return run_path


def relative_to_project(project_root: Path, path: Path) -> str:
    return str(path.relative_to(project_root)).replace("\\", "/")

