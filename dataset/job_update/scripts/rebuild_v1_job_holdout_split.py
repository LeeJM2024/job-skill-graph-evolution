from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_update.frequency_store import rebuild_frequency_table
from job_update.skill_pool_store import SKILL_POOL_COLUMNS
from job_update.text import clean_text, split_semicolon


BASE_DIR = PROJECT_ROOT / "data" / "base"
OUTPUT_DIR = PROJECT_ROOT / "data" / "splits" / "v1_job_holdout"

EVENT_COLUMNS = [
    "job_id",
    "month",
    "standard_job",
    "job_title",
    "job_responsibility",
    "job_requirement",
    "skills",
]

LABELED_COLUMNS = [
    "split",
    "expected_route_status",
    "split_reason",
    "original_standard_category",
    "original_standard_job",
    *EVENT_COLUMNS,
]

NEW_FAMILY_CATEGORIES = {
    "机器人",
    "自动驾驶",
    "多媒体",
}

POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS = {
    "AIGC算法工程师",
    "多模态算法工程师",
    "大模型应用工程师",
    "搜索算法工程师",
    "数据挖掘算法工程师",
    "Go开发工程师",
    "Python开发工程师",
    "DevOps工程师",
    "数据治理工程师",
    "大模型测试工程师",
    "芯片验证工程师",
    "热设计工程师",
}

KNOWN_JOB_INCREMENT_TAIL_RATIO = 0.2
KNOWN_JOB_INCREMENT_MIN_JOB_COUNT = 10


def main() -> None:
    events = read_csv(BASE_DIR / "job_update_event_stream.csv")
    dictionary = read_csv(BASE_DIR / "standard_job_title_dictionary.csv")
    skill_pool = read_csv(BASE_DIR / "skill_pool.csv")

    validate_inputs(events, dictionary)
    category_by_job = dict(zip(dictionary["standard_job_title"], dictionary["standard_category"]))
    new_family_jobs = set(
        dictionary[dictionary["standard_category"].isin(NEW_FAMILY_CATEGORIES)][
            "standard_job_title"
        ]
    )
    hidden_jobs = new_family_jobs | POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS

    assignment = build_assignment(events, category_by_job, new_family_jobs)
    base_events = events[assignment["split"].eq("base")].copy()
    base_dictionary = dictionary[~dictionary["standard_job_title"].isin(hidden_jobs)].copy()

    known_job_increment = labeled_subset(assignment, "known_job_increment")
    potential_new_job = labeled_subset(assignment, "potential_new_job")
    new_family = labeled_subset(assignment, "new_family")
    all_evaluation = pd.concat(
        [known_job_increment, potential_new_job, new_family],
        ignore_index=True,
    )
    new_position_training = pd.concat(
        [potential_new_job, new_family],
        ignore_index=True,
    )

    base_frequency = rebuild_frequency_table(base_events[EVENT_COLUMNS])
    base_skill_pool = rebuild_skill_pool(base_events, dictionary, skill_pool)

    write_outputs(
        dictionary=dictionary,
        base_dictionary=base_dictionary,
        base_events=base_events,
        base_frequency=base_frequency,
        base_skill_pool=base_skill_pool,
        assignment=assignment,
        known_job_increment=known_job_increment,
        potential_new_job=potential_new_job,
        new_family=new_family,
        all_evaluation=all_evaluation,
        new_position_training=new_position_training,
        new_family_jobs=new_family_jobs,
    )


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


