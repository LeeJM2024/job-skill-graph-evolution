from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .output_runs import PROJECT_ROOT


EVENT_STREAM_FILE = "job_update_event_stream_generated.csv"
SKILL_UNIVERSE_FILE = "skill_trend_design.csv"
JOB_DEMAND_ANSWER_FILE = "job_demand_monthly_answer.csv"
SKILL_FREQUENCY_ANSWER_FILE = "job_skill_monthly_frequency_answer.csv"
TITLE_DICTIONARY_FILE = "standard_job_title_dictionary.csv"


@dataclass(frozen=True, slots=True)
class DataStreamInputs:
    run_dir: Path
    run_id: str
    event_stream: Path
    title_dictionary: Path
    skill_universe: Path
    expected_job_demand: Path | None
    expected_skill_frequency: Path | None


@dataclass(frozen=True, slots=True)
class ManualInputs:
    workspace: Path
    manual_run_id: str
    event_stream: Path
    title_dictionary: Path
    skill_universe: Path | None
    expected_job_demand: Path | None
    expected_skill_frequency: Path | None
    output_dir: Path


def resolve_data_stream_inputs(
    run_dir: str | Path,
    title_dictionary: str | Path | None = None,
) -> DataStreamInputs:
    resolved_run_dir = Path(run_dir)
    run_id = resolved_run_dir.name
    event_stream = _required_file(resolved_run_dir / EVENT_STREAM_FILE)
    skill_universe = _required_file(resolved_run_dir / SKILL_UNIVERSE_FILE)
    if title_dictionary is None:
        title_dictionary_path = _infer_title_dictionary_from_run_dir(resolved_run_dir)
    else:
        title_dictionary_path = Path(title_dictionary)
    title_dictionary_path = _required_file(title_dictionary_path)

    expected_job_demand = _optional_file(resolved_run_dir / JOB_DEMAND_ANSWER_FILE)
    expected_skill_frequency = _optional_file(
        resolved_run_dir / SKILL_FREQUENCY_ANSWER_FILE
    )
    return DataStreamInputs(
        run_dir=resolved_run_dir,
        run_id=run_id,
        event_stream=event_stream,
        title_dictionary=title_dictionary_path,
        skill_universe=skill_universe,
        expected_job_demand=expected_job_demand,
        expected_skill_frequency=expected_skill_frequency,
    )


def create_manual_workspace(workspace: str | Path) -> dict[str, str]:
    root = Path(workspace)
    directories = [
        root / "event_stream",
        root / "title_dictionary",
        root / "skill_universe",
        root / "answers" / "job_demand",
        root / "answers" / "skill_frequency",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "\n".join(
                [
                    "# Manual company job update workspace",
                    "",
                    "Place CSV files into these folders before running `run-manual`:",
                    "",
                    "- event_stream/: required event stream CSV",
                    "- title_dictionary/: required standard job title dictionary CSV",
                    "- skill_universe/: optional CSV with standard_job and skill columns",
                    "- answers/job_demand/: optional expected job demand answer CSV",
                    "- answers/skill_frequency/: optional expected skill frequency answer CSV",
                    "",
                    "Manual outputs are saved under company_job_update/outputs/manual_runs/manual_YYYYMMDD_HHMM.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return {directory.name: str(directory) for directory in directories}


def resolve_manual_inputs(workspace: str | Path) -> ManualInputs:
    root = Path(workspace)
    if not root.exists():
        raise FileNotFoundError(f"Manual workspace does not exist: {root}")
    manual_run_id = _manual_run_id()
    output_dir = _unique_output_dir(PROJECT_ROOT / "outputs" / "manual_runs", manual_run_id)
    return ManualInputs(
        workspace=root,
        manual_run_id=output_dir.name,
        event_stream=_single_csv(root / "event_stream", required=True),
        title_dictionary=_single_csv(root / "title_dictionary", required=True),
        skill_universe=_single_csv(root / "skill_universe", required=False),
        expected_job_demand=_single_csv(root / "answers" / "job_demand", required=False),
        expected_skill_frequency=_single_csv(
            root / "answers" / "skill_frequency",
            required=False,
        ),
        output_dir=output_dir,
    )


def write_manifest(output_dir: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(output_dir) / "run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def _infer_title_dictionary_from_run_dir(run_dir: Path) -> Path:
    data_root = None
    parts = [part.lower() for part in run_dir.parts]
    for index, part in enumerate(parts):
        if part == "outputs" and index + 2 < len(parts) and parts[index + 1] == "runs":
            data_root = Path(*run_dir.parts[:index])
            break
    if data_root is None:
        raise ValueError(
            "Cannot infer title dictionary. Pass --title-dictionary explicitly."
        )
    return data_root / "data" / "input" / TITLE_DICTIONARY_FILE


def _required_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _optional_file(path: Path) -> Path | None:
    return path if path.exists() else None


def _single_csv(directory: Path, required: bool) -> Path | None:
    if not directory.exists():
        if required:
            raise FileNotFoundError(f"Missing manual input folder: {directory}")
        return None
    files = sorted(path for path in directory.glob("*.csv") if path.is_file())
    if not files:
        if required:
            raise FileNotFoundError(f"No CSV file found in {directory}")
        return None
    if len(files) > 1:
        raise ValueError(f"Expected one CSV file in {directory}, found {len(files)}")
    return files[0]


def _manual_run_id() -> str:
    return f"manual_{datetime.now().strftime('%Y%m%d_%H%M')}"


def _unique_output_dir(base_dir: Path, run_id: str) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / run_id
    suffix = 2
    while path.exists():
        path = base_dir / f"{run_id}_{suffix:02d}"
        suffix += 1
    return path
