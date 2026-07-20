"""Normalize and filter skill dictionary keywords with project rules.

This script is intentionally rule-first. It does not call an LLM and does not
overwrite the source CSV. One raw keyword can map to multiple normalized skills.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path(
    "C:/Users/LeeJM/Desktop/\u63ed\u699c\u6302\u5e05/"
    "\u5c97\u4f4d\u6570\u636e\u96c6/computer_skill_dictionary_zh_\u5ba1\u6838.csv"
)


@dataclass(frozen=True, slots=True)
class NormalizedItem:
    skill: str
    category: str
    rule_id: str


SHORT_ACRONYM_KEEP = {
    ".net",
    "api",
    "app",
    "sdk",
    "sql",
    "cpu",
    "gpu",
    "npu",
    "tpu",
    "dpu",
    "cuda",
    "ocr",
    "nlp",
    "cv",
    "asr",
    "tts",
    "ue",
    "ar",
    "vr",
    "ide",
    "sre",
    "etl",
    "aes",
    "rsa",
    "ssl",
    "tls",
    "ssh",
    "http",
    "grpc",
    "rest",
    "json",
    "yaml",
    "xml",
    "html",
    "css",
    "js",
    "ts",
    "c",
    "c#",
    "c++",
    "go",
    "php",
    "lua",
    "r",
    "rust",
    "java",
    "bash",
    "awk",
    "git",
    "svn",
    "linux",
    "unix",
    "ios",
    "ue4",
    "ue5",
    "arm",
    "x86",
    "risc",
    "simd",
    "avx",
    "sse",
    "fpga",
    "asic",
    "soc",
    "pcie",
    "nvme",
    "bios",
    "uefi",
    "cmos",
    "can",
    "lin",
    "ble",
    "wifi",
    "5g",
    "4g",
    "3g",
    "3gpp",
    "tcp",
    "udp",
    "ip",
    "dns",
    "cdn",
    "vpn",
    "nat",
    "bgp",
    "ospf",
    "vlan",
    "mqtt",
    "rtsp",
    "rtmp",
    "webrtc",
    "hls",
    "dash",
    "flv",
    "mp4",
    "h264",
    "h265",
    "av1",
    "jpeg",
    "png",
    "yuv",
    "rgb",
    "cnn",
    "rnn",
    "gan",
    "gcn",
    "bert",
    "gpt",
    "llm",
    "vlm",
    "rag",
    "bm25",
    "dpo",
    "sft",
    "ppo",
    "rlhf",
    "grpo",
    "rl",
    "mcp",
    "k8s",
    "kafka",
    "redis",
    "mysql",
    "aigc",
    "anc",
    "ajax",
    "aosp",
    "apm",
    "apu",
    "aws",
    "axi",
    "bf16",
    "blas",
    "bpf",
    "brpc",
    "bsp",
    "cann",
    "cmdb",
    "cni",
    "llvm",
    "mlir",
    "onnx",
    "wasm",
}

ACRONYM_EXACT_DROP = {
    "acqua",
    "ag-ui",
    "aimet",
    "aloha",
    "aquca",
    "asplos",
    "asscc",
    "ast2500",
    "ast2600",
    "audioworx",
    "avrcp",
    "av_sbus",
    "avsbus",
    "bagel",
    "best-rq",
    "bq79xxx",
    "caips",
    "caisp",
    "calvin",
    "cfg++",
    "cipp/e",
    "cisp-pip",
    "coling",
    "coppa",
    "ctcvr",
    "dirac",
    "dnsmos",
    "dover",
    "e-ncap",
    "emnlp",
    "fcbga",
    "fmeda",
    "gaia-1",
    "gb/t32960",
    "gb/t35273",
    "gb/t51314",
    "gb18384",
    "gb50174",
    "grade",
    "gsm8k",
    "h3cie",
    "hipaa",
    "iatf16949",
    "icassp",
    "icdar",
    "ijcai",
    "ijtag",
    "ip69k",
    "ipc-9592",
    "ipdrr",
    "iq-fmea",
    "isolar",
    "isscc",
    "istqb",
    "ivista",
    "jedec",
    "jncie",
    "kwp2000",
    "meosi",
    "misra-c",
    "mosfet",
    "naacl",
    "nisqa",
    "oasys",
    "pci-dss",
    "pdsch",
    "polqa",
    "pucch",
    "pusch",
    "rhsc-et",
    "robocoin",
    "s-iov",
    "sfmea",
    "shram",
    "siggraph",
    "sigir",
    "spec2006",
    "tcl/tk",
    "tia-942",
    "tisax",
    "togaf",
    "tpami",
    "ts16949",
    "tzbsp",
    "v93000",
    "vda-rga",
    "vda6.3",
    "6-sigma",
    "aon-mcu",
    "aspice",
    "behavior-1k",
    "c-ncap",
    "ci/ct",
    "cissp",
    "cnnvd",
    "cobit",
    "dfmea",
    "driver/tia",
    "g.722",
    "h.323",
    "iso/iec",
    "it/cad",
    "itu-t",
    "micro",
    "timer",
    "uitars",
}

ACRONYM_DROP_PREFIXES = (
    "gb/t",
    "gb",
    "iec",
    "ieee",
    "iso",
    "iso/iec",
)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ")
    return " ".join(text.split()).strip()


def norm_text(value: str) -> str:
    return clean_text(value).casefold()


def has(pattern: str, text: str, flags: int = re.IGNORECASE) -> bool:
    return bool(re.search(pattern, text, flags))


def exact(text: str, *values: str) -> bool:
    lowered = norm_text(text)
    return lowered in {value.casefold() for value in values}


def high_priority_normalization(raw: str) -> list[NormalizedItem]:
    items: list[NormalizedItem] = []

    def add(skill: str, category: str, rule_id: str) -> None:
        if skill and skill not in [item.skill for item in items]:
            items.append(NormalizedItem(skill=skill, category=category, rule_id=rule_id))

    if has(r"^C\+\+\d{2}$", raw):
        add("C++", "编程语言", "cpp_version")
        return items

    if has(r"^ARM(?:32|64|v\d+)?$", raw):
        add("ARM", "硬件架构", "arm_family")
        return items

    if has(r"^RISC[-\s]?V$", raw):
        add("RISC-V", "硬件架构", "riscv")
        return items

    if has(r"^(?:HTTP|HTTPS)(?:[-/]?FLV|/?[23])?$", raw):
        add("HTTP", "网络协议", "http_family")
        return items

    if has(r"^(?:H\.?26[456]|AV1|SVT-AV1)$", raw):
        add("视频编码", "音视频技术", "video_codec")
        return items

    if has(r"^(?:JPEG(?:-AI|-XL)?|PNG|YUV|RGB)$", raw):
        add("图像编码", "音视频技术", "image_codec")
        return items

    if has(r"^(?:RS[-\s]?(?:232|485)|RS232|RS485|USART)$", raw):
        add("串口通信", "通信技术", "serial_communication")
        return items

    if has(r"^USB(?:3\.0|4\.0)?$", raw):
        add("USB", "通信接口", "usb")
        return items

    if has(r"^(?:LPDDR(?:5X?|6)?|RDIMM|MRDIMM)$", raw):
        add("内存技术", "硬件", "memory_technology")
        return items

    if has(r"^GPT(?:[-\s]?\d[V]?)?$|^ChatGPT$", raw):
        add("LLM", "大模型", "gpt_family")
        return items

    if has(r"^RAGAS$", raw):
        add("RAG", "检索增强生成", "rag_family")
        return items

    if has(r"^(?:AR|VR|AR/VR)$", raw):
        add("AR/VR技术", "XR技术", "ar_vr_family")
        return items

    if has(r"^(?:CAN(?:-FD|FD)?|CANopen)$", raw):
        add("CAN总线", "通信技术", "can_bus")
        return items

    if has(r"^(?:CI/CD)$", raw):
        add("CI/CD", "运维", "cicd_explicit")
        return items

    if has(r"^(?:DROID-SLAM|ORB-SLAM3?|LIO-SAM|VSLAM)$", raw):
        add("SLAM", "机器人与定位", "slam_family")
        return items

    if has(r"^(?:PL/SQL|MSSQL|TDSQL|NL2SQL|DSL2SQL)$", raw):
        add("SQL", "数据库", "sql_family")
        return items

    if has(r"^(?:RTMP|RTSP|HLS|DASH|MPEG-DASH|HTTP-FLV|FLV|MP4)$", raw):
        add("音视频流媒体", "音视频技术", "streaming_media")
        return items

    if has(r"^(?:TCP/IP|TCP|UDP|QUIC|MP-TCP|MPTCP|MPQUIC|IP|DNS|BGP|OSPF|NAT|VXLAN|VLAN|NETCONF|SD-WAN|SR-TE|L3VPN|P2P-CDN)$", raw):
        add("网络协议", "网络技术", "network_protocol")
        return items

    if has(r"^(?:SSLVPN|VPN)$", raw):
        add("VPN", "网络安全", "vpn_family")
        return items

    if has(r"^(?:DMA-BUF|DMABUF|DMA2D)$", raw):
        add("DMA", "底层系统", "dma_family")
        return items

    if has(r"^(?:RNN-T)$", raw):
        add("RNN", "AI算法", "rnn_family")
        return items

    if has(r"^(?:RLAIF|REINFORCE)$", raw):
        add("RL", "强化学习", "rl_family")
        return items

    if has(r"^(?:VQ-GAN|VQGAN|RQ-VAE|RQVAE)$", raw):
        add("生成模型", "AI算法", "generative_model_family")
        return items

    if has(r"AIGC", raw):
        add("AIGC", "AIGC", "aigc")
        return items

    if has(r"(?:2G|3G|4G)\s*射频(?:技术|协议)?|射频技术|射频协议", raw):
        add("射频技术", "通信技术", "radio_frequency")
        return items

    if re.match(r"^3D", raw, flags=re.IGNORECASE):
        add("3D相关技术", "数字前缀技术", "3d_prefix")
        return items

    if re.match(r"^2D", raw, flags=re.IGNORECASE):
        add("2D相关技术", "数字前缀技术", "2d_prefix")
        return items

    tech_prefix = re.match(r"^([3-9][A-Z])(?:$|[^A-Za-z0-9])", raw, flags=re.IGNORECASE)
    if tech_prefix:
        prefix = tech_prefix.group(1).upper()
        add(f"{prefix}相关技术", "数字前缀技术", "independent_numeric_alpha_prefix")
        return items

    return items


def drop_acronym_noise(raw: str, low: str) -> str | None:
    compact = raw.strip()
    compact_low = compact.casefold()

    if compact_low in ACRONYM_EXACT_DROP:
        return "drop_noisy_acronym_exact"

    if any(compact_low.startswith(prefix) for prefix in ACRONYM_DROP_PREFIXES) and has(r"\d", compact):
        return "drop_standard_code"

    if has(r"^(?:ISO|ISO/IEC|IEC|IEEE|GB/T|GB|IATF|TS|VDA|IPC|TIA|ECMA|ITU)[-/]?\d", compact):
        return "drop_standard_code"

    if has(r"^(?:AST|BQ|CMW|ESP|STM|V)\d{2,}", compact):
        return "drop_part_or_instrument_model"

    if has(r"^[A-Z]{2,5}[-_/]?(?:FMEA|NCAP|RGA)$", compact):
        return "drop_quality_or_compliance_acronym"

    if has(r"^[A-Z]{2,4}\d{2,}$", compact) and compact_low not in SHORT_ACRONYM_KEEP:
        return "drop_model_like_acronym"

    return None


def normalize_keyword(keyword: str) -> tuple[list[NormalizedItem], str]:
    raw = clean_text(keyword)
    low = norm_text(raw)
    items: list[NormalizedItem] = []

    def add(skill: str, category: str, rule_id: str) -> None:
        if skill and skill not in [item.skill for item in items]:
            items.append(NormalizedItem(skill=skill, category=category, rule_id=rule_id))

    if not raw:
        return [], "drop_empty"

    priority_items = high_priority_normalization(raw)
    if priority_items:
        return priority_items, "keep"

    drop_reason = drop_keyword(raw, low)
    if drop_reason:
        return [], drop_reason

    # Keep exact concrete programming languages and explicit project skills.
    explicit_exact = {
        "python": ("Python", "编程语言"),
        "c++": ("C++", "编程语言"),
        "java": ("Java", "编程语言"),
        "rust": ("Rust", "编程语言"),
        "lua": ("Lua", "编程语言"),
        "vlm": ("VLM", "AI模型"),
        "sdk": ("SDK", "工程开发"),
        "tts": ("TTS", "语音音频"),
        "aiops": ("AIops", "运维"),
        "llmops": ("LLMOps/MLOps", "AI工程"),
        "mlops": ("LLMOps/MLOps", "AI工程"),
        "知识图谱": ("知识图谱", "知识工程"),
        "harness工程": ("harness工程", "工程能力"),
        "llm-based ranking": ("LLM-based Ranking", "检索推荐"),
        "具身智能": ("具身智能", "AI方向"),
        "deep learning": ("Deep Learning", "AI算法"),
        "machine learning": ("Machine Learning", "AI算法"),
        "rl": ("RL", "强化学习"),
        "sft": ("SFT", "大模型训练"),
        "dpo": ("DPO", "大模型训练"),
    }
    if low in explicit_exact:
        skill, category = explicit_exact[low]
        add(skill, category, "explicit_exact")
        return items, "keep"

    if exact(raw, "c/c++"):
        add("C++", "编程语言", "cpp_from_c_cpp")
        return items, "keep"

    if has(r"^C\+\+\d{2}$", raw):
        add("C++", "编程语言", "cpp_version")
        return items, "keep"

    if has(r"^ARM(?:32|64|v\d+)?$", raw):
        add("ARM", "硬件架构", "arm_family")
        return items, "keep"

    if has(r"^RISC[-\s]?V$", raw):
        add("RISC-V", "硬件架构", "riscv")
        return items, "keep"

    if has(r"^(?:HTTP|HTTPS)(?:[-/]?FLV|/?[23])?$", raw):
        add("HTTP", "网络协议", "http_family")
        return items, "keep"

    if has(r"^(?:H\.?26[456]|AV1|SVT-AV1)$", raw):
        add("视频编码", "音视频技术", "video_codec")
        return items, "keep"

    if has(r"^(?:JPEG(?:-AI|-XL)?|PNG|YUV|RGB)$", raw):
        add("图像编码", "音视频技术", "image_codec")
        return items, "keep"

    if has(r"^(?:RS[-\s]?(?:232|485)|RS232|RS485|USART)$", raw):
        add("串口通信", "通信技术", "serial_communication")
        return items, "keep"

    if has(r"^USB(?:3\.0|4\.0)?$", raw):
        add("USB", "通信接口", "usb")
        return items, "keep"

    if has(r"^(?:LPDDR(?:5X?|6)?|RDIMM|MRDIMM)$", raw):
        add("内存技术", "硬件", "memory_technology")
        return items, "keep"

    if has(r"^GPT(?:[-\s]?\d[V]?)?$|^ChatGPT$", raw):
        add("LLM", "大模型", "gpt_family")
        return items, "keep"

    if has(r"^RAGAS$", raw):
        add("RAG", "检索增强生成", "rag_family")
        return items, "keep"

    app_skill = has(
        r"^APP(?:$|[\u4e00-\u9fff])|^App(?:$|[\u4e00-\u9fff\s])|Android\s+App|iOS\s+App|iPhone\s+App|"
        r"HarmonyOS\s+App|鸿蒙App|WebApp|uni-?App|UniApp|Hybrid\s+App|客户端App|移动App|大型App|影像App|VR\s+App",
        raw,
    )
    if app_skill and not has(r"Appium|AppArmor|AppKit|AppBuilder|AppContainer|Append|Application|Applied|Approximate|Kappa|Mapping|MAPPO|overlapping|WhatsApp", raw):
        if has(r"安全|漏洞|逆向|反编译|混淆|隐私|风控|加固|个人信息保护", raw):
            add("移动应用安全", "移动开发", "app_security")
        elif has(r"测试|自动化测试|质量", raw):
            add("APP测试", "移动开发", "app_testing")
        else:
            add("APP开发", "移动开发", "app_development")
        return items, "keep"

    api_skill = has(r"(?<![A-Za-z])API(?![A-Za-z])|OpenAPI|FastAPI|RESTful\s+API|REST\s+API|HTTP\s+API|RPC\s+API|Web\s+API|云API|开放API|推理API|大模型API", raw)
    if api_skill and not has(r"Mapillary|Xapian|SAPIEN|WAAPI|WASAPI", raw):
        if has(r"Gateway|网关|APISIX", raw):
            add("API网关", "API", "api_gateway")
        elif has(r"安全|Key|鉴权|权限|漏洞|攻击|防护", raw):
            add("API安全", "API", "api_security")
        elif has(r"测试|自动化测试|稳定性|成功率", raw):
            add("API测试", "API", "api_testing")
        else:
            add("API开发", "API", "api_development")
        return items, "keep"

    # Multi-concept terms.
    if has(r"多模态.*大模型|multimodal.*(llm|large language model)", raw):
        add("Multimodal AI", "多模态", "multimodal_llm_split")
        add("LLM", "大模型", "multimodal_llm_split")
        return items, "keep"

    # Core LLM and agent rules.
    multi_agent_hit = has(r"多智能体|multi[-\s]?agent|多\s*agent|agent\s*group", raw)
    if multi_agent_hit:
        add("multi-agent", "智能体", "multi_agent")
    elif has(r"(?<!multi[-\s])agent|智能体", raw):
        add("agent", "智能体", "agent")

    if has(r"few[-\s]?shot\s*prompt|system\s*prompt|prompt|提示词", raw):
        add("prompt工程", "大模型应用", "prompt_engineering")

    if has(r"kv\s*cache|长上下文|上下文|context|memory", raw):
        add("上下文工程", "大模型应用", "context_engineering")

    if has(r"大语言模型|large language model|\bllm\b|大模型", raw):
        add("LLM", "大模型", "llm")

    if has(r"分布式训练|分布式推理|分布式计算|分布式存储|^分布式$", raw):
        add("分布式系统", "系统架构", "distributed_system")

    if has(r"算子|(?<!code\s)kernel|operator", raw):
        add("算子开发", "AI基础设施", "operator_development")

    # Large-model training and inference.
    if has(r"后训练|post[-\s]?training", raw):
        add("大模型后训练", "大模型训练", "llm_post_training")

    if has(r"微调|指令微调|精调|蒸馏|fine[-\s]?tuning|finetun|sft", raw):
        add("大模型微调", "大模型训练", "llm_finetuning")

    rl_algorithm = r"(?<![a-z0-9])(?:rlhf|ppo|dpo|grpo)(?![a-z0-9])|强化学习"
    rl_context = r"大模型|llm|后训练|post|对齐|alignment|(?<![a-z0-9])(?:rlhf|ppo|dpo|grpo)(?![a-z0-9])"
    if has(rl_algorithm, raw) and has(rl_context, raw):
        add("大模型强化", "大模型训练", "llm_rl")

    if has(r"预训练|基模训练|pre[-\s]?train", raw):
        add("大模型预训练", "大模型训练", "llm_pretraining")

    if has(r"模型训练|训练框架|训练链路|训练优化|训练集群", raw) and not has(r"培训|训练营", raw):
        add("模型训练", "模型工程", "model_training")

    if has(r"模型推理|推理服务|推理引擎|推理框架|推理优化|推理加速|高性能推理系统", raw) and not has(
        r"逻辑推理|推理能力", raw
    ):
        add("模型推理", "模型工程", "model_inference")

    if has(r"大模型.*(评测|效果评估|benchmark|human eval)|llm.*(benchmark|eval)", raw):
        add("大模型评测", "大模型评测", "llm_evaluation")

    for skill, pattern in [
        ("模型对齐", r"模型对齐|alignment"),
        ("模型量化", r"模型量化|量化"),
        ("模型压缩", r"模型压缩|压缩"),
    ]:
        if has(pattern, raw):
            add(skill, "模型工程", skill)

    # Model serving and AI infrastructure.
    model_serving_context = has(r"模型|大模型|llm|推理|模型能力|maas", raw)
    if model_serving_context and has(
        r"api\s*网关|模型部署|推理服务|推理框架|服务化引擎|在线服务|能力封装|工具组件|能力中台|maas|产品链路",
        raw,
    ):
        add("模型服务化", "AI工程", "model_serving")

    if has(
        r"分布式训练.*集群|分布式推理.*集群|训练/推理集群|训练集群|推理集群|分布式训练框架|模型训练框架|"
        r"ai\s*工程平台|maas\s*链路|软硬协同|软硬件协同|模型编译|运行时优化|编译优化|ir\s*改写|"
        r"后端\s*codegen|codegen|模型工具链|算力基础设施|完整训练链路",
        raw,
    ):
        add("AI基础设施", "AI基础设施", "ai_infra")

    # High-performance computing and hardware.
    hardware_exact = {
        "gpu": "GPU",
        "cuda": "CUDA",
        "npu": "NPU",
        "ascend": "Ascend",
        "nvlink": "NVLink",
        "nvswitch": "NVSwitch",
        "infiniband": "InfiniBand",
        "docker": "Docker",
        "sdk": "SDK",
    }
    if low in hardware_exact:
        add(hardware_exact[low], "硬件与工程工具", "hardware_exact")
        return items, "keep"

    if exact(raw, "芯片") or has(r"芯片(设计|开发|验证|架构)?", raw):
        add("芯片", "硬件", "chip")

    if has(
        r"gpu|cuda|triton|算力|吞吐|延迟|通信瓶颈|kernel perf|operator perf|mfu|性能分析|性能调优|"
        r"推理加速|算力利用率|模型吞吐|高性能推理系统",
        raw,
    ):
        add("高性能计算", "高性能计算", "hpc")

    # Data engineering.
    if has(
        r"数据处理|数据分析|数据平台|数据集|数据治理|数据加工|数据清洗|特征提取|数据流水线|数据仓库|"
        r"数据科学|数据库设计|数据库优化|\betl\b|数据etl|spark|flink|hadoop|大数据|数仓|数据库|"
        r"数据生产|数据质检|数据修复|元数据管理|样本构建|训练样本|样本生产|数据存储",
        raw,
    ):
        add("数据工程", "数据工程", "data_engineering")

    # Frontend, backend, engineering development.
    if has(r"前端|大前端|frontend|front-end", raw):
        add("前端架构设计", "工程开发", "frontend_architecture")

    if has(r"微服务", raw):
        if has(r"微服务(架构|治理|拆分)|microservices?", raw):
            add("Microservices", "系统架构", "microservices")
        if has(r"微服务(设计|开发)|服务端开发|后端|后台", raw):
            add("后端开发", "工程开发", "backend_development")

    if has(r"后端|后台|服务端|server[-\s]?side", raw) and not has(r"codegen|编译器后端", raw):
        add("后端开发", "工程开发", "backend_development")

    if has(r"\bios\b|ios开发", raw):
        add("ios开发", "移动开发", "ios_development")

    if has(r"android|安卓", raw):
        add("android开发", "移动开发", "android_development")

    if has(r"跨平台|跨架构", raw):
        add("跨平台开发", "工程开发", "cross_platform")

    # Search, recommendation, workflow.
    if has(
        r"\brag\b|\bsearch\b|\brecall\b|\brerank\b|vector retrieval|搜推|搜广推|search agent|"
        r"向量检索|全文检索|索引|精排|检索|排序算法",
        raw,
    ):
        add("检索排序算法", "检索推荐", "retrieval_ranking")

    if has(r"推荐模型|推荐系统|生成式推荐|llm4rec|\bctr\b|\bcvr\b|推荐算法", raw):
        add("推荐系统算法", "检索推荐", "recommendation_algorithm")

    if has(r"workflow|工作流|任务拆解|planning|reflection|工具调用|多轮决策|编排", raw):
        add("AI工作流设计", "AI应用", "ai_workflow")

    # Game, graphics, multimodal.
    if has(r"\bue5?\b|unreal engine", raw):
        add("UE", "游戏图形", "ue")

    if has(r"\bunity\b", raw):
        add("Unity", "游戏图形", "unity")

    if has(r"ue5引擎|游戏引擎|引擎开发|引擎管线|游戏管线", raw):
        add("游戏引擎开发", "游戏图形", "game_engine")

    if has(r"渲染|shader|渲染管线", raw):
        add("渲染技术", "游戏图形", "rendering")

    if has(r"blender", raw):
        add("Blender", "游戏图形", "blender")

    if has(r"计算机图形学", raw):
        add("计算机图形学", "游戏图形", "computer_graphics")

    if has(r"多模态|multimodal", raw):
        add("Multimodal AI", "多模态", "multimodal")

    if has(r"\bvlm\b", raw):
        add("VLM", "多模态", "vlm")

    # Speech and audio.
    if has(r"\basr\b|语音识别|语音大模型", raw):
        add("大模型ASR", "语音音频", "asr")

    if has(r"\btts\b|语音合成", raw):
        add("TTS", "语音音频", "tts")

    if has(r"语音算法|声学算法|音频算法|语音识别算法", raw):
        add("语音算法", "语音音频", "speech_algorithm")

    if has(r"\banc\b|自适应滤波|声场控制", raw):
        add("音频信号处理", "语音音频", "audio_signal_processing")

    # Safety.
    if has(r"大模型内容安全|幻觉治理|红队|rag\s*安全|安全验证|安全审计|智能化安全审计|风险识别", raw):
        add("大模型安全", "AI安全", "llm_safety")

    if has(r"agent.*沙箱|智能体.*沙箱|安全执行环境|凭据泄露|本地执行|智能体生命周期安全|插件|skill\s*调用", raw):
        add("智能体安全", "AI安全", "agent_safety")

    # Operations and problem analysis.
    if has(r"devops|ci/cd|持续集成|持续部署|自动化运维平台|故障容错|稳定交付|可靠性|可观测性|应急响应", raw):
        add("SRE", "运维", "sre")
        if has(r"ci/cd", raw):
            add("CI/CD", "运维", "cicd_explicit")

    if has(r"疑难问题攻坚|问题定位|故障分析|缺陷分析|badcase|根因定位|模型弱项|缺陷归因|适配问题修复", raw):
        add("bug分析", "工程能力", "bug_analysis")

    # AI coding.
    if has(
        r"vibe coding|ai coding|code agent|code generation|代码生成工具|ide\s*智能助手|"
        r"ai\s*辅助生成代码|生成代码|智能化生成代码",
        raw,
    ):
        add("ai coding", "AI编程", "ai_coding")

    if items:
        return items, "keep"

    return [NormalizedItem(skill=raw, category="未归一", rule_id="unchanged")], "keep_unchanged"


def drop_keyword(raw: str, low: str) -> str | None:
    if raw in {"#NAME?", "#VALUE!", "#REF!", "#DIV/0!"}:
        return "drop_excel_error"

    compact = raw.strip()
    if re.fullmatch(r"[A-Za-z0-9+#./-]{1,4}", compact):
        if compact.casefold() not in SHORT_ACRONYM_KEEP:
            return "drop_ambiguous_short_acronym"

    acronym_noise_reason = drop_acronym_noise(raw, low)
    if acronym_noise_reason:
        return acronym_noise_reason

    if has(r"用户数据|业务数据|业务对象|岗位愿景|行业方向|产品场景枚举|产品场景|业务场景|场景举例", raw):
        return "drop_business_or_scene"

    if exact(raw, "图像", "文本", "视频", "语音", "搜索", "推荐", "存储"):
        return "drop_modality_or_scene_word"

    if has(r"常识|学习能力|沟通能力|责任心|团队合作|抗压|执行力|owner意识|自驱", raw):
        return "drop_soft_skill"

    if has(r"了解业务|熟悉业务|业务理解|行业理解", raw):
        return "drop_generic_business"

    if len(low) == 1 and not has(r"[a-z0-9+#]", low):
        return "drop_too_short"

    return None


def build_outputs(df: pd.DataFrame, skill_column: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    audit_rows: list[dict[str, object]] = []
    grouped: dict[str, dict[str, object]] = {}
    source_keywords: dict[str, set[str]] = defaultdict(set)
    rule_ids: dict[str, set[str]] = defaultdict(set)

    for index, row in df.iterrows():
        raw = clean_text(row.get(skill_column, ""))
        items, action = normalize_keyword(raw)
        normalized_skills = "; ".join(item.skill for item in items)
        categories = "; ".join(dict.fromkeys(item.category for item in items))
        matched_rules = "; ".join(dict.fromkeys(item.rule_id for item in items))
        audit_rows.append(
            {
                "source_row": index + 2,
                "skill_keyword": raw,
                "normalization_action": action,
                "normalized_skills": normalized_skills,
                "categories": categories,
                "matched_rules": matched_rules,
            }
        )

        for item in items:
            key = item.skill.casefold()
            if key not in grouped:
                grouped[key] = {
                    "normalized_skill": item.skill,
                    "category": item.category,
                    "source_count": 0,
                }
            grouped[key]["source_count"] = int(grouped[key]["source_count"]) + 1
            source_keywords[key].add(raw)
            rule_ids[key].add(item.rule_id)

    normalized_rows = []
    for key, data in grouped.items():
        normalized_rows.append(
            {
                **data,
                "source_keywords": "; ".join(sorted(source_keywords[key])),
                "matched_rules": "; ".join(sorted(rule_ids[key])),
            }
        )

    normalized_df = pd.DataFrame(normalized_rows).sort_values(
        ["category", "normalized_skill"], kind="stable"
    )
    audit_df = pd.DataFrame(audit_rows)
    return normalized_df, audit_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize computer skill dictionary with project rules.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--skill-column", default="skill_keyword")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--final-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(args.input)

    output = args.output or args.input.with_name(args.input.stem + "_rules_normalized.csv")
    audit_output = args.audit_output or args.input.with_name(args.input.stem + "_rules_normalized_audit.csv")
    final_output = args.final_output or args.input.with_name(args.input.stem + "_final_skills.csv")

    df = pd.read_csv(args.input, dtype=str).fillna("")
    if args.skill_column not in df.columns:
        raise ValueError(f"Missing skill column: {args.skill_column}. Available columns: {list(df.columns)}")

    normalized_df, audit_df = build_outputs(df, args.skill_column)
    final_df = (
        normalized_df[["normalized_skill"]]
        .rename(columns={"normalized_skill": "skill"})
        .sort_values("skill", key=lambda series: series.str.casefold(), kind="stable")
        .reset_index(drop=True)
    )
    normalized_df.to_csv(output, index=False, encoding="utf-8-sig")
    audit_df.to_csv(audit_output, index=False, encoding="utf-8-sig")
    final_df.to_csv(final_output, index=False, encoding="utf-8-sig")

    kept = audit_df[audit_df["normalization_action"].str.startswith("keep")]
    dropped = audit_df[audit_df["normalization_action"].str.startswith("drop")]
    changed = kept[kept["matched_rules"] != "unchanged"]
    print(f"input_rows={len(df)}")
    print(f"normalized_unique_rows={len(normalized_df)}")
    print(f"changed_source_rows={len(changed)}")
    print(f"dropped_source_rows={len(dropped)}")
    print(f"final_unique_skills={len(final_df)}")
    print(f"output={output}")
    print(f"audit_output={audit_output}")
    print(f"final_output={final_output}")


if __name__ == "__main__":
    main()
