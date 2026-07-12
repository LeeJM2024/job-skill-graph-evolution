"""Extract JD skill mentions with a low-cost OpenAI-compatible API.

Default provider is DeepSeek. A GPT/OpenAI-compatible provider can be selected
with --provider gpt.

The script reads the reviewed gold CSV as the project ontology, asks the LLM
to extract span-level skills, then validates that every span appears in the
original JD sentence before writing mentions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DATASET_DIR = Path(__file__).resolve().parents[1]
SKILL_EXTRACT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = DATASET_DIR / "cleaned" / "all_jobs_23714_normalized.jsonl"
DEFAULT_GOLD = SKILL_EXTRACT_DIR / "job_skill_gold" / "job_skill_gold_clean.csv"
FALLBACK_GOLD = SKILL_EXTRACT_DIR / "job_skill_gold" / "job_skill_gold_ai_reviewed_all.csv"
DEFAULT_OUTPUT_DIR = SKILL_EXTRACT_DIR / "output"
DEFAULT_CACHE = SKILL_EXTRACT_DIR / "cache" / "job_skill_extract_api_cache.jsonl"
PROMPT_VERSION = "job_skill_api_v1_2026_07_12"

PROVIDERS = {
    "deepseek": {
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "default_base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "output_prefix": "job_skill_mentions_deepseek",
    },
    "gpt": {
        "model_env": "GPT_MODEL",
        "default_model": "gpt-4.1-mini",
        "base_url_env": "GPT_BASE_URL",
        "default_base_url": "https://api.openai.com/v1",
        "api_key_env": "GPT_API_KEY",
        "output_prefix": "job_skill_mentions_gpt",
    },
}

BASE_FIELDS = [
    "job_id",
    "job_title",
    "source_type",
    "source_name",
    "raw_skill",
    "normalized_skill",
    "category",
    "span_text",
    "span_start",
    "span_end",
    "skillspan_label",
    "skill_type",
    "evidence_sentence",
    "evidence_field",
    "confidence",
    "match_method",
]

JOB_SKILL_FIELDS = [
    "job_id",
    "job_title",
    "source_type",
    "source_name",
    "normalized_skill",
    "category",
    "skill_type",
    "mention_count",
    "max_confidence",
    "evidence_count",
    "evidence_sentences",
    "evidence_fields",
    "span_texts",
    "match_methods",
]


def load_env_file(path: Path | None = None) -> None:
    env_path = path or (DATASET_DIR / ".env")
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

RULES = """
你是招聘 JD 技能抽取器。只抽能作为简历技能/能力点的内容，不抽纯业务对象、岗位愿景、泛泛职责。