def validate_inputs(events: pd.DataFrame, dictionary: pd.DataFrame) -> None:
    missing_event_columns = set(EVENT_COLUMNS).difference(events.columns)
    if missing_event_columns:
        raise ValueError(f"event stream missing columns: {sorted(missing_event_columns)}")
    missing_dictionary_columns = {"standard_job_title", "standard_category"}.difference(dictionary.columns)
    if missing_dictionary_columns:
        raise ValueError(f"title dictionary missing columns: {sorted(missing_dictionary_columns)}")
    missing_holdouts = POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS.difference(dictionary["standard_job_title"])
    if missing_holdouts:
        raise ValueError(f"holdout standard jobs are not in dictionary: {sorted(missing_holdouts)}")
    missing_categories = NEW_FAMILY_CATEGORIES.difference(dictionary["standard_category"])
    if missing_categories:
        raise ValueError(f"holdout categories are not in dictionary: {sorted(missing_categories)}")
    unknown_event_jobs = set(events["standard_job"]).difference(dictionary["standard_job_title"])
    if unknown_event_jobs:
        raise ValueError(f"event stream contains unknown standard jobs: {sorted(unknown_event_jobs)}")


def build_assignment(
    events: pd.DataFrame,
    category_by_job: dict[str, str],
    new_family_jobs: set[str],
) -> pd.DataFrame:
    assignment = events[EVENT_COLUMNS].copy()
    assignment["original_standard_job"] = assignment["standard_job"]
    assignment["original_standard_category"] = assignment["standard_job"].map(category_by_job).fillna("")
    assignment["split"] = "base"
    assignment["expected_route_status"] = ""
    assignment["split_reason"] = "retained base history"

    new_family_mask = assignment["standard_job"].isin(new_family_jobs)
    assignment.loc[new_family_mask, "split"] = "new_family"
    assignment.loc[new_family_mask, "expected_route_status"] = "new_family"
    assignment.loc[new_family_mask, "split_reason"] = (
        "hidden whole category: " + assignment.loc[new_family_mask, "original_standard_category"]
    )

    potential_mask = assignment["standard_job"].isin(POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS)
    assignment.loc[potential_mask, "split"] = "potential_new_job"
    assignment.loc[potential_mask, "expected_route_status"] = "potential_new_job"
    assignment.loc[potential_mask, "split_reason"] = (
        "hidden standard job: " + assignment.loc[potential_mask, "standard_job"]
    )

    retained_mask = assignment["split"].eq("base")
    for _, group in assignment[retained_mask].groupby("standard_job", sort=True):
        if len(group) < KNOWN_JOB_INCREMENT_MIN_JOB_COUNT:
            continue
        holdout_count = math.floor(len(group) * KNOWN_JOB_INCREMENT_TAIL_RATIO)
        if holdout_count <= 0:
            continue
        holdout_indexes = group.sort_values(["month", "job_id"]).tail(holdout_count).index
        assignment.loc[holdout_indexes, "split"] = "known_job_increment"
        assignment.loc[holdout_indexes, "expected_route_status"] = "existing_job"
        assignment.loc[holdout_indexes, "split_reason"] = (
            f"tail {KNOWN_JOB_INCREMENT_TAIL_RATIO:.0%} of retained standard job"
        )

    columns = [
        "job_id",
        "split",
        "expected_route_status",
        "split_reason",
        "original_standard_category",
        "original_standard_job",
        "month",
        "standard_job",
        "job_title",
        "job_responsibility",
        "job_requirement",
        "skills",
    ]
    return assignment[columns].sort_values("job_id").reset_index(drop=True)


def labeled_subset(assignment: pd.DataFrame, split_name: str) -> pd.DataFrame:
    rows = assignment[assignment["split"].eq(split_name)].copy()
    return rows[LABELED_COLUMNS].sort_values(["month", "job_id"]).reset_index(drop=True)


