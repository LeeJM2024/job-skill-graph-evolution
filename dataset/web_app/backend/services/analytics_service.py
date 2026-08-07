from __future__ import annotations

from functools import lru_cache
import sys
from typing import Any

import pandas as pd

from .paths import (
    BASE_FREQUENCY_OUTPUT,
    BASE_CURRENT_PROFILE,
    BASE_DATABASE,
    BASE_EVENT_STREAM,
    BASE_JOB_PROFILE_DIFF,
    BASE_JOB_PROFILE_SNAPSHOTS,
    BASE_SKILL_POOL,
    BASE_SKILL_LIFECYCLE,
    BASE_SKILL_MIGRATION,
    BASE_SKILL_MONTHLY_SPREAD,
    BASE_TITLE_DICTIONARY,
    DATA_STREAM_SKILL_DICTIONARY,
    DATA_STREAM_TITLE_DICTIONARY,
    DATASET_ROOT,
    SKILL_ALIAS_DICTIONARY,
    SKILL_EXTRACT_ROOT,
)
from .paths import domain_file, resolve_domain
from . import data_source_service
from .profile_override_service import apply_profile_overrides


for path in (DATASET_ROOT, SKILL_EXTRACT_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


STATUS_ORDER = ["新兴技能", "活跃技能", "稳定核心技能", "衰退技能", "废弃技能", "观察中"]
EMERGING_TYPES = {"新增技能", "频率上升技能"}
DECLINING_TYPES = {"消失技能", "频率下降技能"}

PROFILE_CHANGE_BUCKETS = {
    "added": "新增技能",
    "removed": "消失技能",
    "increased": "频率上升技能",
    "decreased": "频率下降技能",
    "stable_core": "稳定核心技能",
}
PROFILE_NUMBER_COLUMNS = [
    "monthly_jd_count",
    "monthly_skill_count",
    "monthly_skill_frequency",
    "cumulative_jd_count",
    "cumulative_skill_count",
    "cumulative_skill_frequency",
    "rank_in_month",
    "is_core_skill",
]
DIFF_NUMBER_COLUMNS = [
    "from_monthly_jd_count",
    "to_monthly_jd_count",
    "from_monthly_skill_count",
    "to_monthly_skill_count",
    "from_monthly_skill_frequency",
    "to_monthly_skill_frequency",
    "frequency_delta",
    "frequency_delta_ratio",
    "from_cumulative_skill_count",
    "to_cumulative_skill_count",
    "from_cumulative_skill_frequency",
    "to_cumulative_skill_frequency",
    "is_stable_core",
]


def data_sources(domain: str = "company") -> list[dict[str, Any]]:
    return data_source_service.list_sources(domain)


def list_jobs(domain: str = "company", source_key: str | None = None) -> list[str]:
    frame = _tables(domain, source_key).frequency
    if frame.empty or "standard_job" not in frame.columns:
        return []
    return sorted(frame["standard_job"].dropna().astype(str).unique().tolist())


def list_months(domain: str = "company", source_key: str | None = None) -> list[str]:
    frame = _tables(domain, source_key).frequency
    if frame.empty or "month" not in frame.columns:
        return []
    return sorted(frame["month"].dropna().astype(str).unique().tolist())


def overview(domain: str = "company", source_key: str | None = None) -> dict[str, Any]:
    domain = resolve_domain(domain)
    tables = _tables(domain, source_key)
    frequency = tables.frequency
    lifecycle = tables.lifecycle
    migration = tables.migration
    diff = tables.diff
    latest_month = _latest_month(frequency, "month")
    return {
        "latest_month": latest_month,
        "job_count": _nunique(frequency, "standard_job"),
        "skill_count": _nunique(frequency, "skill"),
        "frequency_rows": len(frequency),
        "lifecycle_rows": len(lifecycle),
        "migration_skill_count": len(migration),
        "latest_new_skill_count": _count_diff(diff, latest_month, "新增技能"),
        "latest_declining_skill_count": _count_diff(diff, latest_month, "频率下降技能"),
    }


def job_trend(
    standard_job: str | None,
    *,
    top_n: int = 8,
    month_start: str | None = None,
    month_end: str | None = None,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    frame = _tables(domain, source_key).frequency
    if frame.empty:
        return {"standard_job": standard_job or "", "months": [], "series": []}

    job = standard_job or _first_sorted(frame, "standard_job")
    filtered = frame[frame["standard_job"].astype(str) == job].copy()
    filtered = _filter_month_range(filtered, "month", month_start, month_end)
    if filtered.empty:
        return {"standard_job": job, "months": [], "series": []}

    filtered["monthly_skill_frequency"] = _number(filtered, "monthly_skill_frequency")
    filtered["monthly_skill_count"] = _number(filtered, "monthly_skill_count")
    filtered["cumulative_skill_count"] = _number(filtered, "cumulative_skill_count")
    skills = (
        filtered.groupby("skill", as_index=False)
        .agg(monthly_skill_count=("monthly_skill_count", "sum"), cumulative_skill_count=("cumulative_skill_count", "max"))
        .sort_values(["monthly_skill_count", "cumulative_skill_count"], ascending=False)
        .head(_clamp(top_n, 1, 20))["skill"]
        .tolist()
    )
    months = sorted(filtered["month"].astype(str).unique().tolist())
    series = []
    for skill in skills:
        rows = filtered[filtered["skill"].astype(str) == skill]
        by_month = {row["month"]: row for row in rows.to_dict(orient="records")}
        series.append(
            {
                "skill": skill,
                "points": [
                    {
                        "month": month,
                        "frequency": _round_float(by_month.get(month, {}).get("monthly_skill_frequency", 0)),
                        "count": int(float(by_month.get(month, {}).get("monthly_skill_count", 0) or 0)),
                    }
                    for month in months
                ],
            }
        )
    return {"standard_job": job, "months": months, "series": series}


def lifecycle(
    standard_job: str | None = None,
    status: str | None = None,
    limit: int = 120,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    frame = _tables(domain, source_key).lifecycle
    if frame.empty:
        return {"standard_job": standard_job or "", "summary": [], "rows": []}

    job = standard_job or _first_sorted(frame, "standard_job")
    filtered = frame[frame["standard_job"].astype(str) == job].copy()
    if status:
        filtered = filtered[filtered["lifecycle_status"].astype(str) == status]

    for column in ["current_monthly_skill_frequency", "recent_3m_skill_count", "mom_frequency_change"]:
        filtered[column] = _number(filtered, column)

    summary_counts = filtered["lifecycle_status"].value_counts().to_dict()
    summary = [{"status": item, "count": int(summary_counts.get(item, 0))} for item in STATUS_ORDER if item in summary_counts]

    rows = (
        filtered.sort_values(
            ["lifecycle_status", "current_monthly_skill_frequency", "recent_3m_skill_count"],
            ascending=[True, False, False],
        )
        .head(_clamp(limit, 1, 500))
        .to_dict(orient="records")
    )
    return {"standard_job": job, "summary": summary, "rows": [_clean_record(row) for row in rows]}


def migration(skill: str | None = None, limit: int = 20, domain: str = "company", source_key: str | None = None) -> dict[str, Any]:
    tables = _tables(domain, source_key)
    migration_frame = tables.migration
    spread_frame = tables.spread
    if migration_frame.empty:
        return {"skills": [], "selected": None, "spread": []}

    migration_frame["spread_job_count"] = _number(migration_frame, "spread_job_count")
    migration_frame["total_skill_mentions"] = _number(migration_frame, "total_skill_mentions")
    top_skills = (
        migration_frame.sort_values(["spread_job_count", "total_skill_mentions"], ascending=False)
        .head(_clamp(limit, 1, 100))["skill"]
        .astype(str)
        .tolist()
    )
    selected_skill = skill or (top_skills[0] if top_skills else "")
    selected_rows = migration_frame[migration_frame["skill"].astype(str) == selected_skill]
    selected = _clean_record(selected_rows.iloc[0].to_dict()) if not selected_rows.empty else None

    spread = []
    if selected and not spread_frame.empty:
        spread_rows = spread_frame[spread_frame["skill"].astype(str) == selected_skill].copy()
        spread_rows["monthly_skill_frequency"] = _number(spread_rows, "monthly_skill_frequency")
        spread_rows["monthly_frequency_change"] = _number(spread_rows, "monthly_frequency_change")
        spread = (
            spread_rows.sort_values(["month", "standard_job"])
            .tail(120)
            .to_dict(orient="records")
        )
    return {"skills": top_skills, "selected": selected, "spread": [_clean_record(row) for row in spread]}


def monthly_rank(
    month: str | None = None,
    rank_type: str = "emerging",
    standard_job: str | None = None,
    limit: int = 20,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    frame = _tables(domain, source_key).diff
    if frame.empty:
        return {"month": month or "", "type": rank_type, "rows": []}

    selected_month = month or _latest_month(frame, "to_month")
    filtered = frame[frame["to_month"].astype(str) == selected_month].copy()
    if standard_job:
        filtered = filtered[filtered["standard_job"].astype(str) == standard_job]

    if rank_type == "declining":
        filtered = filtered[filtered["change_type"].astype(str).isin(DECLINING_TYPES)]
        ascending = True
    else:
        filtered = filtered[filtered["change_type"].astype(str).isin(EMERGING_TYPES)]
        ascending = False

    filtered["frequency_delta"] = _number(filtered, "frequency_delta")
    filtered["to_monthly_skill_frequency"] = _number(filtered, "to_monthly_skill_frequency")
    filtered["from_monthly_skill_frequency"] = _number(filtered, "from_monthly_skill_frequency")
    rows = (
        filtered.sort_values(["frequency_delta", "to_monthly_skill_frequency"], ascending=[ascending, False])
        .head(_clamp(limit, 1, 100))
        .to_dict(orient="records")
    )
    return {"month": selected_month, "type": rank_type, "rows": [_clean_record(row) for row in rows]}


def profile_compare(
    standard_job: str | None = None,
    from_month: str | None = None,
    to_month: str | None = None,
    limit: int = 80,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    tables = _tables(domain, source_key)
    snapshots = tables.snapshots
    diff = tables.diff
    if snapshots.empty:
        return _empty_profile_compare(standard_job or "", from_month or "", to_month or "")

    job = _resolve_job(snapshots, standard_job)
    job_snapshots = snapshots[snapshots["standard_job"].astype(str) == job].copy()
    months = sorted(job_snapshots["month"].dropna().astype(str).unique().tolist())
    if not months:
        return _empty_profile_compare(job, from_month or "", to_month or "")

    selected_from = from_month if from_month in months else months[0]
    selected_to = to_month if to_month in months else months[-1]
    if selected_from > selected_to:
        selected_from, selected_to = selected_to, selected_from

    from_profile = _snapshot_profile(job_snapshots, selected_from, limit=30)
    to_profile = _snapshot_profile(job_snapshots, selected_to, limit=30)
    changes_frame = _profile_diff_rows(diff, job, selected_from, selected_to)
    if changes_frame.empty:
        changes_frame = _build_profile_diff_from_snapshots(job_snapshots, job, selected_from, selected_to)

    changes_frame = _prepare_diff_frame(changes_frame)
    changes = {}
    summary = {}
    row_limit = _clamp(limit, 1, 300)
    for key, change_type in PROFILE_CHANGE_BUCKETS.items():
        rows = changes_frame[changes_frame["change_type"].astype(str) == change_type].copy()
        summary[key] = int(len(rows))
        if not rows.empty:
            rows["delta_abs"] = rows["frequency_delta"].abs()
            rows = rows.sort_values(
                ["delta_abs", "to_monthly_skill_frequency", "from_monthly_skill_frequency"],
                ascending=[False, False, False],
            )
        changes[key] = [
            _clean_record(row)
            for row in rows.head(row_limit).drop(columns=["delta_abs"], errors="ignore").to_dict(orient="records")
        ]

    summary["modified"] = summary.get("increased", 0) + summary.get("decreased", 0)
    return {
        "standard_job": job,
        "from_month": selected_from,
        "to_month": selected_to,
        "months": months,
        "summary": summary,
        "from_profile": from_profile,
        "to_profile": to_profile,
        "changes": changes,
    }


def optimization_profile(
    standard_job: str | None = None,
    limit: int = 500,
    domain: str = "company",
    source_key: str | None = None,
) -> dict[str, Any]:
    domain = resolve_domain(domain)
    tables = _tables(domain, source_key)
    frame = tables.current_profile
    if data_source_service.is_base_source(domain, source_key):
        frame, override_count = apply_profile_overrides(frame, domain=domain)
    else:
        override_count = 0
    if frame.empty:
        return {
            "standard_job": standard_job or "",
            "jobs": [],
            "skills": [],
            "summary": {
                "job_count": 0,
                "skill_count": 0,
                "source_month": "",
                "source_type": "",
                "manual_override_count": 0,
            },
        }

    jobs = sorted(frame["standard_job"].dropna().astype(str).unique().tolist())
    job = _resolve_job(frame, standard_job)
    filtered = frame[frame["standard_job"].astype(str) == job].copy() if job else frame.head(0).copy()
    for column in [
        "monthly_jd_count",
        "monthly_skill_count",
        "monthly_skill_frequency",
        "cumulative_jd_count",
        "cumulative_skill_count",
        "cumulative_skill_frequency",
        "is_core_skill",
        "rank_in_month",
    ]:
        filtered[column] = _number(filtered, column)
    if "manual_status" not in filtered.columns:
        filtered["manual_status"] = "系统识别"
    if "manual_note" not in filtered.columns:
        filtered["manual_note"] = ""
    rows = (
        filtered.sort_values(
            ["is_core_skill", "monthly_skill_frequency", "monthly_skill_count", "rank_in_month", "skill"],
            ascending=[False, False, False, True, True],
        )
        .head(_clamp(limit, 1, 1000))
        .to_dict(orient="records")
    )
    source_months = sorted(filtered["source_month"].dropna().astype(str).unique().tolist()) if "source_month" in filtered.columns else []
    source_types = sorted(filtered["source_type"].dropna().astype(str).unique().tolist()) if "source_type" in filtered.columns else []
    return {
        "standard_job": job,
        "jobs": jobs,
        "skills": [_clean_record(row) for row in rows],
        "summary": {
            "job_count": len(jobs),
            "skill_count": int(len(filtered)),
            "manual_override_count": override_count,
            "source_month": "、".join(source_months),
            "source_type": "、".join(source_types),
        },
    }


def normalize_optimization_skill(skill: str, domain: str = "company") -> dict[str, Any]:
    domain = resolve_domain(domain)
    raw = str(skill or "").strip()
    if not raw:
        return {"input": "", "normalized_skill": "", "kg_display_skill": "", "matched": False, "message": "请输入技能名称。"}

    row = {
        "job_id": "web_optimization_manual_skill",
        "job_title": "人工优化",
        "skill_keyword": raw,
        "span_text": raw,
        "normalized_skill_candidate": "",
        "evidence_field": "manual_optimization",
        "evidence_sentence": raw,
    }
    normalizer = _skill_extract_normalizer(domain)
    normalized_rows, local_stats = normalizer.normalize_rows([row])
    normalized_row = normalized_rows[0] if normalized_rows else row
    api_stats: dict[str, int] = {}
    api_error = ""
    if str(normalized_row.get("normalization_status")) == "unresolved":
        try:
            from skill_extract import extract_job_skills_api as extract_api
            from skill_extract.normalizer import DEFAULT_CACHE

            cache_path = DEFAULT_CACHE
            prompt_appendix = ""
            if domain == "government":
                from government_job_update.core.config import DEFAULT_SKILL_NORMALIZATION_CACHE
                from government_job_update.core.skill_extraction import GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX

                cache_path = DEFAULT_SKILL_NORMALIZATION_CACHE
                prompt_appendix = GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX

            extract_api.load_env_file()
            normalized_rows, api_counter = normalizer.normalize_unknowns_with_api(
                normalized_rows,
                provider="deepseek",
                cache_path=cache_path,
                batch_size=1,
                allow_new_skills=True,
                prompt_appendix=prompt_appendix,
            )
            normalized_row = normalized_rows[0] if normalized_rows else normalized_row
            api_stats = dict(api_counter)
        except Exception as exc:
            api_error = str(exc)

    return _normalization_response(
        raw,
        normalized_row,
        local_stats=dict(local_stats),
        api_stats=api_stats,
        api_error=api_error,
    )


@lru_cache(maxsize=2)
def _skill_extract_normalizer(domain: str = "company"):
    from skill_extract.normalizer import SkillNormalizer
    if resolve_domain(domain) == "government":
        from government_job_update.core.config import DEFAULT_SKILL_EXTRACTION_DICTIONARY

        return SkillNormalizer(
            extraction_dictionary=DEFAULT_SKILL_EXTRACTION_DICTIONARY,
        )
    return SkillNormalizer()


def _normalization_response(
    raw: str,
    row: dict[str, Any],
    *,
    local_stats: dict[str, int],
    api_stats: dict[str, int],
    api_error: str,
) -> dict[str, Any]:
    normalized_skill = str(row.get("normalized_skill") or "").strip()
    kg_display_skill = str(row.get("kg_display_skill") or "").strip()
    status = str(row.get("normalization_status") or "").strip()
    method = str(row.get("normalization_method") or "").strip()
    reason = str(row.get("normalization_reason") or "").strip()
    proposed = str(row.get("proposed_normalized_skill") or "").strip()
    matched = bool(normalized_skill and kg_display_skill and status in {"normalized", "new_skill_candidate"})
    if matched:
        if status == "new_skill_candidate":
            message = "归一化 API 判断为可新增技能，请确认是否加入当前岗位画像。"
        elif method.startswith("llm_"):
            message = "已通过归一化 API 映射到标准技能，请确认是否加入当前岗位画像。"
        else:
            message = "已通过项目归一化词典映射到标准技能，请确认是否加入当前岗位画像。"
    elif api_error:
        message = f"本地词典未命中，归一化 API 暂不可用：{api_error}"
    else:
        message = reason or "本地词典和归一化 API 均未给出可用标准技能，请先维护词典或人工复核。"
    return {
        "input": raw,
        "normalized_skill": normalized_skill,
        "kg_display_skill": kg_display_skill,
        "matched": matched,
        "match_source": method or ("归一化 API" if api_stats else "项目归一化模块"),
        "message": message,
        "normalization_status": status,
        "normalization_method": method,
        "normalization_confidence": row.get("normalization_confidence") or "",
        "needs_review": str(row.get("needs_review") or "").lower() == "true",
        "proposed_normalized_skill": proposed,
        "normalization_reason": reason,
        "local_stats": local_stats,
        "api_stats": api_stats,
        "api_error": api_error,
    }


def optimization_sources(keyword: str | None = None, scope: str | None = None, limit: int = 80) -> dict[str, Any]:
    configs = [
        {
            "key": "skill_alias",
            "name": "技能泛抽取词典",
            "path": SKILL_ALIAS_DICTIONARY,
            "purpose": "维护原始写法、别名到标准技能名和展示大类的映射。",
            "required_columns": ["skill_keyword", "normalized_skill", "kg_display_skill"],
        },
        {
            "key": "skill_normalized",
            "name": "技能归一化词典",
            "path": SKILL_NORMALIZED_DICTIONARY,
            "purpose": "维护合法的最终标准技能名清单。",
            "required_columns": ["skill"],
        },
        {
            "key": "skill_display",
            "name": "技能展示词典",
            "path": SKILL_DISPLAY_DICTIONARY,
            "purpose": "维护标准技能名到知识图谱展示大类的映射。",
            "required_columns": ["skill", "kg_display_skill"],
        },
        {
            "key": "runtime_job_dictionary",
            "name": "当前运行标准岗位词典",
            "path": BASE_TITLE_DICTIONARY,
            "purpose": "维护当前 Web 与公司岗位路由使用的标准岗位、大族和匹配关键词。",
            "required_columns": ["standard_job_title", "standard_category", "match_keywords"],
        },
        {
            "key": "stream_job_dictionary",
            "name": "数据流标准岗位词典",
            "path": DATA_STREAM_TITLE_DICTIONARY,
            "purpose": "与当前运行岗位词典保持一致，用于以后重建初始基础数据集。",
            "required_columns": ["standard_job_title", "standard_category", "match_keywords"],
        },
        {
            "key": "stream_skill_alias",
            "name": "数据流技能泛抽取词典",
            "path": DATA_STREAM_SKILL_DICTIONARY,
            "purpose": "与技能体系保持一致，用于以后重建初始基础数据集。",
            "required_columns": ["skill_keyword", "normalized_skill", "kg_display_skill"],
        },
    ]
    selected_configs = [item for item in configs if not scope or item["key"] == scope]
    sources = [_source_preview(item, keyword=keyword, limit=limit) for item in selected_configs]
    return {
        "principle": "只维护源头词典，不直接修改事件流、频率、技能池、岗位画像或 SQLite 结果文件。",
        "workflow": [
            "发现新技能或别名：同步维护技能三词典。",
            "发现新标准岗位或岗位关键词问题：维护当前标准岗位词典，并同步数据流输入词典。",
            "真实 JD 更新：走 submit-one / Web 审核入库流程，由系统自动派生运行结果。",
            "词典正式变更后：按需执行 python -m core.cli init-db 同步 SQLite。",
        ],
        "forbidden_files": [
            str(BASE_EVENT_STREAM),
            str(BASE_FREQUENCY_OUTPUT),
            str(BASE_SKILL_POOL),
            str(BASE_SKILL_LIFECYCLE),
            str(BASE_SKILL_MIGRATION),
            str(BASE_SKILL_MONTHLY_SPREAD),
            str(BASE_JOB_PROFILE_SNAPSHOTS),
            str(BASE_JOB_PROFILE_DIFF),
            str(BASE_DATABASE),
        ],
        "sync_checks": _optimization_sync_checks(),
        "sources": sources,
    }


def _read_csv(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def _tables(domain: str = "company", source_key: str | None = None) -> data_source_service.SourceTables:
    return data_source_service.get_source_tables(domain, source_key)


def _source_preview(config: dict[str, Any], *, keyword: str | None, limit: int) -> dict[str, Any]:
    frame = _read_csv(config["path"])
    columns = frame.columns.tolist()
    filtered = _filter_keyword(frame, keyword)
    return {
        "key": config["key"],
        "name": config["name"],
        "path": str(config["path"]),
        "purpose": config["purpose"],
        "required_columns": config["required_columns"],
        "columns": columns,
        "row_count": int(len(frame)),
        "matched_count": int(len(filtered)),
        "missing_columns": [column for column in config["required_columns"] if column not in columns],
        "rows": [_clean_record(row) for row in filtered.head(_clamp(limit, 1, 300)).to_dict(orient="records")],
    }


def _filter_keyword(frame: pd.DataFrame, keyword: str | None) -> pd.DataFrame:
    if frame.empty or not keyword:
        return frame
    needle = str(keyword).strip().lower()
    if not needle:
        return frame
    mask = frame.astype(str).apply(lambda column: column.str.lower().str.contains(needle, regex=False, na=False)).any(axis=1)
    return frame[mask].copy()


def _optimization_sync_checks() -> list[dict[str, Any]]:
    runtime_jobs = _read_csv(BASE_TITLE_DICTIONARY)
    stream_jobs = _read_csv(DATA_STREAM_TITLE_DICTIONARY)
    alias = _read_csv(SKILL_ALIAS_DICTIONARY)
    normalized = _read_csv(SKILL_NORMALIZED_DICTIONARY)
    display = _read_csv(SKILL_DISPLAY_DICTIONARY)
    stream_alias = _read_csv(DATA_STREAM_SKILL_DICTIONARY)

    runtime_job_set = _row_signature_set(runtime_jobs, ["standard_job_title", "standard_category", "match_keywords"])
    stream_job_set = _row_signature_set(stream_jobs, ["standard_job_title", "standard_category", "match_keywords"])
    alias_skills = _value_set(alias, "normalized_skill")
    normalized_skills = _value_set(normalized, "skill")
    display_skills = _value_set(display, "skill")
    stream_alias_skills = _value_set(stream_alias, "normalized_skill")
    return [
        {
            "name": "当前岗位词典与数据流岗位词典",
            "status": "通过" if runtime_job_set == stream_job_set else "需同步",
            "detail": f"当前 {len(runtime_job_set)} 条，数据流 {len(stream_job_set)} 条，差异 {len(runtime_job_set ^ stream_job_set)} 条",
        },
        {
            "name": "泛抽取技能是否都在归一化词典中",
            "status": "通过" if alias_skills <= normalized_skills else "需补齐",
            "detail": f"泛抽取标准技能 {len(alias_skills)} 个，缺失 {len(alias_skills - normalized_skills)} 个",
        },
        {
            "name": "展示词典是否覆盖归一化技能",
            "status": "通过" if normalized_skills <= display_skills else "需补齐",
            "detail": f"归一化技能 {len(normalized_skills)} 个，展示映射缺失 {len(normalized_skills - display_skills)} 个",
        },
        {
            "name": "数据流技能词典是否覆盖当前技能体系",
            "status": "通过" if alias_skills <= stream_alias_skills else "需同步",
            "detail": f"当前标准技能 {len(alias_skills)} 个，数据流缺失 {len(alias_skills - stream_alias_skills)} 个",
        },
    ]


def _row_signature_set(frame: pd.DataFrame, columns: list[str]) -> set[tuple[str, ...]]:
    if frame.empty or any(column not in frame.columns for column in columns):
        return set()
    return {tuple(str(row[column]).strip() for column in columns) for row in frame.to_dict(orient="records")}


def _value_set(frame: pd.DataFrame, column: str) -> set[str]:
    if frame.empty or column not in frame.columns:
        return set()
    return {str(value).strip() for value in frame[column].dropna().tolist() if str(value).strip()}


def _resolve_job(frame: pd.DataFrame, standard_job: str | None) -> str:
    jobs = sorted(frame["standard_job"].dropna().astype(str).unique().tolist())
    if not jobs:
        return standard_job or ""
    if not standard_job:
        return jobs[0]
    job = str(standard_job).strip()
    if job in jobs:
        return job
    lowered = job.lower()
    for candidate in jobs:
        if lowered and lowered in candidate.lower():
            return candidate
    return job


def _snapshot_profile(frame: pd.DataFrame, month: str, *, limit: int) -> list[dict[str, Any]]:
    if frame.empty or not month:
        return []
    filtered = frame[frame["month"].astype(str) == month].copy()
    if filtered.empty:
        return []
    for column in PROFILE_NUMBER_COLUMNS:
        filtered[column] = _number(filtered, column)
    rows = (
        filtered.sort_values(
            ["is_core_skill", "monthly_skill_frequency", "monthly_skill_count", "rank_in_month"],
            ascending=[False, False, False, True],
        )
        .head(_clamp(limit, 1, 1000))
        .to_dict(orient="records")
    )
    return [_clean_record(row) for row in rows]


def _profile_diff_rows(diff: pd.DataFrame, job: str, from_month: str, to_month: str) -> pd.DataFrame:
    if diff.empty:
        return pd.DataFrame()
    return diff[
        (diff["standard_job"].astype(str) == job)
        & (diff["from_month"].astype(str) == from_month)
        & (diff["to_month"].astype(str) == to_month)
    ].copy()


def _prepare_diff_frame(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in DIFF_NUMBER_COLUMNS:
        output[column] = _number(output, column)
    return output


def _build_profile_diff_from_snapshots(
    snapshots: pd.DataFrame,
    job: str,
    from_month: str,
    to_month: str,
) -> pd.DataFrame:
    before = snapshots[snapshots["month"].astype(str) == from_month].copy()
    after = snapshots[snapshots["month"].astype(str) == to_month].copy()
    if before.empty and after.empty:
        return pd.DataFrame()
    for frame in (before, after):
        for column in PROFILE_NUMBER_COLUMNS:
            frame[column] = _number(frame, column)

    before_map = {row["skill"]: row for row in before.to_dict(orient="records")}
    after_map = {row["skill"]: row for row in after.to_dict(orient="records")}
    skills = sorted(set(before_map) | set(after_map))
    rows = []
    for skill in skills:
        before_row = before_map.get(skill, {})
        after_row = after_map.get(skill, {})
        before_frequency = float(before_row.get("monthly_skill_frequency", 0) or 0)
        after_frequency = float(after_row.get("monthly_skill_frequency", 0) or 0)
        if skill not in before_map:
            change_type = PROFILE_CHANGE_BUCKETS["added"]
        elif skill not in after_map:
            change_type = PROFILE_CHANGE_BUCKETS["removed"]
        elif after_frequency > before_frequency:
            change_type = PROFILE_CHANGE_BUCKETS["increased"]
        elif after_frequency < before_frequency:
            change_type = PROFILE_CHANGE_BUCKETS["decreased"]
        else:
            change_type = PROFILE_CHANGE_BUCKETS["stable_core"]
        rows.append(
            {
                "standard_job": job,
                "from_month": from_month,
                "to_month": to_month,
                "skill": skill,
                "kg_display_skill": after_row.get("kg_display_skill") or before_row.get("kg_display_skill") or "",
                "change_type": change_type,
                "from_monthly_jd_count": before_row.get("monthly_jd_count", 0),
                "to_monthly_jd_count": after_row.get("monthly_jd_count", 0),
                "from_monthly_skill_count": before_row.get("monthly_skill_count", 0),
                "to_monthly_skill_count": after_row.get("monthly_skill_count", 0),
                "from_monthly_skill_frequency": before_frequency,
                "to_monthly_skill_frequency": after_frequency,
                "frequency_delta": after_frequency - before_frequency,
                "frequency_delta_ratio": 0 if before_frequency == 0 else (after_frequency - before_frequency) / before_frequency,
                "from_cumulative_skill_count": before_row.get("cumulative_skill_count", 0),
                "to_cumulative_skill_count": after_row.get("cumulative_skill_count", 0),
                "from_cumulative_skill_frequency": before_row.get("cumulative_skill_frequency", 0),
                "to_cumulative_skill_frequency": after_row.get("cumulative_skill_frequency", 0),
                "is_stable_core": 1 if change_type == PROFILE_CHANGE_BUCKETS["stable_core"] else 0,
            }
        )
    return pd.DataFrame(rows)


def _empty_profile_compare(job: str, from_month: str, to_month: str) -> dict[str, Any]:
    return {
        "standard_job": job,
        "from_month": from_month,
        "to_month": to_month,
        "months": [],
        "summary": {"added": 0, "removed": 0, "increased": 0, "decreased": 0, "stable_core": 0, "modified": 0},
        "from_profile": [],
        "to_profile": [],
        "changes": {"added": [], "removed": [], "increased": [], "decreased": [], "stable_core": []},
    }


def _filter_month_range(frame: pd.DataFrame, column: str, month_start: str | None, month_end: str | None) -> pd.DataFrame:
    output = frame
    if month_start:
        output = output[output[column].astype(str) >= month_start]
    if month_end:
        output = output[output[column].astype(str) <= month_end]
    return output


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([0] * len(frame), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _latest_month(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values = sorted(frame[column].dropna().astype(str).unique().tolist())
    return values[-1] if values else ""


def _first_sorted(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values = sorted(frame[column].dropna().astype(str).unique().tolist())
    return values[0] if values else ""


def _nunique(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].nunique())


def _count_diff(frame: pd.DataFrame, month: str, change_type: str) -> int:
    if frame.empty or not month:
        return 0
    return int(((frame["to_month"].astype(str) == month) & (frame["change_type"].astype(str) == change_type)).sum())


def _round_float(value: Any, digits: int = 6) -> float:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: int, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _clean_value(value) for key, value in row.items()}


def _clean_value(value: Any) -> Any:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return round(value, 6)
    return value
