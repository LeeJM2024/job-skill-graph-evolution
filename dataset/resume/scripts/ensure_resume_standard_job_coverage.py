from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


RESUME_DIR = Path(__file__).resolve().parents[1]
DATASET_DIR = RESUME_DIR.parent
BASE_DATA_DIR = DATASET_DIR / "job_update" / "data" / "base"
DEFAULT_ALIGNED = RESUME_DIR / "synthetic_detailed_resumes_aligned.csv"
DEFAULT_STANDARD_JOBS = BASE_DATA_DIR / "standard_job_title_dictionary.csv"
DEFAULT_FREQUENCY = BASE_DATA_DIR / "job_skill_monthly_frequency.csv"
DEFAULT_SKILL_POOL = BASE_DATA_DIR / "skill_pool.csv"
DEFAULT_OUTPUT_CSV = DEFAULT_ALIGNED
DEFAULT_OUTPUT_JSONL = RESUME_DIR / "synthetic_detailed_resumes_aligned.jsonl"
DEFAULT_SAMPLE = RESUME_DIR / "synthetic_detailed_resumes_aligned_sample.csv"
DEFAULT_REPORT = RESUME_DIR / "synthetic_detailed_resumes_aligned_report.json"

REQUIRED_ALIGNMENT_COLUMNS = [
    "resume_skill_overlap_ratio",
    "job_skill_coverage_ratio",
]


NAMES = [
    "陈景然", "李卓航", "王思琪", "赵以恒", "周沐辰", "刘书瑶", "孙泽宇", "何嘉宁", "林若溪", "许知远",
    "高明轩", "朱语晨", "胡一鸣", "郭芷晴", "罗星河", "梁安然", "宋子墨", "谢云帆", "唐雨桐", "邓清扬",
]
COMPANIES = ["大型科技企业", "智能硬件公司", "AI 创业公司", "企业数字化团队", "工业互联网平台", "云计算服务商"]
SCHOOLS = ["985高校", "211高校", "双一流高校", "普通高校"]
EDUCATIONS = [("本科", "学士"), ("硕士研究生", "硕士"), ("博士研究生", "博士")]
LEVELS = ["了解", "掌握", "熟练", "精通"]


JOB_MAJOR_HINTS = {
    "芯片": ["微电子科学与工程", "集成电路设计与集成系统", "电子科学与技术"],
    "硬件": ["电子信息工程", "自动化", "机械设计制造及其自动化"],
    "通信": ["通信工程", "信息与通信工程", "电子信息工程"],
    "多媒体": ["数字媒体技术", "计算机科学与技术", "软件工程"],
    "机器人": ["机器人工程", "自动化", "控制科学与工程"],
    "产品": ["信息管理与信息系统", "计算机科学与技术", "工业工程"],
    "安全": ["网络空间安全", "信息安全", "计算机科学与技术"],
    "AI安全": ["网络空间安全", "人工智能", "计算机科学与技术"],
    "软件研发": ["计算机科学与技术", "软件工程", "电子信息工程"],
}


