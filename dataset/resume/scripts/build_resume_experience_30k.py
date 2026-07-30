from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


RESUME_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = RESUME_DIR / "synthetic_detailed_resumes_aligned.csv"
DEFAULT_OUTPUT = RESUME_DIR / "synthetic_detailed_resumes_experience_30k.csv"

YEAR_POOL = [0, 1, 2, 3, 5, 8, 10]
VARIANTS_PER_RESUME = 5
SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳"
GIVEN_NAMES = [
    "景然", "卓航", "思琪", "以恒", "沐辰", "书瑶", "泽宇", "嘉宁", "若溪", "知远",
    "明轩", "语晨", "一鸣", "芷晴", "星河", "安然", "子墨", "云帆", "雨桐", "清扬",
    "承泽", "亦凡", "昱辰", "若琳", "思远", "嘉禾", "悦然", "远洋", "佳宁", "谨言",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a single ~30k resume dataset with expanded experience years.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = pd.read_csv(args.input, dtype=str, encoding="utf-8-sig").fillna("")
    output_columns = list(source.columns)
    rows: list[dict[str, str]] = []
    for source_index, row in source.iterrows():
        base = row.to_dict()
        years_for_row = pick_years(source_index)
        for variant_index, years in enumerate(years_for_row):
            variant = build_variant(base, int(source_index), variant_index, years)
            rows.append({column: str(variant.get(column, "")) for column in output_columns})

    expanded = pd.DataFrame(rows, columns=output_columns)
    expanded.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"input_rows={len(source)}")
    print(f"variants_per_resume={VARIANTS_PER_RESUME}")
    print(f"output_rows={len(expanded)}")
    print(f"standard_jobs={expanded['standard_job'].nunique()}")
    print(f"standard_categories={expanded['standard_category'].nunique()}")
    print(f"output={args.output}")


def pick_years(source_index: int) -> list[int]:
    rotated = YEAR_POOL[source_index % len(YEAR_POOL) :] + YEAR_POOL[: source_index % len(YEAR_POOL)]
    return sorted(rotated[:VARIANTS_PER_RESUME])


def build_variant(base: dict[str, str], source_index: int, variant_index: int, years: int) -> dict[str, str]:
    row = dict(base)
    seed = source_index * 37 + variant_index * 97 + years * 13
    original_resume_id = str(base.get("resume_id", f"resume_{source_index:06d}"))
    standard_job = str(base.get("standard_job", base.get("standard_job_title", base.get("target_job_family", ""))))
    standard_category = str(base.get("standard_category", ""))
    skills = parse_json_list(base.get("skills_normalized", ""))
    profile_skills = parse_json_list(base.get("job_profile_skills", ""))

    row["resume_id"] = f"{original_resume_id}_exp{years:02d}_{variant_index}"
    row["name"] = make_name(seed)
    row["gender"] = "女" if seed % 2 else "男"
    row["age"] = str(make_age(base, years, seed))
    row["phone"] = f"13{(seed % 9) + 1}{(86000000 + seed) % 100000000:08d}"
    row["email"] = f"{row['resume_id'].replace('-', '_').lower()}@synthetic.local"
    row["years_experience"] = str(years)
    row["skill_levels"] = json.dumps(make_skill_levels(skills, profile_skills, years), ensure_ascii=False)
    row["experience"] = json.dumps(rewrite_experience(base.get("experience", ""), standard_job, years, skills), ensure_ascii=False)
    row["projects"] = json.dumps(rewrite_projects(base.get("projects", ""), standard_job, years, skills), ensure_ascii=False)
    row["profile_text"] = rewrite_profile_text(
        base.get("profile_text", ""),
        standard_job=standard_job,
        standard_category=standard_category,
        years=years,
        skills=skills,
    )
    return row


def rewrite_experience(raw: str, standard_job: str, years: int, skills: list[str]) -> list[dict[str, Any]]:
    parsed = parse_json(raw, default=[])
    if not isinstance(parsed, list) or not parsed:
        parsed = [{"company_type": "企业数字化团队", "role": standard_job, "duration_years": years, "keywords": skills[:10], "highlights": []}]
    durations = allocate_durations(years, len(parsed))
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        item["role"] = standard_job if index == 0 else str(item.get("role", f"{standard_job}项目成员"))
        item["duration_years"] = durations[index]
        item["keywords"] = merge_list(skills[:12], item.get("keywords", []), 14)
        item["highlights"] = experience_highlights(standard_job, years, skills)
    return parsed


def rewrite_projects(raw: str, standard_job: str, years: int, skills: list[str]) -> list[dict[str, Any]]:
    parsed = parse_json(raw, default=[])
    if not isinstance(parsed, list):
        return []
    scale = "large" if years >= 8 else "medium" if years >= 3 else "small"
    role = "负责人" if years >= 8 else "主要负责人" if years >= 5 else "核心成员" if years >= 2 else "参与成员"
    for item in parsed:
        if not isinstance(item, dict):
            continue
        item["project_scale"] = scale
        item["role"] = role
        item["tech_stack"] = merge_list(skills[:12], item.get("tech_stack", []), 14)
        item["description"] = f"围绕{standard_job}岗位能力，基于{skills[0]}、{skills[1]}、{skills[2]}完成方案设计、实现验证和效果复盘。"
        item["outcome"] = outcome_by_years(years)
    return parsed


