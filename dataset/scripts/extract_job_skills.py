"""Extract normalized skill mentions from normalized Chinese job records.

This script is intentionally deterministic. It adds a structured skill layer on
top of the existing dataset without changing the current BM25/BGE-M3 pipeline.
Each extracted mention keeps the original sentence as evidence.
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
DEFAULT_ALIAS_JSON = DATASET_DIR / "config" / "skill_aliases.json"
DEFAULT_OUTPUT_DIR = DATASET_DIR / "structured"


@dataclass(frozen=True)
class SkillAlias:
    raw_skill: str
    normalized_skill: str
    category: str
    source: str
    confidence: float


DEFAULT_SKILL_ALIASES: list[SkillAlias] = [
    SkillAlias("Java", "Java", "编程语言", "seed", 1.0),
    SkillAlias("Python", "Python", "编程语言", "seed", 1.0),
    SkillAlias("Go", "Go", "编程语言", "seed", 1.0),
    SkillAlias("Golang", "Go", "编程语言", "seed", 0.95),
    SkillAlias("JavaScript", "JavaScript", "编程语言", "seed", 1.0),
    SkillAlias("TypeScript", "TypeScript", "编程语言", "seed", 1.0),
    SkillAlias("C++", "C++", "编程语言", "seed", 1.0),
    SkillAlias("C#", "C#", "编程语言", "seed", 1.0),
    SkillAlias("Rust", "Rust", "编程语言", "seed", 1.0),
    SkillAlias("SQL", "SQL", "编程语言", "seed", 1.0),
    SkillAlias("HTML", "HTML", "前端技术", "seed", 1.0),
    SkillAlias("CSS", "CSS", "前端技术", "seed", 1.0),
    SkillAlias("React", "React", "前端技术", "seed", 1.0),
    SkillAlias("Vue", "Vue", "前端技术", "seed", 1.0),
    SkillAlias("Angular", "Angular", "前端技术", "seed", 1.0),
    SkillAlias("Node.js", "Node.js", "后端技术", "seed", 1.0),
    SkillAlias("NodeJS", "Node.js", "后端技术", "seed", 0.95),
    SkillAlias("Spring Boot", "Spring Boot", "后端技术", "seed", 1.0),
    SkillAlias("SpringBoot", "Spring Boot", "后端技术", "seed", 0.95),
    SkillAlias("Spring Cloud", "Spring Cloud", "后端技术", "seed", 1.0),
    SkillAlias("SpringCloud", "Spring Cloud", "后端技术", "seed", 0.95),
    SkillAlias("MyBatis", "MyBatis", "后端技术", "seed", 1.0),
    SkillAlias("Django", "Django", "后端技术", "seed", 1.0),
    SkillAlias("Flask", "Flask", "后端技术", "seed", 1.0),
    SkillAlias("FastAPI", "FastAPI", "后端技术", "seed", 1.0),
    SkillAlias("微服务", "Microservices", "后端技术", "seed", 0.9),
    SkillAlias("MySQL", "MySQL", "数据库", "seed", 1.0),
    SkillAlias("PostgreSQL", "PostgreSQL", "数据库", "seed", 1.0),
    SkillAlias("MongoDB", "MongoDB", "数据库", "seed", 1.0),
    SkillAlias("Redis", "Redis", "数据库", "seed", 1.0),
    SkillAlias("Elasticsearch", "Elasticsearch", "数据库", "seed", 1.0),
    SkillAlias("ElasticSearch", "Elasticsearch", "数据库", "seed", 1.0),
    SkillAlias("ES", "Elasticsearch", "数据库", "seed", 0.7),
    SkillAlias("Oracle", "Oracle", "数据库", "seed", 1.0),
    SkillAlias("ClickHouse", "ClickHouse", "数据库", "seed", 1.0),
    SkillAlias("Milvus", "Milvus", "数据库", "seed", 1.0),
    SkillAlias("向量数据库", "Vector Database", "数据库", "seed", 0.9),
    SkillAlias("Docker", "Docker", "云计算/运维", "seed", 1.0),
    SkillAlias("Kubernetes", "Kubernetes", "云计算/运维", "seed", 1.0),
    SkillAlias("K8s", "Kubernetes", "云计算/运维", "seed", 0.98),
    SkillAlias("容器编排", "Kubernetes", "云计算/运维", "seed", 0.9),
    SkillAlias("Linux", "Linux", "云计算/运维", "seed", 1.0),
    SkillAlias("AWS", "AWS", "云计算/运维", "seed", 1.0),
    SkillAlias("Azure", "Azure", "云计算/运维", "seed", 1.0),
    SkillAlias("Terraform", "Terraform", "云计算/运维", "seed", 1.0),
    SkillAlias("DevOps", "DevOps", "云计算/运维", "seed", 1.0),
    SkillAlias("CI/CD", "CI/CD", "云计算/运维", "seed", 1.0),
    SkillAlias("Prometheus", "Prometheus", "云计算/运维", "seed", 1.0),
    SkillAlias("Grafana", "Grafana", "云计算/运维", "seed", 1.0),
    SkillAlias("PyTorch", "PyTorch", "数据与算法", "seed", 1.0),
    SkillAlias("Pytorch", "PyTorch", "数据与算法", "seed", 1.0),
    SkillAlias("TensorFlow", "TensorFlow", "数据与算法", "seed", 1.0),
    SkillAlias("Tensorflow", "TensorFlow", "数据与算法", "seed", 1.0),
    SkillAlias("Pandas", "Pandas", "数据与算法", "seed", 1.0),
    SkillAlias("Numpy", "NumPy", "数据与算法", "seed", 1.0),
    SkillAlias("NumPy", "NumPy", "数据与算法", "seed", 1.0),
    SkillAlias("Scikit-learn", "Scikit-learn", "数据与算法", "seed", 1.0),
    SkillAlias("sklearn", "Scikit-learn", "数据与算法", "seed", 0.95),
    SkillAlias("机器学习", "Machine Learning", "数据与算法", "seed", 0.9),
    SkillAlias("深度学习", "Deep Learning", "数据与算法", "seed", 0.9),
    SkillAlias("自然语言处理", "NLP", "数据与算法", "seed", 0.9),
    SkillAlias("NLP", "NLP", "数据与算法", "seed", 1.0),
    SkillAlias("计算机视觉", "Computer Vision", "数据与算法", "seed", 0.9),
    SkillAlias("大模型", "Large Language Model", "数据与算法", "seed", 0.9),
    SkillAlias("大语言模型", "Large Language Model", "数据与算法", "seed", 0.9),
    SkillAlias("LLM", "Large Language Model", "数据与算法", "seed", 0.95),
    SkillAlias("RAG", "RAG", "数据与算法", "seed", 1.0),
    SkillAlias("LangChain", "LangChain", "数据与算法", "seed", 1.0),
    SkillAlias("MCP", "Model Context Protocol", "数据与算法", "seed", 0.85),
    SkillAlias("Agent", "AI Agent", "数据与算法", "seed", 0.8),
    SkillAlias("智能体", "AI Agent", "数据与算法", "seed", 0.9),
    SkillAlias("AIGC", "AIGC", "数据与算法", "seed", 1.0),
    SkillAlias("Prompt", "Prompt Engineering", "数据与算法", "seed", 0.85),
    SkillAlias("提示词", "Prompt Engineering", "数据与算法", "seed", 0.9),
    SkillAlias("System Prompt", "Prompt Engineering", "数据与算法", "seed", 0.95),
    SkillAlias("Stable Diffusion", "Stable Diffusion", "数据与算法", "seed", 1.0),
    SkillAlias("Midjourney", "Midjourney", "数据与算法", "seed", 1.0),
    SkillAlias("ComfyUI", "ComfyUI", "数据与算法", "seed", 1.0),
    SkillAlias("Flux", "Flux", "数据与算法", "seed", 0.85),
    SkillAlias("多模态", "Multimodal AI", "数据与算法", "seed", 0.9),
    SkillAlias("Hadoop", "Hadoop", "数据与算法", "seed", 1.0),
    SkillAlias("Spark", "Spark", "数据与算法", "seed", 1.0),
    SkillAlias("Flink", "Flink", "数据与算法", "seed", 1.0),
    SkillAlias("Kafka", "Kafka", "数据与算法", "seed", 1.0),
    SkillAlias("RabbitMQ", "RabbitMQ", "后端技术", "seed", 1.0),
    SkillAlias("数据仓库", "Data Warehouse", "数据与算法", "seed", 0.9),
    SkillAlias("ETL", "ETL", "数据与算法", "seed", 1.0),
    SkillAlias("Tableau", "Tableau", "数据与算法", "seed", 1.0),
    SkillAlias("Power BI", "Power BI", "数据与算法", "seed", 1.0),
    SkillAlias("FineBI", "FineBI", "数据与算法", "seed", 1.0),
    SkillAlias("CUDA", "CUDA", "AI基础设施", "seed", 1.0),
    SkillAlias("GPU", "GPU", "AI基础设施", "seed", 1.0),
    SkillAlias("NPU", "NPU", "AI基础设施", "seed", 1.0),
    SkillAlias("昇腾", "Ascend", "AI基础设施", "seed", 0.9),
    SkillAlias("分布式训练", "Distributed Training", "AI基础设施", "seed", 0.95),
    SkillAlias("分布式推理", "Distributed Inference", "AI基础设施", "seed", 0.95),
    SkillAlias("模型推理", "Model Inference", "AI基础设施", "seed", 0.9),
    SkillAlias("模型训练", "Model Training", "AI基础设施", "seed", 0.9),
    SkillAlias("vLLM", "vLLM", "AI基础设施", "seed", 1.0),
    SkillAlias("SGLang", "SGLang", "AI基础设施", "seed", 1.0),
    SkillAlias("Triton", "Triton", "AI基础设施", "seed", 0.95),
    SkillAlias("LLVM", "LLVM", "AI基础设施", "seed", 1.0),
    SkillAlias("MLIR", "MLIR", "AI基础设施", "seed", 1.0),
    SkillAlias("MPI", "MPI", "AI基础设施", "seed", 1.0),
    SkillAlias("NCCL", "NCCL", "AI基础设施", "seed", 1.0),
    SkillAlias("RDMA", "RDMA", "AI基础设施", "seed", 1.0),
    SkillAlias("ARM", "ARM", "AI基础设施", "seed", 1.0),
    SkillAlias("x86", "x86", "AI基础设施", "seed", 1.0),
    SkillAlias("虚拟化", "Virtualization", "AI基础设施", "seed", 0.9),
    SkillAlias("KVM", "KVM", "AI基础设施", "seed", 1.0),
    SkillAlias("QEMU", "QEMU", "AI基础设施", "seed", 1.0),
    SkillAlias("DPDK", "DPDK", "AI基础设施", "seed", 1.0),
    SkillAlias("SPDK", "SPDK", "AI基础设施", "seed", 1.0),
    SkillAlias("CXL", "CXL", "AI基础设施", "seed", 1.0),
    SkillAlias("PCIe", "PCIe", "AI基础设施", "seed", 1.0),
    SkillAlias("UE5", "Unreal Engine", "游戏开发", "seed", 0.95),
    SkillAlias("Unreal Engine", "Unreal Engine", "游戏开发", "seed", 1.0),
    SkillAlias("Unity", "Unity", "游戏开发", "seed", 1.0),
    SkillAlias("Cocos", "Cocos", "游戏开发", "seed", 1.0),
    SkillAlias("Android", "Android", "移动开发", "seed", 1.0),
    SkillAlias("Kotlin", "Kotlin", "移动开发", "seed", 1.0),
    SkillAlias("iOS", "iOS", "移动开发", "seed", 1.0),
    SkillAlias("Swift", "Swift", "移动开发", "seed", 1.0),
    SkillAlias("Flutter", "Flutter", "移动开发", "seed", 1.0),
    SkillAlias("React Native", "React Native", "移动开发", "seed", 1.0),
    SkillAlias("Selenium", "Selenium", "测试工具", "seed", 1.0),
    SkillAlias("JMeter", "JMeter", "测试工具", "seed", 1.0),
    SkillAlias("Postman", "Postman", "测试工具", "seed", 1.0),
    SkillAlias("自动化测试", "Automated Testing", "测试工具", "seed", 0.9),
    SkillAlias("性能测试", "Performance Testing", "测试工具", "seed", 0.9),
    SkillAlias("安全测试", "Security Testing", "测试工具", "seed", 0.9),
]


PREFERRED_MARKERS = (
    "优先",
    "加分",
    "更佳",
    "有经验者",
    "plus",
    "preferred",
    "nice to have",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def split_sentences(text: str) -> list[str]:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"[\n。！？!?；;]+", text)
    return [part.strip(" \t:-—，,、") for part in parts if part.strip()]


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def compile_alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    if has_cjk(alias):
        return re.compile(escaped, re.IGNORECASE)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def load_existing_combo_aliases(path: Path) -> list[SkillAlias]:
    if not path.exists():
        return []
    combos = json.loads(path.read_text(encoding="utf-8"))
    records: list[SkillAlias] = []
    category_by_skill = {item.normalized_skill: item.category for item in DEFAULT_SKILL_ALIASES}
    for raw_skill, normalized_values in combos.items():
        for normalized in normalized_values:
            records.append(
                SkillAlias(
                    raw_skill=str(normalized),
                    normalized_skill=str(normalized),
                    category=category_by_skill.get(str(normalized), "未分类"),
                    source="existing_skill_aliases",
                    confidence=1.0,
                )
            )
            records.append(
                SkillAlias(
                    raw_skill=str(raw_skill),
                    normalized_skill=str(normalized),
                    category=category_by_skill.get(str(normalized), "未分类"),
                    source="existing_skill_aliases_combo",
                    confidence=0.75,
                )
            )
    return records


def dedupe_aliases(records: Iterable[SkillAlias]) -> list[SkillAlias]:
    best: dict[tuple[str, str], SkillAlias] = {}
    for item in records:
        key = (item.raw_skill.lower(), item.normalized_skill.lower())
        previous = best.get(key)
        if previous is None or item.confidence > previous.confidence:
            best[key] = item
    return sorted(best.values(), key=lambda value: (value.normalized_skill.lower(), value.raw_skill.lower()))


def write_alias_table(path: Path, aliases: list[SkillAlias]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["raw_skill", "normalized_skill", "category", "source", "confidence"],
        )
        writer.writeheader()
        for item in aliases:
            writer.writerow(
                {
                    "raw_skill": item.raw_skill,
                    "normalized_skill": item.normalized_skill,
                    "category": item.category,
                    "source": item.source,
                    "confidence": f"{item.confidence:.2f}",
                }
            )


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def truncate_evidence(sentence: str, limit: int = 260) -> str:
    sentence = clean_text(sentence)
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1] + "…"


def skill_type_for_sentence(sentence: str) -> str:
    lower = sentence.lower()
    if any(marker.lower() in lower for marker in PREFERRED_MARKERS):
        return "preferred"
    return "required"


def build_search_units(record: dict[str, Any]) -> list[tuple[str, str]]:
    units: list[tuple[str, str]] = []
    title = clean_text(record.get("job_title"))
    tags = record.get("tags")
    if isinstance(tags, list):
        tags_text = "；".join(clean_text(item) for item in tags if clean_text(item))
    else:
        tags_text = clean_text(tags)
    if title:
        units.append(("job_title", title))
    if tags_text:
        units.append(("tags", tags_text))
    for sentence in split_sentences(str(record.get("job_description") or "")):
        units.append(("job_description", sentence))
    return units


def extract_mentions(record: dict[str, Any], aliases: list[SkillAlias]) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    units = build_search_units(record)
    compiled = [(alias, compile_alias_pattern(alias.raw_skill)) for alias in aliases]

    for source_field, sentence in units:
        for alias, pattern in compiled:
            match = pattern.search(sentence)
            if not match:
                continue
            key = (alias.normalized_skill.lower(), source_field, sentence)
            if key in seen:
                continue
            seen.add(key)
            field_boost = 1.0 if source_field == "job_description" else 0.9
            mentions.append(
                {
                    "job_id": str(record.get("job_id") or ""),
                    "job_title": clean_text(record.get("job_title")),
                    "source_type": clean_text(record.get("source_type")),
                    "source_name": clean_text(record.get("source_name")),
                    "raw_skill": alias.raw_skill,
                    "normalized_skill": alias.normalized_skill,
                    "category": alias.category,
                    "span_text": sentence[match.start() : match.end()],
                    "span_start": match.start(),
                    "span_end": match.end(),
                    "skillspan_label": "knowledge",
                    "skill_type": skill_type_for_sentence(sentence),
                    "evidence_sentence": truncate_evidence(sentence),
                    "evidence_field": source_field,
                    "confidence": round(min(alias.confidence * field_boost, 1.0), 4),
                    "match_method": "dictionary",
                }
            )
    return mentions


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize(records: list[dict[str, Any]], mentions: list[dict[str, Any]]) -> dict[str, Any]:
    jobs_with_skills = {item["job_id"] for item in mentions}
    skill_counts = Counter(item["normalized_skill"] for item in mentions)
    category_counts = Counter(item["category"] for item in mentions)
    source_type_counts = Counter(item.get("source_type", "") for item in mentions)
    jobs_by_source = Counter(clean_text(record.get("source_type")) for record in records)
    with_skills_by_source: dict[str, set[str]] = defaultdict(set)
    for item in mentions:
        with_skills_by_source[item.get("source_type", "")].add(item["job_id"])

    coverage_by_source = {}
    for source_type, total in jobs_by_source.items():
        covered = len(with_skills_by_source.get(source_type, set()))
        coverage_by_source[source_type or "unknown"] = {
            "jobs": total,
            "jobs_with_skills": covered,
            "coverage": round(covered / total, 4) if total else 0.0,
        }

    return {
        "input_jobs": len(records),
        "jobs_with_skills": len(jobs_with_skills),
        "jobs_without_skills": len(records) - len(jobs_with_skills),
        "job_skill_coverage": round(len(jobs_with_skills) / len(records), 4) if records else 0.0,
        "skill_mentions": len(mentions),
        "unique_normalized_skills": len(skill_counts),
        "top_skills": skill_counts.most_common(50),
        "category_counts": dict(category_counts),
        "mentions_by_source_type": dict(source_type_counts),
        "coverage_by_source_type": coverage_by_source,
        "method": {
            "extractor": "dictionary_sentence_evidence_v1",
            "notes": [
                "Deterministic dictionary matching; no LLM is called.",
                "Evidence is the matched job title, tag string, or JD sentence.",
                "Each mention keeps character-level span offsets in its evidence sentence, following the SkillSpan-style span annotation idea.",
                "Technical terms are exported as skillspan_label=knowledge because this baseline focuses on tools, languages, frameworks, and domain knowledge rather than soft-skill phrases.",
                "Skill type is marked preferred when the evidence contains priority markers such as 优先 or 加分; otherwise required.",
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--aliases-json", type=Path, default=DEFAULT_ALIAS_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="Optional debug limit for input jobs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    aliases = dedupe_aliases([*DEFAULT_SKILL_ALIASES, *load_existing_combo_aliases(args.aliases_json)])
    records = []
    for index, record in enumerate(read_jsonl(args.input), start=1):
        records.append(record)
        if args.limit and index >= args.limit:
            break

    mentions: list[dict[str, Any]] = []
    for record in records:
        mentions.extend(extract_mentions(record, aliases))

    output_dir = args.output_dir
    alias_path = output_dir / "skill_alias_table.csv"
    mentions_jsonl_path = output_dir / "job_skill_mentions.jsonl"
    mentions_csv_path = output_dir / "job_skill_mentions.csv"
    report_path = output_dir / "job_skill_extract_report.json"

    write_alias_table(alias_path, aliases)
    write_jsonl(mentions_jsonl_path, mentions)
    write_csv(
        mentions_csv_path,
        mentions,
        [
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
        ],
    )
    report = summarize(records, mentions)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Input jobs: {report['input_jobs']}")
    print(f"Jobs with skills: {report['jobs_with_skills']}")
    print(f"Skill mentions: {report['skill_mentions']}")
    print(f"Unique normalized skills: {report['unique_normalized_skills']}")
    print(f"Alias table: {alias_path}")
    print(f"Mentions JSONL: {mentions_jsonl_path}")
    print(f"Mentions CSV: {mentions_csv_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
