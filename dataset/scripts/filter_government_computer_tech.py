from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


COMPUTER_MAJOR_WORDS = [
    "计算机",
    "软件",
    "软件工程",
    "网络工程",
    "网络空间安全",
    "信息安全",
    "网络安全",
    "数据安全",
    "信息系统",
    "信息管理与信息系统",
    "数据库",
    "大数据",
    "数据科学",
    "数据计算",
    "信息与计算科学",
    "人工智能",
    "智能科学与技术",
    "算法",
    "信息技术",
    "电子政务",
    "数字媒体技术",
    "空间信息与数字技术",
    "物联网",
    "区块链",
    "密码",
    "保密技术",
    "电子与计算机工程",
]

ADJACENT_MAJOR_WORDS = [
    "电子信息",
    "电子信息工程",
    "电子科学与技术",
    "通信工程",
    "通信与信息系统",
    "信息与通信工程",
    "集成电路",
    "微电子",
]

STRONG_WORK_WORDS = [
    "信息系统",
    "系统运行",
    "系统运维",
    "运行维护",
    "系统维护",
    "信息系统运行维护",
    "软硬件管理",
    "计算机维护",
    "网络日常维护",
    "通信网络日常维护",
    "网络运行技术保障",
    "网络运行",
    "网络安全",
    "信息安全",
    "数据安全",
    "数据库",
    "大数据",
    "数据处理",
    "数据分析",
    "数据建模",
    "数据采集",
    "数据应用",
    "数据管理",
    "软件研发",
    "软件开发",
    "项目开发",
    "程序开发",
    "人工智能",
    "智能分析",
    "算法",
    "云计算",
    "区块链",
    "信息化管理",
    "信息技术规划",
    "信息化系统",
    "技术保障",
]

WEAK_WORK_WORDS = [
    "智慧海关",
    "智慧监管",
    "智慧",
    "科技建设",
    "研发",
    "信息化建设",
    "数字化",
    "数据统计分析",
]

TITLE_WORDS = [
    "信息化",
    "信息管理",
    "网络安全",
    "信息安全",
    "数据",
    "计算机",
    "软件",
    "系统",
    "技术保障",
]

NON_COMPUTER_MAJOR_WORDS = [
    "土木工程",
    "工程管理",
    "工程造价",
    "建筑",
    "水利",
    "交通运输",
    "交通工程",
    "机械",
    "材料",
    "能源动力",
    "电气",
    "自动化",
    "化学",
    "化工",
    "矿业",
    "采矿",
    "冶金",
    "生物",
    "医学",
    "药学",
    "食品",
    "环境",
    "生态",
    "农学",
    "林学",
    "气象",
    "大气科学",
    "海洋",
    "统计学",
    "应用统计",
    "数学",
]

NON_COMPUTER_ROLE_WORDS = [
    "罪犯管理",
    "治安管理",
    "基层海事执法",
    "海事执法",
    "食品检验",
    "动植物检疫",
    "口岸一线",
    "查验监管",
    "基建管理",
    "防汛抗旱",
    "抢险救灾",
    "水利工程建设",
    "工程建设",
    "工程运行",
    "工程质量监督",
    "自然资源督察",
    "文稿起草",
    "综合管理",
    "党建",
    "离退休干部",
    "行政事务",
    "国家审计工作",
    "税收征管",
    "纳税服务",
    "财务管理",
    "出纳",
    "会计",
    "河道巡查",
    "水行政执法",
]


def hit_words(text: str, words: list[str]) -> list[str]:
    return sorted({word for word in words if word in text})


def extract_intro_and_major(row: pd.Series) -> tuple[str, str]:
    tags = str(row.get("tags", ""))
    desc = str(row.get("job_description", ""))
    intro = []
    major = [tags]
    for line in desc.splitlines():
        if line.startswith("职位简介："):
            intro.append(line.removeprefix("职位简介："))
        elif line.startswith("专业要求："):
            major.append(line.removeprefix("专业要求："))
    return "\n".join(intro), "\n".join(major)


def classify(row: pd.Series) -> dict[str, object]:
    title = str(row.get("job_title", "")).strip()
    intro, major = extract_intro_and_major(row)
    title_intro = "\n".join([title, intro])

    title_hits = hit_words(title, TITLE_WORDS)
    work_hits = hit_words(title_intro, STRONG_WORK_WORDS)
    weak_hits = hit_words(title_intro, WEAK_WORK_WORDS)
    major_hits = hit_words(major, COMPUTER_MAJOR_WORDS)
    adjacent_hits = hit_words(major, ADJACENT_MAJOR_WORDS)
    non_major_hits = hit_words(major, NON_COMPUTER_MAJOR_WORDS)
    non_role_hits = hit_words(title_intro, NON_COMPUTER_ROLE_WORDS)

    concrete_terms = {
        "网络安全",
        "信息安全",
        "信息系统",
        "系统运维",
        "系统维护",
        "计算机维护",
        "软件开发",
        "软件研发",
        "程序开发",
        "数据库",
        "云计算",
        "人工智能",
    }
    has_concrete_work = any(term in title_intro for term in concrete_terms)

    is_related = False
    if non_role_hits and not has_concrete_work:
        is_related = False
    elif non_major_hits and not major_hits and not (adjacent_hits and has_concrete_work):
        is_related = False
    elif major_hits and (title_hits or work_hits or not non_role_hits):
        is_related = True
    elif adjacent_hits and work_hits and not non_role_hits:
        is_related = True
    elif work_hits and (title_hits or has_concrete_work) and not (non_major_hits and not major_hits):
        is_related = True

    reason_parts = []
    for label, hits in [
        ("title", title_hits),
        ("work", work_hits),
        ("weak_work", weak_hits),
        ("major", major_hits),
        ("adjacent_major", adjacent_hits),
        ("non_computer_major", non_major_hits),
        ("non_computer_role", non_role_hits),
    ]:
        if hits:
            reason_parts.append(f"{label}:{'|'.join(hits[:10])}")

    return {
        "is_computer_tech": bool(is_related),
        "computer_tech_filter_reason": "; ".join(reason_parts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Keep only computer-industry-related government technical jobs.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()

    audit_output = args.audit_output
    if audit_output is None:
        audit_output = args.output.with_name(args.output.stem + "_audit.csv")

    df = pd.read_csv(args.input, dtype=str, encoding="utf-8-sig").fillna("")
    results = df.apply(classify, axis=1)
    audit = df.copy()
    audit["is_computer_tech"] = [item["is_computer_tech"] for item in results]
    audit["computer_tech_filter_reason"] = [item["computer_tech_filter_reason"] for item in results]
    filtered = df[audit["is_computer_tech"]].copy()

    if args.output.resolve() == args.input.resolve():
        tmp = args.output.with_suffix(args.output.suffix + ".tmp")
        filtered.to_csv(tmp, index=False, encoding="utf-8-sig")
        tmp.replace(args.output)
    else:
        filtered.to_csv(args.output, index=False, encoding="utf-8-sig")
    audit.to_csv(audit_output, index=False, encoding="utf-8-sig")

    print(f"input_rows={len(df)}")
    print(f"filtered_rows={len(filtered)}")
    print(f"removed_rows={len(df) - len(filtered)}")
    print(f"filtered_rate={len(filtered) / len(df):.4f}")
    print(f"output={args.output}")
    print(f"audit_output={audit_output}")


if __name__ == "__main__":
    main()
