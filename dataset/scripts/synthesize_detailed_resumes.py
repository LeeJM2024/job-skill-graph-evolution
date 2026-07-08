"""Generate detailed synthetic resumes from the structured resume table.

The generator uses only the original resume fields and aggregate enterprise
job-keyword vocabulary. It deliberately avoids conditioning on any single JD so
that later resume-job matching experiments do not leak target job answers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DATASET_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RESUMES = DATASET_DIR / "resume" / "revise_Chinese_resume_data_UTF8_BOM_可读版.csv"
DEFAULT_KEYWORDS = DATASET_DIR / "structured" / "job_keyword_vocabulary_enterprise.csv"
DEFAULT_ALIASES = DATASET_DIR / "config" / "skill_aliases.json"
DEFAULT_OUTPUT_DIR = DATASET_DIR / "resume"

SKILL_GROUPS = (
    ("编程语言", "编程语言熟练度", "programming_language"),
    ("前端技术", "前端技术熟练度", "frontend"),
    ("后端技术", "后端技术熟练度", "backend"),
    ("数据库", "数据库熟练度", "database"),
    ("云计算/运维", "云计算/运维熟练度", "cloud_devops"),
    ("数据与算法", "数据与算法熟练度", "data_ai"),
    ("移动开发", "移动开发熟练度", "mobile"),
    ("测试工具", "测试工具熟练度", "testing"),
)

EXPERIENCE_FIELDS = (
    ("小型企业工作经验", "small"),
    ("中型企业工作经验", "medium"),
    ("大型企业工作经验", "large"),
)

PROJECT_FIELDS = (
    ("小规模项目", "small"),
    ("中规模项目", "medium"),
    ("大规模项目", "large"),
)

EDUCATION_PLAN = (
    ("本科", 0.60),
    ("硕士研究生", 0.30),
    ("博士研究生", 0.10),
)
EXTRA_ASSOCIATE_COUNT = 500

DEGREE_BY_EDUCATION = {
    "专科": "无学位",
    "本科": "学士",
    "硕士研究生": "硕士",
    "博士研究生": "博士",
}

SCHOOL_BY_EDUCATION = {
    "专科": ("高职院校", "普通专科", "职业技术学院"),
    "本科": ("普通高校", "211高校", "双一流高校"),
    "硕士研究生": ("211高校", "双一流高校", "985高校"),
    "博士研究生": ("双一流高校", "985高校", "海外高校"),
}

MAJOR_BY_FAMILY = {
    "算法工程师": ("计算机科学与技术", "人工智能", "软件工程", "模式识别与智能系统"),
    "数据分析师": ("统计学", "数据科学与大数据技术", "信息管理与信息系统", "应用数学"),
    "数据工程师": ("数据科学与大数据技术", "软件工程", "计算机科学与技术", "信息工程"),
    "云计算工程师": ("计算机科学与技术", "网络工程", "软件工程", "信息安全"),
    "运维工程师": ("网络工程", "计算机科学与技术", "信息安全", "软件工程"),
    "后端开发工程师": ("软件工程", "计算机科学与技术", "信息工程", "网络工程"),
    "前端开发工程师": ("软件工程", "数字媒体技术", "计算机科学与技术", "交互设计"),
    "移动开发工程师": ("软件工程", "计算机科学与技术", "移动应用开发", "数字媒体技术"),
    "测试工程师": ("软件工程", "计算机科学与技术", "信息安全", "质量管理工程"),
    "全栈开发工程师": ("软件工程", "计算机科学与技术", "信息工程", "网络工程"),
}

FAMILY_CATEGORIES = {
    "算法工程师": ("AI与大模型", "数据与算法", "AI基础设施", "AI框架", "编程语言", "数据工程", "软件工程"),
    "数据分析师": ("数据分析", "数据工程", "数据与算法", "数据库", "产品运营", "编程语言"),
    "数据工程师": ("数据工程", "数据库", "云原生与运维", "编程语言", "软件工程", "数据与算法"),
    "云计算工程师": ("云原生与运维", "AI基础设施", "数据库", "软件工程", "编程语言", "项目管理"),
    "运维工程师": ("云原生与运维", "测试质量", "数据库", "软件工程", "安全", "编程语言"),
    "后端开发工程师": ("后端技术", "软件工程", "数据库", "云原生与运维", "编程语言", "数据工程"),
    "前端开发工程师": ("前端技术", "软件工程", "产品运营", "编程语言", "数据分析"),
    "移动开发工程师": ("移动开发", "前端技术", "产品运营", "软件工程", "编程语言", "测试质量"),
    "测试工程师": ("测试质量", "测试工具", "软件工程", "云原生与运维", "数据库", "编程语言"),
    "全栈开发工程师": ("前端技术", "后端技术", "软件工程", "数据库", "云原生与运维", "编程语言"),
}

FAMILY_DEFAULT_SKILLS = {
    "算法工程师": ["Python", "PyTorch", "TensorFlow", "机器学习", "深度学习", "大模型", "RAG", "模型训练", "模型推理"],
    "数据分析师": ["SQL", "Python", "Pandas", "数据分析", "数据可视化", "Tableau", "Power BI", "经营分析"],
    "数据工程师": ["SQL", "Python", "Spark", "Flink", "Kafka", "数据仓库", "ETL", "数据治理"],
    "云计算工程师": ["Linux", "Docker", "Kubernetes", "Terraform", "云计算", "Prometheus", "Grafana", "CI/CD"],
    "运维工程师": ["Linux", "Shell", "Docker", "Kubernetes", "Prometheus", "Grafana", "自动化运维", "故障排查"],
    "后端开发工程师": ["Java", "Spring Boot", "MySQL", "Redis", "微服务", "高并发", "分布式系统", "Kafka"],
    "前端开发工程师": ["JavaScript", "TypeScript", "React", "Vue", "前端工程化", "性能优化", "用户体验"],
    "移动开发工程师": ["Android", "iOS", "Flutter", "React Native", "移动端性能优化", "自动化测试"],
    "测试工程师": ["Selenium", "JMeter", "Postman", "自动化测试", "性能测试", "接口测试", "质量保障"],
    "全栈开发工程师": ["JavaScript", "TypeScript", "Node.js", "React", "Spring Boot", "MySQL", "Docker", "微服务"],
}

PROJECT_TEMPLATES = {
    "算法工程师": (
        ("企业知识库 RAG 问答平台", "负责语义检索、召回排序、Prompt 模板和效果评估，沉淀离线评测集并优化回答准确率。"),
        ("多模态内容理解与标签系统", "参与图文特征抽取、模型训练和推理服务部署，支持业务侧内容审核与推荐分发。"),
        ("大模型推理性能优化", "围绕批处理、缓存、量化和 GPU 资源利用率进行调优，降低在线推理延迟。"),
    ),
    "数据分析师": (
        ("业务经营分析看板", "建设核心指标体系，使用 SQL 和 BI 工具输出日活、留存、转化和收入分析。"),
        ("用户增长归因分析", "围绕渠道、活动和用户分层构建分析模型，支持运营策略迭代。"),
        ("异常波动监控与复盘", "搭建自动化监控报表，定位指标波动原因并输出数据结论。"),
    ),
    "数据工程师": (
        ("实时数仓与数据治理平台", "负责采集链路、ETL 任务、数据质量校验和主题域建模，提升数据可用性。"),
        ("日志数据实时处理链路", "基于 Kafka/Flink/Spark 完成实时计算任务，支持业务监控和画像分析。"),
        ("离线任务调度与成本优化", "梳理批处理任务依赖，优化资源使用和任务稳定性。"),
    ),
    "云计算工程师": (
        ("企业 Kubernetes 容器平台", "负责集群规划、服务发布、监控告警和资源隔离，支撑多业务应用上云。"),
        ("云资源自动化交付平台", "使用 Terraform 和脚本完成资源编排、权限配置和交付流程标准化。"),
        ("混合云稳定性治理", "参与容量评估、故障演练和成本优化，提升云平台可用性。"),
    ),
    "运维工程师": (
        ("统一监控告警平台", "接入主机、容器、数据库和业务指标，设计告警规则并推进故障闭环。"),
        ("自动化发布与巡检系统", "编写脚本和流水线任务，减少人工发布风险并提升巡检效率。"),
        ("线上故障应急与稳定性治理", "参与故障定位、容量扩容、复盘改进和应急预案建设。"),
    ),
    "后端开发工程师": (
        ("高并发订单服务改造", "负责核心接口、缓存策略、消息队列和数据库索引优化，提升峰值吞吐。"),
        ("微服务治理与网关平台", "参与服务拆分、限流熔断、链路追踪和配置中心建设。"),
        ("企业级权限与账号系统", "实现角色权限、审计日志和多端登录能力，保障业务安全。"),
    ),
    "前端开发工程师": (
        ("企业级运营管理后台", "负责组件库封装、状态管理、权限路由和复杂表单交互。"),
        ("数据可视化大屏", "实现图表组件、实时数据刷新和性能优化，支持业务运营分析。"),
        ("前端工程化体系建设", "推进构建优化、代码规范、自动化测试和发布流程标准化。"),
    ),
    "移动开发工程师": (
        ("移动端核心业务模块重构", "负责页面架构、网络层封装、缓存策略和性能优化。"),
        ("跨端组件与发布体系", "沉淀通用组件，提升 Android/iOS 多端研发效率。"),
        ("移动端稳定性治理", "跟进崩溃率、卡顿、启动耗时和自动化测试覆盖。"),
    ),
    "测试工程师": (
        ("接口自动化测试平台", "设计用例管理、接口执行、报告生成和 CI 集成流程。"),
        ("性能压测与容量评估", "使用压测工具定位瓶颈，输出容量基线和优化建议。"),
        ("质量度量与缺陷治理", "建立缺陷分析、回归测试和质量看板，推动研发流程改进。"),
    ),
    "全栈开发工程师": (
        ("SaaS 业务系统全栈开发", "负责前端页面、后端接口、数据库设计和部署发布。"),
        ("低代码配置平台", "实现表单配置、流程编排、权限控制和可视化搭建能力。"),
        ("业务中台能力建设", "参与公共组件、服务接口和数据看板建设，支撑多业务复用。"),
    ),
}

OUTPUT_COLUMNS = (
    "resume_id",
    "name",
    "gender",
    "age",
    "phone",
    "email",
    "split",
    "target_job_family",
    "education",
    "degree",
    "school_category",
    "major",
    "english_level",
    "years_experience",
    "experience",
    "projects",
    "skills_normalized",
    "skill_levels",
    "job_keywords_used",
    "profile_text",
)

SURNAMES = (
    "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
)

GIVEN_NAME_CHARS = (
    "一", "子", "梓", "宇", "浩", "泽", "晨", "睿", "嘉", "欣",
    "思", "雨", "涵", "佳", "明", "远", "宁", "然", "航", "琪",
    "悦", "博", "文", "清", "辰", "安", "卓", "洋", "彤", "昊",
)

PHONE_PREFIXES = ("130", "131", "132", "155", "156", "166", "176", "185", "186", "188")
EMAIL_DOMAINS = ("qq.com", "163.com", "126.com", "gmail.com", "outlook.com", "hotmail.com")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").strip().split())


def split_values(value: Any) -> list[str]:
    text = clean(value)
    return [part.strip() for part in text.split(",") if part.strip()] if text else []


def stable_int(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)


def stable_id(original_id: Any) -> str:
    digest = hashlib.sha256(f"chinese-resume-v1:{clean(original_id)}".encode("utf-8")).hexdigest()
    return f"resume_{digest[:16]}"


def split_name(group_key: str) -> str:
    bucket = stable_int(group_key) % 100
    if bucket < 60:
        return "train"
    if bucket < 80:
        return "dev"
    return "test"


def choose(items: list[str] | tuple[str, ...], seed: str, offset: int = 0) -> str:
    if not items:
        return ""
    return list(items)[(stable_int(f"{seed}:{offset}") % len(items))]


def pick_many(items: list[str], seed: str, count: int) -> list[str]:
    if not items:
        return []
    scored = sorted((stable_int(f"{seed}:{item}"), item) for item in dict.fromkeys(items))
    return [item for _, item in scored[:count]]


def build_identity(public_index: int, education: str, years: int, seed: str) -> dict[str, Any]:
    gender = choose(("男", "女"), seed, 10)
    surname = choose(SURNAMES, seed, 11)
    given_len = 1 + stable_int(f"{seed}:given-len") % 2
    given = "".join(choose(GIVEN_NAME_CHARS, seed, 20 + index) for index in range(given_len))
    base_age = {
        "专科": 21,
        "本科": 22,
        "硕士研究生": 25,
        "博士研究生": 28,
    }.get(education, 22)
    age = min(45, max(20, base_age + years + stable_int(f"{seed}:age-jitter") % 4))
    phone_prefix = choose(PHONE_PREFIXES, seed, 30)
    phone_suffix = stable_int(f"{seed}:phone") % 100_000_000
    phone = f"{phone_prefix}{phone_suffix:08d}"
    email_domain = choose(EMAIL_DOMAINS, seed, 40)
    email_token = stable_int(f"{seed}:email") % 10_000_000
    email = f"resume{public_index:06d}{email_token:07d}@{email_domain}"
    return {
        "name": f"{surname}{given}",
        "gender": gender,
        "age": age,
        "phone": phone,
        "email": email,
    }


def load_aliases(path: Path) -> dict[str, list[str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_keyword_pool(path: Path) -> dict[str, list[str]]:
    pool: dict[str, list[str]] = defaultdict(list)
    bad_fragments = (
        "解决方案",
        "岗位群",
        "提供",
        "确保",
        "包括",
        "披露",
        "运用",
        "负责",
        "相关",
        "学历代码",
        "腾讯云-",
        "华为云-",
        "PUBG",
        "王者荣耀",
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            keyword = clean(row.get("normalized_keyword"))
            category = clean(row.get("category"))
            keyword_type = clean(row.get("keyword_type"))
            if not keyword or not category:
                continue
            if keyword_type == "title_or_tag" and category == "岗位标签":
                continue
            if keyword_type == "title_or_tag" and category != "岗位角色":
                continue
            if keyword_type == "auto_phrase":
                continue
            if keyword_type == "auto_english" and len(keyword) <= 3 and keyword not in {"AI", "RAG", "GPU", "NPU", "SQL", "UE5"}:
                continue
            if len(keyword) > 28:
                continue
            if keyword[0] in {"责", "如", "等", "和", "及", "或", "与", "为", "在", "对"}:
                continue
            if any(fragment in keyword for fragment in bad_fragments):
                continue
            if re.search(r"学历代码|工作经验|社会招聘|全量补充岗位|[等或如][\u4e00-\u9fff]{2,}|[（(][一二三四五六七八九十0-9]+[）)]", keyword):
                continue
            pool[category].append(keyword)
    return {key: list(dict.fromkeys(values)) for key, values in pool.items()}


def assign_education(rows: list[dict[str, str]]) -> dict[str, str]:
    total = len(rows)
    counts = {
        name: int(total * ratio)
        for name, ratio in EDUCATION_PLAN
    }
    # Put rounding residue into undergraduate so the 60/30/10 plan remains stable.
    counts["本科"] += total - sum(counts.values())
    ordered = sorted(rows, key=lambda row: stable_int(f"education:{clean(row.get('简历编号'))}"))
    education_by_id: dict[str, str] = {}
    cursor = 0
    for education, _ratio in EDUCATION_PLAN:
        for row in ordered[cursor : cursor + counts[education]]:
            education_by_id[clean(row.get("简历编号"))] = education
        cursor += counts[education]
    return education_by_id


def select_extra_associate_rows(rows: list[dict[str, str]], count: int = EXTRA_ASSOCIATE_COUNT) -> list[dict[str, str]]:
    associate_rows = [row for row in rows if clean(row.get("学历层次")) == "专科"]
    if len(associate_rows) < count:
        raise ValueError(f"Need {count} associate-source rows, found {len(associate_rows)}")
    return sorted(
        associate_rows,
        key=lambda row: stable_int(f"associate-extra:{clean(row.get('简历编号'))}"),
    )[:count]


def expand_skills(row: dict[str, str], aliases: dict[str, list[str]]) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    normalized: list[str] = []
    levels: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    for skill_col, level_col, group_name in SKILL_GROUPS:
        raw_skills = split_values(row.get(skill_col))
        raw_levels = split_values(row.get(level_col))
        grouped[group_name] = []
        for index, raw_skill in enumerate(raw_skills):
            level = raw_levels[index] if index < len(raw_levels) else "未标注"
            for skill in aliases.get(raw_skill, [raw_skill]):
                if skill not in normalized:
                    normalized.append(skill)
                grouped[group_name].append(skill)
                previous = levels.get(skill)
                if not previous or previous == "未标注":
                    levels[skill] = level
    return normalized, levels, grouped


def estimate_years(row: dict[str, str], education: str) -> int:
    score = 0
    for column, weight in (("大型企业工作经验", 4), ("中型企业工作经验", 3), ("小型企业工作经验", 2)):
        value = clean(row.get(column))
        if "5" in value:
            score += weight + 3
        elif "3" in value:
            score += weight + 2
        elif "1" in value:
            score += weight
    if score == 0:
        score = stable_int(f"years:{clean(row.get('简历编号'))}") % 3
    years = max(0, min(10, score // 2))
    if education == "硕士研究生":
        years = max(1, min(8, years))
    elif education == "博士研究生":
        years = max(1, min(6, years))
    elif education == "专科":
        years = max(0, min(6, years))
    return years


def build_keyword_profile(
    family: str,
    base_skills: list[str],
    keyword_pool: dict[str, list[str]],
    seed: str,
) -> list[str]:
    categories = FAMILY_CATEGORIES.get(family, ("软件工程", "编程语言", "数据库"))
    keywords: list[str] = []
    for category in categories:
        category_terms = keyword_pool.get(category, [])
        take = 4 if category in {"AI与大模型", "数据与算法", "AI基础设施", "云原生与运维"} else 3
        keywords.extend(pick_many(category_terms, f"{seed}:{category}", take))
    keywords.extend(FAMILY_DEFAULT_SKILLS.get(family, []))
    keywords.extend(base_skills)
    clean_keywords = []
    for keyword in keywords:
        keyword = clean(keyword)
        if keyword and keyword not in clean_keywords:
            clean_keywords.append(keyword)
    return clean_keywords[:28]


def build_education(row: dict[str, str], education: str, seed: str) -> dict[str, str]:
    family = clean(row.get("意向岗位"))
    major = choose(MAJOR_BY_FAMILY.get(family, ("计算机科学与技术", "软件工程")), seed)
    school = choose(SCHOOL_BY_EDUCATION[education], seed, 1)
    original_english = clean(row.get("英语水平"))
    if education == "博士研究生":
        english = "英语六级"
    elif education == "硕士研究生":
        english = "英语六级" if original_english in {"", "无", "英语四级"} else original_english
    else:
        english = original_english or "英语四级"
    return {
        "education": education,
        "degree": DEGREE_BY_EDUCATION[education],
        "school_category": school,
        "major": major,
        "english_level": english,
    }


def build_work_experiences(
    family: str,
    years: int,
    education: str,
    keywords: list[str],
    seed: str,
) -> list[dict[str, Any]]:
    if years <= 0:
        return []
    company_sizes = ["中型互联网企业", "大型科技企业", "AI 创业公司", "企业数字化团队"]
    roles = {
        "算法工程师": "算法工程师",
        "数据分析师": "数据分析师",
        "数据工程师": "数据工程师",
        "云计算工程师": "云平台工程师",
        "运维工程师": "SRE/运维工程师",
        "后端开发工程师": "后端开发工程师",
        "前端开发工程师": "前端开发工程师",
        "移动开发工程师": "移动开发工程师",
        "测试工程师": "测试开发工程师",
        "全栈开发工程师": "全栈开发工程师",
    }
    if education == "博士研究生":
        roles["算法工程师"] = "高级算法研究员"
        roles["数据工程师"] = "数据平台算法工程师"
    exp_count = 1 if years <= 3 else 2
    experiences: list[dict[str, Any]] = []
    remaining = years
    for index in range(exp_count):
        duration = remaining if index == exp_count - 1 else max(1, years // exp_count)
        remaining -= duration
        selected_keywords = pick_many(keywords, f"{seed}:work:{index}", 6)
        highlights = [
            f"围绕{family.replace('工程师', '')}方向，负责需求拆解、方案设计、开发落地和效果复盘。",
            f"主要使用{ '、'.join(selected_keywords[:4]) }等技术或方法，支撑线上业务迭代。",
            "与产品、研发、测试和运维团队协作，沉淀文档、规范和可复用组件。",
        ]
        if index == 0 and years >= 4:
            highlights.append("承担模块负责人职责，参与排期评估、风险识别和新人代码评审。")
        experiences.append(
            {
                "company_type": choose(company_sizes, seed, index),
                "role": roles.get(family, family),
                "duration_years": duration,
                "keywords": selected_keywords,
                "highlights": highlights,
            }
        )
    return experiences


def project_scale(row: dict[str, str]) -> str:
    counts = {}
    for column, key in PROJECT_FIELDS:
        value = clean(row.get(column))
        try:
            counts[key] = int(float(value)) if value else 0
        except ValueError:
            counts[key] = 0
    if counts.get("large", 0) > 0:
        return "large"
    if counts.get("medium", 0) > 0:
        return "medium"
    return "small"


def build_projects(
    row: dict[str, str],
    family: str,
    keywords: list[str],
    seed: str,
    education: str,
) -> list[dict[str, Any]]:
    templates = PROJECT_TEMPLATES.get(family, PROJECT_TEMPLATES["后端开发工程师"])
    scale = project_scale(row)
    project_count = 3 if education in {"硕士研究生", "博士研究生"} else 2
    projects: list[dict[str, Any]] = []
    for index, (name, responsibility) in enumerate(templates[:project_count]):
        selected_keywords = pick_many(keywords, f"{seed}:project:{index}", 7)
        result_metric = choose(
            [
                "将核心流程耗时降低约 20%",
                "支撑多业务线稳定复用",
                "提升问题定位和交付效率",
                "形成可复用的技术方案和项目文档",
                "显著改善系统稳定性和可维护性",
            ],
            seed,
            index,
        )
        projects.append(
            {
                "project_name": name,
                "project_scale": scale,
                "role": "核心成员" if index else "主要负责人",
                "tech_stack": selected_keywords,
                "description": responsibility,
                "outcome": result_metric,
            }
        )
    return projects


def skill_text(skill_levels: dict[str, str]) -> str:
    return "、".join(f"{skill}（{level}）" for skill, level in skill_levels.items())


def build_resume_text(record: dict[str, Any]) -> str:
    work_text = []
    for item in record["experience"]:
        highlights = "；".join(item["highlights"])
        work_text.append(
            f"{item['company_type']}，{item['role']}，{item['duration_years']}年。{highlights}"
        )
    if not work_text:
        work_text.append("暂无正式企业工作经历，但具备课程项目、实验项目和工程实践基础。")

    project_text = []
    for item in record["projects"]:
        project_text.append(
            f"{item['project_name']}：担任{item['role']}，技术栈包括{'、'.join(item['tech_stack'][:6])}。"
            f"{item['description']}项目结果：{item['outcome']}。"
        )

    if record["degree"] == "无学位":
        education_text = f"{record['education']}，{record['school_category']}，{record['major']}专业，{record['english_level']}。"
    else:
        education_text = f"{record['education']}，{record['degree']}学位，{record['school_category']}，{record['major']}专业，{record['english_level']}。"

    parts = [
        f"求职意向：{record['target_job_family']}。",
        f"教育背景：{education_text}",
        f"个人概述：具备{record['years_experience']}年左右相关实践经验，关注{'、'.join(record['job_keywords_used'][:8])}等方向，能够从需求理解、方案设计、工程实现到效果复盘完整推进任务。",
        f"技能栈：{skill_text(record['skill_levels'])}。",
        "工作经历：" + " ".join(work_text),
        "项目经历：" + " ".join(project_text),
        "综合能力：具备文档沉淀、跨团队沟通、问题定位、数据化复盘和持续学习能力，能够根据业务目标选择合适的技术方案。",
    ]
    return "\n".join(parts)


def synthesize_record(
    row: dict[str, str],
    education: str,
    aliases: dict[str, list[str]],
    keyword_pool: dict[str, list[str]],
    public_index: int,
    variant: str = "main",
) -> dict[str, Any]:
    seed_row_id = clean(row.get("简历编号"))
    seed_resume_id = stable_id(seed_row_id)
    seed = f"{seed_resume_id}:synthetic-detailed-v1:{variant}"
    family = clean(row.get("意向岗位"))
    base_skills, levels, _grouped = expand_skills(row, aliases)
    keywords = build_keyword_profile(family, base_skills, keyword_pool, seed)
    education_info = build_education(row, education, seed)
    years = estimate_years(row, education)
    skills = list(dict.fromkeys(base_skills + keywords[:10] + FAMILY_DEFAULT_SKILLS.get(family, [])[:5]))
    skill_levels = {
        skill: levels.get(skill) or choose(["了解", "掌握", "熟练", "精通"], f"{seed}:level:{skill}")
        for skill in skills[:32]
    }
    work_experiences = build_work_experiences(family, years, education, keywords, seed)
    project_experiences = build_projects(row, family, keywords, seed, education)
    identity = build_identity(public_index, education, years, seed)
    record: dict[str, Any] = {
        "resume_id": f"resume_{public_index:06d}",
        **identity,
        "split": split_name(seed_resume_id),
        "target_job_family": family,
        **education_info,
        "years_experience": years,
        "experience": work_experiences,
        "projects": project_experiences,
        "skills_normalized": list(skill_levels.keys()),
        "skill_levels": skill_levels,
        "job_keywords_used": keywords,
    }
    record["profile_text"] = build_resume_text(record)
    return record


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            output = public_output_record(record)
            handle.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def public_output_record(record: dict[str, Any]) -> dict[str, Any]:
    return {column: record[column] for column in OUTPUT_COLUMNS}


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for record in records:
            row = {}
            for column, value in public_output_record(record).items():
                if isinstance(value, (dict, list, bool)):
                    value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                row[column] = value
            writer.writerow(row)


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report(records: list[dict[str, Any]], output_paths: dict[str, Path]) -> dict[str, Any]:
    education_counts = Counter(record["education"] for record in records)
    family_counts = Counter(record["target_job_family"] for record in records)
    split_counts = Counter(record["split"] for record in records)
    degree_counts = Counter(record["degree"] for record in records)
    skill_counts = Counter(skill for record in records for skill in record["skills_normalized"])
    keyword_counts = Counter(keyword for record in records for keyword in record["job_keywords_used"])
    text_lengths = [len(record["profile_text"]) for record in records]
    return {
        "records": len(records),
        "dataset_version": "detailed_resume_v2_public_schema",
        "education_counts": dict(education_counts),
        "degree_counts": dict(degree_counts),
        "target_job_family_counts": dict(family_counts),
        "split_counts": dict(split_counts),
        "avg_resume_text_chars": round(sum(text_lengths) / len(text_lengths), 2) if text_lengths else 0,
        "min_resume_text_chars": min(text_lengths) if text_lengths else 0,
        "max_resume_text_chars": max(text_lengths) if text_lengths else 0,
        "top_skills": skill_counts.most_common(50),
        "top_job_keywords_used": keyword_counts.most_common(80),
        "schema": list(OUTPUT_COLUMNS),
        "hidden_generation_lineage": "Formal outputs intentionally omit source resume IDs and source row IDs.",
        "leakage_guard": "Generated from aggregate enterprise vocabulary only; no concrete job_id/JD is used as generation input.",
        "outputs": {name: str(path) for name, path in output_paths.items()},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resumes", type=Path, default=DEFAULT_RESUMES)
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.resumes)
    aliases = load_aliases(args.aliases)
    keyword_pool = load_keyword_pool(args.keywords)
    education_by_id = assign_education(rows)

    records = [
        synthesize_record(row, education_by_id[clean(row.get("简历编号"))], aliases, keyword_pool, public_index=index)
        for index, row in enumerate(rows, start=1)
    ]
    next_index = len(records) + 1
    records.extend(
        synthesize_record(row, "专科", aliases, keyword_pool, public_index=next_index + offset, variant="associate_extra")
        for offset, row in enumerate(select_extra_associate_rows(rows))
    )

    jsonl_path = args.output_dir / "synthetic_detailed_resumes.jsonl"
    csv_path = args.output_dir / "synthetic_detailed_resumes.csv"
    report_path = args.output_dir / "synthetic_detailed_resumes_report.json"
    sample_path = args.output_dir / "synthetic_detailed_resumes_sample_50.jsonl"

    write_jsonl(jsonl_path, records)
    write_csv(csv_path, records)
    write_jsonl(sample_path, records[:50])
    report = build_report(
        records,
        {
            "jsonl": jsonl_path,
            "csv": csv_path,
            "sample_50_jsonl": sample_path,
            "report": report_path,
        },
    )
    write_json(report_path, report)

    print(f"Synthetic detailed resumes: {len(records)}")
    print(f"Education counts: {report['education_counts']}")
    print(f"Average resume text chars: {report['avg_resume_text_chars']}")
    print(f"JSONL: {jsonl_path}")
    print(f"CSV: {csv_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
