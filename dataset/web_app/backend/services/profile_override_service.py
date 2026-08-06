from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import json
import sqlite3
from typing import Any

import pandas as pd

from .paths import GOVERNMENT_BASE_DATABASE, BASE_DATABASE, resolve_domain


def apply_profile_overrides(frame: pd.DataFrame, *, domain: str) -> tuple[pd.DataFrame, int]:
    """Overlay active manual edits without changing historical profile snapshots."""
    domain = resolve_domain(domain)
    if frame.empty:
        return frame, 0
    overrides = _active_overrides(domain, standard_job="")
    if not overrides:
        return frame, 0

    output = frame.copy()
    for column, default in (("manual_status", "系统识别"), ("manual_note", "")):
        if column not in output.columns:
            output[column] = default
    for item in overrides:
        job = item["standard_job"]
        skill = item["skill"]
        mask = (output["standard_job"].astype(str) == job) & (output["skill"].astype(str) == skill)
        payload = item["payload"]
        if item["action"] == "delete":
            output = output.loc[~mask].copy()
            continue
        values = {
            "kg_display_skill": payload.get("kg_display_skill", ""),
            "snapshot_skill_status": payload.get("snapshot_skill_status", "人工新增技能"),
            "is_core_skill": payload.get("is_core_skill", 0),
            "manual_status": "人工新增" if item["action"] == "add" else "人工修改",
            "manual_note": payload.get("manual_note", ""),
            "source_type": "manual_override",
        }
        if mask.any():
            for column, value in values.items():
                output.loc[mask, column] = value
            continue
        row = {column: "" for column in output.columns}
        row.update(payload)
        row.update(values)
        row["standard_job"] = job
        row["skill"] = skill
        output = pd.concat([output, pd.DataFrame([row])], ignore_index=True)
    return output, len(overrides)


def save_profile_overrides(*, domain: str, standard_job: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
    domain = resolve_domain(domain)
    job = str(standard_job or "").strip()
    if not job:
        raise ValueError("standard_job is required")
    normalized = [_normalize_change(change, job) for change in changes]
    normalized = [change for change in normalized if change is not None]
    if not normalized:
        raise ValueError("At least one valid profile change is required")

    path = _database_path(domain)
    with closing(_connect(path)) as conn:
        _migrate(conn)
        for change in normalized:
            conn.execute(
                "UPDATE job_profile_manual_overrides SET is_active = 0 WHERE standard_job = ? AND skill = ? AND is_active = 1",
                (job, change["skill"]),
            )
            conn.execute(
                """
                INSERT INTO job_profile_manual_overrides
                (standard_job, skill, action, payload_json, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (job, change["skill"], change["action"], json.dumps(change["payload"], ensure_ascii=False), _now()),
            )
        conn.commit()
    return {"domain": domain, "standard_job": job, "saved_changes": len(normalized)}


def _normalize_change(change: dict[str, Any], standard_job: str) -> dict[str, Any] | None:
    action = str(change.get("action") or "").strip().lower()
    if action not in {"add", "update", "delete"}:
        return None
    source = change.get("after") if action != "delete" else change.get("before")
    source = source if isinstance(source, dict) else {}
    skill = str(change.get("skill") or source.get("skill") or "").strip()
    if not skill:
        return None
    payload = {
        "standard_job": standard_job,
        "skill": skill,
        "kg_display_skill": str(source.get("kg_display_skill") or "").strip(),
        "snapshot_skill_status": str(source.get("snapshot_skill_status") or "").strip(),
        "is_core_skill": 1 if str(source.get("is_core_skill") or "0") in {"1", "true", "True"} else 0,
        "manual_note": str(change.get("note") or source.get("manual_note") or "").strip(),
    }
    if action != "delete" and not payload["kg_display_skill"]:
        raise ValueError(f"kg_display_skill is required for manually {action}d skill: {skill}")
    return {"action": action, "skill": skill, "payload": payload}


def _active_overrides(domain: str, *, standard_job: str) -> list[dict[str, Any]]:
    path = _database_path(domain)
    with closing(_connect(path)) as conn:
        _migrate(conn)
        sql = "SELECT standard_job, skill, action, payload_json FROM job_profile_manual_overrides WHERE is_active = 1"
        params: tuple[str, ...] = ()
        if standard_job:
            sql += " AND standard_job = ?"
            params = (standard_job,)
        rows = conn.execute(sql + " ORDER BY override_id", params).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload_json"] or "{}")}
        for row in rows
    ]


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_profile_manual_overrides (
            override_id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard_job TEXT NOT NULL,
            skill TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('add', 'update', 'delete')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_profile_overrides_active ON job_profile_manual_overrides (standard_job, skill, is_active)"
    )


def _database_path(domain: str):
    return BASE_DATABASE if domain == "company" else GOVERNMENT_BASE_DATABASE


def _connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
