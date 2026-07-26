from __future__ import annotations

from datetime import datetime
import json
import shutil
from pathlib import Path

from .paths import (
    BACKUP_ROOT,
    BASE_DATABASE,
    BASE_EVENT_STREAM,
    BASE_FREQUENCY_OUTPUT,
    BASE_SKILL_POOL,
    BASE_TITLE_DICTIONARY,
)


BACKUP_FILES = [
    BASE_DATABASE,
    BASE_TITLE_DICTIONARY,
    BASE_EVENT_STREAM,
    BASE_FREQUENCY_OUTPUT,
    BASE_SKILL_POOL,
]


def create_backup(reason: str) -> dict[str, object]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    copied: list[dict[str, str]] = []
    for source in BACKUP_FILES:
        if not source.exists():
            copied.append({"source": str(source), "status": "missing"})
            continue
        target = backup_dir / source.name
        shutil.copy2(source, target)
        copied.append({"source": str(source), "backup": str(target), "status": "copied"})

    manifest = {
        "backup_id": timestamp,
        "reason": reason,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": copied,
    }
    (backup_dir / "backup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"backup_id": timestamp, "backup_dir": str(backup_dir), "files": copied}


def list_backups() -> list[dict[str, object]]:
    if not BACKUP_ROOT.exists():
        return []
    rows: list[dict[str, object]] = []
    for directory in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        if not directory.is_dir():
            continue
        manifest_path = directory / "backup_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
        else:
            manifest = {}
        rows.append(
            {
                "backup_id": directory.name,
                "backup_dir": str(directory),
                "reason": manifest.get("reason", ""),
                "created_at": manifest.get("created_at", ""),
                "file_count": len(manifest.get("files", [])) if isinstance(manifest.get("files"), list) else 0,
            }
        )
    return rows
