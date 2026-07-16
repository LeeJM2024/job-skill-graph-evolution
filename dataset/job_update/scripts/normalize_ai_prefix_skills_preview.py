"""Preview semantic normalization for skills that start with AI.

Inputs a one-column final skill dictionary and writes:
1. An audit mapping for AI-prefix skills.
2. A one-column full skill dictionary where AI-prefix skills are replaced,
   deduplicated, or dropped according to this preview normalization.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path(
    "C:/Users/LeeJM/Desktop/\u63ed\u699c\u6302\u5e05/"
    "\u5c97\u4f4d\u6570\u636e\u96c6/computer_skill_dictionary_zh_\u5ba1\u6838_final_skills.csv"
)


@dataclass(frozen=True, slots=True)
class Mapping:
    normalized_skill: str
    action: str
    rationale: str


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split()).strip()


def has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def normalize_ai_skill(skill: str) -> Mapping:
    raw = clean_text(skill)
    low = raw.casefold()

    if not raw.startswith("AI"):
        return Mapping(raw, "keep_non_ai", "not_ai_prefix")

    acronym_keep = {
        "aidl": "AIDL",
        "aimet": "AIMET",
        "aide": "AIDE",
        "aigb": "AIGB",
        "aigp": "AIGP",
        "aidc": "AIDC",
        "aidd": "AIDD",
        "aios": "AIOS",
        "aiot": "AIoT",
    }
    if low in acronym_keep:
        return Mapping(acronym_keep[low], "keep_acronym", "ambiguous_acronym_not_collapsed")

    if raw in {"AI", "AI转型", "AI项目", "AI辅助", "AI业务落地", "AI业务内核支持"}:
        return Mapping("", "drop", "too_generic_or_business_outcome")

    if raw in {"AI AF", "AI Core", "AI DSA", "AI DSL", "AI Skill", "AI原生TDD"}:
        return Mapping("", "drop", "user_requested_drop_ai_residual")

    if has(
        r"银行核心项目|财务应用|面试|证书|论文复现|项目POC|项目落地|运营工具|转型|"
        r"培训|基础知识|基础原理|技术原理|相关原理|理论|前沿技术研究|开源|实践|知识$|AI研究$|AI技术$",
        raw,
    ):
        return Mapping("", "drop", "business_scene_or_non_skill")

    if has(r"multi[-\s]?agent|多\s*agent|多智能体|agent\s*group", raw):
        return Mapping("multi-agent", "normalize", "multi_agent_concept")
    if has(r"agent|智能体", raw):
        if has(r"沙箱|安全|凭据|插件|skill|执行环境|攻击面", raw):
            return Mapping("智能体安全", "normalize", "agent_security")
        return Mapping("agent", "normalize", "agent_concept")

    if has(r"\btest\b|testing|测试|质量|质效|门禁|写评|测评", raw):
        return Mapping("AI质量工程", "normalize", "ai_quality_engineering")

    if has(
        r"coding|coder|copilot|code review|for code|for coding|for se\b|ai\+se|ai4se(?!c)|"
        r"代码|编程|编码|开发工具|辅助开发|低代码|ide|集成开发环境|软件开发|驱动开发",
        raw,
    ):
        return Mapping("ai coding", "normalize", "ai_coding_or_developer_assistant")

    if has(r"aiops|ai ops|运维|故障诊断|问题分析|问题排查", raw):
        return Mapping("AIops", "normalize", "ai_operations")

    if has(
        r"safety|security|ai4sec|guardrail|red team|risk|风险|风控|资损|安全|漏洞|逆向|攻击|攻防|"
        r"透明度|护栏|合规|伦理|审计|治理|对抗",
        raw,
    ):
        return Mapping("大模型安全", "normalize", "ai_security_or_risk_control")

    if has(r"ranking|搜索|检索|排序", raw):
        return Mapping("检索排序算法", "normalize", "ai_search_or_ranking")
    if has(r"推荐", raw):
        return Mapping("推荐系统算法", "normalize", "ai_recommendation")

    if has(
        r"infra|infrastructure|ai/ml infra|云原生基础设施|基础设施|集群|算力|workload|workloads|"
        r"compiler|编译|runtime|运行时|运行栈|stack|软件栈|工程平台|一体机|边缘计算设备|"
        r"训练网络|训练通信|调度|软硬件|软硬件全栈|基础架构|服务器|工作负载|全链路|传输协议|"
        r"内存带宽|存储需求|子系统|基础工具|框架内核|框架集成|框架开发|技术栈",
        raw,
    ):
        return Mapping("AI基础设施", "normalize", "ai_infrastructure")

    if has(r"accelerator|asic|soc|芯片|物理设计|ip验证|isp|codec|硬件|处理器|加速卡", raw):
        return Mapping("芯片", "normalize", "ai_hardware_chip")

    if has(r"加速|性能优化|访存|吞吐|延迟|画质提升", raw):
        return Mapping("高性能计算", "normalize", "ai_performance_optimization")

    if has(
        r"api|gateway|网关|serving|saas|服务化|部署|平台|studio|builder|function|中台|能力|"
        r"在线推理|推理网关|服务落地|服务计费|模型路由|模型集成|模型落地|端侧落地",
        raw,
    ):
        return Mapping("模型服务化", "normalize", "model_serving_or_platformization")

    if has(r"推理", raw) and not has(r"逻辑推理|推理能力", raw):
        return Mapping("模型推理", "normalize", "model_inference")

    if has(r"训练数据|训练样本|数据管道|数据建设|训练数据管道", raw):
        return Mapping("数据工程", "normalize", "training_data_engineering")
    if has(r"训练|tuning|调优|模型调优|验证", raw):
        return Mapping("模型训练", "normalize", "model_training_or_tuning")
    if has(r"评测|评估|benchmark|测试集|评测集|效果评估", raw):
        return Mapping("大模型评测", "normalize", "model_evaluation")

    if has(r"for db|ai4db|数据库|数据|sql|schema|db|lakehouse|数据结构|数据开发|数据洞察|标注", raw):
        return Mapping("数据工程", "normalize", "data_engineering")

    if has(r"对齐", raw):
        return Mapping("模型对齐", "normalize", "model_alignment")

    if has(
        r"native|应用开发|业务开发|应用|问答|chat|chatbot|bot|tutor|输入法|驱动ui|"
        r"产品开发|产品功能|客服|客服系统|外呼|数字员工|办公|文档理解|知识库|知识管理|"
        r"智能助手|助手|助理|协作|协同|建站|全栈开发|产品$|产品运营",
        raw,
    ):
        return Mapping("AI应用开发", "normalize", "ai_application_development")

    if has(r"workflow|工作流|编排|自动化|任务|流程", raw):
        return Mapping("AI工作流设计", "normalize", "ai_workflow")

    if has(r"aigc|生成|音乐|音效|超分|超清|图像|视频|设计工具|设计|创作|影像|特效|插帧|显示功能|直播", raw):
        return Mapping("AIGC", "normalize", "ai_generated_content_or_design")

    if has(r"语音|音频", raw):
        return Mapping("音频信号处理", "normalize", "audio_ai")

    if has(r"harness", raw):
        return Mapping("harness工程", "normalize", "ai_harness_engineering")

    if has(r"AI算法|AI模型|算法开发|模型开发|模型优化|模型算法|AI/ML$", raw):
        return Mapping("Machine Learning", "normalize", "ai_model_or_algorithm")

    if has(r"AI/ML系统", raw):
        return Mapping("AI基础设施", "normalize", "ai_ml_system")

    if has(r"AI Engineering|AI for Engineering|AI系统$|AI系统交互|AI系统优化|AI原生系统|AI组件库|AI优化流水线", raw):
        return Mapping("AI工程化", "normalize", "ai_engineering")

    if has(r"AI能效优化", raw):
        return Mapping("高性能计算", "normalize", "ai_energy_efficiency")

    if has(r"AI实验分析|AI效果偏差分析", raw):
        return Mapping("大模型评测", "normalize", "ai_evaluation_analysis")

    if has(r"AI智能化改造|AI智能辅助", raw):
        return Mapping("AI应用开发", "normalize", "ai_application_development")

    if has(r"AI规划", raw):
        return Mapping("AI工作流设计", "normalize", "ai_planning")

    if has(r"AI色彩影调", raw):
        return Mapping("AIGC", "normalize", "ai_media_generation")

    if has(r"逻辑推理|场景孵化|场景落地|企业落地|技术落地|AI落地|解决方案|营销|医疗器械|AI手机|AI眼镜|关卡编辑|AI基础$|AI总结$|AI提效$|AI预测$|AI项目搭建", raw):
        return Mapping("", "drop", "generic_scene_product_or_non_skill")

    if has(r"AI云|AI网络|网络优化|网络故障定位|AI计算|计算单元|计算系统|AI虚拟化|通信策略|AI互联|分发机制|AI系统保护|组件攻防", raw):
        return Mapping("AI基础设施", "normalize", "ai_system_infrastructure")

    if has(r"AI监控", raw):
        return Mapping("AIops", "normalize", "ai_monitoring_ops")

    if has(r"AI移动端|AI跨端全栈", raw):
        return Mapping("跨平台开发", "normalize", "ai_cross_platform_application")

    if has(r"AI感知|AI视觉|AI预测|AI行为策略|AI自适应速度规划|AI网络模型|AI开发模型", raw):
        return Mapping("Machine Learning", "normalize", "ai_model_or_algorithm")

    if has(r"AI绘画|AI翻译|AI辅助FMEA|AI辅助仿真|AI辅助文档|AI辅助校核|AI辅助生产", raw):
        return Mapping("AI应用开发", "normalize", "ai_assisted_application")

    if has(r"工具|工具链|开发框架|技术框架|技术建设|技术生态|功能优化|功能调试|模块|软件平台|软件架构|软件工程|研发|工程|全栈分析|开发$|架构$|框架$|AI原生$", raw):
        return Mapping("AI工程化", "normalize", "ai_engineering")

    if has(r"for science|ai4s|materials|research|phy|optimization|network|scientist|科学|材料", raw):
        return Mapping("", "drop", "research_or_domain_direction")

    return Mapping(raw, "keep_uncertain", "no_confident_ai_prefix_normalization")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize AI-prefix skill names for preview.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--skill-column", default="skill")
    parser.add_argument("--mapping-output", type=Path)
    parser.add_argument("--final-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input, dtype=str).fillna("")
    if args.skill_column not in df.columns:
        raise ValueError(f"Missing skill column: {args.skill_column}. Available: {list(df.columns)}")

    mapping_output = args.mapping_output or args.input.with_name(
        args.input.stem + "_ai_prefix_normalization_preview.csv"
    )
    final_output = args.final_output or args.input.with_name(
        args.input.stem + "_ai_prefix_normalized.csv"
    )

    rows: list[dict[str, str]] = []
    final_skills: list[str] = []
    ai_source_count = 0
    changed_count = 0
    dropped_count = 0

    for skill in df[args.skill_column].map(clean_text):
        if skill.startswith("AI"):
            ai_source_count += 1
            result = normalize_ai_skill(skill)
            if result.action in {"normalize", "drop"}:
                changed_count += 1
            if result.action == "drop":
                dropped_count += 1
            rows.append(
                {
                    "original_skill": skill,
                    "normalized_skill": result.normalized_skill,
                    "action": result.action,
                    "rationale": result.rationale,
                }
            )
            if result.normalized_skill:
                final_skills.append(result.normalized_skill)
        elif skill:
            final_skills.append(skill)

    final_df = (
        pd.DataFrame({"skill": final_skills})
        .drop_duplicates(subset=["skill"], keep="first")
        .sort_values("skill", key=lambda series: series.str.casefold(), kind="stable")
        .reset_index(drop=True)
    )
    mapping_df = pd.DataFrame(rows).sort_values("original_skill", key=lambda series: series.str.casefold())

    mapping_df.to_csv(mapping_output, index=False, encoding="utf-8-sig")
    final_df.to_csv(final_output, index=False, encoding="utf-8-sig")

    print(f"source_rows={len(df)}")
    print(f"ai_prefix_rows={ai_source_count}")
    print(f"changed_or_dropped_ai_rows={changed_count}")
    print(f"dropped_ai_rows={dropped_count}")
    print(f"final_rows_after_ai_prefix_normalization={len(final_df)}")
    print(f"mapping_output={mapping_output}")
    print(f"final_output={final_output}")


if __name__ == "__main__":
    main()