硬规则：
1. span_text 必须是原句中连续出现的原文片段；normalized_skill 才是归一后的技能名。span_text 尽量取最小但语义完整的触发词，不要把修饰词和后续动作一起吞进去。例：基座大模型/AI大模型 -> span_text 取“大模型”；llm大模型 -> span_text 取“llm”；UE5引擎 -> 对 UE 取“UE5”，对游戏引擎开发可取“UE5引擎”；C/C++ -> 对 C++ 取“C++”。
2. LLM/大模型/大语言模型 -> LLM。span_text 优先取最小触发词“大模型/LLM/大语言模型”，不要取“AI大模型/基座大模型/大模型训练/推理”等更长片段。
3. prompt/提示词/System Prompt/Few-shot Prompt -> prompt工程。
4. Agent/智能体 -> agent；多智能体/Multi-Agent/多 Agent/Agent Group -> multi-agent，并且同一句同一概念不要再重复抽 agent。
5. 微调/SFT/精调/蒸馏/指令微调 -> 大模型微调。
6. RL/RLHF/PPO/DPO/GRPO/强化学习，在大模型后训练语境下 -> 大模型强化。
7. 后训练/强化学习后训练 -> 大模型后训练；预训练/基模训练 -> 大模型预训练；保留模型训练可重复命中。
8. 训练只在模型语境抽为模型训练；推理只在模型推理/部署/服务/引擎/性能语境抽为模型推理。逻辑推理、推理能力、推理总结不要抽模型推理。
9. 分布式 -> 分布式系统。凡是原文出现“分布式计算/分布式存储/分布式训练/分布式推理/分布式深度学习/分布式系统”等，span_text 优先只取连续原文里的最小触发词“分布式”，normalized_skill 固定为“分布式系统”。不要把 span_text 扩成“分布式计算/分布式存储”等长词。
10. context/上下文/长上下文/长序列/KV Cache/Memory 等上下文或推理记忆语境 -> 上下文工程。
11. 评测/benchmark/human eval/效果评估，在大模型语境下 -> 大模型评测。
12. API 网关、模型部署、推理服务、主流推理框架、服务化引擎、在线服务、能力封装、工具组件、能力中台、MaaS 产品链路 -> 模型服务化。只有在模型/大模型/推理/服务化语境下才把“部署/上线”抽为模型服务化，普通软件部署流程不要抽。
13. GPU/CUDA/Triton/算力/吞吐/延迟/通信瓶颈/kernel/operator perf/MFU/性能分析与调优/性能优化/推理加速/算力利用率/模型吞吐/高性能推理系统，在计算、模型、系统优化语境下 -> 高性能计算。CUDA 本身仍可抽 CUDA，但不要把 Nsight Systems/Nsight Compute/CUDA Profiler 归一成 GPU。
14. 算子/kernel/operator 算子语境 -> 算子开发。
15. RAG/search/recall/rerank/vector retrieval/搜推/搜广推 -> 检索排序算法；推荐/推荐模型/LLM4Rec/搜广推 -> 推荐系统算法。
16. 数据处理、数据分析、数据平台、数据集、数据治理、数据加工、数据清洗、特征提取、数据流水线、数据仓库、数据科学、数据库设计优化、ETL、数据ETL、Spark、Flink、Hadoop、大数据、数仓、数据库等数据技术语境 -> 数据工程。此时 normalized_skill 只写数据工程，不要写 Spark/Flink/Hadoop/ETL/数据库。单独“存储”不是数据工程，除非原文是数据存储、分布式存储、数据库存储等数据技术语境。用户数据/业务数据这类纯业务对象不抽。
17. 前端相关但无具体技术时 -> 前端架构设计；后端/后台/服务端相关但无更具体技术时 -> 后端开发。微服务单独作为架构技术时抽 Microservices，span_text 只取“微服务”；如果原文是“微服务设计/微服务开发/微服务设计开发/微服务重构/服务端开发”等后端工程动作，再额外抽后端开发。编译器后端 CodeGen 不是后端开发。
18. UE/UE4/UE5/Unreal Engine/Unreal Engine 5 -> UE，normalized_skill 不要写 Unreal Engine；Unity 保留 Unity；出现“UE5引擎/ue4/ue5引擎/游戏引擎/引擎开发/引擎管线/管线”等游戏引擎语境时，还要抽游戏引擎开发，span_text 优先取完整短语如“UE5引擎/ue4/ue5引擎/游戏引擎/管线”，不要只取“引擎”。“蓝图”单独出现不要抽游戏引擎开发；渲染/Shader/渲染管线 -> 渲染技术。
19. ASR/语音识别/语音大模型 -> 大模型ASR；TTS/语音合成 -> TTS；只有语音算法、声学算法、音频算法、语音识别算法等算法语境才抽语音算法，单纯“图像/文本/视频/语音”模态枚举不要抽语音算法；ANC/自适应滤波/声场控制 -> 音频信号处理。
20. 安全要区分：大模型内容安全/红队/RAG安全/安全验证/安全审计/智能化安全审计 -> 大模型安全；Agent 沙箱/终端/插件/凭据泄露 -> 智能体安全。
21. vibe coding/AI coding/code agent/code generation/代码生成工具/IDE智能助手/AI辅助生成代码/生成代码/智能化生成代码 编程助手语境 -> ai coding。
22. iOS/Android -> ios开发/android开发；跨平台/跨架构开发 -> 跨平台开发。
23. VLM、SFT、DPO、SDK、RL、TTS、AIops、LLMOps/MLOps、知识图谱、模型对齐、模型量化、模型压缩、AI基础设施、具身智能、Docker、NVLink、NVSwitch、InfiniBand、芯片等显式出现时按对应技能抽取。
24. 分布式训练/推理集群、训练/推理集群、分布式训练框架、模型训练框架、AI工程平台、MaaS链路、软硬协同适配、软硬件协同设计、模型编译、运行时优化、编译优化、IR改写、后端CodeGen、模型工具链、算力基础设施等 AI 系统底座语境 -> AI基础设施。单独“云服务/算力租赁”只有明确作为 AI 基础设施建设对象时才抽 AI基础设施。
25. DevOps、CI/CD、持续集成/持续部署、自动化运维平台、故障容错、稳定交付、可靠性、可观测性、应急响应等系统稳定性语境 -> SRE。若原文同时出现“CI/CD”，并且要抽 CI/CD 这个具体技能，span_text 优先取“CI/CD”。
26. 多模态/Multimodal -> Multimodal AI；多模态大模型这种复合词要分别抽“多模态/Multimodal AI”和“大模型/LLM”，不要把 span_text 扩成整个“多模态大模型”。
27. C/C++ 这种并列表达中，如果 normalized_skill 是 C++，span_text 优先取原文里的 C++，不要取整个 C/C++。
28. 疑难问题攻坚、问题定位、故障分析、缺陷分析等工程排障语境 -> bug分析。
29. 优先使用 ontology 中已有 normalized_skill；只有原文出现明确新技术且 ontology 没有时才新增 normalized_skill。不要把同一类技能自由改名，例如 UE 不要改成 Unreal Engine，数据工程不要改成 Spark，模型服务化不要改成模型部署。

