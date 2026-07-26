from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

CURRENT_FILE = Path(__file__).resolve()
DATASET_ROOT = CURRENT_FILE.parents[2]
JOB_UPDATE_ROOT = DATASET_ROOT / "job_update"
for path in (DATASET_ROOT, JOB_UPDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from .schemas import ExistingReviewInput, JobInput, NewJobReviewInput, RunExistingInput, RunFullInput
from .services.backup_service import create_backup, list_backups
from .services.job_service import (
    confirm_existing,
    confirm_new_job,
    get_review_items,
    import_csv,
    reject_update,
    submit_one_dry_run,
)
from .services.paths import FRONTEND_ROOT
from .services.pipeline_service import list_runs, read_pipeline_result, run_existing, run_full_pipeline


app = FastAPI(title="岗位技能更新系统 Web 控制台")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

assets_dir = FRONTEND_ROOT / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_ROOT / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/pipeline/runs")
def api_list_runs() -> list[dict[str, str]]:
    return list_runs()


@app.post("/api/pipeline/run-full")
def api_run_full(payload: RunFullInput) -> dict[str, object]:
    try:
        return run_full_pipeline(payload.month_start, payload.month_end, payload.pass_threshold)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/pipeline/run-existing")
def api_run_existing(payload: RunExistingInput) -> dict[str, object]:
    try:
        return run_existing(payload.run_id, payload.month_start, payload.month_end, payload.pass_threshold)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pipeline/result/{run_id}")
def api_pipeline_result(run_id: str) -> dict[str, object]:
    try:
        return read_pipeline_result(run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/jobs/submit-one-dry-run")
def api_submit_one(payload: JobInput) -> dict[str, Any]:
    try:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return submit_one_dry_run(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/import-csv")
async def api_import_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        content = await file.read()
        from io import BytesIO

        frame = pd.read_csv(BytesIO(content), dtype=str, encoding="utf-8-sig").fillna("")
        return import_csv(frame)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review/items")
def api_review_items() -> list[dict[str, Any]]:
    return get_review_items()


@app.post("/api/review/{item_id}/reject-update")
def api_reject_update(item_id: str) -> dict[str, Any]:
    try:
        return reject_update(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/review/{item_id}/confirm-existing")
def api_confirm_existing(item_id: str, payload: ExistingReviewInput) -> dict[str, Any]:
    try:
        return confirm_existing(item_id, payload.merge_database)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/review/{item_id}/confirm-new-job")
def api_confirm_new_job(item_id: str, payload: NewJobReviewInput) -> dict[str, Any]:
    try:
        return confirm_new_job(
            item_id,
            standard_category=payload.standard_category,
            standard_job_title=payload.standard_job_title,
            match_keywords=payload.match_keywords,
            merge_database=payload.merge_database,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/database/backup")
def api_backup() -> dict[str, object]:
    try:
        return create_backup("manual backup from web console")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/database/backups")
def api_backups() -> list[dict[str, object]]:
    return list_backups()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8787, reload=True)
