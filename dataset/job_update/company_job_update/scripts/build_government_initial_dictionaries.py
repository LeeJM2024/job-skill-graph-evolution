"""Build the isolated initial dictionaries for the government-job data domain.

This script intentionally has no dependency on the big-company job or skill
dictionaries.  It only reads the screened government source file and creates
the seed dictionaries that the future government pipeline will use.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


JOB_DEFINITIONS = [
    {
        "standard_job_title": "政府信息化建设与管理岗",
        "standard_category": "政务信息化",
        "match_keywords": "信息化建设|信息化管理|政务信息管理|数字化建设|数字政府|信息系统规划|信息技术规划|信息技术管理|政务信息化|智慧海关",
    },
    {
        "standard_job_title": "政府信息系统开发岗",
        "standard_category": "政务软件与系统",
        "match_keywords": "系统开发|软件开发|应用开发|程序开发|软件设计|信息系统开发|平台开发",
    },
    {
        "standard_job_title": "政府信息系统运维岗",
        "standard_category": "政务软件与系统",
        "match_keywords": "系统维护|系统运维|运行维护|设备维护|服务器|机房|系统保障|技术维护",
    },
    {
        "standard_job_title": "政府网络与通信运维岗",
        "standard_category": "网络与基础设施",
        "match_keywords": "网络维护|网络运维|网络管理|网络设备|网络建设|通信网络|通信保障|无线电",
    },
    {
        "standard_job_title": "政府网络与数据安全岗",
        "standard_category": "网络与安全",
        "match_keywords": "网络安全|信息安全|数据安全|网络空间安全|密码|保密|安全运维|安全管理|攻防",
    },
    {
        "standard_job_title": "政府数据治理与统计分析岗",
        "standard_category": "数据与统计",
        "match_keywords": "数据治理|数据管理|数据分析|数据处理|数据开发|大数据|统计分析|统计调查|统计信息",
    },
    {
        "standard_job_title": "政府电子数据取证与情报技术岗",
        "standard_category": "政法信息技术",
        "match_keywords": "电子数据|数据取证|网络侦查|技术侦查|情报技术|信息化侦查|网络犯罪",
    },
    {
        "standard_job_title": "政府警务信息技术保障岗",
        "standard_category": "政法信息技术",
        "match_keywords": "计算机维护|计算机相关工作|警务信息化|智慧警务|智慧缉私|公安信息化",
    },
    {
        "standard_job_title": "政府信息化审计岗",
        "standard_category": "政务信息化",
        "match_keywords": "信息化审计|信息技术审计|审计信息化|信息系统审计",
    },
    {
        "standard_job_title": "政府数字监管与科技执法岗",
        "standard_category": "政务信息化",
        "match_keywords": "电子信息化类|科技管理|科技监管|技术监管|网络监管|信息化监管|风险防控",
    },
    {
        "standard_job_title": "政府智能化与自动化技术岗",
        "standard_category": "智能化技术",
        "match_keywords": "人工智能|智能化|自动化|机器人|智能系统|算法应用",
    },
    {
        "standard_job_title": "政府通信电子技术岗",
        "standard_category": "通信与电子技术",
        "match_keywords": "通信工程|电子信息|电子工程|信号|无线通信|通信技术",
    },
    {
        "standard_job_title": "政府地理信息与空间数据技术岗",
        "standard_category": "空间信息技术",
        "match_keywords": "地理信息|GIS|遥感|空间数据|卫星|测绘信息化",
    },
    {
        "standard_job_title": "政府通用计算机技术岗",
        "standard_category": "通用计算机技术",
        "match_keywords": "计算机类|计算机科学与技术|软件工程|网络工程|信息安全|数据科学与大数据技术|计算机应用",
    },
]


SKILL_DEFINITIONS = [
    ("计算机科学与技术", "计算机基础", "专业技术基础", ["计算机科学与技术", "计算机类", "计算机技术"]),
    ("软件工程", "软件工程", "专业技术基础", ["软件工程", "软件开发", "软件设计"]),
    ("信息系统", "政务信息化", "业务技术能力", ["信息系统", "信息化系统", "管理信息系统"]),
    ("信息化建设", "政务信息化", "业务技术能力", ["信息化建设", "政务信息化", "数字化建设", "数字政府"]),
    ("网络工程", "网络与基础设施", "专业技术基础", ["网络工程", "计算机网络", "网络技术"]),
    ("网络运维", "网络与基础设施", "业务技术能力", ["网络运维", "网络维护", "网络管理", "网络设备"]),
    ("系统运维", "网络与基础设施", "业务技术能力", ["系统运维", "系统维护", "运行维护", "技术维护"]),
    ("信息安全", "网络与安全", "专业技术基础", ["信息安全", "网络安全", "网络与信息安全"]),
    ("网络空间安全", "网络与安全", "专业技术基础", ["网络空间安全"]),
    ("数据安全", "网络与安全", "业务技术能力", ["数据安全", "安全管理", "安全运维"]),
    ("密码技术", "网络与安全", "专业技术基础", ["密码", "密码科学与技术", "密码技术"]),
    ("数据科学与大数据技术", "数据与统计", "专业技术基础", ["数据科学与大数据技术", "大数据技术", "数据科学"]),
    ("数据治理", "数据与统计", "业务技术能力", ["数据治理"]),
    ("数据管理", "数据与统计", "业务技术能力", ["数据管理"]),
    ("数据处理", "数据与统计", "业务技术能力", ["数据处理"]),
    ("数据分析", "数据与统计", "业务技术能力", ["数据分析", "数据挖掘"]),
    ("数据计算及应用", "数据与统计", "专业技术基础", ["数据计算及应用"]),
    ("统计分析", "数据与统计", "业务技术能力", ["统计分析", "统计调查"]),
    ("统计学", "数据与统计", "专业技术基础", ["统计学", "应用统计学"]),
    ("信息管理与信息系统", "政务信息化", "专业技术基础", ["信息管理与信息系统"]),
    ("大数据管理与应用", "政务信息化", "专业技术基础", ["大数据管理与应用"]),
    ("人工智能", "智能化技术", "专业技术基础", ["人工智能", "智能科学与技术", "智能系统"]),
    ("自动化", "智能化技术", "专业技术基础", ["自动化", "自动化类", "控制科学与工程"]),
    ("物联网工程", "智能化技术", "专业技术基础", ["物联网工程", "物联网"]),
    ("通信工程", "通信与电子技术", "专业技术基础", ["通信工程", "信息与通信工程", "通信技术"]),
    ("电子信息工程", "通信与电子技术", "专业技术基础", ["电子信息工程"]),
    ("电子信息", "通信与电子技术", "专业技术基础", ["电子信息", "电子与计算机工程"]),
    ("情报技术", "政法信息技术", "业务技术能力", ["情报技术", "技术侦查", "网络侦查", "信息化侦查"]),
    ("地理信息系统", "空间信息技术", "专业技术基础", ["地理信息", "GIS", "地理信息系统"]),
    ("遥感技术", "空间信息技术", "专业技术基础", ["遥感", "遥感科学与技术"]),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build government-only seed dictionaries.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source = pd.read_csv(args.input, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"job_title", "job_description", "publish_time", "source"}
    missing = sorted(required.difference(source.columns))
    if missing:
        raise ValueError(f"Government source is missing required columns: {missing}")
    if set(source["source"].astype(str).str.strip()) != {"government_jobs"}:
        raise ValueError("This builder only accepts the screened government_jobs source.")

    output_dir = args.output_dir
    skill_dir = output_dir / "skill_extract"
    skill_dir.mkdir(parents=True, exist_ok=True)
    texts = (source["job_title"].astype(str) + "\n" + source["job_description"].astype(str)).str.casefold()

    jobs = pd.DataFrame(JOB_DEFINITIONS)
    jobs.to_csv(output_dir / "standard_job_title_dictionary.csv", index=False, encoding="utf-8-sig")

    job_audit = jobs.copy()
    job_audit["matched_source_rows"] = [
        _matched_rows(texts, value) for value in job_audit["match_keywords"]
    ]
    job_audit["source_file"] = args.input.name
    job_audit.to_csv(output_dir / "job_dictionary_seed_audit.csv", index=False, encoding="utf-8-sig")

    normalized_rows: list[dict[str, str]] = []
    display_rows: list[dict[str, str]] = []
    extraction_rows: list[dict[str, str]] = []
    skill_audit_rows: list[dict[str, object]] = []
    for skill, display, skill_type, aliases in SKILL_DEFINITIONS:
        normalized_rows.append({"skill": skill})
        display_rows.append({"skill": skill, "kg_display_skill": display})
        alias_counts: dict[str, int] = {}
        for alias in aliases:
            count = int(texts.map(lambda value: value.count(alias.casefold())).sum())
            alias_counts[alias] = count
            extraction_rows.append(
                {
                    "skill_keyword": alias,
                    "normalized_skill": skill,
                    "kg_display_skill": display,
                }
            )
        skill_audit_rows.append(
            {
                "skill": skill,
                "kg_display_skill": display,
                "skill_type": skill_type,
                "alias_count": len(aliases),
                "matched_source_rows": int(texts.map(lambda value: any(alias.casefold() in value for alias in aliases)).sum()),
                "alias_match_counts": "; ".join(f"{alias}:{count}" for alias, count in alias_counts.items()),
                "source_file": args.input.name,
            }
        )

    pd.DataFrame(normalized_rows).to_csv(
        skill_dir / "归一化级词典.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(display_rows).to_csv(
        skill_dir / "展示级词典.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(extraction_rows).drop_duplicates().to_csv(
        skill_dir / "government_skill_dictionary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(skill_audit_rows).to_csv(
        output_dir / "skill_dictionary_seed_audit.csv", index=False, encoding="utf-8-sig"
    )

    zero_coverage = [
        row["skill"] for row in skill_audit_rows if int(row["matched_source_rows"]) == 0
    ]
    if zero_coverage:
        raise ValueError(f"Seed skills must occur in the government source: {zero_coverage}")

    print(
        {
            "source_rows": len(source),
            "job_dictionary_rows": len(jobs),
            "normalized_skill_rows": len(normalized_rows),
            "extraction_dictionary_rows": len(extraction_rows),
            "output_dir": str(output_dir),
        }
    )


def _matched_rows(texts: pd.Series, keyword_pattern: str) -> int:
    aliases = [item.strip().casefold() for item in keyword_pattern.split("|") if item.strip()]
    return int(texts.map(lambda value: any(alias in value for alias in aliases)).sum())


if __name__ == "__main__":
    main()