SEMANTIC_SKILLS = {
    "AI产品经理": ["AI产品设计", "大模型产品", "AIGC产品", "需求分析", "PRD", "用户研究", "数据分析", "原型设计", "Prompt工程", "RAG", "产品规划", "增长分析"],
    "AI安全工程师": ["大模型安全", "Prompt Injection", "Jailbreak", "Guardrail", "红队测试", "模型评测", "内容安全", "对抗样本", "风险控制", "安全策略", "Python", "安全测试"],
    "FPGA工程师": ["FPGA", "Verilog", "VHDL", "Vivado", "时序约束", "RTL设计", "AXI", "PCIe", "DDR", "硬件调试", "数字电路", "信号完整性"],
    "图形图像工程师": ["C++", "OpenGL", "Vulkan", "DirectX", "图形渲染", "Shader", "图像处理", "GPU", "CUDA", "计算机视觉", "Unreal", "Unity"],
    "嵌入式软件工程师": ["C/C++", "嵌入式系统", "Linux", "RTOS", "ARM", "MCU", "驱动开发", "串口", "CAN", "I2C", "SPI", "硬件调试"],
    "机器人软件工程师": ["ROS", "C++", "Python", "SLAM", "运动规划", "路径规划", "机器人控制", "传感器融合", "Linux", "Gazebo", "实时系统", "算法部署"],
    "热设计工程师": ["热设计", "散热仿真", "CFD", "Icepak", "FloTHERM", "结构设计", "热测试", "材料导热", "可靠性测试", "有限元分析", "硬件工程", "测试验证"],
    "电源工程师": ["电源设计", "电力电子", "DC-DC", "BMS", "模拟电路", "PCB设计", "EMC", "电池管理", "Altium Designer", "硬件调试", "可靠性测试", "示波器"],
    "硬件工程师": ["硬件设计", "原理图设计", "PCB设计", "单板调试", "示波器", "信号完整性", "EMC", "Altium Designer", "ARM", "硬件测试", "可靠性测试", "电路分析"],
    "系统软件工程师": ["C/C++", "Linux Kernel", "操作系统", "驱动开发", "编译器", "SDK", "性能优化", "进程调度", "内存管理", "系统软件", "调试工具", "并发编程"],
    "结构工程师": ["结构设计", "SolidWorks", "CAD", "机械设计", "可靠性测试", "3D建模", "公差分析", "材料力学", "有限元分析", "样机验证", "热设计", "工艺评审"],
    "网络安全工程师": ["网络安全", "渗透测试", "漏洞挖掘", "安全攻防", "Web安全", "代码审计", "应急响应", "Python", "Linux", "安全测试", "威胁建模", "日志分析"],
    "芯片测试工程师": ["芯片测试", "ATE", "测试方案", "Python", "C/C++", "LabVIEW", "量产测试", "测试覆盖率", "硬件调试", "示波器", "数据分析", "DFT"],
    "芯片设计工程师": ["SoC设计", "ASIC", "Verilog", "RTL设计", "数字IC", "SystemVerilog", "低功耗设计", "时序分析", "综合约束", "脚本自动化", "Python", "EDA工具"],
    "芯片验证工程师": ["UVM", "SystemVerilog", "Verilog", "覆盖率驱动验证", "仿真", "断言", "Python", "Perl", "SoC验证", "验证计划", "回归测试", "DFT"],
    "通信工程师": ["5G", "6G", "通信协议", "TCP/IP", "无线通信", "信号处理", "C/C++", "Python", "SDR", "网络优化", "基站系统", "高性能通信"],
    "音视频工程师": ["FFmpeg", "WebRTC", "音视频编解码", "H.264", "H.265", "RTP/RTCP", "C++", "流媒体", "音频处理", "视频处理", "低延迟传输", "性能优化"],
    "驱动开发工程师": ["Linux驱动", "Kernel", "C/C++", "设备树", "PCIe", "USB", "I2C", "SPI", "ARM", "硬件调试", "中断处理", "DMA"],
}


FALLBACK_BY_CATEGORY = {
    "软件研发": ["C/C++", "Python", "Linux", "软件开发", "系统设计", "性能优化", "调试工具", "并发编程", "Git", "代码测试", "架构设计", "工程化"],
    "AI算法": ["Python", "PyTorch", "机器学习", "深度学习", "LLM", "模型训练", "模型评估", "数据处理", "算法优化", "NLP", "多模态", "TensorFlow"],
    "AI应用": ["RAG", "Prompt工程", "LangChain", "Function Calling", "MCP", "向量数据库", "AI应用开发", "Python", "后端开发", "工作流编排", "API设计", "模型服务化"],
    "数据": ["SQL", "Python", "Spark", "Hadoop", "数据仓库", "ETL", "数据治理", "数据建模", "Kafka", "Flink", "数据质量", "指标体系"],
    "基础设施": ["Linux", "Docker", "Kubernetes", "Shell脚本", "网络技术", "云计算", "DevOps", "Prometheus", "MySQL", "故障排查", "自动化运维", "高可用"],
    "测试质量": ["软件测试", "自动化测试", "性能测试", "接口测试", "Python", "Selenium", "JMeter", "质量保障", "测试开发", "缺陷管理", "CI/CD", "安全测试"],
}


