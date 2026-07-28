from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


DATASET_ROOT = Path(__file__).resolve().parents[1]
INPUT = DATASET_ROOT / "cleaned" / "government_jobs_2026_normalized.csv"
OUTPUT = DATASET_ROOT / "cleaned" / "government_jobs_2026_tech_filtered.csv"
AUDIT_OUTPUT = DATASET_ROOT / "cleaned" / "government_jobs_2026_tech_filter_audit.csv"

TECH_GROUP = "计算机相关技术岗"

COMPUTER_MAJOR_WORDS = [
    "计算机",
    "软件工程",
    "软件",
    "网络工程",
    "网络空间安全",
    "信息安全",
    "网络安全",
    "数据安全",
    "信息系统",
    "信息管理与信息系统",
    "数据库",
    "大数据",
    "数据科学与大数据技术",
    "人工智能",
    "智能科学与技术",
    "算法",
    "信息技术",
    "电子政务",
    "数字媒体技术",
    "空间信息与数字技术",
    "物联网工程",
    "区块链工程",
    "密码科学与技术",
    "保密技术",
    "电子与计算机工程",
    "计算机技术",
    "大数据技术与工程",
]

COMPUTER_WORK_WORDS = [
    "信息化",
    "信息技术",
    "信息科技",
    "金融科技",
    "科技建设",
    "数字技术",
    "数字化",
    "电子政务",
    "智慧海关",
    "智慧监管",
    "智慧",
    "信息系统",
    "系统运行",
    "系统运维",
    "运行维护",
    "系统维护",
    "信息系统运行维护",
    "软硬件管理",
    "电子设备软硬件管理",
    "计算机维护",
    "网络日常维护",
    "通信网络日常维护",
    "网络安全",
    "信息安全",
    "数据安全",
    "安全保障",
    "数据处理",
    "数据分析",
    "数据统计分析",
    "数据建模",
    "大数据",
    "数据库",
    "数据采集",
    "数据应用",
    "数据管理",
    "软件研发",
    "软件开发",
    "项目开发",
    "程序开发",
    "研发",
    "人工智能",
    "智能分析",
    "算法",
    "云计算",
    "区块链",
    "密码",
    "保密",
    "文件传输",
    "设备安全保障",
]

