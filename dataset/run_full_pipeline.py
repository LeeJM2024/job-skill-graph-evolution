from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_MONTH_START = "2024-12"
DEFAULT_MONTH_END = "2026-07"
DEFAULT_PASS_THRESHOLD = 0.9


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run data-stream generation, job-update analysis, and validation.",
    )
    parser.add_argument("--data-stream-root", type=Path, default=None)
    parser.add_argument("--job-update-root", type=Path, default=None)
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument("--month-start", default=DEFAULT_MONTH_START)
    parser.add_argument("--month-end", default=DEFAULT_MONTH_END)
    parser.add_argument("--pass-threshold", type=float, default=DEFAULT_PASS_THRESHOLD)
    args = parser.parse_args()

    configure_encoding()
    script_root = Path(__file__).resolve().parent

    try:
        data_stream_root = resolve_data_stream_root(script_root, args.data_stream_root)
        job_update_root = resolve_job_update_root(script_root, args.job_update_root)
        validate_root(data_stream_root, "data stream system")
        validate_root(job_update_root, "job_update system")

        print("Starting full pipeline")
        print(f"DataStreamRoot: {data_stream_root}")
        print(f"JobUpdateRoot:   {job_update_root}")
        print(f"Month range:     {args.month_start} to {args.month_end}")
        print(f"Pass threshold:  {args.pass_threshold}")

        env = build_child_env()
        run_step(
            "Step 1/6 profile inputs",
            data_stream_root,
            [args.python_exe, "src/profile_inputs.py"],
            env,
        )
        run_step(
            "Step 2/6 generate job demand plan",
            data_stream_root,
            [args.python_exe, "src/generate_job_demand_plan.py"],
            env,
        )
        run_step(
            "Step 3/6 generate skill trend plan",
            data_stream_root,
            [args.python_exe, "src/generate_skill_trend_plan.py"],
            env,
        )
        run_step(
            "Step 4/6 generate event stream",
            data_stream_root,
            [args.python_exe, "src/generate_event_stream.py"],
            env,
        )
        run_step(
            "Step 5/6 build answer tables",
            data_stream_root,
            [args.python_exe, "src/build_answer_tables.py"],
            env,
        )

        run_id = read_current_run_id(data_stream_root)
        run_dir = data_stream_root / "outputs" / "runs" / run_id
        if not run_dir.exists():
            raise RuntimeError(f"Generated run folder does not exist: {run_dir}")

        run_step(
            "Step 6/6 analyze and compare with job_update",
            job_update_root,
            [
                args.python_exe,
                "-m",
                "job_update.cli",
                "run-data-stream",
                "--run-dir",
                str(run_dir),
                "--month-start",
                args.month_start,
                "--month-end",
                args.month_end,
                "--pass-threshold",
                str(args.pass_threshold),
            ],
            env,
        )

        comparison_report = (
            job_update_root
            / "outputs"
            / "comparison_runs"
            / run_id
            / "comparison_report.json"
        )
        if not comparison_report.exists():
            raise RuntimeError(f"Missing comparison report: {comparison_report}")

        report = json.loads(comparison_report.read_text(encoding="utf-8"))
        print_result(run_id, comparison_report, report)

        if report.get("passed") is True:
            print("SUCCESS: full pipeline completed and validation passed.")
            return 0

        print("FAILED: full pipeline completed but validation did not pass.")
        return 2
    except Exception as exc:
        print()
        print(f"FAILED: {exc}")
        return 1


def configure_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def build_child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def resolve_data_stream_root(script_root: Path, explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root.resolve()

    candidates = [
        path
        for path in script_root.iterdir()
        if path.is_dir()
        and (path / "config" / "generation_config.json").exists()
        and (path / "src" / "profile_inputs.py").exists()
        and (path / "src" / "build_answer_tables.py").exists()
    ]
    if not candidates:
        raise RuntimeError(
            "Could not auto-detect data stream system folder. "
            "Pass --data-stream-root explicitly."
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "Multiple data stream candidates found. "
            "Pass --data-stream-root explicitly."
        )
    return candidates[0].resolve()


def resolve_job_update_root(script_root: Path, explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root.resolve()

    candidate = script_root / "job_update"
    if not (candidate / "job_update" / "cli.py").exists():
        raise RuntimeError(
            "Could not auto-detect job_update folder. "
            "Pass --job-update-root explicitly."
        )
    return candidate.resolve()


def validate_root(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} folder does not exist: {path}")


def run_step(name: str, cwd: Path, command: list[str], env: dict[str, str]) -> None:
    print()
    print(f"==> {name}")
    completed = subprocess.run(command, cwd=cwd, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {completed.returncode}")


def read_current_run_id(data_stream_root: Path) -> str:
    current_run_file = data_stream_root / "outputs" / "current_run_id.txt"
    if not current_run_file.exists():
        raise RuntimeError(f"Missing current run marker: {current_run_file}")
    run_id = current_run_file.read_text(encoding="utf-8").strip()
    if not run_id:
        raise RuntimeError(f"Current run id is empty: {current_run_file}")
    return run_id


def print_result(run_id: str, comparison_report: Path, report: dict[str, object]) -> None:
    print()
    print("Full pipeline result")
    print(f"RunId: {run_id}")
    print(f"ComparisonReport: {comparison_report}")
    print(f"passed: {report.get('passed')}")
    print(f"pass_threshold: {report.get('pass_threshold')}")
    print(f"job_demand_match_rate: {report.get('job_demand_match_rate')}")
    print(f"skill_frequency_match_rate: {report.get('skill_frequency_match_rate')}")
    print(f"job_demand_mismatch_count: {report.get('job_demand_mismatch_count')}")
    print(f"skill_frequency_mismatch_count: {report.get('skill_frequency_mismatch_count')}")


if __name__ == "__main__":
    raise SystemExit(main())