KG_BY_KEYWORD = [
    (["安全", "漏洞", "攻防", "红队", "Jailbreak", "Injection", "Guardrail"], "安全"),
    (["芯片", "FPGA", "ASIC", "SoC", "RTL", "Verilog", "UVM", "ATE", "硬件", "电源", "PCB", "散热", "结构"], "硬件与芯片"),
    (["通信", "5G", "6G", "TCP/IP", "无线", "基站", "RTP", "WebRTC"], "通信"),
    (["图形", "图像", "音视频", "FFmpeg", "OpenGL", "Vulkan", "Shader", "编解码"], "多媒体"),
    (["AI", "大模型", "LLM", "Prompt", "RAG", "模型", "Agent", "AIGC"], "AI"),
    (["数据", "SQL", "Spark", "Hadoop", "ETL", "Flink", "Kafka", "仓库"], "数据工程"),
    (["Linux", "Docker", "Kubernetes", "运维", "DevOps", "云计算"], "系统与运维"),
    (["测试", "质量", "Selenium", "JMeter"], "软件工程"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Supplement aligned synthetic resumes so every standard job has coverage.")
    parser.add_argument("--aligned", type=Path, default=DEFAULT_ALIGNED)
    parser.add_argument("--standard-jobs", type=Path, default=DEFAULT_STANDARD_JOBS)
    parser.add_argument("--frequency", type=Path, default=DEFAULT_FREQUENCY)
    parser.add_argument("--skill-pool", type=Path, default=DEFAULT_SKILL_POOL)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--per-missing-job", type=int, default=30)
    args = parser.parse_args()

    aligned = pd.read_csv(args.aligned, dtype=str, encoding="utf-8-sig").fillna("")
    standard_jobs = pd.read_csv(args.standard_jobs, dtype=str, encoding="utf-8-sig").fillna("")
    frequency = pd.read_csv(args.frequency, dtype=str, encoding="utf-8-sig").fillna("")
    skill_pool = pd.read_csv(args.skill_pool, dtype=str, encoding="utf-8-sig").fillna("")

    base_aligned = aligned[aligned.get("alignment_method", "") != "generated_full_coverage_by_standard_job"].copy()
    category_by_job = dict(zip(standard_jobs["standard_job_title"], standard_jobs["standard_category"]))
    skill_kg = dict(zip(skill_pool["normalized_skill"], skill_pool["kg_display_skill"]))
    job_profiles = build_job_profiles(frequency, skill_pool, standard_jobs)

    missing_jobs = [job for job in standard_jobs["standard_job_title"].tolist() if job not in set(base_aligned["standard_job"])]
    existing_columns = list(aligned.columns)
    for column in REQUIRED_ALIGNMENT_COLUMNS:
        if column not in existing_columns:
            existing_columns.append(column)
    supplement_rows: list[dict[str, Any]] = []
    start_index = len(base_aligned) + 1
    for job_index, standard_job in enumerate(missing_jobs):
        category = category_by_job.get(standard_job, "")
        profile_skills = dedupe(semantic_skills_for(standard_job, category) + job_profiles.get(standard_job, []))[:24]
        for offset in range(args.per_missing_job):
            supplement_rows.append(
                build_resume_record(
                    global_index=start_index + len(supplement_rows),
                    job_index=job_index,
                    offset=offset,
                    standard_job=standard_job,
                    standard_category=category,
                    profile_skills=profile_skills,
                    skill_kg=skill_kg,
                    columns=existing_columns,
                )
            )

    supplement = pd.DataFrame(supplement_rows)
    full = pd.concat([base_aligned, supplement], ignore_index=True) if len(supplement) else base_aligned.copy()
    full = recompute_coverage_columns(full)
    full = full[existing_columns]
    full.to_csv(args.output_csv, index=False, encoding="utf-8-sig")
    write_jsonl(full.to_dict("records"), args.output_jsonl)
    sample = full.groupby("standard_job", group_keys=False).head(2)
    sample.to_csv(args.sample, index=False, encoding="utf-8-sig")
    write_report(full, base_aligned, supplement, standard_jobs, args.report)

    print(f"input_aligned_rows={len(aligned)}")
    print(f"base_aligned_rows={len(base_aligned)}")
    print(f"supplement_rows={len(supplement)}")
    print(f"output_rows={len(full)}")
    print(f"standard_jobs_used={full['standard_job'].nunique()}")
    print(f"standard_jobs_total={len(standard_jobs)}")
    print(f"missing_jobs_before={len(missing_jobs)}")
    print(f"output_csv={args.output_csv}")
    print(f"output_jsonl={args.output_jsonl}")
    print(f"sample={args.sample}")
    print(f"report={args.report}")


def build_job_profiles(frequency: pd.DataFrame, skill_pool: pd.DataFrame, standard_jobs: pd.DataFrame) -> dict[str, list[str]]:
    profiles: dict[str, list[str]] = {}
    if not frequency.empty:
        work = frequency.copy()
        for col in ["cumulative_skill_frequency", "monthly_skill_frequency", "cumulative_skill_count"]:
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
        work = work.sort_values(
            ["standard_job", "skill", "month", "cumulative_skill_frequency", "cumulative_skill_count"],
            ascending=[True, True, False, False, False],
        )
        latest = work.drop_duplicates(["standard_job", "skill"], keep="first")
        latest = latest.sort_values(
            ["standard_job", "cumulative_skill_frequency", "monthly_skill_frequency", "cumulative_skill_count"],
            ascending=[True, False, False, False],
        )
        for job, group in latest.groupby("standard_job"):
            profiles[job] = dedupe([str(skill).strip() for skill in group["skill"].tolist() if str(skill).strip()])[:24]
    if not skill_pool.empty:
        work = skill_pool.copy()
        work["mention_count_num"] = pd.to_numeric(work.get("mention_count", 0), errors="coerce").fillna(0)
        work = work.sort_values(["mention_count_num", "normalized_skill"], ascending=[False, True])
        for _, row in work.iterrows():
            skill = str(row.get("normalized_skill", "")).strip()
            if not skill:
                continue
            for job in [item.strip() for item in str(row.get("standard_jobs", "")).split(";") if item.strip()]:
                profiles.setdefault(job, [])
                if skill not in profiles[job]:
                    profiles[job].append(skill)
    for _, row in standard_jobs.iterrows():
        job = row["standard_job_title"]
        category = row["standard_category"]
        if not profiles.get(job):
            profiles[job] = semantic_skills_for(job, category)
        else:
            profiles[job] = dedupe(profiles[job] + semantic_skills_for(job, category))[:24]
    return profiles


def semantic_skills_for(job: str, category: str) -> list[str]:
    if job in SEMANTIC_SKILLS:
        return SEMANTIC_SKILLS[job]
    return FALLBACK_BY_CATEGORY.get(category, ["需求分析", "系统设计", "项目推进", "数据分析", "文档沉淀", "问题定位", "沟通协作", "质量保障"])


def build_resume_record(
    global_index: int,
    job_index: int,
    offset: int,
    standard_job: str,
    standard_category: str,
    profile_skills: list[str],
    skill_kg: dict[str, str],
    columns: list[str],
) -> dict[str, Any]:
    years = [1, 2, 3, 5, 7, 9][(job_index + offset) % 6]
    education, degree = EDUCATIONS[(job_index + offset) % len(EDUCATIONS)]
    name = NAMES[(job_index * 3 + offset) % len(NAMES)]
    gender = "女" if (job_index + offset) % 2 else "男"
    age = str(22 + min(years, 10) + (1 if education == "硕士研究生" else 0) + (3 if education == "博士研究生" else 0))
    resume_id = f"resume_std_{global_index:06d}"
    skills = dedupe(profile_skills[:18] + semantic_skills_for(standard_job, standard_category))[:24]
    skill_levels = {skill: skill_level(years, idx, offset) for idx, skill in enumerate(skills)}
    major = choose_major(standard_category, standard_job, offset)
    company_a = COMPANIES[(job_index + offset) % len(COMPANIES)]
    company_b = COMPANIES[(job_index + offset + 2) % len(COMPANIES)]
    split = "train" if offset % 10 < 6 else "dev" if offset % 10 < 8 else "test"

    experience = [
        {
            "company_type": company_a,
            "role": standard_job,
            "duration_years": max(1, years - 1),
            "keywords": skills[:10],
            "highlights": [
                f"围绕{standard_job}方向，负责需求拆解、方案设计、开发落地和效果复盘。",
                f"重点使用{skills[0]}、{skills[1]}、{skills[2]}、{skills[3]}等能力支撑核心业务迭代。",
                f"结合{standard_category}岗位画像，沉淀标准流程、质量检查清单和可复用组件。",
            ],
        },
        {
            "company_type": company_b,
            "role": f"{standard_job}项目成员",
            "duration_years": 1 if years <= 2 else 2,
            "keywords": skills[6:16],
            "highlights": [
                f"参与{project_name(standard_job, standard_category, offset + 1)}，承担模块实现、联调测试和结果复盘。",
                f"围绕{skills[6]}与{skills[7]}优化关键链路，提升系统稳定性和交付效率。",
            ],
        },
    ]
    projects = [
        {
            "project_name": project_name(standard_job, standard_category, offset),
            "project_scale": ["small", "medium", "large"][(job_index + offset) % 3],
            "role": "主要负责人" if offset % 3 == 0 else "核心成员",
            "tech_stack": skills[:12],
            "description": project_description(standard_job, standard_category, skills),
            "outcome": ["形成可复用的技术方案和项目文档", "将关键流程耗时降低约 20%", "支撑多业务线稳定复用"][(job_index + offset) % 3],
        },
        {
            "project_name": project_name(standard_job, standard_category, offset + 2),
            "project_scale": "medium",
            "role": "核心成员",
            "tech_stack": skills[5:17],
            "description": f"基于{skills[5]}、{skills[6]}等技术完成方案验证、问题定位和迭代优化。",
            "outcome": "提升问题定位和交付效率",
        },
    ]
    profile_text = build_profile_text(
        standard_job=standard_job,
        category=standard_category,
        education=education,
        degree=degree,
        school=SCHOOLS[(job_index + offset) % len(SCHOOLS)],
        major=major,
        years=years,
        skills=skills,
        experience=experience,
        projects=projects,
    )
    row = {
        "resume_id": resume_id,
        "name": name,
        "gender": gender,
        "age": age,
        "phone": f"139{global_index % 100000000:08d}",
        "email": f"{resume_id}@synthetic.local",
        "split": split,
        "target_job_family": standard_job,
        "education": education,
        "degree": degree,
        "school_category": SCHOOLS[(job_index + offset) % len(SCHOOLS)],
        "major": major,
        "english_level": "英语六级" if education != "本科" or offset % 2 else "英语四级",
        "years_experience": str(years),
        "experience": json.dumps(experience, ensure_ascii=False),
        "projects": json.dumps(projects, ensure_ascii=False),
        "skills_normalized": json.dumps(skills, ensure_ascii=False),
        "skill_levels": json.dumps(skill_levels, ensure_ascii=False),
        "job_keywords_used": json.dumps(dedupe(skills + [standard_job, standard_category])[:32], ensure_ascii=False),
        "profile_text": profile_text,
        "original_target_job_family": "__generated_full_coverage__",
        "standard_job": standard_job,
        "standard_job_title": standard_job,
        "standard_category": standard_category,
        "alignment_method": "generated_full_coverage_by_standard_job",
        "job_profile_skills": json.dumps(profile_skills, ensure_ascii=False),
        "kg_display_skills": json.dumps(
            [{"normalized_skill": skill, "kg_display_skill": skill_kg.get(skill, infer_kg(skill))} for skill in skills],
            ensure_ascii=False,
        ),
        "resume_skill_overlap_count": str(len(set(skills) & set(profile_skills))),
        "resume_skill_overlap_ratio": "1.0000",
        "job_skill_coverage_ratio": f"{len(set(skills) & set(profile_skills)) / max(len(profile_skills), 1):.4f}",
    }
    for column in columns:
        row.setdefault(column, "")
    return row


def choose_major(category: str, job: str, seed: int) -> str:
    for key, majors in JOB_MAJOR_HINTS.items():
        if key in category or key in job:
            return majors[seed % len(majors)]
    return ["计算机科学与技术", "软件工程", "人工智能", "数据科学与大数据技术"][seed % 4]


def skill_level(years: int, idx: int, seed: int) -> str:
    if years >= 7 and idx < 8:
        return "精通" if (idx + seed) % 3 == 0 else "熟练"
    if years >= 3:
        return "熟练" if idx < 12 else "掌握"
    return "掌握" if idx < 10 else "了解"


def project_name(job: str, category: str, seed: int) -> str:
    templates = {
        "芯片": ["芯片验证回归平台", "SoC 子系统设计项目", "量产测试数据分析平台"],
        "硬件": ["智能硬件样机验证", "单板调试与可靠性提升", "硬件热设计优化项目"],
        "通信": ["5G 通信链路优化", "高性能网络传输模块", "通信协议栈联调项目"],
        "多媒体": ["低延迟音视频处理系统", "图形渲染性能优化", "实时流媒体传输平台"],
        "机器人": ["机器人导航与控制系统", "多传感器融合平台", "机器人软件中间件"],
        "产品": ["大模型产品工作台", "AI 助手需求闭环平台", "智能推荐产品增长项目"],
        "安全": ["安全攻防演练平台", "漏洞治理与风险监控", "大模型安全评测体系"],
    }
    choices = templates.get(category, [f"{job}核心能力建设", f"{category}流程优化平台", f"{job}质量提升项目"])
    return choices[seed % len(choices)]


def project_description(job: str, category: str, skills: list[str]) -> str:
    return f"面向{job}岗位场景，围绕{skills[0]}、{skills[1]}、{skills[2]}构建从方案设计、实现验证到质量复盘的闭环能力。"


def build_profile_text(
    standard_job: str,
    category: str,
    education: str,
    degree: str,
    school: str,
    major: str,
    years: int,
    skills: list[str],
    experience: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> str:
    skill_text = "、".join(skills[:12])
    exp_text = " ".join(
        f"{item['company_type']}，{item['role']}，{item['duration_years']}年。{'；'.join(item['highlights'])}"
        for item in experience
    )
    project_text = " ".join(
        f"{item['project_name']}：担任{item['role']}，技术栈包括{'、'.join(item['tech_stack'][:8])}。{item['description']}项目结果：{item['outcome']}。"
        for item in projects
    )
    return "\n".join(
        [
            f"求职意向：{standard_job}。",
            f"标准岗位：{standard_job}；岗位大族：{category}；岗位系统技能画像：{'、'.join(skills[:10])}。",
            f"教育背景：{education}，{degree}学位，{school}，{major}专业。",
            f"个人概述：具备{years}年左右{standard_job}相关实践经验，关注{skill_text}等方向，能够从需求理解、方案设计、工程实现到结果复盘完整推进任务。",
            f"技能栈：{skill_text}。",
            f"工作经历：{exp_text}",
            f"项目经历：{project_text}",
            "综合能力：具备文档沉淀、跨团队沟通、问题定位、质量意识和持续学习能力，能够根据业务目标选择合适的技术方案。",
        ]
    )


def infer_kg(skill: str) -> str:
    for keywords, kg in KG_BY_KEYWORD:
        if any(keyword in skill for keyword in keywords):
            return kg
    if any(lang in skill for lang in ["Python", "Java", "C++", "Go", "Shell", "Verilog", "VHDL"]):
        return "编程语言"
    return "软件工程"


def recompute_coverage_columns(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    overlap_counts = []
    resume_ratios = []
    job_ratios = []
    for _, row in work.iterrows():
        skills = set(parse_json_list(row.get("skills_normalized", "")))
        profile = set(parse_json_list(row.get("job_profile_skills", "")))
        overlap = len(skills & profile)
        overlap_counts.append(str(overlap))
        resume_ratios.append(f"{overlap / max(len(skills), 1):.4f}")
        job_ratios.append(f"{overlap / max(len(profile), 1):.4f}")
    work["resume_skill_overlap_count"] = overlap_counts
    work["resume_skill_overlap_ratio"] = resume_ratios
    work["job_skill_coverage_ratio"] = job_ratios
    return work


def parse_json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return dedupe([str(item) for item in parsed])


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(full: pd.DataFrame, aligned: pd.DataFrame, supplement: pd.DataFrame, standard_jobs: pd.DataFrame, path: Path) -> None:
    used_jobs = set(full["standard_job"])
    all_jobs = set(standard_jobs["standard_job_title"])
    report = {
        "input_aligned_rows": int(len(aligned)),
        "supplement_rows": int(len(supplement)),
        "output_rows": int(len(full)),
        "standard_job_dictionary_rows": int(len(standard_jobs)),
        "standard_jobs_used": int(full["standard_job"].nunique()),
        "standard_categories_used": int(full["standard_category"].nunique()),
        "missing_standard_jobs_after": sorted(all_jobs - used_jobs),
        "supplemented_standard_jobs": supplement["standard_job"].value_counts().to_dict() if len(supplement) else {},
        "aligned_standard_job_distribution": full["standard_job"].value_counts().to_dict(),
        "aligned_standard_category_distribution": full["standard_category"].value_counts().to_dict(),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


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