def rebuild_skill_pool(
    base_events: pd.DataFrame,
    dictionary: pd.DataFrame,
    source_skill_pool: pd.DataFrame,
) -> pd.DataFrame:
    category_by_job = dict(zip(dictionary["standard_job_title"], dictionary["standard_category"]))
    family_by_skill = dict(zip(source_skill_pool["normalized_skill"], source_skill_pool["kg_display_skill"]))
    rows_by_skill: dict[str, dict[str, object]] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for _, event in base_events.sort_values(["month", "job_id"]).iterrows():
        month = clean_text(event["month"])
        job_id = clean_text(event["job_id"])
        standard_job = clean_text(event["standard_job"])
        standard_category = clean_text(category_by_job.get(standard_job))
        for skill in sorted(set(split_semicolon(event["skills"]))):
            family = clean_text(family_by_skill.get(skill))
            if not family:
                raise ValueError(f"skill_pool is missing kg_display_skill for skill: {skill}")
            item = rows_by_skill.setdefault(
                skill.casefold(),
                {
                    "normalized_skill": skill,
                    "kg_display_skill": family,
                    "skill_type": "",
                    "standard_categories": [],
                    "standard_jobs": [],
                    "first_seen_month": month,
                    "last_seen_month": month,
                    "first_seen_job_id": job_id,
                    "last_seen_job_id": job_id,
                    "mention_count": 0,
                    "source_job_ids": [],
                    "sources": ["base_split"],
                    "updated_at": now,
                },
            )
            append_unique(item["standard_categories"], standard_category)
            append_unique(item["standard_jobs"], standard_job)
            append_unique(item["source_job_ids"], job_id)
            item["mention_count"] = int(item["mention_count"]) + 1
            if month < str(item["first_seen_month"]):
                item["first_seen_month"] = month
                item["first_seen_job_id"] = job_id
            if month >= str(item["last_seen_month"]):
                item["last_seen_month"] = month
                item["last_seen_job_id"] = job_id

    output_rows = []
    for item in rows_by_skill.values():
        source_job_ids = item["source_job_ids"]
        output_rows.append(
            {
                "normalized_skill": item["normalized_skill"],
                "kg_display_skill": item["kg_display_skill"],
                "skill_type": item["skill_type"],
                "standard_categories": "; ".join(item["standard_categories"]),
                "standard_jobs": "; ".join(item["standard_jobs"]),
                "first_seen_month": item["first_seen_month"],
                "last_seen_month": item["last_seen_month"],
                "first_seen_job_id": item["first_seen_job_id"],
                "last_seen_job_id": item["last_seen_job_id"],
                "mention_count": str(item["mention_count"]),
                "source_job_ids": "; ".join(source_job_ids),
                "source_count": str(len(source_job_ids)),
                "sources": "; ".join(item["sources"]),
                "updated_at": item["updated_at"],
            }
        )
    return pd.DataFrame(output_rows, columns=SKILL_POOL_COLUMNS).sort_values("normalized_skill")


