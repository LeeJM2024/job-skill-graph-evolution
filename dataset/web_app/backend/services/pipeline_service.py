from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

from .paths import DATA_STREAM_ROOT, JOB_UPDATE_ROOT, RUN_FULL_SCRIPT


def list_runs() -> list[dict[str, str]]:
    runs_root = DATA_STREAM_ROOT / "outputs" / "runs"
    if not runs_root.exists():
        return []
    rows: list[dict[str, str]] = []
    for path in sorted(runs_root.iterdir(), reverse=True):
        if path.is_dir() and path.name != ".gitkeep":
            rows.append({"run_id": path.name, "run_dir": str(path)})
    return rows


def run_full_pipeline(month_start: str, month_end: str, pass_threshold: float) -> dict[str, object]:
    command = [
        sys.executable,
        str(RUN_FULL_SCRIPT),
        "--month-start",
        month_start,
        "--month-end",
        month_end,
        "--pass-threshold",
        str(pass_threshold),
    ]
    completed = _run_command(command, cwd=RUN_FULL_SCRIPT.parent)
    run_id = _read_current_run_id()
    return _build_pipeline_payload(run_id, completed)


def run_existing(run_id: str, month_start: str, month_end: str, pass_threshold: float) -> dict[str, object]:
    run_dir = DATA_STREAM_ROOT / "outputs" / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    command = [
        sys.executable,
        "-m",
        "core.cli",
        "run-data-stream",
        "--run-dir",
        str(run_dir),
        "--month-start",
        month_start,
        "--month-end",
        month_end,
        "--pass-threshold",
        str(pass_threshold),
    ]
    completed = _run_command(command, cwd=JOB_UPDATE_ROOT)
    return _build_pipeline_payload(run_id, completed)


def read_pipeline_result(run_id: str) -> dict[str, object]:
    return _build_pipeline_payload(run_id, None)


def _run_command(command: list[str], cwd: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": " ".join(command),
    }


def _read_current_run_id() -> str:
    marker = DATA_STREAM_ROOT / "outputs" / "current_run_id.txt"
    if not marker.exists():
        return ""
    return marker.read_text(encoding="utf-8").strip()


def _build_pipeline_payload(run_id: str, completed: dict[str, object] | None) -> dict[str, object]:
    comparison_dir = JOB_UPDATE_ROOT / "outputs" / "comparison_runs" / run_id
    analysis_dir = JOB_UPDATE_ROOT / "outputs" / "analysis_runs" / run_id
    comparison_report_path = comparison_dir / "comparison_report.json"
    analysis_report_path = analysis_dir / "analysis_quality_report.json"

    report = _read_json(comparison_report_path)
    analysis_report = _read_json(analysis_report_path)
    charts = _build_charts(analysis_dir)
    diff_preview = {
        "job_demand": _read_csv_preview(comparison_dir / "job_demand_diff.csv"),
        "skill_frequency": _read_csv_preview(comparison_dir / "skill_frequency_diff.csv"),
    }

    return {
        "run_id": run_id,
        "completed": completed,
        "report": report,
        "analysis_report": analysis_report,
        "charts": charts,
        "diff_preview": diff_preview,
        "paths": {
            "analysis_dir": str(analysis_dir),
            "comparison_dir": str(comparison_dir),
            "comparison_report": str(comparison_report_path),
        },
    }


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_preview(path: Path, limit: int = 20) -> dict[str, object]:
    if not path.exists():
        return {"columns": [], "rows": [], "path": str(path)}
    frame = pd.read_csv(path, dtype=str).fillna("")
    return {
        "columns": list(frame.columns),
        "rows": frame.head(limit).to_dict(orient="records"),
        "row_count": len(frame),
        "path": str(path),
    }


def _build_charts(analysis_dir: Path) -> dict[str, object]:
    job_path = analysis_dir / "job_demand_monthly_analysis.csv"
    skill_path = analysis_dir / "job_skill_monthly_frequency_analysis.csv"
    charts: dict[str, object] = {"category_distribution": [], "top_skills": [], "monthly_trend": []}
    if job_path.exists():
        jobs = pd.read_csv(job_path, dtype=str).fillna("")
        if {"standard_category", "monthly_jd_count"}.issubset(jobs.columns):
            jobs["monthly_jd_count_num"] = pd.to_numeric(jobs["monthly_jd_count"], errors="coerce").fillna(0)
            charts["category_distribution"] = (
                jobs.groupby("standard_category", as_index=False)["monthly_jd_count_num"]
                .sum()
                .sort_values("monthly_jd_count_num", ascending=False)
                .head(12)
                .rename(columns={"standard_category": "label", "monthly_jd_count_num": "value"})
                .to_dict(orient="records")
            )
        if {"month", "monthly_jd_count"}.issubset(jobs.columns):
            charts["monthly_trend"] = (
                jobs.groupby("month", as_index=False)["monthly_jd_count_num"]
                .sum()
                .sort_values("month")
                .rename(columns={"month": "label", "monthly_jd_count_num": "value"})
                .to_dict(orient="records")
            )
    if skill_path.exists():
        skills = pd.read_csv(skill_path, dtype=str).fillna("")
        if {"skill", "monthly_skill_count"}.issubset(skills.columns):
            skills["monthly_skill_count_num"] = pd.to_numeric(skills["monthly_skill_count"], errors="coerce").fillna(0)
            charts["top_skills"] = (
                skills.groupby("skill", as_index=False)["monthly_skill_count_num"]
                .sum()
                .sort_values("monthly_skill_count_num", ascending=False)
                .head(15)
                .rename(columns={"skill": "label", "monthly_skill_count_num": "value"})
                .to_dict(orient="records")
            )
    return charts
