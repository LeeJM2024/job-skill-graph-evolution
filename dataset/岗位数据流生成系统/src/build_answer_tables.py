"""Build answer tables and final QA report.

Step 5 recalculates demand and skill frequencies from the generated event
stream. The answer tables are used to compare against downstream system output.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from run_context import get_current_run_dir, relative_to_project


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "generation_config.json"


def read_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_project_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_int(value: str | int | None) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def split_skills(value: str | None) -> list[str]:
    if not value:
        return []
    skills: list[str] = []
    seen: set[str] = set()
    for part in value.replace("；", ";").split(";"):
        skill = part.strip()
        if not skill or skill in seen:
            continue
        seen.add(skill)
        skills.append(skill)
    return skills


def month_sequence(start: str, end: str) -> list[str]:
    start_year, start_month = [int(part) for part in start.split("-")]
    end_year, end_month = [int(part) for part in end.split("-")]
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0000"
    return f"{numerator / denominator:.4f}"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_answers(run_dir: Path) -> tuple[list[dict], list[dict], dict, str]:
    config = read_config()
    event_path = run_dir / Path(config["output_event_stream_file"]).name
    skill_answer_path = run_dir / Path(config["output_skill_frequency_answer_file"]).name

    months = month_sequence(config["month_start"], config["month_end"])
    demand_plan_rows = read_csv_dicts(run_dir / "job_demand_monthly_plan.csv")
    job_trend_rows = read_csv_dicts(run_dir / "job_demand_trend_design.csv")
    skill_trend_rows = read_csv_dicts(run_dir / "skill_trend_design.csv")
    event_rows = read_csv_dicts(event_path)

    job_trend_by_job = {
        row["standard_job"]: row
        for row in job_trend_rows
        if row.get("standard_job")
    }
    skill_meta = {
        (row["standard_job"], row["skill"]): row
        for row in skill_trend_rows
        if row.get("standard_job") and row.get("skill")
    }

    planned_counts = {
        (row["standard_job"], row["month"]): parse_int(row.get("planned_jd_count"))
        for row in demand_plan_rows
    }

    event_counts: Counter[tuple[str, str]] = Counter()
    skill_counts: Counter[tuple[str, str, str]] = Counter()
    invalid_skills: set[tuple[str, str]] = set()

    for row in event_rows:
        job = row["standard_job"]
        month = row["month"]
        event_counts[(job, month)] += 1
        for skill in split_skills(row.get("skills")):
            skill_counts[(job, month, skill)] += 1
            if (job, skill) not in skill_meta:
                invalid_skills.add((job, skill))

    standard_jobs = [row["standard_job"] for row in job_trend_rows]
    job_answer_rows: list[dict] = []
    cumulative_job_counts: Counter[str] = Counter()
    demand_mismatches: list[dict] = []

    for job in standard_jobs:
        trend_info = job_trend_by_job[job]
        for month_index, month in enumerate(months, start=1):
            actual = event_counts[(job, month)]
            planned = planned_counts.get((job, month), 0)
            cumulative_job_counts[job] += actual
            if actual != planned:
                demand_mismatches.append(
                    {
                        "standard_job": job,
                        "month": month,
                        "planned": planned,
                        "actual": actual,
                    }
                )
            job_answer_rows.append(
                {
                    "standard_job": job,
                    "standard_category": trend_info.get("standard_category", ""),
                    "month": month,
                    "month_index": month_index,
                    "monthly_jd_count": actual,
                    "cumulative_jd_count": cumulative_job_counts[job],
                    "demand_trend_type": trend_info.get("demand_trend_type", ""),
                    "is_active_month": "yes" if actual > 0 else "no",
                }
            )

    skill_answer_rows: list[dict] = []
    cumulative_skill_counts: Counter[tuple[str, str]] = Counter()
    cumulative_skill_denominators: Counter[tuple[str, str]] = Counter()

    for meta in skill_trend_rows:
        job = meta["standard_job"]
        skill = meta["skill"]
        for month_index, month in enumerate(months, start=1):
            monthly_jd_count = event_counts[(job, month)]
            monthly_skill_count = skill_counts[(job, month, skill)]
            cumulative_skill_counts[(job, skill)] += monthly_skill_count
            cumulative_skill_denominators[(job, skill)] += monthly_jd_count
            skill_answer_rows.append(
                {
                    "month": month,
                    "month_index": month_index,
                    "standard_job": job,
                    "standard_category": meta.get("standard_category", ""),
                    "skill": skill,
                    "monthly_jd_count": monthly_jd_count,
                    "monthly_skill_count": monthly_skill_count,
                    "monthly_skill_frequency": ratio(
                        monthly_skill_count, monthly_jd_count
                    ),
                    "cumulative_jd_count": cumulative_skill_denominators[(job, skill)],
                    "cumulative_skill_count": cumulative_skill_counts[(job, skill)],
                    "cumulative_skill_frequency": ratio(
                        cumulative_skill_counts[(job, skill)],
                        cumulative_skill_denominators[(job, skill)],
                    ),
                    "skill_trend_type": meta.get("skill_trend_type", ""),
                    "skill_stage": meta.get("skill_stage", ""),
                    "job_demand_trend_type": meta.get("job_demand_trend_type", ""),
                }
            )

    expected_event_fields = config["event_stream_fields"]
    event_fields = list(event_rows[0].keys()) if event_rows else []
    excluded_fields_present = [
        field
        for field in config.get("excluded_event_stream_fields", [])
        if field in event_fields
    ]

    skill_stage_counts: Counter[str] = Counter(
        row["skill_stage"] for row in skill_answer_rows
    )
    skill_trend_counts: Counter[str] = Counter(
        row["skill_trend_type"] for row in skill_trend_rows
    )

    event_quality = load_json(run_dir / "event_stream_quality_report.json")
    final_report = {
        "config_seed": config["seed"],
        "run_dir": relative_to_project(PROJECT_ROOT, run_dir),
        "month_start": config["month_start"],
        "month_end": config["month_end"],
        "month_count": len(months),
        "standard_job_count": len(standard_jobs),
        "event_stream_file": relative_to_project(PROJECT_ROOT, event_path),
        "event_stream_rows": len(event_rows),
        "event_stream_fields": event_fields,
        "expected_event_stream_fields": expected_event_fields,
        "event_stream_fields_match_config": event_fields == expected_event_fields,
        "excluded_fields_present": excluded_fields_present,
        "unique_generated_jobs": len({row["standard_job"] for row in event_rows}),
        "unique_generated_months": len({row["month"] for row in event_rows}),
        "job_demand_answer_rows": len(job_answer_rows),
        "skill_frequency_answer_file": relative_to_project(
            PROJECT_ROOT, skill_answer_path
        ),
        "skill_frequency_answer_rows": len(skill_answer_rows),
        "skill_trend_design_rows": len(skill_trend_rows),
        "demand_plan_mismatch_count": len(demand_mismatches),
        "invalid_skill_pair_count": len(invalid_skills),
        "total_monthly_jd_count_from_answer": sum(
            int(row["monthly_jd_count"]) for row in job_answer_rows
        ),
        "jobs_without_generated_jd": [
            job
            for job in standard_jobs
            if sum(event_counts[(job, month)] for month in months) == 0
        ],
        "skill_stage_row_counts": dict(sorted(skill_stage_counts.items())),
        "skill_trend_type_counts": dict(sorted(skill_trend_counts.items())),
        "event_stream_quality_report": event_quality,
    }

    summary = build_summary(final_report)
    return job_answer_rows, skill_answer_rows, final_report, summary


def build_summary(report: dict) -> str:
    lines = [
        "岗位数据流生成系统运行摘要",
        "",
        f"Seed: {report['config_seed']}",
        f"时间范围: {report['month_start']} 至 {report['month_end']}",
        f"标准岗位数: {report['standard_job_count']}",
        f"生成事件流行数: {report['event_stream_rows']}",
        f"事件流覆盖岗位数: {report['unique_generated_jobs']}",
        f"事件流覆盖月份数: {report['unique_generated_months']}",
        f"岗位需求答案表行数: {report['job_demand_answer_rows']}",
        f"技能频率答案表行数: {report['skill_frequency_answer_rows']}",
        f"岗位需求计划不一致数: {report['demand_plan_mismatch_count']}",
        f"非法岗位-技能组合数: {report['invalid_skill_pair_count']}",
        f"事件流字段是否匹配配置: {report['event_stream_fields_match_config']}",
        f"被禁止字段是否出现: {report['excluded_fields_present']}",
        "",
        "未生成JD的标准岗位:",
        "、".join(report["jobs_without_generated_jd"]) or "无",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    config = read_config()
    run_dir = get_current_run_dir(PROJECT_ROOT)
    skill_answer_path = run_dir / Path(config["output_skill_frequency_answer_file"]).name
    job_answer_rows, skill_answer_rows, final_report, summary = build_answers(run_dir)

    write_csv(
        run_dir / "job_demand_monthly_answer.csv",
        [
            "standard_job",
            "standard_category",
            "month",
            "month_index",
            "monthly_jd_count",
            "cumulative_jd_count",
            "demand_trend_type",
            "is_active_month",
        ],
        job_answer_rows,
    )
    write_csv(
        skill_answer_path,
        [
            "month",
            "month_index",
            "standard_job",
            "standard_category",
            "skill",
            "monthly_jd_count",
            "monthly_skill_count",
            "monthly_skill_frequency",
            "cumulative_jd_count",
            "cumulative_skill_count",
            "cumulative_skill_frequency",
            "skill_trend_type",
            "skill_stage",
            "job_demand_trend_type",
        ],
        skill_answer_rows,
    )

    with (run_dir / "final_quality_report.json").open("w", encoding="utf-8") as f:
        json.dump(final_report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with (run_dir / "run_summary.txt").open("w", encoding="utf-8") as f:
        f.write(summary)

    print(json.dumps(final_report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

