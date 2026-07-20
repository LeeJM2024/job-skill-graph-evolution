"""Aggressively clean the normalized final skill list.

Input is the already normalized single-column final skill CSV. The script writes:
- an audit file with delete / normalize / keep decisions for every source skill
- a new single-column cleaned final skill CSV

The goal here is dictionary compression: noisy English/digit fragments are either
deleted or folded into broader resume/JD skill names.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INPUT = Path(
    "C:/Users/LeeJM/Desktop/\u63ed\u699c\u6302\u5e05/"
    "\u5c97\u4f4d\u6570\u636e\u96c6/computer_skill_dictionary_zh_\u5ba1\u6838_final_skills_ai_prefix_normalized.csv"
)


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    output_skill: str
    reason: str


def clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split()).strip()


def has(pattern: str, text: str, flags: int = re.IGNORECASE) -> bool:
    return bool(re.search(pattern, text, flags))


def exact(text: str, *values: str) -> bool:
    low = clean_text(text).casefold()
    return low in {value.casefold() for value in values}


DELETE_EXACT = {
    "acp模式",
    "access control",
    "access token安全",
    "act战斗系统",
    "aging",
    "air log",
    "airdrop",
    "airtable",
    "allan方差",
    "allocations",
    "alpha channel",
    "alphaevolve",
    "amazon tam",
    "ampere altra",
    "amplifier",
    "amundsen",
    "anti-lca",
    "aon系统",
    "application notes",
    "applied scientist",
    "append表",
    "approximate模型",
    "areal",
    "arena对战评测",
    "arista",
    "arxiv论文复现",
    "asset manager",
    "astra-sim",
    "attester",
    "ati vision",
    "auction",
    "audit",
    "aurora",
    "auto-analysis",
    "automation equipment",
    "automation production line",
    "avatar换装",
    "backward",
    "balloon",
    "barefoot",
    "base64",
    "basetech",
    "battery",
    "bidding",
    "billing",
    "binder",
    "blade",
    "block",
    "bolt.new",
    "bridge",
    "bring-up",
    "budget",
    "buffer",
    "burn-in",
    "busway",
    "cache",
    "callbacks",
    "camera",
    "camera1",
    "camera2",
    "category",
    "celsius",
    "chain",
    "chains",
    "channel",
    "charger",
    "chart",
    "checkpoint",
    "chunking",
    "claude.md",
    "component",
    "context",
    "dashboard",
    "document",
    "driver/tia",
    "eagle",
    "foreground",
    "foundation",
    "framework",
    "generic",
    "launcher",
    "logic",
    "mapping",
    "memory",
    "pipeline",
    "platform",
    "profile",
    "runtime",
    "scene",
    "service",
    "solution",
    "system",
    "timer",
    "tool",
    "workflow",
}


DELETE_PATTERNS = [
    (r"^(?:Amazon|Google|Meta|Apple|Microsoft|Alibaba|Huawei|Tencent|ByteDance|AMD|Intel|NVIDIA|Qualcomm)\s+TAM$", "brand_job_or_business_term"),
    (r"^(?:ANSI|ASIL|CMMI|CMM|DOORS|ECU-TEST|FIDO2|HIPAA|IATF|IEC|IEEE|ISO|ISO/IEC|ISTQB|MISRA|PCI-DSS|SOTIF|TISAX|TOGAF|VDA)(?:$|[-/\s][A-Z0-9.]+$)", "standard_or_certification"),
    (r"^(?:ACM|ACL|COLING|EMNLP|ICASSP|ICDAR|IJCAI|ISSCC|NAACL|SIGGRAPH|SIGIR|TPAMI)(?:算法|论文|会议)?$", "conference_or_paper_label"),
    (r"^(?:BigBench|GSM8K|HumanEval|KITTI|BEHAVIOR-1K|C-Eval|C-NCAP|E-NCAP|IVISTA)$", "benchmark_dataset_not_skill"),
    (r"^(?:AST|BQ|CMW|ESP|STM|V)\d{2,}", "part_or_instrument_model"),
    (r"^[A-Z]{1,5}\d{2,}[A-Z0-9-]*$", "model_code_fragment"),
    (r"^[A-Z]{2,6}[-_/]?(?:FMEA|NCAP|RGA)$", "quality_compliance_fragment"),
    (r"^(?:Air|Audio|Auto|Cloud|Data|Edge|Foundation|Generation|Image|Model|Open|Smart|Video)\s*$", "generic_english_modality"),
    (r".*(?:岗位|愿景|场景|业务对象|业务数据|用户数据|产品场景).*", "business_or_scene_not_skill"),
]


NORMALIZE_EXACT = {
    ".net": ".NET",
    "access token": "API安全",
    "acid事务": "数据库",
    "a-star": "路径规划算法",
    "acm算法": "算法能力",
    "adrc控制": "控制算法",
    "ad域控": "Windows域控",
    "aes": "加密算法",
    "afnetworking": "ios开发",
    "after effects": "多媒体工具",
    "aider": "ai coding",
    "agibot": "具身智能",
    "agibot go1": "具身智能",
    "agibot world": "具身智能",
    "agilent电源": "硬件测试",
    "agi评测": "大模型评测",
    "ai工程化": "AI工程",
    "ai应用开发": "AI应用开发",
    "ai质量工程": "AI质量工程",
    "ajax": "前端开发",
    "alamofire": "ios开发",
    "alarmmanager": "android开发",
    "aliyun": "云计算",
    "all-to-all": "分布式通信",
    "all2all": "分布式通信",
    "allgather": "分布式通信",
    "allreduce": "分布式通信",
    "alltoall": "分布式通信",
    "alluxio": "大数据平台",
    "allegro": "EDA工具",
    "altera haps": "FPGA原型验证",
    "altium designer": "EDA工具",
    "amba3": "AMBA总线",
    "amba4": "AMBA总线",
    "amba5": "AMBA总线",
    "ambari": "大数据平台",
    "ambisonics": "音频信号处理",
    "amesim": "CAE仿真",
    "analog测试": "模拟电路测试",
    "analyticdb": "数据库",
    "angular": "前端开发",
    "angular.js": "前端开发",
    "angular2": "前端开发",
    "angularjs": "前端开发",
    "ant design": "前端开发",
    "antdesign": "前端开发",
    "anthropic": "LLM",
    "antigravity": "ai coding",
    "antlr": "编译原理",
    "anysplat": "3D相关技术",
    "aone copilot": "ai coding",
    "apache": "后端开发",
    "apisix": "API网关",
    "apk构建": "android开发",
    "apm": "APM监控",
    "apollo": "自动驾驶",
    "aosp": "android开发",
    "aosp源码": "android开发",
    "appium": "APP测试",
    "appkit": "ios开发",
    "ap电声测试软件": "音频测试",
    "ap音频仪": "音频测试",
    "apu": "AI芯片",
    "arch linux": "Linux",
    "archlinux": "Linux",
    "arcore": "AR/VR技术",
    "argocd": "DevOps",
    "argo cd": "DevOps",
    "arima": "时间序列算法",
    "arize": "LLMOps/MLOps",
    "arkit": "AR/VR技术",
    "arkit hand tracking": "AR/VR技术",
    "arkui": "鸿蒙开发",
    "arkui-x": "鸿蒙开发",
    "arkts": "鸿蒙开发",
    "arkts性能优化": "鸿蒙开发",
    "arduino": "嵌入式开发",
    "arrow": "数据工程",
    "arthas": "Java诊断",
    "aruco": "计算机视觉",
    "ascend c": "Ascend",
    "ascendc": "Ascend",
    "assertion": "芯片验证",
    "assetbundle": "Unity",
    "ast分析": "编译原理",
    "ast解析": "编译原理",
    "asyncio": "Python",
    "at command": "通信协议",
    "atlas": "GPU",
    "atrace": "性能分析",
    "att&ck": "网络安全",
    "attention": "LLM",
    "attention-ffn分离": "LLM",
    "attention优化": "LLM",
    "attention分析": "LLM",
    "attention加速": "LLM",
    "audacity": "音频工具",
    "audition": "音频工具",
    "auto layout": "ios开发",
    "auto-tuning": "自动调优",
    "autocad": "CAD",
    "autocad electrical": "CAD",
    "autoencoder": "Deep Learning",
    "autogen": "agent",
    "autogpt": "agent",
    "autograd": "Deep Learning",
    "automl": "AutoML",
    "autope": "自动化运维",
    "autopilot": "自动驾驶",
    "autoregressive generation": "自回归模型",
    "autoregressive model": "自回归模型",
    "autoregressive models": "自回归模型",
    "autoregressive video": "自回归模型",
    "autoregressive模型": "自回归模型",
    "autoresearch": "AI工作流设计",
    "autoware": "自动驾驶",
    "avfoundation": "ios开发",
    "avocado测试框架": "自动化测试",
    "aws": "云计算",
    "axios": "前端开发",
    "axure": "产品原型工具",
    "azkaban": "工作流调度",
    "azure": "云计算",
    "agent": "agent",
    "ai coding": "ai coding",
    "aigc": "AIGC",
    "aiops": "AIops",
    "ascend": "Ascend",
    "awk": "awk",
    "b+tree": "数据库",
    "bash": "Bash",
    "bayesian networks": "Machine Learning",
    "bayesian optimization": "Machine Learning",
    "beautifulsoup": "Python爬虫",
    "benchmark": "性能评测",
    "benchmarking": "性能评测",
    "bert": "LLM",
    "bfloat16": "低精度计算",
    "bigquery": "数据库",
    "bigtable": "数据库",
    "binary exploitation": "网络安全",
    "binlog": "数据库",
    "bios": "BIOS",
    "blas": "高性能计算",
    "ble": "蓝牙开发",
    "bloom": "LLM",
    "bluetooth": "蓝牙开发",
    "bokeh": "数据可视化",
    "boost": "C++",
    "bootloader": "嵌入式开发",
    "bpf": "Linux内核",
    "bpftrace": "Linux性能分析",
    "brpc": "RPC框架",
    "bsp": "BSP开发",
    "bugbounty": "网络安全",
    "bugcrowd": "网络安全",
    "bugreport": "bug分析",
    "burp suite": "网络安全",
    "c": "C",
    "c#": "C#",
    "c++": "C++",
    "cpu": "CPU",
    "gpu": "GPU",
    "go": "Go",
    "java": "Java",
    "python": "Python",
    "rust": "Rust",
    "lua": "Lua",
    "php": "PHP",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "linux": "Linux",
    "sdk": "SDK",
    "sql": "SQL",
    "mysql": "数据库",
    "redis": "数据库",
    "html": "前端开发",
    "css": "前端开发",
    "javascript": "前端开发",
    "typescript": "前端开发",
    "cadence": "EDA工具",
    "caffe": "AI框架",
    "caffe2": "AI框架",
    "calico": "云原生网络",
    "canal": "数据工程",
    "cann": "Ascend",
    "cargo": "Rust",
    "carla": "自动驾驶仿真",
    "carmaker": "自动驾驶仿真",
    "carsim": "自动驾驶仿真",
    "cassandra": "数据库",
    "catia": "CAD",
    "ccache": "构建工具",
    "cdn": "CDN",
    "celery": "后端开发",
    "centos": "Linux",
    "cephfs": "分布式存储",
    "ceres": "优化算法",
    "cgroup": "Linux容器",
    "cgroup v2": "Linux容器",
    "cgroups": "Linux容器",
    "chain of thought": "prompt工程",
    "chain-of-thought": "prompt工程",
    "chaos engineering": "SRE",
    "chaos monkey": "SRE",
    "charles": "网络抓包",
    "chatbot": "agent",
    "chatglm": "LLM",
    "chatlearn": "大模型训练",
    "chatops": "SRE",
    "cheerio": "Web爬虫",
    "chiplet": "芯片",
    "chisel": "芯片设计",
    "chroma": "向量数据库",
    "chromium": "浏览器内核",
    "ci/cd": "CI/CD",
    "cilium": "云原生网络",
    "circleci": "CI/CD",
    "ckafka": "消息队列",
    "clang": "编译原理",
    "classloader": "Java",
    "claude": "LLM",
    "claude 3.5": "LLM",
    "claude code": "ai coding",
    "claude code sdk": "ai coding",
    "claudecode": "ai coding",
    "clean architecture": "软件架构",
    "client-go": "Kubernetes",
    "cline": "ai coding",
    "cmdb": "运维平台",
    "cmodel": "芯片验证",
    "cmos": "CMOS",
    "cni": "云原生网络",
    "cnn": "Deep Learning",
    "cocotb": "芯片验证",
    "code interpreter": "ai coding",
    "code interpreter sandbox": "ai coding",
    "code review": "代码审查",
    "codeact": "ai coding",
    "codebuddy": "ai coding",
    "codeium": "ai coding",
    "codellm": "ai coding",
    "codemirror": "前端开发",
    "codeql": "代码安全",
    "coderag": "ai coding",
    "codesandbox": "前端开发",
    "codex": "ai coding",
    "codex cli": "ai coding",
    "coding": "编程能力",
    "colmap": "3D重建",
    "colossal-ai": "大模型训练",
    "colossalai": "大模型训练",
    "comfyui": "AIGC",
    "commonjs": "前端开发",
    "compiler": "编译原理",
    "compose": "移动开发",
    "compose multiplatform": "跨平台开发",
    "computer use": "agent",
    "computer vision": "计算机视觉",
    "comsol": "CAE仿真",
    "comsol multiphysics": "CAE仿真",
    "confluence": "项目协作工具",
    "conformer": "Deep Learning",
    "consistency model": "生成模型",
    "consistency models": "生成模型",
    "consistent hashing": "分布式系统",
    "containerd": "容器技术",
    "continue training": "大模型后训练",
    "continuous batching": "模型推理",
    "controlnet": "AIGC",
    "copilot": "ai coding",
    "bf16": "低精度计算",
    "bm25": "检索排序算法",
    "x86": "x86架构",
}


NORMALIZE_PATTERNS = [
    (r"^aeb", "ADAS算法", "adas_algorithm"),
    (r"^adas", "ADAS", "adas"),
    (r"^afe", "模拟前端", "analog_frontend"),
    (r"^agv", "AGV机器人", "agv"),
    (r"^aot", "AOT编译", "aot_compiler"),
    (r"^apt", "网络安全", "apt_security"),
    (r"^ar(?:-|/|交互|产品|平台|感知|显示|模型|测试|生成|眼镜|算法|试穿|音频|$)", "AR/VR技术", "ar_vr"),
    (r"^arm(?:\s|64|体系|固件|处理器|平台|开源|指令|服务器|架构|汇编|设备|逆向|部署|$)", "ARM", "arm_family"),
    (r"^amba(?:\s|$)", "AMBA总线", "amba_bus"),
    (r"^amd\s+(?:amf|fsr|gpa|mi300|rocm|ryzen ai|sev)", "GPU计算", "amd_gpu_family"),
    (r"^ami\s+bmc|bmc", "BMC开发", "bmc"),
    (r"^ams模型", "模拟混合信号", "ams"),
    (r"^android", "android开发", "android"),
    (r"^animate|^animation|^animator", "动画技术", "animation"),
    (r"^ann算法", "Deep Learning", "ann"),
    (r"^anomaly detection", "异常检测", "anomaly_detection"),
    (r"^anr", "android性能优化", "android_anr"),
    (r"^ansys|^ansoft", "CAE仿真", "cae"),
    (r"^anti-ddos", "网络安全", "ddos_security"),
    (r"^anti-grain geometry", "图形渲染", "graphics"),
    (r"^apache\s+airflow|^airflow$", "工作流调度", "airflow"),
    (r"^apache\s+dolphinscheduler", "工作流调度", "dolphinscheduler"),
    (r"^apache\s+dubbo", "RPC框架", "dubbo"),
    (r"^apache\s+madlib", "Machine Learning", "madlib"),
    (r"^apache\s+paimon", "数据湖", "paimon"),
    (r"^apache\s+pulsar", "消息队列", "pulsar"),
    (r"^apache\s+redhawk", "软件无线电", "sdr"),
    (r"^apache\s+traffic server", "Web服务器", "traffic_server"),
    (r"^apache\s+yarn", "大数据平台", "yarn"),
    (r"^app(?:armor|builder|container)", "APP开发", "app_family"),
    (r"^apple intelligence sdk", "SDK", "sdk"),
    (r"^apm", "APM监控", "apm"),
    (r"^apaas$", "低代码平台", "paas"),
    (r"^april(?:tag)?", "计算机视觉", "apriltag"),
    (r"^asic", "ASIC", "asic"),
    (r"^asil\s+[a-z]", "功能安全", "functional_safety"),
    (r"^ate", "芯片测试", "ate"),
    (r"^audio(?:\s|-|effect|flinger|policy|queue|record|service|track|unit|ldm|lm|$)", "音频技术", "audio"),
    (r"^autocad", "CAD", "cad"),
    (r"^autoform", "CAE仿真", "cae"),
    (r"^autosar", "AUTOSAR", "autosar"),
    (r"^avx", "SIMD", "simd"),
    (r"^aws(?:\s|安全|$)", "云计算", "aws_cloud"),
    (r"^azure(?:\s|安全|$)", "云计算", "azure_cloud"),
    (r"^axi(?:\s|$)", "AMBA总线", "axi"),
    (r"^(?:airtest|selenium|appium|junit|pytest|testng|robot framework|postman|jmeter)", "自动化测试", "test_tools"),
    (r"^3gpp(?:\s|$)", "通信协议", "3gpp"),
    (r"^(?:ansible|terraform|jenkins|gitlab|github actions|prometheus|grafana|elk|helm|harbor|istio|envoy|consul|vault)$", "SRE", "devops_tools"),
    (r"^(?:babylon\.js|backbone|canvas|canvas2d)$", "前端开发", "frontend_tools"),
    (r"^(?:react|vue|angular|svelte|next\.js|nuxt|jquery|webpack|vite|babel|bootstrap|tailwind|sass|less|axios)$", "前端开发", "frontend_tools"),
    (r"^(?:node\.js|express|koa|spring|spring boot|django|flask|fastapi|gin|beego|dubbo|grpc)$", "后端开发", "backend_tools"),
    (r"^(?:mysql|postgresql|postgres|oracle|sql server|mongodb|redis|clickhouse|elasticsearch|neo4j|tidb|doris|starrocks|hbase|hive|sqlite)$", "数据库", "database_tools"),
    (r"^(?:spark|flink|hadoop|hdfs|kafka|pulsar|rocketmq|rabbitmq|airflow|azkaban|dolphinscheduler)$", "数据工程", "data_tools"),
    (r"^(?:pytorch|tensorflow|keras|scikit-learn|sklearn|xgboost|lightgbm|onnx|tensorrt|openvino)$", "AI框架", "ai_frameworks"),
    (r"^(?:bev|blip|clip|camera|opencv|yolo|resnet|sam|segment anything)", "计算机视觉", "cv_models_tools"),
    (r"^(?:blender|maya|houdini|cinema 4d|unity|unreal|ue4|ue5)$", "游戏图形", "graphics_tools"),
    (r"^(?:balun|bandedge|bandgap|beamforming)", "射频技术", "rf"),
    (r"^(?:bazel|build cache|buck|cmake|makefile|ninja)$", "构建工具", "build_tools"),
    (r"^(?:behavior cloning|behavior model|behavioral model)", "模仿学习", "imitation_learning"),
    (r"^(?:bert|bloom|gpt|llama|qwen|glm|ernie|mamba|transformer)", "LLM", "llm_models"),
    (r"^(?:bigvgan|bert-vits|vall-e)", "语音算法", "speech_models"),
    (r"^(?:bind|bookkeeper)", "后端开发", "backend_infra"),
    (r"^(?:bit-accurate|c-model|c2rtl|rtl2gds|block dv|block synthesis)", "芯片验证", "chip_verification"),
    (r"^(?:blackwell|cuda|cutlass|cupti|nvidia|nv)", "GPU计算", "gpu_compute"),
    (r"^(?:blendshape|blueprint)", "游戏图形", "graphics_tools"),
    (r"^(?:bluetooth|ble)", "蓝牙开发", "bluetooth"),
    (r"^(?:board bring-up|boot|boundary scan|bsp)", "嵌入式开发", "embedded"),
    (r"^(?:browser control|browser use)", "AI工作流设计", "browser_agent"),
    (r"^(?:bundle adjustment|cartographer|vslam|slam)", "SLAM", "slam"),
    (r"^(?:bytetrack)", "目标跟踪", "object_tracking"),
    (r"^(?:cadence|calibre)", "EDA工具", "eda_tools"),
    (r"^(?:cache coherence|calling convention|buddy system|buffer pool|block io|block layer)", "底层系统", "low_level_system"),
    (r"^(?:cam|camera)", "相机系统", "camera_system"),
    (r"^(?:can fd|canalyzer|canape|canbus|canoe|canopen)", "CAN总线", "can_bus"),
    (r"^(?:base model|ca model|behavior model|behavioral model)", "模型训练", "model_training"),
    (r"^(?:bangc|cann)", "Ascend", "ascend_stack"),
    (r"^(?:batching|continuous batching|chunked prefill)", "模型推理", "llm_inference"),
    (r"^(?:beyondmimic|bot ai)", "AI算法", "ai_algorithm"),
    (r"^(?:blink|chromium|chrome devtools|chromium devtools|v8)", "浏览器内核", "browser_engine"),
    (r"^(?:bluebeam|cadence|catia|comsol)", "CAD/CAE工具", "cad_cae_tools"),
    (r"^(?:boost converter|buck converter|buck-boost|charge pump)", "电源设计", "power_design"),
    (r"^(?:broadcom|cavium)", "芯片", "chip_vendor"),
    (r"^(?:browsecomp|browser control|browser use|computer use)", "agent", "agent_browser"),
    (r"^(?:byte buddy|jvmti)", "Java", "java_runtime"),
    (r"^(?:c\+\+ addon|c\+\+ stl)", "C++", "cpp_family"),
    (r"^(?:c2c phy|chi mesh|chi vip|coherent noc|connector spi)", "芯片互连", "chip_interconnect"),
    (r"^(?:calcite|cockroachdb|cloud spanner)", "数据库", "database_tools"),
    (r"^(?:calibration|color manager|colormanager)", "图像调试", "image_tuning"),
    (r"^(?:ceva dsp)", "DSP开发", "dsp"),
    (r"^(?:classifier-free guidance|cfg)", "AIGC", "aigc"),
    (r"^(?:clock|clk|clock gating|clock mux|clock reset)", "芯片时钟设计", "chip_clock"),
    (r"^(?:cloud hypervisor|cloud ide|cloudfoundry|cloudwego|confidential containers)", "云计算", "cloud"),
    (r"^(?:cluster|co-design|co-simulation|coherency|collective communication)", "分布式系统", "distributed_system"),
    (r"^(?:cocoa|cocoapods)", "ios开发", "ios"),
    (r"^(?:cocos|cocos creator)", "游戏开发", "game_dev"),
    (r"^(?:codec|codec2|codec avatar)", "音视频编解码", "codec"),
    (r"^(?:codel llama|codellama|code llama)", "ai coding", "coding_llm"),
    (r"^(?:cogvideo)", "视频生成", "video_generation"),
    (r"^(?:command processor)", "操作系统", "os"),
    (r"^(?:competitive coding)", "算法能力", "algorithm"),
    (r"^(?:complex instruct following)", "大模型评测", "llm_eval"),
    (r"^(?:compositor|view体系|view子系统)", "图形系统", "graphics_system"),
    (r"^(?:constrained-random|constraint)", "芯片验证", "chip_verification"),
    (r"^(?:container toolkit)", "容器技术", "container"),
]


def decide(skill: str) -> Decision:
    raw = clean_text(skill)
    low = raw.casefold()
    if not raw:
        return Decision("delete", "", "empty")

    if low in DELETE_EXACT:
        return Decision("delete", "", "delete_exact")

    if low in NORMALIZE_EXACT:
        output = NORMALIZE_EXACT[low]
        action = "normalize" if output.casefold() != low else "keep"
        return Decision(action, output, "normalize_exact")

    for pattern, output, reason in NORMALIZE_PATTERNS:
        if has(pattern, raw):
            action = "normalize" if output.casefold() != low else "keep"
            return Decision(action, output, reason)

    for pattern, reason in DELETE_PATTERNS:
        if has(pattern, raw):
            return Decision("delete", "", reason)

    if has(r"^[A-Za-z0-9.#/+_-]", raw) and not has(r"[\u4e00-\u9fff]", raw):
        return Decision("delete", "", "delete_unmatched_latin_fragment")

    return Decision("keep", raw, "kept_as_skill")


def read_skills(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames or "skill" not in reader.fieldnames:
            raise ValueError(f"Missing 'skill' column in {path}")
        return [clean_text(row["skill"]) for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggressively clean normalized final skill CSV.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.input
    output = args.output or source.with_name(source.stem + "_aggressive_cleaned.csv")
    audit_output = args.audit_output or source.with_name(source.stem + "_aggressive_cleaned_audit.csv")

    skills = read_skills(source)
    audit_rows: list[dict[str, str]] = []
    final_by_key: dict[str, str] = {}
    counts = {"delete": 0, "normalize": 0, "keep": 0}

    for skill in skills:
        decision = decide(skill)
        counts[decision.action] = counts.get(decision.action, 0) + 1
        audit_rows.append(
            {
                "source_skill": skill,
                "decision": decision.action,
                "output_skill": decision.output_skill,
                "reason": decision.reason,
            }
        )
        if decision.output_skill:
            final_by_key.setdefault(decision.output_skill.casefold(), decision.output_skill)

    final_rows = [{"skill": skill} for skill in sorted(final_by_key.values(), key=str.casefold)]
    write_csv(audit_output, ["source_skill", "decision", "output_skill", "reason"], audit_rows)
    write_csv(output, ["skill"], final_rows)

    print(f"input_rows={len(skills)}")
    print(f"deleted_rows={counts.get('delete', 0)}")
    print(f"normalized_rows={counts.get('normalize', 0)}")
    print(f"kept_rows={counts.get('keep', 0)}")
    print(f"final_unique_rows={len(final_rows)}")
    print(f"output={output}")
    print(f"audit_output={audit_output}")


if __name__ == "__main__":
    main()
