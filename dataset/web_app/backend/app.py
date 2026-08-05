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
from .services import analytics_service
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


@app.get("/api/analytics/jobs")
def api_analytics_jobs() -> list[str]:
    return analytics_service.list_jobs()


@app.get("/api/analytics/months")
def api_analytics_months() -> list[str]:
    return analytics_service.list_months()


@app.get("/api/analytics/overview")
def api_analytics_overview() -> dict[str, Any]:
    return analytics_service.overview()


@app.get("/api/analytics/job-trend")
def api_analytics_job_trend(
    standard_job: str | None = None,
    top_n: int = 8,
    month_start: str | None = None,
    month_end: str | None = None,
) -> dict[str, Any]:
    return analytics_service.job_trend(
        standard_job,
        top_n=top_n,
        month_start=month_start,
        month_end=month_end,
    )


@app.get("/api/analytics/lifecycle")
def api_analytics_lifecycle(
    standard_job: str | None = None,
    status: str | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    return analytics_service.lifecycle(standard_job, status=status, limit=limit)


@app.get("/api/analytics/skill-migration")
def api_analytics_skill_migration(skill: str | None = None, limit: int = 20) -> dict[str, Any]:
    return analytics_service.migration(skill, limit=limit)


@app.get("/api/analytics/monthly-rank")
def api_analytics_monthly_rank(
    month: str | None = None,
    type: str = "emerging",
    standard_job: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    return analytics_service.monthly_rank(month, rank_type=type, standard_job=standard_job, limit=limit)


@app.get("/api/analytics/profile-compare")
def api_analytics_profile_compare(
    standard_job: str | None = None,
    from_month: str | None = None,
    to_month: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    return analytics_service.profile_compare(
        standard_job,
        from_month=from_month,
        to_month=to_month,
        limit=limit,
    )


@app.get("/api/optimization/profile")
def api_optimization_profile(
    standard_job: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    return analytics_service.optimization_profile(standard_job=standard_job, limit=limit)


@app.get("/api/optimization/normalize-skill")
def api_optimization_normalize_skill(skill: str) -> dict[str, Any]:
    return analytics_service.normalize_optimization_skill(skill)


@app.get("/api/optimization/sources")
def api_optimization_sources(
    keyword: str | None = None,
    scope: str | None = None,
    limit: int = 80,
) -> dict[str, Any]:
    return analytics_service.optimization_sources(keyword=keyword, scope=scope, limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8787, reload=True)