STRONG_TITLE_WORDS = [
    "信息化",
    "网络安全",
    "信息安全",
    "数据",
    "计算机",
    "软件",
    "系统",
    "科技部门",
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

EXCLUDE_WORK_WORDS = [
    "法务",
    "财务",
    "会计",
    "审计",
    "文秘",
    "党务",
    "党建",
    "宣传",
    "文字",
    "组织宣传",
    "综合文秘",
    "行政管理",
    "人事",
    "纪检",
    "税收征管",
    "税费征收",
    "纳税服务",
    "税务相关工作",
    "税收相关工作",
    "税费征收管理",
    "综合税费管理",
    "邮政行业监督管理",
    "金融非现场监管、现场检查及其他金融监管工作",
    "金融非现场监管、现场检查及其他金融监管综合工作",
]


def main() -> None:
    jobs = pd.read_csv(INPUT, dtype=str, encoding="utf-8-sig").fillna("")
    matches = jobs.apply(classify_row, axis=1)
    audit = jobs.copy()
    audit["is_tech_related"] = [item["is_tech_related"] for item in matches]
    audit["tech_group"] = [item["tech_group"] for item in matches]
    audit["tech_filter_reason"] = [item["tech_filter_reason"] for item in matches]
    audit["matched_keywords"] = [item["matched_keywords"] for item in matches]
    audit["match_score"] = [item["match_score"] for item in matches]

    filtered = jobs[audit["is_tech_related"]].copy()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    audit.to_csv(AUDIT_OUTPUT, index=False, encoding="utf-8-sig")

    print(f"input_rows={len(jobs)}")
    print(f"filtered_rows={len(filtered)}")
    print(f"filtered_rate={len(filtered) / len(jobs):.4f}")
    print(f"output={OUTPUT}")
    print(f"audit_output={AUDIT_OUTPUT}")
    print(f"group_counts:")
    print(f"  {TECH_GROUP}: {len(filtered)}")


def classify_row(row: pd.Series) -> dict[str, object]:
    title = clean(row.get("job_title"))
    tags = clean(row.get("tags"))
    description = clean(row.get("job_description"))
    company = clean(row.get("company_name"))

    intro_text, major_text = extract_intro_and_major(tags, description)
    title_intro = "\n".join([title, intro_text])
    all_text = "\n".join([title_intro, major_text, company])

    title_hits = hit_words(title, STRONG_TITLE_WORDS)
    work_hits = hit_words(title_intro, COMPUTER_WORK_WORDS)
    major_hits = hit_words(major_text, COMPUTER_MAJOR_WORDS)
    non_computer_hits = hit_words(major_text, NON_COMPUTER_MAJOR_WORDS)
    exclude_hits = hit_words("\n".join([title, intro_text]), EXCLUDE_WORK_WORDS)

    has_computer_major = bool(major_hits)
    has_computer_work = bool(work_hits)
    has_title_signal = bool(title_hits)

    score = 0
    reasons: list[str] = []
    if has_title_signal:
        score += 2
        reasons.append("title:" + "|".join(title_hits))
    if has_computer_work:
        score += 3
        reasons.append("work:" + "|".join(work_hits))
    if has_computer_major:
        score += 2
        reasons.append("major:" + "|".join(major_hits))
    if non_computer_hits and not has_computer_major:
        score -= 3
        reasons.append("non_computer_major:" + "|".join(non_computer_hits[:8]))
    if exclude_hits and not has_computer_work:
        score -= 3
        reasons.append("exclude_work:" + "|".join(exclude_hits))

    is_tech_related = False
    if has_computer_work and (has_computer_major or has_title_signal):
        is_tech_related = True
    elif has_strong_computer_work(title_intro):
        is_tech_related = True
    elif has_title_signal and has_computer_major and not exclude_hits:
        is_tech_related = True

    if is_tech_related and is_false_positive(title, intro_text, major_text):
        is_tech_related = False
        reasons.append("blocked:false_positive_rule")

    matched_keywords = sorted(set(title_hits + work_hits + major_hits + non_computer_hits))
    return {
        "is_tech_related": bool(is_tech_related),
        "tech_group": TECH_GROUP if is_tech_related else "",
        "tech_filter_reason": "; ".join(reasons),
        "matched_keywords": "; ".join(matched_keywords),
        "match_score": score,
    }


def has_strong_computer_work(text: str) -> bool:
    clear_terms = [
        "信息系统",
        "信息化",
        "数字技术",
        "数据建模",
        "大数据",
        "网络安全",
        "信息安全",
        "信息系统运行维护",
        "系统运维",
        "软件研发",
        "软件开发",
        "人工智能",
        "智能分析",
        "计算机维护",
        "通信网络日常维护",
    ]
    return any(term in text for term in clear_terms)


def is_false_positive(title: str, intro_text: str, major_text: str) -> bool:
    title_intro = "\n".join([title, intro_text])
    if "高新技术产业园区" in title and not has_strong_computer_work(title_intro):
        return True
    if "专业技术员" in title and hit_words(title_intro, ["税务", "税收"]) and not has_strong_computer_work(title_intro):
        return True
    if hit_words(title_intro, ["综合管理", "党建", "宣传", "文秘", "财务", "法务", "审计"]) and not has_strong_computer_work(title_intro):
        return True
    if hit_words(title_intro, ["新媒体账号运行维护", "数字媒体制作发布"]) and not hit_words(major_text, COMPUTER_MAJOR_WORDS):
        return True
    if hit_words(major_text, NON_COMPUTER_MAJOR_WORDS) and not hit_words(major_text, COMPUTER_MAJOR_WORDS):
        return True
    return False


def extract_intro_and_major(tags: str, description: str) -> tuple[str, str]:
    intro_pieces = []
    major_pieces = [tags]
    for line in re.split(r"[\r\n]+", description):
        if line.startswith("职位简介："):
            intro_pieces.append(line.removeprefix("职位简介："))
        elif line.startswith("专业要求："):
            major_pieces.append(line.removeprefix("专业要求："))
    return "\n".join(intro_pieces), "\n".join(major_pieces)


def hit_words(text: str, words: list[str]) -> list[str]:
    return sorted({word for word in words if word and word in text})


def clean(value: object) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    main()
