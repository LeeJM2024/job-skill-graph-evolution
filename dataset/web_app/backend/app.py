from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

CURRENT_FILE = Path(__file__).resolve()
DATASET_ROOT = CURRENT_FILE.parents[2]
JOB_UPDATE_ROOT = DATASET_ROOT / "job_update" / "company_job_update"
GOVERNMENT_JOB_UPDATE_ROOT = DATASET_ROOT / "job_update" / "government_job_update"
JOB_UPDATE_GROUP_ROOT = DATASET_ROOT / "job_update"
for path in (DATASET_ROOT, JOB_UPDATE_GROUP_ROOT, JOB_UPDATE_ROOT, GOVERNMENT_JOB_UPDATE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from .schemas import ExistingReviewInput, JobInput, NewJobReviewInput, ProfileOverrideInput, RunExistingInput, RunFullInput, SkillReviewInput
from .services.profile_override_service import save_profile_overrides
from .services.backup_service import create_backup, list_backups
from .services.job_service import (
    confirm_existing,
    confirm_new_job,
    get_review_items,
    import_csv,
    reject_update,
    review_skill,
    submit_one_dry_run,
)
from .services import government_job_service
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


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


@app.get("/api/data-sources")
def api_data_sources(domain: str = "company") -> list[dict[str, Any]]:
    return analytics_service.data_sources(domain)


@app.post("/api/jobs/submit-one-dry-run")
def api_submit_one(payload: JobInput, domain: str = "company") -> dict[str, Any]:
    try:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return government_job_service.submit_one_dry_run(data) if domain == "government" else submit_one_dry_run(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/import-csv")
async def api_import_csv(file: UploadFile = File(...), domain: str = "company") -> dict[str, Any]:
    try:
        content = await file.read()
        from io import BytesIO

        frame = pd.read_csv(BytesIO(content), dtype=str, encoding="utf-8-sig").fillna("")
        return government_job_service.import_csv(frame) if domain == "government" else import_csv(frame)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/review/items")
def api_review_items(domain: str = "company") -> list[dict[str, Any]]:
    return government_job_service.get_review_items() if domain == "government" else get_review_items()


@app.post("/api/review/{item_id}/reject-update")
def api_reject_update(item_id: str, domain: str = "company") -> dict[str, Any]:
    try:
        return government_job_service.reject_update(item_id) if domain == "government" else reject_update(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/review/{item_id}/confirm-existing")
def api_confirm_existing(item_id: str, payload: ExistingReviewInput, domain: str = "company") -> dict[str, Any]:
    try:
        if domain == "government":
            return government_job_service.confirm_existing(item_id, standard_job_title=payload.standard_job_title, skills=payload.skills)
        return confirm_existing(
            item_id,
            merge_database=payload.merge_database,
            standard_job_title=payload.standard_job_title,
            standard_category=payload.standard_category,
            skills=payload.skills,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/review/{item_id}/confirm-new-job")
def api_confirm_new_job(item_id: str, payload: NewJobReviewInput, domain: str = "company") -> dict[str, Any]:
    try:
        if domain == "government":
            return government_job_service.confirm_new_job(item_id, standard_category=payload.standard_category, standard_job_title=payload.standard_job_title, match_keywords=payload.match_keywords)
        return confirm_new_job(
            item_id,
            standard_category=payload.standard_category,
            standard_job_title=payload.standard_job_title,
            match_keywords=payload.match_keywords,
            merge_database=payload.merge_database,
            skills=payload.skills,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/review/{item_id}/review-skill")
def api_review_skill(item_id: str, payload: SkillReviewInput, domain: str = "company") -> dict[str, Any]:
    try:
        if domain == "government":
            return government_job_service.review_skill(item_id, decision=payload.decision, normalized_skill=payload.normalized_skill, kg_display_skill=payload.kg_display_skill, skill_type=payload.skill_type)
        return review_skill(
            item_id,
            decision=payload.decision,
            normalized_skill=payload.normalized_skill,
            kg_display_skill=payload.kg_display_skill,
            skill_type=payload.skill_type,
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
def api_analytics_jobs(domain: str = "company", source_key: str | None = None) -> list[str]:
    return analytics_service.list_jobs(domain, source_key=source_key)


@app.get("/api/analytics/months")
def api_analytics_months(domain: str = "company", source_key: str | None = None) -> list[str]:
    return analytics_service.list_months(domain, source_key=source_key)


@app.get("/api/analytics/overview")
def api_analytics_overview(domain: str = "company", source_key: str | None = None) -> dict[str, Any]:
    return analytics_service.overview(domain, source_key=source_key)


@app.get("/api/analytics/job-trend")
def api_analytics_job_trend(
    standard_job: str | None = None,
    top_n: int = 8,
    month_start: str | None = None,
    month_end: str | None = None,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.job_trend(
        standard_job,
        top_n=top_n,
        month_start=month_start,
        month_end=month_end,
        domain=domain,
        source_key=source_key,
    )


@app.get("/api/analytics/lifecycle")
def api_analytics_lifecycle(
    standard_job: str | None = None,
    status: str | None = None,
    limit: int = 120,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.lifecycle(standard_job, status=status, limit=limit, domain=domain, source_key=source_key)


@app.get("/api/analytics/skill-migration")
def api_analytics_skill_migration(
    skill: str | None = None,
    limit: int = 20,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.migration(skill, limit=limit, domain=domain, source_key=source_key)


@app.get("/api/analytics/monthly-rank")
def api_analytics_monthly_rank(
    month: str | None = None,
    type: str = "emerging",
    standard_job: str | None = None,
    limit: int = 20,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.monthly_rank(
        month,
        rank_type=type,
        standard_job=standard_job,
        limit=limit,
        domain=domain,
        source_key=source_key,
    )


@app.get("/api/analytics/profile-compare")
def api_analytics_profile_compare(
    standard_job: str | None = None,
    from_month: str | None = None,
    to_month: str | None = None,
    limit: int = 80,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.profile_compare(
        standard_job,
        from_month=from_month,
        to_month=to_month,
        limit=limit,
        domain=domain,
        source_key=source_key,
    )


@app.get("/api/optimization/profile")
def api_optimization_profile(
    standard_job: str | None = None,
    limit: int = 500,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    return analytics_service.optimization_profile(standard_job=standard_job, limit=limit, domain=domain, source_key=source_key)


@app.get("/api/optimization/normalize-skill")
def api_optimization_normalize_skill(skill: str, domain: str = "company") -> dict[str, Any]:
    return analytics_service.normalize_optimization_skill(skill, domain=domain)


@app.post("/api/optimization/overrides")
def api_optimization_overrides(payload: ProfileOverrideInput, domain: str = "company") -> dict[str, Any]:
    try:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return save_profile_overrides(domain=domain, **data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