只返回 JSON 对象，格式必须是：
{"mentions":[{"sentence_id":"...","span_text":"...","normalized_skill":"...","category":"...","skill_type":"required|preferred","confidence":0.0,"reason":"..."}]}
""".strip()


# These rules summarize non-literal mappings repeatedly confirmed in the
# reviewed gold data. Examples are selected dynamically from gold rows below.
SEMANTIC_RULE_DESCRIPTIONS = {
    "AI基础设施": "描述 AI 系统底座、训练/推理框架与集群、GPU/RDMA/存储资源、模型编译与运行时、完整训练链路、数据/任务 Pipeline、Agent 运行环境或沙箱建设时，即使没有直写 AI 基础设施，也归一为 AI基础设施。单纯采购大模型、购买云服务或算力租赁不抽。",
    "模型服务化": "描述把模型能力封装成 API、工具、组件、能力中台、MaaS 产品，或完成模型接入、在线服务和规模化交付时，归一为 模型服务化。普通软件/算法部署流程不抽，必须存在模型、推理服务或模型能力产品化语境。",
    "SRE": "描述监控、可观测性、告警、容灾降级、故障恢复、自动化运维、可靠性、稳定性或高可用保障时，归一为 SRE。",
    "高性能计算": "描述训练/推理的延迟、吞吐、显存、通信、资源利用率、GPU/CUDA/Triton Kernel、模型加速或大规模高效训练时，归一为 高性能计算。",
    "数据工程": "描述数据采集、清洗、合成、生产、质检、修复、版本/元数据管理、Pipeline、样本构建或训练数据加载链路时，统一归一为 数据工程。",
    "bug分析": "描述 badcase、根因定位、模型弱项、缺陷归因、疑难问题攻坚、故障分析或适配问题修复时，归一为 bug分析。",
    "推荐系统算法": "描述推荐召回、排序/重排、CTR/CVR、个性化推荐、LLM4Rec、生成式推荐或推荐训练/推理链路的研发、设计或优化时，归一为 推荐系统算法。仅把推荐列为业务使用场景或产品举例时不抽。",
    "检索排序算法": "描述 Search、RAG/知识检索、Embedding/向量检索、全文检索、索引、召回、精排或排序模型的研发、设计或优化时，归一为 检索排序算法。仅把搜索列为业务使用场景或产品举例时不抽。",
    "后端开发": "描述后台/服务端系统、微服务工程、高并发高可用架构、服务器或服务接口的设计开发时，归一为 后端开发。仅出现全栈职位名、但没有后台/服务端证据时不自动补后端开发。",
    "前端架构设计": "描述前端开发、前端架构、AI 对话界面或前端侧工作流实现，且没有更合适的具体前端技能时，归一为 前端架构设计。",
    "AI工作流设计": "描述 Agent 工作流、任务拆解、Planning、Reflection、工具调用、多轮决策、编排或端到端自动执行流程时，归一为 AI工作流设计。",
    "游戏引擎开发": "描述 UE/Unity 引擎接口、运行时、客户端、关卡/动画管线或引擎集成开发时，归一为 游戏引擎开发。仅出现蓝图但没有 UE/Unreal/Unity/游戏引擎语境时不抽。",
    "大模型安全": "描述大模型/AIGC 内容安全、幻觉治理、红队、RAG 安全、安全验证/审计、风险识别或模型安全防御时，归一为 大模型安全。",
    "智能体安全": "描述 Agent 沙箱、安全执行环境、终端/插件/Skill 调用、凭据、本地执行或智能体生命周期安全时，归一为 智能体安全。",
    "大模型评测": "描述模型/Agent 的评测基准、指标体系、Rubric、自动化评测流水线、效果验证、回归或评测数据建设时，归一为 大模型评测。",
    "模型训练": "描述模型语境中的训练框架、训练流程、训练方法、训练需求或训练与优化时，归一为 模型训练；普通业务培训不抽。",
    "模型推理": "描述模型推理引擎、推理优化/加速、投机解码、训推优化或推理部署链路时，归一为 模型推理；逻辑推理能力不抽。",
}


SEMANTIC_EXAMPLE_HINTS = {
    "AI基础设施": ["完整训练链路", "训练框架", "推理框架", "训练/推理集群", "集群", "软硬协同", "模型编译", "运行时", "Infra", "底座", "Pipeline", "Sandbox"],
    "模型服务化": ["能力封装", "API", "工具与组件", "能力中台", "MaaS", "模型服务", "规模化部署"],
    "SRE": ["可观测性", "告警", "容灾", "故障恢复", "自动化运维", "可靠性", "稳定性", "高可用"],
    "高性能计算": ["延迟", "吞吐", "显存", "通信", "资源效率", "CUDA", "Triton", "Kernel", "加速"],
    "数据工程": ["数据Pipeline", "数据生产", "数据清洗", "数据合成", "质检", "数据修复", "元数据", "样本"],
    "bug分析": ["badcase", "根因", "弱项", "缺陷归因", "疑难问题", "故障问题", "适配问题"],
    "推荐系统算法": ["召回", "排序", "重排", "CTR", "CVR", "个性化推荐", "LLM4Rec", "推荐模型"],
    "检索排序算法": ["Search", "RAG", "Embedding", "向量", "全文检索", "索引", "召回", "精排"],
    "后端开发": ["后台", "服务端", "微服务", "高并发", "高可用", "服务器", "服务架构"],
    "前端架构设计": ["前端", "大前端", "对话界面"],
    "AI工作流设计": ["Workflow", "工作流", "任务拆解", "Planning", "Reflection", "工具调用", "多轮决策", "编排"],
    "游戏引擎开发": ["UE", "Unreal", "Unity", "引擎", "关卡", "动画管线", "运行时"],
    "大模型安全": ["内容安全", "幻觉", "红队", "RAG安全", "安全验证", "安全审计", "风险识别"],
    "智能体安全": ["Agent沙箱", "安全执行环境", "终端", "插件", "Skill 调用", "凭据", "生命周期安全"],
    "大模型评测": ["评测", "Evaluation", "Rubric", "Benchmark", "指标体系", "效果验证", "回归"],
    "模型训练": ["训练框架", "训练流程", "训练方法", "训练需求", "训练和优化"],
    "模型推理": ["推理引擎", "推理优化", "推理加速", "投机", "训推优化", "推理部署"],
}


SEMANTIC_EXTRACTION_CHECKLIST = """
返回 JSON 前必须逐句完成三步检查：
1. 显式技能必检：原句明确出现大模型/LLM、大语言模型、分布式、prompt/提示词、Agent/智能体、训练、推理、数据技术、UE/Unity、芯片、Docker 等项目规则触发词时，不能漏掉对应 normalized_skill。
2. 隐含技能复核：按 semantic_inference_rules 判断职责、研发对象、系统建设和优化目标中隐含的技能；允许一个 span 支撑多个确有依据的汇总技能。
3. 业务枚举过滤：如果技术词只出现在“例如/比如/场景包括/应用于”等业务或产品举例中，且句子没有要求研发、设计、实现、训练、优化、构建或相关能力，不要把该举例抽成岗位技能。
不要因为职位名、采购对象、泛化行业方向或常识联想补技能。宁可引用明确的职责证据，也不能脱离原句生成技能。
""".strip()


MANDATORY_LITERAL_RULES = [
    (r"大语言模型|大模型|(?<![A-Za-z])LLM(?![A-Za-z])", "LLM"),
    (r"System\s+Prompt|Few-shot\s+Prompt|提示词|(?<![A-Za-z])prompt(?![A-Za-z])", "prompt工程"),
    (r"分布式", "分布式系统"),
    (r"上下文|(?<![A-Za-z])context(?![A-Za-z])", "上下文工程"),
    (r"(?<![A-Za-z])VLM(?![A-Za-z])", "VLM"),
    (r"(?<![A-Za-z])ASR(?![A-Za-z])", "大模型ASR"),
    (r"(?<![A-Za-z])TTS(?![A-Za-z])", "TTS"),
    (r"(?<![A-Za-z])SDK(?![A-Za-z])", "SDK"),
    (r"(?<![A-Za-z])Docker(?![A-Za-z])", "Docker"),
    (r"(?<![A-Za-z])NVLink(?![A-Za-z])", "NVLink"),
    (r"(?<![A-Za-z])NVSwitch(?![A-Za-z])", "NVSwitch"),
    (r"(?<![A-Za-z])InfiniBand(?![A-Za-z])", "InfiniBand"),
    (r"(?<![A-Za-z])Blender(?![A-Za-z])", "Blender"),
    (r"(?<![A-Za-z])iOS(?![A-Za-z])", "ios开发"),
    (r"(?<![A-Za-z])Android(?![A-Za-z])", "android开发"),
    (r"UE5|UE4|(?<![A-Za-z])UE(?![A-Za-z])|Unreal\s+Engine(?:\s+5)?", "UE"),
    (r"知识图谱", "知识图谱"),
    (r"芯片", "芯片"),
    (r"算子", "算子开发"),
    (r"SFT|微调|精调|蒸馏", "大模型微调"),
    (r"DPO|GRPO|强化学习|强化", "大模型强化"),
    (r"vibe\s+coding|AI\s+coding", "ai coding"),
    (r"harness", "harness工程"),
    (r"AIOps", "AIops"),
    (r"bug分析", "bug分析"),
    (r"计算机图形学", "计算机图形学"),
    (r"LLM-based\s+Ranking", "LLM-based Ranking"),
    (r"LLMOps|MLOps", "LLMOps/MLOps"),
    (r"模型对齐", "模型对齐"),
    (r"模型量化", "模型量化"),
    (r"模型压缩", "模型压缩"),
    (r"大模型安全", "大模型安全"),
    (r"智能体安全", "智能体安全"),
    (r"大模型评测", "大模型评测"),
    (r"AI基础设施|AI\s+Infra", "AI基础设施"),
    (r"(?<![A-Za-z])SRE(?![A-Za-z])", "SRE"),
    (r"具身", "具身智能"),
    (r"深度学习", "Deep Learning"),
    (r"完整训练链路", "AI基础设施"),
    (r"基于\s*LLM\s*的企业级落地项目", "模型服务化"),
    (r"游戏引擎", "游戏引擎开发"),
    (r"渲染技术", "渲染技术"),
    (r"语音算法", "语音算法"),
    (r"ANC|自适应滤波|声场控制", "音频信号处理"),
]


DATA_ENGINEERING_TRIGGER = re.compile(
    r"数据处理|数据分析|数据平台|数据集|数据治理|数据加工|数据清洗|数据流水线|数据仓库|数据科学|数据生产|数据质检|数据修复|"
    r"数据Pipeline|数据\s*Pipeline|数据ETL|样本构建|训练样本|样本生产|样本相关后台|(?<![A-Za-z])ETL(?![A-Za-z])|(?<![A-Za-z])Spark(?![A-Za-z])|"
    r"(?<![A-Za-z])Flink(?![A-Za-z])|(?<![A-Za-z])Hadoop(?![A-Za-z])|大数据|数仓"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def build_semantic_gold_rules(
    rows: Iterable[dict[str, Any]],
    examples_per_skill: int = 3,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        skill = clean_text(row.get("normalized_skill") or row.get("gold_normalized_skill"))
        if skill not in SEMANTIC_RULE_DESCRIPTIONS:
            continue
        span = clean_text(row.get("span_text") or row.get("gold_span_text"))
        sentence = clean_text(row.get("text"))
        if not span or not sentence:
            continue
        grouped[skill].append(
            {
                "span_text": span,
                "normalized_skill": skill,
                "sentence": sentence[:180],
            }
        )

    rules: list[dict[str, Any]] = []
    for skill, instruction in SEMANTIC_RULE_DESCRIPTIONS.items():
        hints = SEMANTIC_EXAMPLE_HINTS.get(skill, [])

        def example_score(example: dict[str, str]) -> tuple[int, int, int]:
            span = example["span_text"]
            sentence = example["sentence"]
            non_literal = 1 if skill.casefold() not in span.casefold() else 0
            hint_score = sum(4 for hint in hints if hint.casefold() in span.casefold())
            hint_score += sum(1 for hint in hints if hint.casefold() in sentence.casefold())
            useful_length = min(len(span), 60)
            return non_literal, hint_score, useful_length

        candidates = sorted(grouped.get(skill, []), key=example_score, reverse=True)
        selected: list[dict[str, str]] = []
        seen_spans: set[str] = set()
        for example in candidates:
            span_key = example["span_text"].casefold()
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)
            selected.append(example)
            if len(selected) >= examples_per_skill:
                break
        rules.append(
            {
                "normalized_skill": skill,
                "semantic_rule": instruction,
                "gold_examples": selected,
            }
        )
    return rules


def split_sentences(text: str) -> list[str]:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"[\n。！？；;]+", text)
    return [part.strip(" \t:-—，,、)") for part in parts if part.strip()]


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BASE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_job_skill_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOB_SKILL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_gold_ontology(path: Path, max_examples: int = 50) -> dict[str, Any]:
    skill_counts: Counter[str] = Counter()
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples_by_skill: dict[str, list[dict[str, str]]] = defaultdict(list)
    gold_rows: list[dict[str, Any]] = []
    if not path.exists() and path.name == "job_skill_gold_clean.csv" and FALLBACK_GOLD.exists():
        path = FALLBACK_GOLD
    if not path.exists():
        return {"skills": [], "examples": [], "semantic_rules": []}

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("decision") == "REJECT":
                continue
            skill = clean_text(row.get("normalized_skill") or row.get("gold_normalized_skill"))
            span = clean_text(row.get("span_text") or row.get("gold_span_text"))
            category = clean_text(row.get("category") or row.get("gold_category")) or "未分类"
            text = clean_text(row.get("text"))
            if not skill or not span:
                continue
            gold_rows.append(dict(row))
            skill_counts[skill] += 1
            category_counts[skill][category] += 1
            if len(examples_by_skill[skill]) < 1:
                examples_by_skill[skill].append(
                    {
                        "span_text": span,
                        "normalized_skill": skill,
                        "category": category,
                        "sentence": text[:160],
                    }
                )

    skills = [
        {
            "normalized_skill": skill,
            "category": category_counts[skill].most_common(1)[0][0],
            "gold_count": count,
        }
        for skill, count in skill_counts.most_common()
    ]
    examples: list[dict[str, str]] = []
    for item in skills:
        examples.extend(examples_by_skill[item["normalized_skill"]])
        if len(examples) >= max_examples:
            break
    return {
        "skills": skills,
        "examples": examples[:max_examples],
        "semantic_rules": build_semantic_gold_rules(gold_rows),
    }


def load_jobs(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return list(read_jsonl(path))
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError(f"Unsupported input format: {path}")


def build_units(job: dict[str, Any], max_sentences_per_job: int) -> list[dict[str, str]]:
    fields = ["job_title", "job_description", "requirements", "qualification", "responsibility"]
    units: list[dict[str, str]] = []
    for field in fields:
        value = clean_text(job.get(field))
        if not value:
            continue
        parts = [value] if field == "job_title" else split_sentences(value)
        for index, sentence in enumerate(parts, start=1):
            units.append(
                {
                    "sentence_id": f"{clean_text(job.get('job_id')) or 'job'}::{field}::{index:04d}",
                    "evidence_field": field,
                    "text": sentence,
                }
            )
            if len(units) >= max_sentences_per_job:
                return units
    return units


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(path):
        key = item.get("cache_key")
        if key:
            cache[str(key)] = item
    return cache


def append_cache(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig", newline="\n") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def cache_key(
    model: str,
    base_url: str,
    units: list[dict[str, str]],
    ontology_digest: str,
) -> str:
    payload = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "base_url": base_url.rstrip("/"),
        "ontology_digest": ontology_digest,
        "units": units,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def endpoint(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return value + "/chat/completions"


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def call_chat_api(
    *,
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    timeout: int,
    retries: int,
    temperature: float,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(endpoint(base_url), data=encoded, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return extract_json_object(content)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"API request failed after {retries + 1} attempts: {last_error}")


def call_skill_extraction(
    *,
    api_key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    timeout: int,
    retries: int,
    temperature: float,
    literal_skills: Iterable[str] = (),
) -> dict[str, Any]:
    sentence_by_id = {
        str(unit.get("sentence_id", "")): clean_text(unit.get("text"))
        for unit in user_payload.get("sentences", [])
    }

    def prepare_mentions(mentions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for mention in mentions:
            sid = str(mention.get("sentence_id", ""))
            prepared.append(canonicalize_api_mention(mention, sentence_by_id.get(sid, "")))
        return prepared

    def mention_key(mention: dict[str, Any]) -> tuple[str, str, str]:
        return (
            clean_text(mention.get("sentence_id")),
            clean_text(mention.get("span_text")),
            clean_text(mention.get("normalized_skill")),
        )

    first_result = call_chat_api(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_payload=user_payload,
        timeout=timeout,
        retries=retries,
        temperature=temperature,
    )
    all_mentions = prepare_mentions(first_result.get("mentions", []))
    first_pass_count = len(all_mentions)
    first_pass_keys = {mention_key(mention) for mention in all_mentions}
    mandatory_mentions = prepare_mentions(
        build_mandatory_rule_mentions(user_payload.get("sentences", []), literal_skills=literal_skills)
    )
    mandatory_new_mentions = [mention for mention in mandatory_mentions if mention_key(mention) not in first_pass_keys]
    mandatory_keys = {mention_key(mention) for mention in mandatory_mentions}
    all_mentions.extend(mandatory_new_mentions)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for mention in all_mentions:
        key = mention_key(mention)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mention)
    filtered_mentions = [
        mention
        for mention in deduped
        if mention_key(mention) in mandatory_keys
        or has_project_skill_evidence(
            clean_text(mention.get("normalized_skill")),
            sentence_by_id.get(clean_text(mention.get("sentence_id")), ""),
        )
    ]
    return {
        "mentions": filtered_mentions,
        "pipeline_stats": {
            "first_pass_mentions": first_pass_count,
            "mandatory_rule_new_mentions": len(mandatory_new_mentions),
            "final_deduped_mentions": len(filtered_mentions),
            "boundary_filtered_mentions": len(deduped) - len(filtered_mentions),
            "net_new_mentions": len(filtered_mentions) - first_pass_count,
        },
        "mandatory_added_mentions": mandatory_new_mentions,
    }


def build_system_prompt(ontology: dict[str, Any], max_ontology_skills: int) -> str:
    compact_ontology = {
        "preferred_skills": ontology["skills"][:max_ontology_skills],
        "gold_examples": ontology["examples"],
        "semantic_inference_rules": ontology.get("semantic_rules", []),
    }
    return (
        RULES
        + "\n\n下面是本项目已人工审过的 gold ontology，优先沿用其中 normalized_skill 和 category：\n"
        + json.dumps(compact_ontology, ensure_ascii=False, separators=(",", ":"))
        + "\n\nsemantic_inference_rules 是从人工金标中归纳出的高优先级语义规则和 few-shot。"
        + "即使原句没有直接出现 normalized_skill 名称，只要句意与规则及 gold_examples 一致，也要抽取该技能；"
        + "但必须引用原句中的连续证据作为 span_text，不能脱离原句凭常识补技能。"
        + "\n\n"
        + SEMANTIC_EXTRACTION_CHECKLIST
        + "\n\n必须只返回合法 JSON 对象，不要 Markdown，不要代码块。"
    )


SKILL_ALIASES = {
    "Unreal Engine": "UE",
    "UE4": "UE",
    "UE5": "UE",
    "多模态": "Multimodal AI",
    "Spark": "数据工程",
    "Flink": "数据工程",
    "Hadoop": "数据工程",
    "ETL": "数据工程",
    "数据ETL": "数据工程",
}


def first_present(text: str, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate and candidate in text:
            return candidate
    return None


def canonicalize_api_mention(mention: dict[str, Any], sentence: str) -> dict[str, Any]:
    """Hard-normalize API output to the project gold-label rules."""
    result = dict(mention)
    span = clean_text(result.get("span_text"))
    skill = clean_text(result.get("normalized_skill"))
    skill = SKILL_ALIASES.get(skill, skill)

    lower_span = span.lower()
    if skill == "agent" and any(token in lower_span for token in ["multi-agent", "multi agent", "多智能体", "多 agent"]):
        skill = "multi-agent"

    if skill == "LLM":
        fixed = first_present(span, ["LLM", "llm", "大语言模型", "大模型"])
        if fixed:
            span = fixed
    elif skill == "UE":
        match = re.search(r"(?i)UE[45]?", span)
        if match:
            span = span[match.start() : match.end()]
        else:
            fixed = first_present(span, ["Unreal Engine 5", "Unreal Engine"])
            if fixed:
                span = fixed
    elif skill == "C++":
        fixed = first_present(span, ["C++"])
        if fixed:
            span = fixed
    elif skill == "CI/CD":
        fixed = first_present(span, ["CI/CD"])
        if fixed:
            span = fixed
    elif skill == "CUDA":
        fixed = first_present(span, ["CUDA"])
        if fixed:
            span = fixed
    elif skill == "分布式系统":
        fixed = first_present(span, ["分布式"])
        if fixed:
            span = fixed
    elif skill == "大模型微调":
        fixed = first_present(span, ["SFT", "sft", "微调", "精调", "蒸馏", "指令微调"])
        if fixed:
            span = fixed
    elif skill == "大模型强化":
        fixed = first_present(span, ["DPO", "GRPO", "RLHF", "PPO", "RL", "强化"])
        if fixed:
            span = fixed
    elif skill == "模型训练":
        fixed = first_present(span, ["模型训练", "训练"])
        if fixed:
            span = fixed
    elif skill == "模型推理":
        fixed = first_present(span, ["推理"])
        if fixed:
            span = fixed
    elif skill == "数据工程":
        fixed = first_present(
            span,
            [
                "Spark",
                "Flink",
                "Hadoop",
                "ETL",
                "数据治理",
                "数据加工",
                "数据处理",
                "数据分析",
                "数据平台",
                "数据集",
                "大数据",
                "数据库",
                "数仓",
            ],
        )
        if fixed:
            span = fixed

    result["span_text"] = span
    result["normalized_skill"] = skill
    return result


def build_mandatory_rule_mentions(
    units: Iterable[dict[str, Any]],
    literal_skills: Iterable[str] = (),
) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    ontology_skills = sorted({clean_text(skill) for skill in literal_skills if clean_text(skill)}, key=len, reverse=True)

    def add_mention(sentence_id: str, match: re.Match[str], skill: str) -> None:
        mentions.append(
            {
                "sentence_id": sentence_id,
                "span_text": match.group(0),
                "normalized_skill": skill,
                "category": "未分类",
                "skill_type": "required",
                "confidence": 1.0,
                "reason": "project_mandatory_literal_rule",
            }
        )

    for unit in units:
        sentence_id = clean_text(unit.get("sentence_id"))
        sentence = clean_text(unit.get("text"))
        if not sentence_id or not sentence:
            continue

        multi_ranges: list[tuple[int, int]] = []
        for match in re.finditer(r"多智能体|Multi[- ]Agent|Agent\s+Group|多\s*Agent", sentence, flags=re.IGNORECASE):
            add_mention(sentence_id, match, "multi-agent")
            multi_ranges.append((match.start(), match.end()))
        for match in re.finditer(r"智能体|(?<![A-Za-z])Agent(?![A-Za-z])", sentence, flags=re.IGNORECASE):
            if any(start <= match.start() and match.end() <= end for start, end in multi_ranges):
                continue
            add_mention(sentence_id, match, "agent")

        for pattern, skill in MANDATORY_LITERAL_RULES:
            for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
                add_mention(sentence_id, match, skill)

        for skill in ontology_skills:
            escaped = re.escape(skill)
            if re.fullmatch(r"[A-Za-z0-9_+#. /-]+", skill):
                pattern = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
            else:
                pattern = escaped
            for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
                add_mention(sentence_id, match, skill)

        for match in DATA_ENGINEERING_TRIGGER.finditer(sentence):
            add_mention(sentence_id, match, "数据工程")

        model_context = re.search(r"大模型|大语言模型|LLM|VLM|多模态模型|模型训练|模型推理|SFT|RLHF", sentence, re.IGNORECASE)
        if model_context:
            for match in re.finditer(r"训练", sentence):
                add_mention(sentence_id, match, "模型训练")
            for match in re.finditer(r"推理", sentence):
                add_mention(sentence_id, match, "模型推理")

        for match in re.finditer(r"前端", sentence):
            add_mention(sentence_id, match, "前端架构设计")
        if "CodeGen" not in sentence:
            for match in re.finditer(r"后端|后台|服务端", sentence):
                add_mention(sentence_id, match, "后端开发")

    return mentions


def has_project_skill_evidence(skill: str, sentence: str) -> bool:
    if skill == "模型服务化":
        return bool(re.search(r"模型|LLM|推理服务|MaaS|模型API|能力封装|能力中台|服务化", sentence, re.IGNORECASE))
    if skill == "前端架构设计":
        return "前端" in sentence or "大前端" in sentence
    if skill == "后端开发":
        return bool(re.search(r"后端|后台|服务端|微服务|服务器", sentence))
    if skill == "推荐系统算法":
        return bool(re.search(r"推荐算法|推荐模型|推荐系统|召回|排序|重排|CTR|CVR|LLM4Rec|生成式推荐", sentence, re.IGNORECASE))
    if skill == "检索排序算法":
        return bool(re.search(r"搜索算法|检索|RAG|Embedding|向量引擎|全文检索|索引|召回|精排|排序模型|Search\s+Agent", sentence, re.IGNORECASE))
    if skill == "大模型预训练":
        return bool(re.search(r"预训练|Pretrain|基模训练|基础模型训练", sentence, re.IGNORECASE))
    if skill == "模型训练":
        return "训练" in sentence and bool(
            re.search(r"大模型|大语言模型|模型训练|LLM|VLM|多模态模型|预训练|微调|SFT|RLHF", sentence, re.IGNORECASE)
        )
    if skill == "数据工程":
        return bool(DATA_ENGINEERING_TRIGGER.search(sentence) or "数据工程" in sentence)
    if skill == "Multimodal AI":
        return bool(re.search(r"多模态|跨模态|Multimodal|(?<![A-Za-z])VLM(?![A-Za-z])", sentence, re.IGNORECASE))
    return True


def normalize_mention(
    mention: dict[str, Any],
    unit_by_id: dict[str, dict[str, str]],
    job: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    sid = clean_text(mention.get("sentence_id"))
    unit = unit_by_id.get(sid)
    if not unit:
        return None, f"unknown sentence_id: {sid}"

    sentence = unit["text"]
    mention = canonicalize_api_mention(mention, sentence)
    span = clean_text(mention.get("span_text"))
    if not span:
        return None, "empty span_text"
    start = sentence.find(span)
    if start < 0:
        return None, f"span not found: {span}"
    end = start + len(span)
    skill = clean_text(mention.get("normalized_skill"))
    if not skill:
        return None, "empty normalized_skill"

    skill_type = clean_text(mention.get("skill_type")) or "required"
    if skill_type not in {"required", "preferred"}:
        skill_type = "required"

    return (
        {
            "job_id": clean_text(job.get("job_id")),
            "job_title": clean_text(job.get("job_title")),
            "source_type": clean_text(job.get("source_type")),
            "source_name": clean_text(job.get("source_name")) or clean_text(job.get("source")),
            "raw_skill": span,
            "normalized_skill": skill,
            "category": clean_text(mention.get("category")) or "未分类",
            "span_text": span,
            "span_start": start,
            "span_end": end,
            "skillspan_label": "knowledge",
            "skill_type": skill_type,
            "evidence_sentence": sentence,
            "evidence_field": unit["evidence_field"],
            "confidence": float(mention.get("confidence") or 0.80),
            "match_method": "llm_api_semantic",
        },
        None,
    )


def dedupe_mentions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int, int, str]] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row["job_id"],
            row["evidence_sentence"],
            int(row["span_start"]),
            int(row["span_end"]),
            row["normalized_skill"],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def aggregate_job_skills(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge sentence-level mentions into one Job-Skill row with traceable evidence."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        job_id = clean_text(row.get("job_id"))
        skill = clean_text(row.get("normalized_skill"))
        if not job_id or not skill:
            continue
        key = (job_id, skill)
        item = grouped.setdefault(
            key,
            {
                "job_id": job_id,
                "job_title": clean_text(row.get("job_title")),
                "source_type": clean_text(row.get("source_type")),
                "source_name": clean_text(row.get("source_name")),
                "normalized_skill": skill,
                "category_counts": Counter(),
                "skill_types": set(),
                "mentions": [],
                "evidence_seen": set(),
            },
        )
        category = clean_text(row.get("category")) or "未分类"
        item["category_counts"][category] += 1
        item["skill_types"].add(clean_text(row.get("skill_type")) or "required")

        evidence_key = (
            clean_text(row.get("evidence_sentence")),
            clean_text(row.get("evidence_field")),
            clean_text(row.get("span_text")),
            int(row.get("span_start") or 0),
            int(row.get("span_end") or 0),
        )
        if evidence_key in item["evidence_seen"]:
            continue
        item["evidence_seen"].add(evidence_key)
        item["mentions"].append(
            {
                "raw_skill": clean_text(row.get("raw_skill")),
                "span_text": clean_text(row.get("span_text")),
                "span_start": int(row.get("span_start") or 0),
                "span_end": int(row.get("span_end") or 0),
                "evidence_sentence": clean_text(row.get("evidence_sentence")),
                "evidence_field": clean_text(row.get("evidence_field")),
                "confidence": float(row.get("confidence") or 0.0),
                "match_method": clean_text(row.get("match_method")),
            }
        )

    aggregated: list[dict[str, Any]] = []
    for item in grouped.values():
        mentions = item["mentions"]
        category_counts: Counter[str] = item["category_counts"]
        skill_type = "required" if "required" in item["skill_types"] else "preferred"
        evidence_sentences = list(dict.fromkeys(mention["evidence_sentence"] for mention in mentions))
        evidence_fields = list(dict.fromkeys(mention["evidence_field"] for mention in mentions))
        span_texts = list(dict.fromkeys(mention["span_text"] for mention in mentions))
        match_methods = list(dict.fromkeys(mention["match_method"] for mention in mentions))
        aggregated.append(
            {
                "job_id": item["job_id"],
                "job_title": item["job_title"],
                "source_type": item["source_type"],
                "source_name": item["source_name"],
                "normalized_skill": item["normalized_skill"],
                "category": category_counts.most_common(1)[0][0],
                "skill_type": skill_type,
                "mention_count": len(mentions),
                "max_confidence": max(mention["confidence"] for mention in mentions),
                "evidence_count": len(evidence_sentences),
                "evidence_sentences": evidence_sentences,
                "evidence_fields": evidence_fields,
                "span_texts": span_texts,
                "match_methods": match_methods,
                "evidence": mentions,
            }
        )
    return sorted(aggregated, key=lambda item: (item["job_id"], item["normalized_skill"]))


def flatten_job_skill_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        flattened.append(
            {
                **row,
                "evidence_sentences": json.dumps(row["evidence_sentences"], ensure_ascii=False),
                "evidence_fields": json.dumps(row["evidence_fields"], ensure_ascii=False),
                "span_texts": json.dumps(row["span_texts"], ensure_ascii=False),
                "match_methods": json.dumps(row["match_methods"], ensure_ascii=False),
            }
        )
    return flattened


def resolve_provider_config(args: argparse.Namespace) -> dict[str, str]:
    provider = PROVIDERS[args.provider]
    model = args.model or os.getenv(provider["model_env"], provider["default_model"])
    base_url = args.base_url or os.getenv(provider["base_url_env"], provider["default_base_url"])
    api_key_env = args.api_key_env or provider["api_key_env"]
    output_prefix = getattr(args, "output_prefix", None) or provider["output_prefix"]
    return {
        "provider": args.provider,
        "model": model,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "output_prefix": output_prefix,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract JD skills with DeepSeek/OpenAI-compatible API.")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="deepseek")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input JD jsonl/csv path.")
    parser.add_argument("--jd-text", default="", help="Direct JD text. If set, --input is ignored.")
    parser.add_argument("--jd-title", default="新招聘启事", help="Job title used with --jd-text.")
    parser.add_argument("--single-job-id", default="manual_jd_0001", help="Job id used with --jd-text.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD, help="Reviewed gold CSV used as ontology/rule examples.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-prefix", default=None)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--limit", type=int, default=20, help="Max jobs to process. Use 0 for all.")
    parser.add_argument("--job-id", action="append", default=[], help="Process only selected job_id. Can repeat.")
    parser.add_argument("--max-sentences-per-job", type=int, default=40)
    parser.add_argument("--max-ontology-skills", type=int, default=260)
    parser.add_argument("--max-gold-examples", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true", help="Build prompt/input and report counts without calling API.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file()
    provider_config = resolve_provider_config(args)
    if args.jd_text:
        jobs = [
            {
                "job_id": args.single_job_id,
                "job_title": args.jd_title,
                "source_type": "manual",
                "source_name": "manual_input",
                "job_description": args.jd_text,
            }
        ]
    else:
        jobs = load_jobs(args.input)
    if args.job_id and not args.jd_text:
        wanted = set(args.job_id)
        jobs = [job for job in jobs if clean_text(job.get("job_id")) in wanted]
    if args.limit and args.limit > 0:
        jobs = jobs[: args.limit]

    ontology = load_gold_ontology(args.gold, max_examples=args.max_gold_examples)
    ontology_digest = hashlib.sha256(
        json.dumps(ontology, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    system_prompt = build_system_prompt(ontology, args.max_ontology_skills)
    cache = load_cache(args.cache)

    if args.dry_run:
        units = sum(len(build_units(job, args.max_sentences_per_job)) for job in jobs)
        print(
            json.dumps(
                {
                    "jobs": len(jobs),
                    "sentence_units": units,
                    "gold_skills": len(ontology["skills"]),
                    "gold_examples": len(ontology["examples"]),
                    "semantic_rules": len(ontology.get("semantic_rules", [])),
                    "semantic_gold_examples": sum(
                        len(rule.get("gold_examples", [])) for rule in ontology.get("semantic_rules", [])
                    ),
                    "provider": provider_config["provider"],
                    "model": provider_config["model"],
                    "base_url": provider_config["base_url"],
                    "api_key_env": provider_config["api_key_env"],
                    "prompt_chars": len(system_prompt),
                    "cache_entries": len(cache),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    api_key = os.getenv(provider_config["api_key_env"])
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${provider_config['api_key_env']} first.")

    mentions: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()

    for job in jobs:
        units = build_units(job, args.max_sentences_per_job)
        if not units:
            continue
        key = cache_key(
            provider_config["model"],
            provider_config["base_url"],
            units,
            ontology_digest,
        )
        if key in cache:
            result = cache[key]["result"]
            stats["cache_hit"] += 1
        else:
            payload = {
                "job": {
                    "job_id": clean_text(job.get("job_id")),
                    "job_title": clean_text(job.get("job_title")),
                    "source_type": clean_text(job.get("source_type")),
                    "source_name": clean_text(job.get("source_name")) or clean_text(job.get("source")),
                },
                "sentences": units,
            }
            result = call_skill_extraction(
                api_key=api_key,
                model=provider_config["model"],
                base_url=provider_config["base_url"],
                system_prompt=system_prompt,
                user_payload=payload,
                timeout=args.timeout,
                retries=args.retries,
                temperature=args.temperature,
                literal_skills=(item["normalized_skill"] for item in ontology["skills"]),
            )
            append_cache(
                args.cache,
                {
                    "cache_key": key,
                    "provider": provider_config["provider"],
                    "model": provider_config["model"],
                    "base_url": provider_config["base_url"],
                    "result": result,
                },
            )
            stats["api_call"] += 1

        pipeline_stats = result.get("pipeline_stats", {})
        stats["first_pass_mentions"] += int(pipeline_stats.get("first_pass_mentions", 0))
        stats["pipeline_net_new_mentions"] += int(pipeline_stats.get("net_new_mentions", 0))
        unit_by_id = {unit["sentence_id"]: unit for unit in units}
        for mention in result.get("mentions", []):
            row, error = normalize_mention(mention, unit_by_id, job)
            if error:
                rejects.append(
                    {
                        "job_id": clean_text(job.get("job_id")),
                        "job_title": clean_text(job.get("job_title")),
                        "mention": mention,
                        "error": error,
                    }
                )
                stats["rejected"] += 1
                continue
            mentions.append(row)
            stats["accepted"] += 1

    mentions = dedupe_mentions(mentions)
    job_skills = aggregate_job_skills(mentions)
    output_csv = args.output_dir / f"{provider_config['output_prefix']}.csv"
    output_jsonl = args.output_dir / f"{provider_config['output_prefix']}.jsonl"
    job_skills_csv = args.output_dir / f"{provider_config['output_prefix']}_by_job.csv"
    job_skills_jsonl = args.output_dir / f"{provider_config['output_prefix']}_by_job.jsonl"
    report_path = args.output_dir / f"{provider_config['output_prefix']}_report.json"
    write_csv(output_csv, mentions)
    write_jsonl(output_jsonl, mentions)
    write_job_skill_csv(job_skills_csv, flatten_job_skill_rows(job_skills))
    write_jsonl(job_skills_jsonl, job_skills)
    report = {
        "input": "direct_jd_text" if args.jd_text else str(args.input),
        "gold": str(args.gold),
        "provider": provider_config["provider"],
        "model": provider_config["model"],
        "base_url": provider_config["base_url"],
        "prompt_version": PROMPT_VERSION,
        "jobs": len(jobs),
        "mentions": len(mentions),
        "job_skill_pairs": len(job_skills),
        "jobs_with_skills": len({item["job_id"] for item in job_skills}),
        "stats": dict(stats),
        "rejected_samples": rejects[:50],
        "outputs": {
            "csv": str(output_csv),
            "jsonl": str(output_jsonl),
            "job_skills_csv": str(job_skills_csv),
            "job_skills_jsonl": str(job_skills_jsonl),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
