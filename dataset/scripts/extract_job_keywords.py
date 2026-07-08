"""Extract a high-recall keyword layer from normalized job records.

The skill extractor is intentionally conservative. This script is wider: it
collects seed technical/business keywords and automatically mined phrases from
job titles, tags, and JD text. The output is meant to support later synthetic
resume generation, keyword coverage analysis, and manual vocabulary pruning.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DATASET_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = DATASET_DIR / "cleaned" / "all_jobs_23714_normalized.jsonl"
DEFAULT_OUTPUT_DIR = DATASET_DIR / "structured"


@dataclass(frozen=True)
class KeywordAlias:
    raw_keyword: str
    normalized_keyword: str
    category: str
    keyword_type: str
    source: str
    confidence: float


@dataclass
class KeywordHit:
    job_id: str
    job_title: str
    company_name: str
    source_type: str
    source_name: str
    raw_keyword: str
    normalized_keyword: str
    category: str
    keyword_type: str
    source: str
    evidence_field: str
    evidence_sentence: str
    confidence: float
    match_method: str


SEED_KEYWORDS: list[KeywordAlias] = [
    # AI and large models
    KeywordAlias("AI", "AI", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("人工智能", "人工智能", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("大模型", "大模型", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("大语言模型", "大语言模型", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("LLM", "大语言模型", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("多模态", "多模态AI", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("AIGC", "AIGC", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("Agent", "AI Agent", "AI与大模型", "technology", "seed", 0.9),
    KeywordAlias("智能体", "AI Agent", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("RAG", "RAG", "AI与大模型", "technology", "seed", 1.0),
    KeywordAlias("知识库", "知识库", "AI与大模型", "technology", "seed", 0.9),
    KeywordAlias("向量检索", "向量检索", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("向量数据库", "向量数据库", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("Embedding", "Embedding", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("Prompt", "Prompt Engineering", "AI与大模型", "technology", "seed", 0.9),
    KeywordAlias("提示词", "Prompt Engineering", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("System Prompt", "System Prompt", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("Few-shot", "Few-shot", "AI与大模型", "technology", "seed", 0.9),
    KeywordAlias("微调", "模型微调", "AI与大模型", "technology", "seed", 0.9),
    KeywordAlias("LoRA", "LoRA", "AI与大模型", "technology", "seed", 0.95),
    KeywordAlias("模型训练", "模型训练", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("模型推理", "模型推理", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("分布式训练", "分布式训练", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("分布式推理", "分布式推理", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("推理加速", "推理加速", "AI基础设施", "technology", "seed", 0.95),
    KeywordAlias("模型压缩", "模型压缩", "AI基础设施", "technology", "seed", 0.9),
    KeywordAlias("量化", "模型量化", "AI基础设施", "technology", "seed", 0.85),
    KeywordAlias("GPU", "GPU", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("NPU", "NPU", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("CUDA", "CUDA", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("vLLM", "vLLM", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("SGLang", "SGLang", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("Triton", "Triton", "AI基础设施", "technology", "seed", 0.95),
    KeywordAlias("NCCL", "NCCL", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("RDMA", "RDMA", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("MLIR", "MLIR", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("LLVM", "LLVM", "AI基础设施", "technology", "seed", 1.0),
    KeywordAlias("昇腾", "昇腾", "AI基础设施", "technology", "seed", 0.95),
    KeywordAlias("MindSpore", "MindSpore", "AI框架", "technology", "seed", 1.0),
    KeywordAlias("PyTorch", "PyTorch", "AI框架", "technology", "seed", 1.0),
    KeywordAlias("TensorFlow", "TensorFlow", "AI框架", "technology", "seed", 1.0),
    KeywordAlias("LangChain", "LangChain", "AI框架", "technology", "seed", 1.0),
    KeywordAlias("Stable Diffusion", "Stable Diffusion", "AI应用", "technology", "seed", 1.0),
    KeywordAlias("ComfyUI", "ComfyUI", "AI应用", "technology", "seed", 1.0),
    KeywordAlias("Midjourney", "Midjourney", "AI应用", "technology", "seed", 1.0),
    KeywordAlias("机器学习", "机器学习", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("深度学习", "深度学习", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("自然语言处理", "自然语言处理", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("NLP", "自然语言处理", "数据与算法", "technology", "seed", 0.95),
    KeywordAlias("计算机视觉", "计算机视觉", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("CV", "计算机视觉", "数据与算法", "technology", "seed", 0.8),
    KeywordAlias("推荐系统", "推荐系统", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("搜索算法", "搜索算法", "数据与算法", "technology", "seed", 0.95),
    KeywordAlias("风控模型", "风控模型", "数据与算法", "technology", "seed", 0.95),
    KeywordAlias("数据挖掘", "数据挖掘", "数据与算法", "technology", "seed", 1.0),
    KeywordAlias("特征工程", "特征工程", "数据与算法", "technology", "seed", 1.0),
    # Programming and software engineering
    KeywordAlias("Python", "Python", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("Java", "Java", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("Go", "Go", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("Golang", "Go", "编程语言", "technology", "seed", 0.95),
    KeywordAlias("C++", "C++", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("C#", "C#", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("Rust", "Rust", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("JavaScript", "JavaScript", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("TypeScript", "TypeScript", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("SQL", "SQL", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("Shell", "Shell", "编程语言", "technology", "seed", 1.0),
    KeywordAlias("React", "React", "前端技术", "technology", "seed", 1.0),
    KeywordAlias("Vue", "Vue", "前端技术", "technology", "seed", 1.0),
    KeywordAlias("Angular", "Angular", "前端技术", "technology", "seed", 1.0),
    KeywordAlias("Node.js", "Node.js", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("Spring Boot", "Spring Boot", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("Spring Cloud", "Spring Cloud", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("MyBatis", "MyBatis", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("Django", "Django", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("Flask", "Flask", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("FastAPI", "FastAPI", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("微服务", "微服务", "后端技术", "technology", "seed", 1.0),
    KeywordAlias("高并发", "高并发", "软件工程", "technology", "seed", 0.95),
    KeywordAlias("分布式系统", "分布式系统", "软件工程", "technology", "seed", 1.0),
    KeywordAlias("系统设计", "系统设计", "软件工程", "technology", "seed", 0.95),
    KeywordAlias("架构设计", "架构设计", "软件工程", "technology", "seed", 1.0),
    KeywordAlias("代码生成", "代码生成", "软件工程", "technology", "seed", 0.85),
    KeywordAlias("代码测试", "代码测试", "软件工程", "technology", "seed", 0.85),
    # Cloud, data, test, mobile, game, security
    KeywordAlias("云计算", "云计算", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("Docker", "Docker", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("Kubernetes", "Kubernetes", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("K8s", "Kubernetes", "云原生与运维", "technology", "seed", 0.98),
    KeywordAlias("Linux", "Linux", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("DevOps", "DevOps", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("CI/CD", "CI/CD", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("Terraform", "Terraform", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("Prometheus", "Prometheus", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("Grafana", "Grafana", "云原生与运维", "technology", "seed", 1.0),
    KeywordAlias("MySQL", "MySQL", "数据库", "technology", "seed", 1.0),
    KeywordAlias("PostgreSQL", "PostgreSQL", "数据库", "technology", "seed", 1.0),
    KeywordAlias("MongoDB", "MongoDB", "数据库", "technology", "seed", 1.0),
    KeywordAlias("Redis", "Redis", "数据库", "technology", "seed", 1.0),
    KeywordAlias("Elasticsearch", "Elasticsearch", "数据库", "technology", "seed", 1.0),
    KeywordAlias("ClickHouse", "ClickHouse", "数据库", "technology", "seed", 1.0),
    KeywordAlias("数据仓库", "数据仓库", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("数据湖", "数据湖", "数据工程", "technology", "seed", 0.95),
    KeywordAlias("ETL", "ETL", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("Hadoop", "Hadoop", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("Spark", "Spark", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("Flink", "Flink", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("Kafka", "Kafka", "数据工程", "technology", "seed", 1.0),
    KeywordAlias("Tableau", "Tableau", "数据分析", "technology", "seed", 1.0),
    KeywordAlias("Power BI", "Power BI", "数据分析", "technology", "seed", 1.0),
    KeywordAlias("Selenium", "Selenium", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("JMeter", "JMeter", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("Postman", "Postman", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("自动化测试", "自动化测试", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("性能测试", "性能测试", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("安全测试", "安全测试", "测试质量", "technology", "seed", 1.0),
    KeywordAlias("Android", "Android", "移动开发", "technology", "seed", 1.0),
    KeywordAlias("iOS", "iOS", "移动开发", "technology", "seed", 1.0),
    KeywordAlias("Flutter", "Flutter", "移动开发", "technology", "seed", 1.0),
    KeywordAlias("React Native", "React Native", "移动开发", "technology", "seed", 1.0),
    KeywordAlias("Unreal Engine", "Unreal Engine", "游戏开发", "technology", "seed", 1.0),
    KeywordAlias("UE5", "Unreal Engine", "游戏开发", "technology", "seed", 0.95),
    KeywordAlias("Unity", "Unity", "游戏开发", "technology", "seed", 1.0),
    KeywordAlias("Cocos", "Cocos", "游戏开发", "technology", "seed", 1.0),
    KeywordAlias("3D", "3D", "游戏美术", "technology", "seed", 0.9),
    KeywordAlias("BJD", "BJD", "游戏美术", "technology", "seed", 0.9),
    KeywordAlias("IP", "IP", "产品运营", "business", "seed", 0.8),
    KeywordAlias("网络安全", "网络安全", "安全", "technology", "seed", 1.0),
    KeywordAlias("信息安全", "信息安全", "安全", "technology", "seed", 1.0),
    KeywordAlias("风控", "风控", "安全", "business", "seed", 0.95),
    # Product, operation, management, government constraints
    KeywordAlias("产品经理", "产品经理", "岗位角色", "role", "seed", 1.0),
    KeywordAlias("项目管理", "项目管理", "项目管理", "business", "seed", 1.0),
    KeywordAlias("PMP", "PMP", "证书资质", "constraint", "seed", 1.0),
    KeywordAlias("ACP", "ACP", "证书资质", "constraint", "seed", 0.95),
    KeywordAlias("数据分析", "数据分析", "数据分析", "business", "seed", 1.0),
    KeywordAlias("用户增长", "用户增长", "产品运营", "business", "seed", 0.95),
    KeywordAlias("用户研究", "用户研究", "产品运营", "business", "seed", 0.95),
    KeywordAlias("市场营销", "市场营销", "产品运营", "business", "seed", 0.95),
    KeywordAlias("品牌", "品牌", "产品运营", "business", "seed", 0.8),
    KeywordAlias("运营", "运营", "产品运营", "business", "seed", 0.8),
    KeywordAlias("交付", "交付", "项目管理", "business", "seed", 0.8),
    KeywordAlias("客户成功", "客户成功", "项目管理", "business", "seed", 0.9),
    KeywordAlias("本科", "本科", "学历要求", "constraint", "seed", 0.95),
    KeywordAlias("硕士", "硕士", "学历要求", "constraint", "seed", 0.95),
    KeywordAlias("博士", "博士", "学历要求", "constraint", "seed", 0.95),
    KeywordAlias("英语四级", "英语四级", "语言能力", "constraint", "seed", 0.95),
    KeywordAlias("英语六级", "英语六级", "语言能力", "constraint", "seed", 0.95),
    KeywordAlias("CET-4", "英语四级", "语言能力", "constraint", "seed", 0.95),
    KeywordAlias("CET-6", "英语六级", "语言能力", "constraint", "seed", 0.95),
    KeywordAlias("党员", "党员", "公务员条件", "constraint", "seed", 0.95),
    KeywordAlias("基层工作经历", "基层工作经历", "公务员条件", "constraint", "seed", 0.95),
    KeywordAlias("应届高校毕业生", "应届高校毕业生", "公务员条件", "constraint", "seed", 0.95),
]


ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "work",
    "location",
    "china",
    "job",
    "team",
    "global",
}

GENERIC_CHINESE_STOPWORDS = {
    "岗位职责",
    "岗位要求",
    "任职要求",
    "职位简介",
    "职位要求",
    "工作职责",
    "能力要求",
    "知识要求",
    "其他要求",
    "相关工作",
    "相关经验",
    "工作经验",
    "优先",
    "加分",
    "不限",
    "无要求",
    "岗位",
    "工作",
    "要求",
    "能力",
    "负责",
    "参与",
    "具备",
}

CHINESE_SUFFIXES = [
    "大模型",
    "语言模型",
    "机器学习",
    "深度学习",
    "自然语言处理",
    "计算机视觉",
    "推荐系统",
    "搜索算法",
    "模型训练",
    "模型推理",
    "推理加速",
    "模型评估",
    "模型部署",
    "模型优化",
    "数据分析",
    "数据挖掘",
    "数据治理",
    "数据仓库",
    "数据平台",
    "数据安全",
    "云计算",
    "云原生",
    "容器平台",
    "微服务",
    "分布式系统",
    "架构设计",
    "系统设计",
    "平台建设",
    "项目管理",
    "产品设计",
    "产品规划",
    "产品运营",
    "用户研究",
    "用户增长",
    "需求分析",
    "市场营销",
    "品牌营销",
    "客户管理",
    "客户成功",
    "解决方案",
    "交付管理",
    "质量保障",
    "自动化测试",
    "性能测试",
    "安全测试",
    "网络安全",
    "信息安全",
    "风险管理",
    "成本管理",
    "预算预测",
    "经营分析",
    "财务管理",
    "游戏开发",
    "游戏运营",
    "游戏策划",
    "关卡设计",
    "角色设计",
    "场景设计",
    "技术美术",
    "虚拟化",
    "编译器",
    "操作系统",
    "数据库",
    "中间件",
    "工程化",
    "工作流",
    "方法论",
    "标准化",
    "自动化",
    "智能化",
    "数字化",
    "产业分析",
    "行业分析",
    "政策研究",
    "法律",
    "法务",
    "审计",
    "监管",
    "学历",
    "学位",
    "专业",
    "证书",
    "英语",
]

LEFT_TRIM_RE = re.compile(
    r"^(?:熟悉|精通|掌握|了解|具备|拥有|负责|参与|主导|推动|完成|开展|进行|能够|可以|需要|要求|具有|基于|面向|通过|使用|应用|建设|制定|设计|实现|落地|优化|提升|支持|支撑|协同|持续|独立|相关|丰富|扎实|良好|较强|优秀|出色|一定|多个|一种|多种|主流|核心|先进|复杂|大型|企业级)+"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(clean_text(item) for item in value)
    return str(value).replace("\u3000", " ").strip()


def compact_space(value: str) -> str:
    return " ".join(clean_text(value).split())


def split_sentences(text: str) -> list[str]:
    text = clean_text(text).replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"[\n。！？!?；;]+", text)
    return [part.strip(" \t,，:：、.-0123456789()（）[]【】") for part in parts if part.strip()]


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def compile_keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword)
    if has_cjk(keyword):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def load_skill_aliases() -> list[KeywordAlias]:
    """Reuse the conservative skill aliases when available."""
    aliases: list[KeywordAlias] = []
    try:
        import sys

        sys.path.insert(0, str(DATASET_DIR / "scripts"))
        from extract_job_skills import DEFAULT_SKILL_ALIASES, DEFAULT_ALIAS_JSON, load_existing_combo_aliases

        skill_items = list(DEFAULT_SKILL_ALIASES) + list(load_existing_combo_aliases(DEFAULT_ALIAS_JSON))
        for item in skill_items:
            aliases.append(
                KeywordAlias(
                    raw_keyword=item.raw_skill,
                    normalized_keyword=item.normalized_skill,
                    category=item.category,
                    keyword_type="technology",
                    source="skill_aliases",
                    confidence=float(item.confidence),
                )
            )
    except Exception:
        pass
    return aliases


def dedupe_aliases(records: Iterable[KeywordAlias]) -> list[KeywordAlias]:
    best: dict[tuple[str, str], KeywordAlias] = {}
    for item in records:
        raw = compact_space(item.raw_keyword)
        norm = compact_space(item.normalized_keyword)
        if not raw or not norm:
            continue
        key = (raw.lower(), norm.lower())
        previous = best.get(key)
        if previous is None or item.confidence > previous.confidence:
            best[key] = KeywordAlias(raw, norm, item.category, item.keyword_type, item.source, item.confidence)
    return sorted(best.values(), key=lambda item: (item.normalized_keyword.lower(), item.raw_keyword.lower()))


def normalize_keyword(keyword: str) -> str:
    keyword = compact_space(keyword)
    keyword = keyword.strip(" ,，.。:：;；/\\[]【】<>《》\"'")
    return keyword


def clean_chinese_candidate(candidate: str) -> str:
    candidate = normalize_keyword(candidate)
    candidate = LEFT_TRIM_RE.sub("", candidate)
    candidate = candidate.strip("的和与及或并等类中上下一二三四五六七八九十")
    return normalize_keyword(candidate)


def infer_category(keyword: str, keyword_type: str) -> str:
    lower = keyword.lower()
    if keyword_type == "title_or_tag":
        if any(word in keyword for word in ["工程师", "经理", "专家", "专员", "设计师", "架构师"]):
            return "岗位角色"
        return "岗位标签"
    if any(word in keyword for word in ["大模型", "AI", "智能体", "Agent", "RAG", "Prompt", "AIGC", "多模态"]):
        return "AI与大模型"
    if any(word in keyword for word in ["模型", "算法", "机器学习", "深度学习", "NLP", "CV", "推荐", "搜索"]):
        return "数据与算法"
    if any(word in keyword for word in ["GPU", "NPU", "CUDA", "推理", "训练", "昇腾", "芯片", "编译器", "LLVM", "RDMA"]):
        return "AI基础设施"
    if any(word in keyword for word in ["云", "容器", "Kubernetes", "Docker", "Linux", "DevOps", "运维", "集群"]):
        return "云原生与运维"
    if any(word in keyword for word in ["数据", "ETL", "SQL", "Kafka", "Spark", "Flink", "仓库"]):
        return "数据工程"
    if any(word in keyword for word in ["测试", "质量", "Selenium", "JMeter"]):
        return "测试质量"
    if any(word in keyword for word in ["游戏", "Unity", "Unreal", "UE5", "3D", "角色", "场景", "美术"]):
        return "游戏开发"
    if any(word in keyword for word in ["产品", "用户", "运营", "市场", "品牌", "营销"]):
        return "产品运营"
    if any(word in keyword for word in ["项目", "交付", "客户", "管理", "预算", "成本"]):
        return "项目管理"
    if any(word in keyword for word in ["本科", "硕士", "博士", "英语", "CET", "证书", "党员"]):
        return "硬约束"
    if lower in {"java", "python", "go", "golang", "c++", "c#", "rust", "javascript", "typescript", "sql"}:
        return "编程语言"
    return "自动短语"


def source_fields(job: dict[str, Any]) -> list[tuple[str, str]]:
    tags = clean_text(job.get("tags"))
    return [
        ("job_title", clean_text(job.get("job_title"))),
        ("keyword", clean_text(job.get("keyword"))),
        ("tags", tags),
        ("job_description", clean_text(job.get("job_description"))),
    ]


def evidence_units(field: str, value: str) -> list[str]:
    if not value:
        return []
    if field in {"job_title", "keyword", "tags"}:
        return [value]
    return split_sentences(value)


def extract_seed_hits(job: dict[str, Any], aliases: list[KeywordAlias], patterns: dict[str, re.Pattern[str]]) -> list[KeywordHit]:
    hits: list[KeywordHit] = []
    seen: set[tuple[str, str, str]] = set()
    for field, value in source_fields(job):
        for sentence in evidence_units(field, value):
            sentence_clean = compact_space(sentence)
            if not sentence_clean:
                continue
            for alias in aliases:
                pattern = patterns[alias.raw_keyword]
                if not pattern.search(sentence_clean):
                    continue
                key = (alias.normalized_keyword.lower(), field, sentence_clean[:160])
                if key in seen:
                    continue
                seen.add(key)
                hits.append(make_hit(job, alias.raw_keyword, alias.normalized_keyword, alias.category, alias.keyword_type, alias.source, field, sentence_clean, alias.confidence, "seed_dictionary"))
    return hits


def extract_english_terms(text: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9+#._-]{1,})(?:/[A-Za-z][A-Za-z0-9+#._-]{1,})?(?![A-Za-z0-9])", text):
        term = normalize_keyword(match.group(0))
        if not term:
            continue
        if term.lower() in ENGLISH_STOPWORDS:
            continue
        if len(term) == 2 and term.lower() not in {"ai", "cv", "go", "ip"}:
            continue
        terms.append(term)
    return terms


def extract_chinese_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    suffix_pattern = "|".join(re.escape(item) for item in sorted(CHINESE_SUFFIXES, key=len, reverse=True))
    pattern = re.compile(rf"[\u4e00-\u9fffA-Za-z0-9+#._/-]{{0,12}}(?:{suffix_pattern})")
    for match in pattern.finditer(text):
        phrase = clean_chinese_candidate(match.group(0))
        if not phrase or phrase in GENERIC_CHINESE_STOPWORDS:
            continue
        if len(phrase) < 2 or len(phrase) > 24:
            continue
        if re.fullmatch(r"[\d一二三四五六七八九十]+", phrase):
            continue
        phrases.append(phrase)
    return phrases


def extract_title_tag_terms(job: dict[str, Any]) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    title = normalize_keyword(clean_text(job.get("job_title")))
    if 2 <= len(title) <= 40:
        terms.append((title, "job_title"))
    keyword = normalize_keyword(clean_text(job.get("keyword")))
    if 2 <= len(keyword) <= 40:
        terms.append((keyword, "keyword"))
    tags = job.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            tag_text = normalize_keyword(clean_text(tag))
            if 2 <= len(tag_text) <= 40 and tag_text not in GENERIC_CHINESE_STOPWORDS:
                terms.append((tag_text, "tags"))
    elif tags:
        for tag_text in re.split(r"[;；,，|/]+", clean_text(tags)):
            tag_text = normalize_keyword(tag_text)
            if 2 <= len(tag_text) <= 40 and tag_text not in GENERIC_CHINESE_STOPWORDS:
                terms.append((tag_text, "tags"))
    return terms


def extract_auto_hits(job: dict[str, Any]) -> list[KeywordHit]:
    hits: list[KeywordHit] = []
    seen: set[tuple[str, str]] = set()

    for term, field in extract_title_tag_terms(job):
        norm = normalize_keyword(term)
        key = (norm.lower(), field)
        if key in seen:
            continue
        seen.add(key)
        hits.append(make_hit(job, term, norm, infer_category(norm, "title_or_tag"), "title_or_tag", "auto_title_tag", field, norm, 0.72, "title_tag"))

    for field, value in source_fields(job):
        if not value:
            continue
        for sentence in evidence_units(field, value):
            sentence_clean = compact_space(sentence)
            if not sentence_clean:
                continue
            for term in extract_english_terms(sentence_clean):
                norm = normalize_keyword(term)
                key = (norm.lower(), field)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(make_hit(job, term, norm, infer_category(norm, "auto_english"), "auto_english", "regex_english", field, sentence_clean, 0.65, "regex_english"))
            for term in extract_chinese_phrases(sentence_clean):
                norm = normalize_keyword(term)
                key = (norm.lower(), field)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(make_hit(job, term, norm, infer_category(norm, "auto_phrase"), "auto_phrase", "regex_chinese_phrase", field, sentence_clean, 0.6, "regex_chinese_phrase"))
    return hits


def make_hit(
    job: dict[str, Any],
    raw_keyword: str,
    normalized_keyword: str,
    category: str,
    keyword_type: str,
    source: str,
    evidence_field: str,
    evidence_sentence: str,
    confidence: float,
    match_method: str,
) -> KeywordHit:
    return KeywordHit(
        job_id=str(job.get("job_id") or ""),
        job_title=clean_text(job.get("job_title")),
        company_name=clean_text(job.get("company_name")),
        source_type=clean_text(job.get("source_type")),
        source_name=clean_text(job.get("source_name") or job.get("source")),
        raw_keyword=raw_keyword,
        normalized_keyword=normalized_keyword,
        category=category,
        keyword_type=keyword_type,
        source=source,
        evidence_field=evidence_field,
        evidence_sentence=evidence_sentence[:500],
        confidence=confidence,
        match_method=match_method,
    )


def job_key(job: dict[str, Any], index: int) -> str:
    return str(job.get("job_id") or f"row_{index:06d}")


def hit_to_row(hit: KeywordHit) -> dict[str, Any]:
    return {
        "job_id": hit.job_id,
        "job_title": hit.job_title,
        "company_name": hit.company_name,
        "source_type": hit.source_type,
        "source_name": hit.source_name,
        "raw_keyword": hit.raw_keyword,
        "normalized_keyword": hit.normalized_keyword,
        "category": hit.category,
        "keyword_type": hit.keyword_type,
        "source": hit.source,
        "evidence_field": hit.evidence_field,
        "evidence_sentence": hit.evidence_sentence,
        "confidence": hit.confidence,
        "match_method": hit.match_method,
    }


def choose_best_hits(hits: list[KeywordHit], keep_keywords: set[str], max_keywords_per_job: int) -> list[KeywordHit]:
    best: dict[str, KeywordHit] = {}
    for hit in hits:
        key = hit.normalized_keyword.lower()
        if key not in keep_keywords:
            continue
        previous = best.get(key)
        if previous is None:
            best[key] = hit
            continue
        if (hit.confidence, len(hit.evidence_sentence)) > (previous.confidence, len(previous.evidence_sentence)):
            best[key] = hit
    ordered = sorted(best.values(), key=lambda item: (-item.confidence, item.category, item.normalized_keyword.lower()))
    return ordered[:max_keywords_per_job]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_vocabulary_rows(hits: list[KeywordHit]) -> list[dict[str, Any]]:
    doc_counts: dict[str, set[str]] = defaultdict(set)
    mention_counts: Counter[str] = Counter()
    display_keyword: dict[str, str] = {}
    category_counter: dict[str, Counter[str]] = defaultdict(Counter)
    type_counter: dict[str, Counter[str]] = defaultdict(Counter)
    source_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[KeywordHit]] = defaultdict(list)

    for hit in hits:
        key = hit.normalized_keyword.lower()
        display_keyword.setdefault(key, hit.normalized_keyword)
        doc_counts[key].add(hit.job_id)
        mention_counts[key] += 1
        category_counter[key][hit.category] += 1
        type_counter[key][hit.keyword_type] += 1
        source_type_counts[key][hit.source_type or "unknown"] += 1
        if len(examples[key]) < 3:
            examples[key].append(hit)

    rows: list[dict[str, Any]] = []
    for key in doc_counts:
        sample_hits = examples[key]
        main_category = category_counter[key].most_common(1)[0][0]
        main_type = type_counter[key].most_common(1)[0][0]
        source_counts = ";".join(f"{name}:{count}" for name, count in source_type_counts[key].most_common())
        rows.append(
            {
                "normalized_keyword": display_keyword.get(key, sample_hits[0].normalized_keyword if sample_hits else key),
                "category": main_category,
                "keyword_type": main_type,
                "doc_count": len(doc_counts[key]),
                "mention_count": mention_counts[key],
                "source_type_counts": source_counts,
                "example_job_ids": ";".join(hit.job_id for hit in sample_hits),
                "example_job_titles": " | ".join(hit.job_title for hit in sample_hits),
                "example_evidence": " | ".join(hit.evidence_sentence for hit in sample_hits),
            }
        )
    rows.sort(key=lambda row: (-int(row["doc_count"]), -int(row["mention_count"]), str(row["normalized_keyword"]).lower()))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-auto-doc-count", type=int, default=2)
    parser.add_argument("--max-keywords-per-job", type=int, default=220)
    args = parser.parse_args()

    aliases = dedupe_aliases([*SEED_KEYWORDS, *load_skill_aliases()])
    patterns = {alias.raw_keyword: compile_keyword_pattern(alias.raw_keyword) for alias in aliases}

    args.output_dir.mkdir(parents=True, exist_ok=True)
    job_hits: dict[str, list[KeywordHit]] = {}
    all_jobs: dict[str, dict[str, Any]] = {}
    doc_counts: dict[str, set[str]] = defaultdict(set)
    mention_counts: Counter[str] = Counter()
    display_keyword: dict[str, str] = {}
    category_counter: dict[str, Counter[str]] = defaultdict(Counter)
    type_counter: dict[str, Counter[str]] = defaultdict(Counter)
    source_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[KeywordHit]] = defaultdict(list)
    input_jobs = 0

    with args.input.open("r", encoding="utf-8") as file:
        for index, line in enumerate(file):
            if args.limit and index >= args.limit:
                break
            if not line.strip():
                continue
            job = json.loads(line)
            jid = job_key(job, index)
            job["job_id"] = jid
            all_jobs[jid] = job
            input_jobs += 1

            hits = extract_seed_hits(job, aliases, patterns)
            hits.extend(extract_auto_hits(job))
            job_hits[jid] = hits

            seen_in_job: set[str] = set()
            for hit in hits:
                key = hit.normalized_keyword.lower()
                display_keyword.setdefault(key, hit.normalized_keyword)
                category_counter[key][hit.category] += 1
                type_counter[key][hit.keyword_type] += 1
                source_type_counts[key][hit.source_type or "unknown"] += 1
                mention_counts[key] += 1
                seen_in_job.add(key)
                if len(examples[key]) < 3:
                    examples[key].append(hit)
            for key in seen_in_job:
                doc_counts[key].add(jid)

    keep_keywords: set[str] = set()
    for key, jobs in doc_counts.items():
        main_type = type_counter[key].most_common(1)[0][0]
        if main_type in {"technology", "business", "constraint", "role", "title_or_tag"}:
            keep_keywords.add(key)
        elif len(jobs) >= args.min_auto_doc_count:
            keep_keywords.add(key)

    final_hits: list[KeywordHit] = []
    for jid, hits in job_hits.items():
        final_hits.extend(choose_best_hits(hits, keep_keywords, args.max_keywords_per_job))

    vocab_rows = build_vocabulary_rows(final_hits)
    source_type_vocab_rows = {
        source_type: build_vocabulary_rows([hit for hit in final_hits if (hit.source_type or "unknown") == source_type])
        for source_type in sorted({hit.source_type or "unknown" for hit in final_hits})
    }

    mention_rows = [hit_to_row(hit) for hit in final_hits]
    mention_rows.sort(key=lambda row: (row["job_id"], row["category"], row["normalized_keyword"]))

    vocabulary_csv = args.output_dir / "job_keyword_vocabulary.csv"
    vocabulary_by_source_type = {
        source_type: args.output_dir / f"job_keyword_vocabulary_{source_type}.csv"
        for source_type in source_type_vocab_rows
    }
    mentions_jsonl = args.output_dir / "job_keyword_mentions.jsonl"
    mentions_csv = args.output_dir / "job_keyword_mentions.csv"
    report_json = args.output_dir / "job_keyword_extract_report.json"

    write_csv(
        vocabulary_csv,
        vocab_rows,
        [
            "normalized_keyword",
            "category",
            "keyword_type",
            "doc_count",
            "mention_count",
            "source_type_counts",
            "example_job_ids",
            "example_job_titles",
            "example_evidence",
        ],
    )
    for source_type, rows in source_type_vocab_rows.items():
        write_csv(
            vocabulary_by_source_type[source_type],
            rows,
            [
                "normalized_keyword",
                "category",
                "keyword_type",
                "doc_count",
                "mention_count",
                "source_type_counts",
                "example_job_ids",
                "example_job_titles",
                "example_evidence",
            ],
        )
    with mentions_jsonl.open("w", encoding="utf-8") as file:
        for row in mention_rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_csv(
        mentions_csv,
        mention_rows,
        [
            "job_id",
            "job_title",
            "company_name",
            "source_type",
            "source_name",
            "raw_keyword",
            "normalized_keyword",
            "category",
            "keyword_type",
            "source",
            "evidence_field",
            "evidence_sentence",
            "confidence",
            "match_method",
        ],
    )

    category_counts = Counter(row["category"] for row in vocab_rows)
    type_counts = Counter(row["keyword_type"] for row in vocab_rows)
    jobs_with_keywords = len({row["job_id"] for row in mention_rows})
    report = {
        "input_jobs": input_jobs,
        "jobs_with_keywords": jobs_with_keywords,
        "job_keyword_coverage": round(jobs_with_keywords / input_jobs, 4) if input_jobs else 0,
        "unique_keywords": len(vocab_rows),
        "job_keyword_mentions": len(mention_rows),
        "min_auto_doc_count": args.min_auto_doc_count,
        "max_keywords_per_job": args.max_keywords_per_job,
        "category_counts": dict(category_counts.most_common()),
        "keyword_type_counts": dict(type_counts.most_common()),
        "top_keywords": [
            {
                "normalized_keyword": row["normalized_keyword"],
                "category": row["category"],
                "doc_count": row["doc_count"],
                "mention_count": row["mention_count"],
            }
            for row in vocab_rows[:80]
        ],
        "method": "seed_dictionary + regex_english + regex_chinese_phrase + title_tag_terms",
        "outputs": {
            "vocabulary_csv": str(vocabulary_csv),
            "vocabulary_by_source_type": {source_type: str(path) for source_type, path in vocabulary_by_source_type.items()},
            "mentions_jsonl": str(mentions_jsonl),
            "mentions_csv": str(mentions_csv),
            "report_json": str(report_json),
        },
    }
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Input jobs: {input_jobs}")
    print(f"Jobs with keywords: {jobs_with_keywords}")
    print(f"Unique keywords: {len(vocab_rows)}")
    print(f"Job-keyword mentions: {len(mention_rows)}")
    print(f"Vocabulary: {vocabulary_csv}")
    print(f"Mentions JSONL: {mentions_jsonl}")
    print(f"Mentions CSV: {mentions_csv}")
    print(f"Report: {report_json}")


if __name__ == "__main__":
    main()
