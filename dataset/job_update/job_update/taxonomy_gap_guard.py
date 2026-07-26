from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GuardStatus = Literal["potential_new_job", "new_family"]


@dataclass(slots=True)
class TaxonomyGapDecision:
    status: GuardStatus
    reason: str


NEW_FAMILY_RULES = [
    ("new_family_robotics", ["机器人", "具身", "具身智能", "Robotaxi", "Robotics", "无人机", "传感器工程师"], ["机器人"]),
    ("new_family_autonomous_driving", ["自动驾驶", "无人车", "车云协同", "域控制器", "数据闭环", "汽车法规"], ["自动驾驶"]),
    (
        "new_family_multimedia_graphics_audio_video",
        [
            "音视频",
            "图形渲染",
            "图形显示",
            "图像传感器",
            "图像评测",
            "技术美术",
            "UE5",
            "游戏引擎",
            "Camera",
            "相机色彩",
            "图像调校",
            "视频编解码",
            "GPU渲染",
            "PCG技术美术",
            "虚拟人交互",
        ],
        ["多媒体"],
    ),
]


POTENTIAL_NEW_JOB_RULES = [
    (
        "gap_llm_test_quality",
        [
            ["AI", "Agent", "智能体", "大模型", "模型", "LLM", "AIGC", "MaaS", "Agent Harness", "RL Data", "AI基建"],
            ["测试", "评测", "质量", "QA", "Harness", "RL Data", "基建"],
        ],
        [],
        ["大模型测试工程师"],
    ),
    (
        "gap_multimodal_algorithm",
        [["多模态", "跨模态", "Omni", "多模", "VLM"], ["算法", "研究", "模型", "理解", "生成", "推荐", "交互", "内容安全", "策略", "推理"]],
        [],
        ["多模态算法工程师"],
    ),
    (
        "gap_aigc_algorithm",
        [["AIGC", "生成式AI", "生成式影像", "生成式视频", "数字人"], ["算法", "生成", "影像", "视频", "数字人", "技术专家"]],
        ["应用开发", "应用研发", "产品"],
        ["AIGC算法工程师"],
    ),
    ("gap_search_algorithm", [["搜索", "展示召回"], ["算法", "排序", "召回", "架构", "引擎", "AI搜索", "搜索产品"]], [], ["搜索算法工程师"]),
    ("gap_data_mining", [["数据挖掘"]], [], ["数据挖掘算法工程师"]),
    ("gap_data_governance", [["数据治理", "数据质量", "数据采集", "数据标注", "标注", "地图测绘"]], [], ["数据治理工程师"]),
    ("gap_go_development", [["Go", "Golang", "GO开发", "Go开发"], ["开发", "研发", "工程师", "后端", "服务端"]], [], ["Go开发工程师"]),
    ("gap_python_development", [["Python"], ["开发", "研发", "工程师", "后端", "服务端"]], [], ["Python开发工程师"]),
    ("gap_devops", [["DevOps", "SRE", "运维开发", "云原生运维", "平台运维", "工程效能", "研发效能", "构建优化"]], [], ["DevOps工程师"]),
    ("gap_chip_verification", [["芯片", "IC", "SoC", "SOC", "IP", "CPU", "DPU", "DFT", "原型验证", "存储系统验证"], ["验证", "DFT"]], [], ["芯片验证工程师"]),
    ("gap_thermal_design", [["热设计", "散热", "热仿真", "热管理", "仿真工程师"]], [], ["热设计工程师"]),
    (
        "gap_llm_application",
        [
            [
                "大模型应用",
                "LLM应用",
                "RAG",
                "知识库问答",
                "Prompt工程",
                "提示词工程",
                "AI科学计算",
                "AI Coding",
                "存储优化",
                "UGC",
                "引擎工程师",
                "不动产技术",
            ],
            ["开发", "研发", "工程", "后端", "应用", "科学计算", "Coding", "存储优化", "引擎", "技术负责人"],
        ],
        ["Agent", "智能体", "Agentic"],
        ["大模型应用工程师"],
    ),
    (
        "gap_misc_platform_and_experience",
        [
            [
                "安全策略",
                "安全与隐私保护工程师",
                "用户体验",
                "供应链交付",
                "基础设施平台",
                "内存系统验证",
                "数据生产",
                "SNIC软件应用",
                "增程器设计验证",
                "视频大模型编导",
                "Agent工程师",
                "大模型Agent框架",
                "视觉创作Agent技术专家",
            ]
        ],
        [],
        [],
    ),
]


def detect_taxonomy_gap(
    *,
    raw_job_title: str,
    routing_job_title: str = "",
    job_responsibility: str = "",
    job_requirement: str = "",
    current_standard_jobs: set[str] | None = None,
    current_standard_categories: set[str] | None = None,
) -> TaxonomyGapDecision | None:
    # The current calibrated guard is intentionally title-led. Responsibilities are
    # accepted for future rule expansion, but broad business-context terms should
    # not override an otherwise clear existing job title.
    _ = job_responsibility, job_requirement
    title_text = " ".join([raw_job_title or "", routing_job_title or ""])
    known_jobs = {value.casefold() for value in (current_standard_jobs or set())}
    known_categories = {value.casefold() for value in (current_standard_categories or set())}

    for rule_name, terms, covered_categories in NEW_FAMILY_RULES:
        if contains_any(title_text, terms) and not contains_any_casefold(known_categories, covered_categories):
            return TaxonomyGapDecision("new_family", f"taxonomy gap guard: {rule_name}")

    for rule_name, required_groups, excluded_terms, covered_jobs in POTENTIAL_NEW_JOB_RULES:
        if (
            contains_all_groups(title_text, required_groups)
            and not contains_any(title_text, excluded_terms)
            and not contains_any_casefold(known_jobs, covered_jobs)
        ):
            return TaxonomyGapDecision("potential_new_job", f"taxonomy gap guard: {rule_name}")
    return None


def contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def contains_all_groups(text: str, groups: list[list[str]]) -> bool:
    return all(contains_any(text, group) for group in groups)


def contains_any_casefold(values: set[str], terms: list[str]) -> bool:
    return any(term.casefold() in values for term in terms)
