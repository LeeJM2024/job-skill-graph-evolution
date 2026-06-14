import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


DATASET_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = DATASET_ROOT / "raw" / "chinese_jobs"
GOV_RAW_DIR = DATASET_ROOT / "raw" / "government_jobs"


COLUMN_ALIASES = {
    "department": ["部门名称", "招录机关", "招考单位", "主管部门", "单位名称", "用人司局", "招录单位"],
    "job_title": ["职位名称", "岗位名称", "职位", "岗位", "招考职位"],
    "job_code": ["职位代码", "岗位代码", "职位编号", "岗位编号", "招考职位代码"],
    "location": ["工作地点", "地区", "省份", "城市", "工作地区", "落户地点"],
    "education": ["学历", "学历要求", "最低学历"],
    "degree": ["学位", "学位要求"],
    "major": ["专业", "专业要求", "所学专业"],
    "political_status": ["政治面貌", "政治面貌要求"],
    "grassroots_experience": ["基层工作最低年限", "基层工作经历", "基层工作经验"],
    "headcount": ["招考人数", "招聘人数", "人数", "计划人数"],
    "description": ["职位简介", "岗位简介", "职位描述", "岗位职责", "工作内容", "备注"],
    "exam_category": ["考试类别", "试卷类别", "类别"],
    "phone": ["咨询电话", "联系电话"]
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_value(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def first_value(row, aliases):
    for alias in aliases:
        if alias in row:
            value = clean_value(row.get(alias))
            if value:
                return value
    return ""


def detect_header_row(frame):
    required_markers = {"部门代码", "部门名称", "职位代码", "招考职位", "职位简介"}
    best_index = 0
    best_score = -1
    for index, row in frame.head(12).iterrows():
        values = {clean_value(value) for value in row.tolist()}
        score = len(values & required_markers)
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def normalize_table_frame(frame):
    frame = frame.dropna(how="all")
    if frame.empty:
        return frame

    header_index = detect_header_row(frame)
    columns = [clean_value(value) for value in frame.loc[header_index].tolist()]
    data = frame.loc[header_index + 1 :].copy()
    data.columns = columns
    data = data.dropna(how="all")
    data = data.loc[:, [column for column in data.columns if column]]
    return data


def load_table(input_path, sheet_name=None):
    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if sheet_name is None:
            sheets = pd.read_excel(input_path, sheet_name=None, header=None, dtype=str)
            frames = []
            for name, frame in sheets.items():
                normalized = normalize_table_frame(frame)
                if not normalized.empty:
                    normalized["来源Sheet"] = str(name)
                    frames.append(normalized)
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        frame = pd.read_excel(input_path, sheet_name=sheet_name, header=None, dtype=str)
        normalized = normalize_table_frame(frame)
        normalized["来源Sheet"] = str(sheet_name)
        return normalized
    if suffix == ".csv":
        frame = pd.read_csv(input_path, dtype=str, encoding="utf-8-sig", header=None)
        return normalize_table_frame(frame)
    raise ValueError(f"Unsupported government job file type: {suffix}. Use .xlsx, .xls, or .csv.")


def build_description(row):
    parts = []
    description = first_value(row, COLUMN_ALIASES["description"])
    if description:
        parts.append(f"职位简介：{description}")

    for label, key in [
        ("学历要求", "education"),
        ("学位要求", "degree"),
        ("专业要求", "major"),
        ("政治面貌", "political_status"),
        ("基层工作经历", "grassroots_experience"),
        ("考试类别", "exam_category")
    ]:
        value = first_value(row, COLUMN_ALIASES[key])
        if value:
            parts.append(f"{label}：{value}")

    if not parts:
        raw_pairs = [f"{key}：{clean_value(value)}" for key, value in row.items() if clean_value(value)]
        parts.append("\n".join(raw_pairs[:20]))
    return "\n".join(parts)


def normalize_row(row, source_name, source_file):
    department = first_value(row, COLUMN_ALIASES["department"])
    job_title = first_value(row, COLUMN_ALIASES["job_title"]) or department or "政府公开职位"
    job_code = first_value(row, COLUMN_ALIASES["job_code"])
    location = first_value(row, COLUMN_ALIASES["location"])
    headcount = first_value(row, COLUMN_ALIASES["headcount"])
    tags = [
        "公务员/事业单位",
        first_value(row, COLUMN_ALIASES["education"]),
        first_value(row, COLUMN_ALIASES["degree"]),
        first_value(row, COLUMN_ALIASES["major"]),
        first_value(row, COLUMN_ALIASES["exam_category"])
    ]
    tags = [tag for tag in tags if tag]

    return {
        "source": "government_jobs",
        "source_name": source_name,
        "keyword": "公务员/事业单位岗位",
        "city": location or "全国",
        "crawl_time": now_iso(),
        "job_title": job_title,
        "company_name": department or source_name,
        "salary_text": "",
        "location": location,
        "tags": tags,
        "job_description": build_description(row),
        "source_url": f"local://{source_file.name}#{job_code or job_title}",
        "publish_time": "",
        "raw": row
    }


def make_query_result(records, source_file, source_name):
    jobs = [
        {
            "index": index,
            "source_url": record["source_url"],
            "list_item": record,
            "detail": None
        }
        for index, record in enumerate(records)
    ]
    return {
        "source": "government_jobs",
        "search_args": {
            "keyword": "公务员/事业单位岗位",
            "raw_file": str(source_file),
            "source_name": source_name
        },
        "searched_at": now_iso(),
        "pages": [
            {
                "pageIndex": 1,
                "url": f"local://{source_file.name}",
                "ok": True,
                "status": 200,
                "total_count": len(records),
                "returned_count": len(records),
                "error": None
            }
        ],
        "jobs": jobs,
        "parsed_job_count": len(jobs)
    }


def main():
    parser = argparse.ArgumentParser(description="Import official government/civil-service job tables into dataset raw JSON.")
    parser.add_argument("--input", required=True, help="Path to official .xlsx/.xls/.csv job table.")
    parser.add_argument("--sheet", default=None, help="Excel sheet name or index. Defaults to all sheets.")
    parser.add_argument("--source-name", default="政府公开职位表", help="Source name shown in normalized output.")
    parser.add_argument("--output", default=None, help="Output raw JSON path.")
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    GOV_RAW_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    sheet = int(args.sheet) if args.sheet and args.sheet.isdigit() else args.sheet
    table = load_table(input_path, sheet_name=sheet)
    table = table.dropna(how="all")

    records = []
    for raw_row in table.to_dict(orient="records"):
        row = {clean_value(key): clean_value(value) for key, value in raw_row.items() if clean_value(key)}
        record = normalize_row(row, args.source_name, input_path)
        if record["job_title"] or record["job_description"]:
            records.append(record)

    output = {
        "schema_version": 3,
        "collector": "government-job-table-importer",
        "source": "government_jobs",
        "target_records": len(records),
        "started_at": now_iso(),
        "finished_at": now_iso(),
        "collected_job_count": len(records),
        "config": {
            "input": str(input_path),
            "sheet": args.sheet,
            "source_name": args.source_name
        },
        "queries": [make_query_result(records, input_path, args.source_name)]
    }

    output_path = Path(args.output).resolve() if args.output else RAW_DIR / f"{timestamp()}_government_jobs.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Input: {input_path}")
    print(f"Records: {len(records)}")
    print(f"Wrote raw JSON: {output_path}")
    print("Next: npm run normalize -- --input " + str(output_path))


if __name__ == "__main__":
    main()
