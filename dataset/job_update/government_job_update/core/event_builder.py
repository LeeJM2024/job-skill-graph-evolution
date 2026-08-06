from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from shared.text_utils import clean_text, stable_identifier


NORMALIZED_POSTING_COLUMNS = [
    "job_id",
    "publish_time",
    "month",
    "recruitment_year",
    "source",
    "source_name",
    "source_url",
    "government_agency",
    "government_department",
    "location",
    "job_title",
    "cleaned_job_title",
    "rule_cleaned_job_title",
    "job_responsibility",
    "job_requirement",
    "routing_text",
    "tags",
    "planned_headcount",
    "source_job_uid",
    "source_sheet",
    "raw_description",
]

RAW_EVENT_COLUMNS = [
    "job_id",
    "month",
    "standard_job",
    "job_title",
    "job_responsibility",
    "job_requirement",
    "skills",
    "source",
    "source_name",
    "publish_time",
    "recruitment_year",
    "source_url",
    "government_agency",
    "government_department",
    "location",
    "cleaned_job_title",
    "routing_text",
    "route_status",
    "event_time_type",
    "source_time_granularity",
]

REQUIRED_SOURCE_COLUMNS = {
    "source",
    "source_name",
    "job_title",
    "company_name",
    "location",
    "tags",
    "job_description",
    "source_url",
    "publish_time",
    "raw",
}


@dataclass(slots=True)
class GovernmentEventBuildResult:
    normalized_postings: pd.DataFrame
    raw_event_stream: pd.DataFrame
    audit: dict[str, Any]


def build_government_event_stream(source: pd.DataFrame) -> GovernmentEventBuildResult:
    _validate_source(source)
    rows = [_normalize_source_row(row) for _, row in source.fillna("").iterrows()]
    normalized = pd.DataFrame(rows, columns=NORMALIZED_POSTING_COLUMNS)
    if normalized["job_id"].duplicated().any():
        duplicates = normalized.loc[normalized["job_id"].duplicated(), "job_id"].head(5).tolist()
        raise ValueError(f"Government source contains duplicate stable job_id values: {duplicates}")

    normalized = normalized.sort_values(["publish_time", "job_id"]).reset_index(drop=True)
    raw_event_stream = pd.DataFrame(
        [
            {
                "job_id": row["job_id"],
                "month": row["month"],
                "standard_job": "",
                "job_title": row["job_title"],
                "job_responsibility": row["job_responsibility"],
                "job_requirement": row["job_requirement"],
                "skills": "",
                "source": "government",
                "source_name": row["source_name"],
                "publish_time": row["publish_time"],
                "recruitment_year": row["recruitment_year"],
                "source_url": row["source_url"],
                "government_agency": row["government_agency"],
                "government_department": row["government_department"],
                "location": row["location"],
                "cleaned_job_title": row["cleaned_job_title"],
                "routing_text": row["routing_text"],
                "route_status": "unprocessed",
                "event_time_type": "published",
                "source_time_granularity": "annual_recruitment_cycle",
            }
            for _, row in normalized.iterrows()
        ],
        columns=RAW_EVENT_COLUMNS,
    )
    audit = {
        "source_rows": len(source),
        "normalized_rows": len(normalized),
        "raw_event_rows": len(raw_event_stream),
        "source_values": sorted(set(normalized["source"])),
        "publish_month_counts": normalized["month"].value_counts().sort_index().to_dict(),
        "recruitment_year_counts": normalized["recruitment_year"].value_counts().sort_index().to_dict(),
        "blank_responsibility_rows": int((normalized["job_responsibility"] == "").sum()),
        "blank_requirement_rows": int((normalized["job_requirement"] == "").sum()),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "time_policy": "month is derived only from the original publish_time; no synthetic dates are created.",
        "event_policy": "standard_job and skills remain empty until government routing and skill extraction complete.",
    }
    return GovernmentEventBuildResult(normalized, raw_event_stream, audit)