def append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def write_outputs(
    *,
    dictionary: pd.DataFrame,
    base_dictionary: pd.DataFrame,
    base_events: pd.DataFrame,
    base_frequency: pd.DataFrame,
    base_skill_pool: pd.DataFrame,
    assignment: pd.DataFrame,
    known_job_increment: pd.DataFrame,
    potential_new_job: pd.DataFrame,
    new_family: pd.DataFrame,
    all_evaluation: pd.DataFrame,
    new_position_training: pd.DataFrame,
    new_family_jobs: set[str],
) -> None:
    for directory in [
        OUTPUT_DIR / "base",
        OUTPUT_DIR / "datasets",
        OUTPUT_DIR / "eval",
        OUTPUT_DIR / "eval" / "base_analysis_check",
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    base_dictionary.to_csv(
        OUTPUT_DIR / "base" / "standard_job_title_dictionary.base_v1.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_events[EVENT_COLUMNS].sort_values("job_id").to_csv(
        OUTPUT_DIR / "base" / "job_update_event_stream.base_v1.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_frequency.to_csv(
        OUTPUT_DIR / "base" / "job_skill_monthly_frequency.base_v1_rebuilt.csv",
        index=False,
        encoding="utf-8-sig",
    )
    base_skill_pool.to_csv(
        OUTPUT_DIR / "base" / "skill_pool.base_v1_rebuilt.csv",
        index=False,
        encoding="utf-8-sig",
    )

    write_labeled("known_job_increment", known_job_increment)
    write_labeled("potential_new_job", potential_new_job)
    write_labeled("new_family", new_family)
    write_labeled("all_evaluation_samples", all_evaluation)
    write_labeled("new_position_training_set", new_position_training)

    assignment.to_csv(
        OUTPUT_DIR / "eval" / "all_source_events_split_assignment.csv",
        index=False,
        encoding="utf-8-sig",
    )
    all_evaluation[
        [
            "job_id",
            "expected_route_status",
            "split",
            "original_standard_category",
            "original_standard_job",
            "job_title",
        ]
    ].to_csv(
        OUTPUT_DIR / "eval" / "route_expected_labels.csv",
        index=False,
        encoding="utf-8-sig",
    )
    split_summary_by_job(assignment).to_csv(
        OUTPUT_DIR / "eval" / "split_summary_by_job.csv",
        index=False,
        encoding="utf-8-sig",
    )
    split_summary_by_category(assignment).to_csv(
        OUTPUT_DIR / "eval" / "split_summary_by_category.csv",
        index=False,
        encoding="utf-8-sig",
    )
    write_base_analysis_check(base_events, base_dictionary)
    write_manifest(
        dictionary=dictionary,
        base_dictionary=base_dictionary,
        base_events=base_events,
        base_frequency=base_frequency,
        base_skill_pool=base_skill_pool,
        assignment=assignment,
        known_job_increment=known_job_increment,
        potential_new_job=potential_new_job,
        new_family=new_family,
        all_evaluation=all_evaluation,
        new_position_training=new_position_training,
        new_family_jobs=new_family_jobs,
    )
    write_readme(
        dictionary=dictionary,
        base_dictionary=base_dictionary,
        base_events=base_events,
        known_job_increment=known_job_increment,
        potential_new_job=potential_new_job,
        new_family=new_family,
        all_evaluation=all_evaluation,
        new_family_jobs=new_family_jobs,
    )


def write_labeled(name: str, frame: pd.DataFrame) -> None:
    frame.to_csv(
        OUTPUT_DIR / "datasets" / f"{name}.labeled.csv",
        index=False,
        encoding="utf-8-sig",
    )


def split_summary_by_job(assignment: pd.DataFrame) -> pd.DataFrame:
    return (
        assignment.groupby(
            ["split", "expected_route_status", "original_standard_category", "standard_job"],
            dropna=False,
        )
        .agg(
            event_count=("job_id", "nunique"),
            month_count=("month", "nunique"),
            first_month=("month", "min"),
            last_month=("month", "max"),
        )
        .reset_index()
        .rename(
            columns={
                "original_standard_category": "standard_category",
            }
        )
        .sort_values(["split", "standard_category", "standard_job"])
    )


def split_summary_by_category(assignment: pd.DataFrame) -> pd.DataFrame:
    return (
        assignment.groupby(["split", "expected_route_status", "original_standard_category"], dropna=False)
        .agg(
            standard_job_count=("standard_job", "nunique"),
            event_count=("job_id", "nunique"),
        )
        .reset_index()
        .rename(columns={"original_standard_category": "standard_category"})
        .sort_values(["split", "standard_category"])
    )


def write_base_analysis_check(base_events: pd.DataFrame, base_dictionary: pd.DataFrame) -> None:
    job_demand = (
        base_events.groupby(["standard_job", "month"], as_index=False)
        .agg(monthly_jd_count=("job_id", "nunique"))
        .sort_values(["standard_job", "month"])
    )
    category_by_job = dict(zip(base_dictionary["standard_job_title"], base_dictionary["standard_category"]))
    job_demand["standard_category"] = job_demand["standard_job"].map(category_by_job).fillna("")
    job_demand["month_index"] = job_demand.groupby("standard_job").cumcount() + 1
    job_demand["cumulative_jd_count"] = job_demand.groupby("standard_job")["monthly_jd_count"].cumsum()
    job_demand["is_active_month"] = True
    job_demand[
        [
            "standard_job",
            "standard_category",
            "month",
            "month_index",
            "monthly_jd_count",
            "cumulative_jd_count",
            "is_active_month",
        ]
    ].to_csv(
        OUTPUT_DIR / "eval" / "base_analysis_check" / "job_demand_monthly_analysis.csv",
        index=False,
        encoding="utf-8-sig",
    )
    frequency = rebuild_frequency_table(base_events[EVENT_COLUMNS])
    frequency.insert(
        3,
        "standard_category",
        frequency["standard_job"].map(category_by_job).fillna(""),
    )
    frequency["month_index"] = frequency.groupby("standard_job")["month"].rank(method="dense").astype(int)
    frequency[
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
        ]
    ].to_csv(
        OUTPUT_DIR / "eval" / "base_analysis_check" / "job_skill_monthly_frequency_analysis.csv",
        index=False,
        encoding="utf-8-sig",
    )
    unknown_jobs = sorted(set(base_events["standard_job"]).difference(base_dictionary["standard_job_title"]))
    report = {
        "base_event_rows": len(base_events),
        "base_standard_jobs": int(base_events["standard_job"].nunique()),
        "base_dictionary_jobs": len(base_dictionary),
        "unknown_standard_jobs": unknown_jobs,
    }
    (OUTPUT_DIR / "eval" / "base_analysis_check" / "analysis_quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_manifest(**payload: object) -> None:
    dictionary = payload["dictionary"]
    base_dictionary = payload["base_dictionary"]
    base_events = payload["base_events"]
    base_frequency = payload["base_frequency"]
    base_skill_pool = payload["base_skill_pool"]
    assignment = payload["assignment"]
    known_job_increment = payload["known_job_increment"]
    potential_new_job = payload["potential_new_job"]
    new_family = payload["new_family"]
    all_evaluation = payload["all_evaluation"]
    new_position_training = payload["new_position_training"]
    new_family_jobs = payload["new_family_jobs"]
    manifest = {
        "split_name": "v1_job_holdout",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_base_dir": str(BASE_DIR),
        "output_dir": str(OUTPUT_DIR),
        "principle": "Hold out whole standard jobs and whole standard categories to simulate new-position detection.",
        "new_family_categories": sorted(NEW_FAMILY_CATEGORIES),
        "new_family_holdout_standard_jobs": sorted(new_family_jobs),
        "potential_new_job_holdout_standard_jobs": sorted(POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS),
        "known_job_increment_rule": {
            "retained_jobs_only": True,
            "sort": ["month", "job_id"],
            "tail_ratio": KNOWN_JOB_INCREMENT_TAIL_RATIO,
            "min_job_count": KNOWN_JOB_INCREMENT_MIN_JOB_COUNT,
            "expected_route_status": "existing_job",
        },
        "counts": {
            "source_standard_jobs": len(dictionary),
            "source_events": len(assignment),
            "base_standard_jobs": len(base_dictionary),
            "base_events": len(base_events),
            "base_frequency_rows": len(base_frequency),
            "base_skill_pool_rows": len(base_skill_pool),
            "known_job_increment_events": len(known_job_increment),
            "potential_new_job_events": len(potential_new_job),
            "new_family_events": len(new_family),
            "evaluation_events_total": len(all_evaluation),
            "new_position_training_events": len(new_position_training),
        },
        "files": {
            "base_title_dictionary": "base/standard_job_title_dictionary.base_v1.csv",
            "base_event_stream": "base/job_update_event_stream.base_v1.csv",
            "base_frequency": "base/job_skill_monthly_frequency.base_v1_rebuilt.csv",
            "base_skill_pool": "base/skill_pool.base_v1_rebuilt.csv",
            "known_job_increment": "datasets/known_job_increment.labeled.csv",
            "potential_new_job": "datasets/potential_new_job.labeled.csv",
            "new_family": "datasets/new_family.labeled.csv",
            "all_evaluation_samples": "datasets/all_evaluation_samples.labeled.csv",
            "new_position_training_set": "datasets/new_position_training_set.labeled.csv",
            "route_expected_labels": "eval/route_expected_labels.csv",
            "split_summary_by_job": "eval/split_summary_by_job.csv",
            "split_summary_by_category": "eval/split_summary_by_category.csv",
            "all_source_events_split_assignment": "eval/all_source_events_split_assignment.csv",
        },
        "validation": validate_outputs(
            base_dictionary=base_dictionary,
            base_events=base_events,
            base_frequency=base_frequency,
            base_skill_pool=base_skill_pool,
            assignment=assignment,
            hidden_jobs=set(new_family_jobs) | POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS,
            hidden_categories=NEW_FAMILY_CATEGORIES,
        ),
    }
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_outputs(
    *,
    base_dictionary: pd.DataFrame,
    base_events: pd.DataFrame,
    base_frequency: pd.DataFrame,
    base_skill_pool: pd.DataFrame,
    assignment: pd.DataFrame,
    hidden_jobs: set[str],
    hidden_categories: set[str],
) -> dict[str, object]:
    base_titles = set(base_dictionary["standard_job_title"])
    return {
        "hidden_jobs_in_base_titles": len(base_titles & hidden_jobs),
        "hidden_categories_in_base_titles": int(base_dictionary["standard_category"].isin(hidden_categories).sum()),
        "hidden_jobs_in_base_events": int(base_events["standard_job"].isin(hidden_jobs).sum()),
        "hidden_jobs_in_base_frequency": int(base_frequency["standard_job"].isin(hidden_jobs).sum())
        if not base_frequency.empty
        else 0,
        "hidden_jobs_mentioned_in_base_skill_pool_standard_jobs": int(
            base_skill_pool["standard_jobs"].map(
                lambda value: bool(set(split_semicolon(value)) & hidden_jobs)
            ).sum()
        )
        if not base_skill_pool.empty
        else 0,
        "base_event_duplicate_job_ids": int(base_events["job_id"].duplicated().sum()),
        "evaluation_duplicate_job_ids": int(
            assignment[~assignment["split"].eq("base")]["job_id"].duplicated().sum()
        ),
        "base_and_eval_job_id_overlap": len(
            set(assignment[assignment["split"].eq("base")]["job_id"])
            & set(assignment[~assignment["split"].eq("base")]["job_id"])
        ),
    }


def write_readme(
    *,
    dictionary: pd.DataFrame,
    base_dictionary: pd.DataFrame,
    base_events: pd.DataFrame,
    known_job_increment: pd.DataFrame,
    potential_new_job: pd.DataFrame,
    new_family: pd.DataFrame,
    all_evaluation: pd.DataFrame,
    new_family_jobs: set[str],
) -> None:
    text = f"""# v1_job_holdout 数据集切分说明

本目录由 `scripts/rebuild_v1_job_holdout_split.py` 从当前 `data/base/` 重新生成。

切分目标：

1. `existing_job`：base 已保留岗位的未来增量 JD。
2. `potential_new_job`：隐藏具体标准岗位，但保留岗位大族。
3. `new_family`：隐藏整个岗位大族。

## 当前规模

| 数据项 | 数量 |
|---|---:|
| 源标准岗位 | {len(dictionary)} |
| 源事件流 JD | {len(base_events) + len(all_evaluation)} |
| base 标准岗位 | {len(base_dictionary)} |
| base 事件流 JD | {len(base_events)} |
| known_job_increment | {len(known_job_increment)} |
| potential_new_job | {len(potential_new_job)} |
| new_family | {len(new_family)} |
| 评估集总计 | {len(all_evaluation)} |

## 隐藏标准岗位

`potential_new_job` 隐藏：

{bullet_list(sorted(POTENTIAL_NEW_JOB_HOLDOUT_STANDARD_JOBS))}

`new_family` 隐藏大族：

{bullet_list(sorted(NEW_FAMILY_CATEGORIES))}

`new_family` 对应标准岗位：

{bullet_list(sorted(new_family_jobs))}

## 重新生成命令

```powershell
cd B:\\揭榜挂帅\\dataset\\job_update
python scripts\\rebuild_v1_job_holdout_split.py
```
"""
    (OUTPUT_DIR / "README.md").write_text(text, encoding="utf-8")


def bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


if __name__ == "__main__":
    main()
