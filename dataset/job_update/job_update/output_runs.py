from __future__ import annotations

from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def derive_run_id_from_path(path: str | Path) -> str | None:
    parts = Path(path).parts
    lowered = [part.lower() for part in parts]
    for index, part in enumerate(lowered[:-1]):
        if part == "runs":
            return parts[index + 1]
    return None


def resolve_run_output_dir(
    explicit_output_dir: str | Path | None,
    run_id: str | None,
    source_paths: list[str | Path],
    run_group: str,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _first_run_id(source_paths)
    if explicit_output_dir is not None:
        return Path(explicit_output_dir), resolved_run_id or ""
    if not resolved_run_id:
        resolved_run_id = _fallback_run_id()
    return PROJECT_ROOT / "outputs" / run_group / resolved_run_id, resolved_run_id


def write_current_run_marker(run_group: str, run_id: str) -> Path | None:
    if not run_id:
        return None
    output_dir = PROJECT_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    marker_name_by_group = {
        "analysis_runs": "current_analysis_run_id.txt",
        "comparison_runs": "current_comparison_run_id.txt",
    }
    marker_path = output_dir / marker_name_by_group.get(
        run_group,
        f"current_{run_group}_run_id.txt",
    )
    marker_path.write_text(run_id + "\n", encoding="utf-8")
    return marker_path


def _first_run_id(paths: list[str | Path]) -> str | None:
    for path in paths:
        run_id = derive_run_id_from_path(path)
        if run_id:
            return run_id
    return None


def _fallback_run_id() -> str:
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
