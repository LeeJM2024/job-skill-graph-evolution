from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import csv
import json
import sys
from typing import Any

import pandas as pd

from .paths import (
    BASE_CURRENT_PROFILE,
    BASE_EVENT_STREAM,
    BASE_FREQUENCY_OUTPUT,
    BASE_JOB_PROFILE_DIFF,
    BASE_JOB_PROFILE_SNAPSHOTS,
    BASE_SKILL_LIFECYCLE,
    BASE_SKILL_MIGRATION,
    BASE_SKILL_MONTHLY_SPREAD,
    DATASET_ROOT,
    DATA_STREAM_ROOT,
    GOVERNMENT_BASE_CURRENT_PROFILE,
    GOVERNMENT_BASE_EVENT_STREAM,
    GOVERNMENT_BASE_FREQUENCY_OUTPUT,
    GOVERNMENT_BASE_JOB_PROFILE_DIFF,
    GOVERNMENT_BASE_JOB_PROFILE_SNAPSHOTS,
    GOVERNMENT_BASE_SKILL_LIFECYCLE,
    GOVERNMENT_BASE_SKILL_MIGRATION,
    GOVERNMENT_BASE_SKILL_MONTHLY_SPREAD,
    JOB_UPDATE_ROOT,
    resolve_domain,
)