def experience_highlights(standard_job: str, years: int, skills: list[str]) -> list[str]:
    if years <= 0:
        return [
            f"围绕{standard_job}方向完成课程项目、实训项目和实验室课题实践。",
            f"使用{skills[0]}、{skills[1]}、{skills[2]}完成原型验证和文档沉淀。",
            "具备基础工程实现、问题拆解和持续学习能力。",
        ]
    if years <= 2:
        return [
            f"参与{standard_job}相关模块开发、测试验证和线上问题跟进。",
            f"主要使用{skills[0]}、{skills[1]}、{skills[2]}支撑业务迭代。",
            "在资深同事指导下完成需求拆解、代码实现和交付复盘。",
        ]
    if years <= 5:
        return [
            f"独立负责{standard_job}方向核心模块的方案设计、开发落地和效果复盘。",
            f"围绕{skills[0]}、{skills[1]}、{skills[2]}优化关键链路，提升交付效率。",
            "参与跨团队协作、排期评估、风险识别和质量保障。",
        ]
    if years <= 8:
        return [
            f"主导{standard_job}方向多个核心项目，负责技术方案、任务拆解和质量把控。",
            f"基于{skills[0]}、{skills[1]}、{skills[2]}沉淀通用能力和可复用组件。",
            "承担模块负责人职责，推动性能、稳定性和工程效率持续优化。",
        ]
    return [
        f"作为{standard_job}方向骨干，负责技术规划、架构演进和关键项目攻坚。",
        f"围绕{skills[0]}、{skills[1]}、{skills[2]}建立团队级方法论和工程规范。",
        "指导新人和跨团队协同，推动复杂问题定位、方案评审和长期能力建设。",
    ]


def rewrite_profile_text(raw: str, standard_job: str, standard_category: str, years: int, skills: list[str]) -> str:
    lines = [line for line in str(raw).splitlines() if line.strip()]
    while lines and (lines[0].startswith("求职意向：") or lines[0].startswith("标准岗位：") or lines[0].startswith("岗位系统技能画像：")):
        lines.pop(0)
    prefix = [
        f"求职意向：{standard_job}。",
        f"标准岗位：{standard_job}；岗位大族：{standard_category}；经验年限：{years}年；候选人层级：{seniority_label(years)}。",
        f"岗位系统技能画像：{'、'.join(skills[:12])}。",
        f"个人概述：具备{years}年左右{standard_job}相关实践经验，熟悉{'、'.join(skills[:8])}，能够承担{responsibility_by_years(years)}。",
    ]
    body = []
    for line in lines:
        if line.startswith("个人概述："):
            continue
        if line.startswith("技能栈："):
            body.append(f"技能栈：{'、'.join(skills[:18])}。")
        elif line.startswith("工作经历："):
            body.append(f"工作经历：{standard_job}方向，累计{years}年相关实践，主要覆盖方案设计、开发实现、测试验证、问题定位和结果复盘。")
        else:
            body.append(line)
    return "\n".join(prefix + body)


def make_skill_levels(skills: list[str], profile_skills: list[str], years: int) -> dict[str, str]:
    profile = set(profile_skills)
    result = {}
    for index, skill in enumerate(skills):
        if years >= 8:
            result[skill] = "精通" if skill in profile and index < 10 else "熟练"
        elif years >= 5:
            result[skill] = "精通" if skill in profile and index < 5 else "熟练"
        elif years >= 3:
            result[skill] = "熟练" if index < 12 else "掌握"
        elif years >= 1:
            result[skill] = "掌握" if index < 12 else "了解"
        else:
            result[skill] = "掌握" if index < 8 else "了解"
    return result


def make_age(base: dict[str, str], years: int, seed: int) -> int:
    education = str(base.get("education", ""))
    base_age = 22 if education == "本科" else 25 if education == "硕士研究生" else 28 if education == "博士研究生" else 22
    return base_age + max(years, 0) + (seed % 3)


def make_name(seed: int) -> str:
    return SURNAMES[seed % len(SURNAMES)] + GIVEN_NAMES[(seed // len(SURNAMES)) % len(GIVEN_NAMES)]


def allocate_durations(years: int, count: int) -> list[int]:
    count = max(count, 1)
    if years <= 0:
        return [0] * count
    first = max(1, years - min(2, count - 1))
    durations = [first]
    remaining = years - first
    for _ in range(1, count):
        value = 1 if remaining > 0 else 0
        durations.append(value)
        remaining -= value
    durations[0] += max(remaining, 0)
    return durations[:count]


def seniority_label(years: int) -> str:
    if years <= 0:
        return "校招/无全职经验"
    if years <= 2:
        return "初级"
    if years <= 5:
        return "中级"
    if years <= 8:
        return "高级"
    return "专家"


def responsibility_by_years(years: int) -> str:
    if years <= 0:
        return "基础实践、原型验证和学习型任务"
    if years <= 2:
        return "模块开发、测试验证和问题跟进"
    if years <= 5:
        return "独立模块交付、跨团队协作和质量改进"
    if years <= 8:
        return "核心项目主导、方案评审和复杂问题攻坚"
    return "技术规划、架构演进、团队赋能和关键项目决策"


def outcome_by_years(years: int) -> str:
    if years <= 0:
        return "完成可演示原型和技术文档"
    if years <= 2:
        return "提升问题定位和交付效率"
    if years <= 5:
        return "将关键流程耗时降低约 20%"
    if years <= 8:
        return "支撑多业务线稳定复用"
    return "沉淀团队级技术规范并支撑复杂业务规模化落地"


def parse_json(value: str, default: Any) -> Any:
    try:
        return json.loads(str(value))
    except Exception:
        return default


def parse_json_list(value: str) -> list[str]:
    parsed = parse_json(value, default=[])
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def merge_list(primary: list[str], secondary: Any, limit: int) -> list[str]:
    if not isinstance(secondary, list):
        secondary = []
    return dedupe([*primary, *[str(item) for item in secondary]])[:limit]


def dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        item = str(item).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


if __name__ == "__main__":
    main()