def write_government_event_build(
    result: GovernmentEventBuildResult,
    *,
    normalized_postings_path: Path,
    raw_event_stream_path: Path,
    audit_path: Path,
) -> None:
    for path in (normalized_postings_path, raw_event_stream_path, audit_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    result.normalized_postings.to_csv(normalized_postings_path, index=False, encoding="utf-8-sig")
    result.raw_event_stream.to_csv(raw_event_stream_path, index=False, encoding="utf-8-sig")
    audit_path.write_text(json.dumps(result.audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_source(source: pd.DataFrame) -> None:
    missing = sorted(REQUIRED_SOURCE_COLUMNS.difference(source.columns))
    if missing:
        raise ValueError(f"Government source is missing required columns: {missing}")
    source_values = {clean_text(value) for value in source["source"] if clean_text(value)}
    if source_values != {"government_jobs"}:
        raise ValueError(f"Expected only government_jobs source rows, got: {sorted(source_values)}")


def _normalize_source_row(row: pd.Series) -> dict[str, str]:
    raw = _parse_raw(row.get("raw"))
    original = raw.get("original") if isinstance(raw.get("original"), dict) else {}
    publish_time = _normalize_date(row.get("publish_time"))
    job_title = clean_text(row.get("job_title"))
    source_url = clean_text(row.get("source_url"))
    source_job_uid = clean_text(raw.get("job_uid"))
    job_id = source_job_uid or stable_identifier("GOV", source_url, job_title, publish_time)
    recruitment_year = clean_text(raw.get("dataset_year")) or _year_from_text(row.get("source_name"))
    responsibility = _first_nonempty(
        original.get("职位简介"),
        _section_from_description(row.get("job_description"), "职位简介"),
    )
    requirement = _requirements_from_original(original)
    if not requirement:
        requirement = _requirements_from_description(row.get("job_description"))
    rule_cleaned_title = clean_government_title(job_title)
    routing_requirement = _first_nonempty(
        original.get("专业"),
        _section_from_description(row.get("job_description"), "专业要求"),
    )
    routing_text = "\n".join(
        part
        for part in [
            f"岗位名称：{job_title}",
            f"职位简介：{responsibility}" if responsibility else "",
            f"专业要求：{routing_requirement}" if routing_requirement else "",
            f"技术标签：{clean_text(row.get('tags'))}" if clean_text(row.get("tags")) else "",
        ]
        if part
    )
    return {
        "job_id": job_id,
        "publish_time": publish_time,
        "month": publish_time[:7],
        "recruitment_year": recruitment_year,
        "source": "government",
        "source_name": clean_text(row.get("source_name")),
        "source_url": source_url,
        "government_agency": clean_text(row.get("company_name")) or clean_text(original.get("部门名称")),
        "government_department": clean_text(original.get("用人司局")),
        "location": clean_text(row.get("location")) or clean_text(row.get("city")),
        "job_title": job_title,
        "cleaned_job_title": "",
        "rule_cleaned_job_title": rule_cleaned_title,
        "job_responsibility": responsibility,
        "job_requirement": requirement,
        "routing_text": routing_text,
        "tags": clean_text(row.get("tags")),
        "planned_headcount": clean_text(original.get("招考人数")),
        "source_job_uid": source_job_uid,
        "source_sheet": clean_text(raw.get("source_sheet")) or clean_text(original.get("来源Sheet")),
        "raw_description": clean_text(row.get("job_description")),
    }


def clean_government_title(job_title: str) -> str:
    """Remove administrative rank suffixes while retaining the functional title."""
    title = clean_text(job_title)
    cleaned = re.sub(
        r"(?:一|二|三|四|五|六|七|八|九|十)?级?(?:主任科员|行政执法员|主办|主管|警长|警员|科员|专业技术员)(?:及以下)?(?:（[^）]*）)?$",
        "",
        title,
    )
    cleaned = re.sub(r"[\-—–]+$", "", cleaned).strip()
    return cleaned or title


def _parse_raw(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise ValueError("Government source contains invalid raw JSON") from exc
    return parsed if isinstance(parsed, dict) else {}


def _normalize_date(value: Any) -> str:
    parsed = pd.to_datetime(clean_text(value), errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Government source has invalid publish_time: {value!r}")
    return parsed.strftime("%Y-%m-%d")


def _requirements_from_original(original: dict[str, Any]) -> str:
    labels = ["专业", "学历", "学位", "备注"]
    parts = [f"{label}：{clean_text(original.get(label))}" for label in labels if clean_text(original.get(label))]
    return "\n".join(parts)


def _requirements_from_description(description: Any) -> str:
    labels = ("专业要求", "学历要求", "学位要求", "备注")
    text = str(description or "")
    lines = [clean_text(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if any(line.startswith(label) for label in labels))


def _section_from_description(description: Any, label: str) -> str:
    for line in str(description or "").splitlines():
        line = clean_text(line)
        if line.startswith(f"{label}："):
            return clean_text(line.removeprefix(f"{label}："))
    return ""


def _year_from_text(value: Any) -> str:
    match = re.search(r"(20\d{2})", clean_text(value))
    return match.group(1) if match else ""


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""