JOB_UPDATE_GROUP_ROOT = DATASET_ROOT / "job_update"
for path in (JOB_UPDATE_ROOT, JOB_UPDATE_GROUP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from company_job_update.core.current_profile import build_current_profile
from company_job_update.core.job_profile import build_job_profile_tables
from company_job_update.core.skill_lifecycle import build_skill_lifecycle_table
from company_job_update.core.skill_migration import build_skill_migration_tables


BASE_SOURCE_KEY = "base"
TEST_STREAM_ROOT = JOB_UPDATE_GROUP_ROOT / "data" / "test_streams"
ANALYSIS_RUN_ROOTS = [
    JOB_UPDATE_ROOT / "outputs" / "analysis_runs",
    JOB_UPDATE_GROUP_ROOT / "outputs" / "analysis_runs",
]


@dataclass(frozen=True, slots=True)
class DataSource:
    key: str
    label: str
    kind: str
    domain: str
    event_stream_path: Path | None
    run_id: str | None = None
    run_dir: Path | None = None
    skill_universe_path: Path | None = None
    frequency_path: Path | None = None
    derived_dir: Path | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class SourceTables:
    source: dict[str, Any]
    frequency: pd.DataFrame
    lifecycle: pd.DataFrame
    migration: pd.DataFrame
    spread: pd.DataFrame
    snapshots: pd.DataFrame
    diff: pd.DataFrame
    current_profile: pd.DataFrame


def list_sources(domain: str = "company") -> list[dict[str, Any]]:
    domain = resolve_domain(domain)
    sources = [_base_source(domain)]
    if domain == "company":
        sources.extend(_test_stream_sources())
        sources.extend(_run_sources({source.run_id for source in sources if source.run_id}))
    return [_source_to_dict(source) for source in sources]


def get_source_info(domain: str = "company", source_key: str | None = None) -> dict[str, Any]:
    return _source_to_dict(_resolve_source(domain, source_key))


def get_source_tables(domain: str = "company", source_key: str | None = None) -> SourceTables:
    source = _resolve_source(domain, source_key)
    signature = _source_signature(source)
    return _get_source_tables_cached(source.domain, source.key, signature)


def is_base_source(domain: str = "company", source_key: str | None = None) -> bool:
    return _resolve_source(domain, source_key).kind == "base"


def _base_source(domain: str) -> DataSource:
    if resolve_domain(domain) == "government":
        return DataSource(
            key=BASE_SOURCE_KEY,
            label="政府岗位正式基础库 · government_job_event_stream.csv",
            kind="base",
            domain="government",
            event_stream_path=GOVERNMENT_BASE_EVENT_STREAM,
            frequency_path=GOVERNMENT_BASE_FREQUENCY_OUTPUT,
            note="政府技术岗位默认数据源，读取 government_job_update/data/base 下的正式分析结果。",
        )
    return DataSource(
        key=BASE_SOURCE_KEY,
        label="公司岗位正式基础库 · job_update_event_stream.csv",
        kind="base",
        domain="company",
        event_stream_path=BASE_EVENT_STREAM,
        frequency_path=BASE_FREQUENCY_OUTPUT,
        note="公司岗位默认数据源，读取 company_job_update/data/base 下的正式分析结果。",
    )


def _test_stream_sources() -> list[DataSource]:
    if not TEST_STREAM_ROOT.exists():
        return []
    sources: list[DataSource] = []
    for folder in sorted(TEST_STREAM_ROOT.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        manifest = _read_json(folder / "manifest.json")
        event_file = folder / str(manifest.get("event_stream_file") or "")
        if not event_file.exists():
            event_file = _first_csv(folder, "job_update_event_stream*.csv")
        if event_file is None or not event_file.exists():
            continue
        run_id = str(manifest.get("run_id") or folder.name)
        run_dir = DATA_STREAM_ROOT / "outputs" / "runs" / run_id
        skill_universe = run_dir / "skill_trend_design.csv"
        label = str(manifest.get("frontend_entry") or "")
        if "->" in label:
            label = label.split("->")[-1].strip()
        rows = manifest.get("event_stream_rows")
        if not label:
            label = f"测试数据流 · {folder.name}" if not rows else f"测试数据流 · {rows}条 · {folder.name}"
        sources.append(
            DataSource(
                key=f"test_stream:{folder.name}",
                label=label,
                kind="test_stream",
                domain="company",
                event_stream_path=event_file,
                run_id=run_id,
                run_dir=run_dir if run_dir.exists() else None,
                skill_universe_path=skill_universe if skill_universe.exists() else None,
                frequency_path=_analysis_file(run_id, "job_skill_monthly_frequency_analysis.csv"),
                derived_dir=folder / "derived",
                note=str(manifest.get("notice") or "测试数据源，只用于前端查看和分析，不覆盖正式基础库。"),
            )
        )
    return sources


def _run_sources(skip_run_ids: set[str]) -> list[DataSource]:
    runs_root = DATA_STREAM_ROOT / "outputs" / "runs"
    if not runs_root.exists():
        return []
    sources: list[DataSource] = []
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir() or run_dir.name in skip_run_ids:
            continue
        event_file = run_dir / "job_update_event_stream_generated.csv"
        if not event_file.exists():
            continue
        note = _read_json(run_dir / "large_test_generation_note.json")
        rows = note.get("actual_total_planned_jd_count")
        label = f"生成 run · {run_dir.name}" if not rows else f"JD大样本测试 · {rows}条 · {run_dir.name}"
        sources.append(
            DataSource(
                key=f"run:{run_dir.name}",
                label=label,
                kind="run",
                domain="company",
                event_stream_path=event_file,
                run_id=run_dir.name,
                run_dir=run_dir,
                skill_universe_path=run_dir / "skill_trend_design.csv",
                frequency_path=_analysis_file(run_dir.name, "job_skill_monthly_frequency_analysis.csv"),
                note="来自岗位数据流生成系统 outputs/runs。",
            )
        )
    return sources


def _resolve_source(domain: str, source_key: str | None) -> DataSource:
    domain = resolve_domain(domain)
    key = source_key or BASE_SOURCE_KEY
    sources = [_base_source(domain)]
    if domain == "company":
        sources.extend(_test_stream_sources())
        sources.extend(_run_sources({source.run_id for source in sources if source.run_id}))
    for source in sources:
        if source.key == key:
            return source
    return _base_source(domain)


def _source_to_dict(source: DataSource) -> dict[str, Any]:
    return {
        "key": source.key,
        "label": source.label,
        "kind": source.kind,
        "domain": source.domain,
        "run_id": source.run_id or "",
        "run_dir": str(source.run_dir or ""),
        "event_stream_path": str(source.event_stream_path or ""),
        "event_stream_name": source.event_stream_path.name if source.event_stream_path else "",
        "skill_universe_path": str(source.skill_universe_path or ""),
        "frequency_path": str(source.frequency_path or ""),
        "derived_dir": str(source.derived_dir or ""),
        "row_count": _csv_row_count(source.event_stream_path),
        "note": source.note,
    }


def _source_signature(source: DataSource) -> str:
    base_paths = _base_table_paths(source.domain) if source.kind == "base" else []
    paths = [
        source.event_stream_path,
        source.frequency_path,
        source.skill_universe_path,
        *(sorted(source.derived_dir.glob("*.csv")) if source.derived_dir and source.derived_dir.exists() else []),
        *base_paths,
    ]
    parts = []
    for path in paths:
        if path and path.exists():
            stat = path.stat()
            parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts)


@lru_cache(maxsize=8)
def _get_source_tables_cached(domain: str, source_key: str, _signature: str) -> SourceTables:
    source = _resolve_source(domain, source_key)
    if source.kind == "base":
        frequency, lifecycle, migration, spread, snapshots, diff, current_profile = [
            _read_csv(path) for path in _base_table_paths(source.domain)
        ]
        return SourceTables(
            source=_source_to_dict(source),
            frequency=frequency,
            lifecycle=lifecycle,
            migration=migration,
            spread=spread,
            snapshots=snapshots,
            diff=diff,
            current_profile=current_profile,
        )

    frequency = _read_frequency_for_source(source)
    derived = _read_derived_tables(source)
    if derived is None:
        skill_pool = _read_skill_pool_for_source(source)
        lifecycle = build_skill_lifecycle_table(frequency, skill_pool=skill_pool)
        migration, spread = build_skill_migration_tables(frequency, skill_pool=skill_pool)
        snapshots, diff = build_job_profile_tables(frequency, skill_pool=skill_pool)
        current_profile = build_current_profile(snapshots)
    else:
        lifecycle, migration, spread, snapshots, diff, current_profile = derived
    return SourceTables(
        source=_source_to_dict(source),
        frequency=frequency,
        lifecycle=lifecycle,
        migration=migration,
        spread=spread,
        snapshots=snapshots,
        diff=diff,
        current_profile=current_profile,
    )


def _base_table_paths(domain: str) -> list[Path]:
    if resolve_domain(domain) == "government":
        return [
            GOVERNMENT_BASE_FREQUENCY_OUTPUT,
            GOVERNMENT_BASE_SKILL_LIFECYCLE,
            GOVERNMENT_BASE_SKILL_MIGRATION,
            GOVERNMENT_BASE_SKILL_MONTHLY_SPREAD,
            GOVERNMENT_BASE_JOB_PROFILE_SNAPSHOTS,
            GOVERNMENT_BASE_JOB_PROFILE_DIFF,
            GOVERNMENT_BASE_CURRENT_PROFILE,
        ]
    return [
        BASE_FREQUENCY_OUTPUT,
        BASE_SKILL_LIFECYCLE,
        BASE_SKILL_MIGRATION,
        BASE_SKILL_MONTHLY_SPREAD,
        BASE_JOB_PROFILE_SNAPSHOTS,
        BASE_JOB_PROFILE_DIFF,
        BASE_CURRENT_PROFILE,
    ]


def _analysis_file(run_id: str, name: str) -> Path | None:
    for root in ANALYSIS_RUN_ROOTS:
        path = root / run_id / name
        if path.exists():
            return path
    return ANALYSIS_RUN_ROOTS[0] / run_id / name


def _read_frequency_for_source(source: DataSource) -> pd.DataFrame:
    if source.frequency_path and source.frequency_path.exists():
        return _read_csv(source.frequency_path)
    if source.run_dir:
        answer = source.run_dir / "job_skill_monthly_frequency_answer.csv"
        if answer.exists():
            return _read_csv(answer)
    return pd.DataFrame()


def _read_skill_pool_for_source(source: DataSource) -> pd.DataFrame:
    path = source.skill_universe_path
    if path and path.exists():
        frame = _read_csv(path)
        if "skill_stage" in frame.columns and "skill_type" not in frame.columns:
            frame["skill_type"] = frame["skill_stage"]
        return frame
    return pd.DataFrame()


def _read_derived_tables(
    source: DataSource,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    derived_dir = source.derived_dir
    if not derived_dir or not derived_dir.exists():
        return None
    paths = [
        derived_dir / "skill_lifecycle.csv",
        derived_dir / "skill_migration.csv",
        derived_dir / "skill_job_monthly_spread.csv",
        derived_dir / "job_profile_snapshots.csv",
        derived_dir / "job_profile_diff.csv",
        derived_dir / "job_current_profile_system.csv",
    ]
    if not all(path.exists() for path in paths):
        return None
    return tuple(_read_csv(path) for path in paths)  # type: ignore[return-value]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _first_csv(folder: Path, pattern: str) -> Path | None:
    files = sorted(path for path in folder.glob(pattern) if path.is_file())
    return files[0] if files else None


def _csv_row_count(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            return max(sum(1 for _row in csv.reader(handle)) - 1, 0)
    except (OSError, csv.Error):
        return None
