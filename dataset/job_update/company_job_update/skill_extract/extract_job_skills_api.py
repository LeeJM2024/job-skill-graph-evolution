"""Extract JD skill mentions and leave final normalization to a later layer.

Default behavior still calls the configured LLM API. The broad extraction
dictionary is used for high-recall literal matching and prompt hints. Pass
`--no-api` only when you explicitly want dictionary-only extraction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DATASET_DIR = Path(__file__).resolve().parents[1]
SKILL_EXTRACT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = DATASET_DIR / "cleaned" / "all_jobs_23714_normalized.jsonl"
DEFAULT_EXTRACTION_DICTIONARY = SKILL_EXTRACT_DIR / "\u6cdb\u62bd\u53d6\u7ea7\u8bcd\u5178.csv"
DEFAULT_GOLD = DEFAULT_EXTRACTION_DICTIONARY
DEFAULT_OUTPUT_DIR = SKILL_EXTRACT_DIR / "output"
DEFAULT_CACHE = SKILL_EXTRACT_DIR / "cache" / "job_skill_extract_api_cache.jsonl"
PROMPT_VERSION = "job_skill_extraction_v3_2026_07_17_split_extract_normalize"

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
    "skill_keyword",
    "dictionary_skill_keyword",
    "normalized_skill_candidate",
    "kg_display_skill_candidate",
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
    "skill_keyword",
    "dictionary_skill_keyword",
    "normalized_skill_candidate",
    "kg_display_skill_candidate",
    "skill_type",
    "mention_count",
    "max_confidence",
    "evidence_count",
    "evidence_sentences",
    "evidence_fields",
    "span_texts",
    "match_methods",
]

TECH_ACTION_WORDS = (
    "\u5f00\u53d1",
    "\u8bbe\u8ba1",
    "\u5b9e\u73b0",
    "\u642d\u5efa",
    "\u6784\u5efa",
    "\u8bad\u7ec3",
    "\u63a8\u7406",
    "\u90e8\u7f72",
    "\u8c03\u4f18",
    "\u4f18\u5316",
    "\u6cbb\u7406",
    "\u6d4b\u8bd5",
    "\u8fd0\u7ef4",
    "\u5206\u6790",
    "\u5efa\u6a21",
    "\u7f16\u6392",
    "\u96c6\u6210",
    "\u7814\u53d1",
    "\u5de5\u7a0b\u5316",
)

BROAD_NON_SKILL_PATTERNS = [
    re.compile("\u4e1a\u52a1|\u4ea7\u54c1|\u9879\u76ee|\u5ba2\u6237|\u7528\u6237|\u8fd0\u8425|\u8425\u9500|\u9500\u552e|\u8d22\u52a1|\u8ba2\u5355|\u652f\u4ed8|\u4ea4\u6613|\u5ba2\u670d"),
    re.compile("\u613f\u666f|\u804c\u8d23|\u65b9\u5411|\u7ecf\u9a8c|\u4f18\u5148|\u719f\u6089|\u4e86\u89e3|\u610f\u8bc6|\u80fd\u529b$|\u601d\u7ef4$"),
]

SYSTEM_RULES = """
You are a JD skill extraction engine. Do extraction only; do not perform final
normalization.

Extract only content that can be used as resume skills, technical capabilities,
or engineering capabilities. Do not extract business objects, product scenarios,
industry directions, job visions, vague responsibilities, or skills inferred
only from common sense.

`span_text` must be a continuous substring from the original JD sentence. Use
the smallest complete evidence span. Output `skill_keyword` as the extracted
candidate skill. Do not output `normalized_skill`.

If text only lists scenarios such as search, recommendation, customer service,
office assistant, or marketing use cases without technical actions such as
develop, design, train, deploy, optimize, build, evaluate, or operate, do not
extract the scenario word as a skill.

Return only valid JSON:
{"mentions":[{"sentence_id":"...","span_text":"...","skill_keyword":"...","skill_type":"required|preferred","confidence":0.0,"reason":"..."}]}
""".strip()

CATEGORY_EXTRACTION_RULES = """
How to use the dictionary in this prompt:
1. Treat the dictionary as the current project boundary for "what counts as a
   skill", not as a closed vocabulary. If the JD clearly mentions a new
   technology outside the dictionary, still extract it as `skill_keyword`.
2. The dictionary is grouped by KG display categories. Use those groups to judge
   whether a phrase is a technical skill family: AI/model engineering, big-model
   training and inference, programming languages, software development, data
   engineering, cloud/ops, hardware/chips, security, algorithms/math, computer
   vision/graphics, audio/video, communication/networking, testing, robotics,
   simulation, industrial/IoT, and knowledge graph.
3. Do not collapse or rewrite aliases. For example, if the sentence says Spark,
   output Spark; if it says LLM, output LLM; if it says Agent framework, output
   the original span or closest extracted keyword. The normalization layer will
   decide whether these become data engineering, LLM, agent, etc.
4. Prefer explicit technologies, frameworks, languages, methods, platforms,
   tools, algorithms, engineering capabilities, or measurable technical work.
   Avoid pure business nouns, product names without technical action, domain
   scenarios, and vague capabilities.
5. For ambiguous words such as search, recommendation, training, inference,
   deployment, security, data, platform, or testing, extract only when the
   sentence shows technical work such as developing, designing, implementing,
   training, deploying, optimizing, operating, evaluating, debugging, or building
   systems.
6. Keep evidence local. Every extracted span must appear in the same sentence
   and must support the skill by itself or with nearby technical action words.
""".strip()

BOUNDARY_RULES = """
Important boundary rules kept from the old API prompt, rewritten for extraction
only:
1. Big-model terms: extract explicit terms such as LLM, large language model,
   foundation model, prompt, system prompt, few-shot prompt, agent,
   multi-agent, context, KV Cache, memory, SFT, RLHF, DPO, GRPO, pretraining,
   post-training, model alignment, model quantization, and model compression
   when they appear as technical requirements. Output the original evidence
   phrase; do not normalize the name.
2. Training and inference: extract training or inference only in model,
   deployment, serving, engine, performance, or AI-system contexts. Do not
   extract ordinary employee training, logical reasoning, reasoning ability, or
   reasoning summaries as model skills.
3. Model serving and AI infrastructure: extract model deployment, inference
   serving, MaaS, model API, AI platform, AI engineering platform, training or
   inference cluster, model compiler, runtime optimization, IR rewrite, CodeGen,
   toolchain, GPU/RDMA/storage resource scheduling, and similar AI-system
   foundation work only when the sentence is about model/AI systems, not normal
   software release work.
4. Data skills: extract Spark, Flink, Hadoop, ETL, data cleaning, data pipeline,
   data governance, feature extraction, data warehouse, database optimization,
   metadata, sample construction, and training data production when they are
   technical work. Do not extract user data, business data, or plain storage as
   skills without data-engineering context.
5. Search/recommendation/workflow: extract RAG, vector retrieval, full-text
   search, recall, rerank, ranking, recommendation model, CTR, CVR, workflow,
   planning, reflection, tool calling, orchestration, and multi-step decision
   only when they are design/development/optimization skills, not product
   examples.
6. Frontend/backend/client/server: extract frontend, backend, server-side,
   client, iOS, Android, cross-platform, microservices, API gateway, SDK, and
   related engineering only when the sentence gives engineering evidence. Do
   not infer backend from a full-stack job title alone; compiler backend CodeGen
   is not backend development.
7. Hardware/HPC: extract GPU, CUDA, Triton, NPU, Ascend, NVLink, NVSwitch,
   InfiniBand, kernel/operator performance, latency, throughput, MFU, profiling,
   acceleration, chip, ASIC, BSP, BMC, DSP, driver, embedded system, and hardware
   toolchain when explicit. Do not rewrite profiler/tool names into GPU.
8. Security: distinguish general security, big-model/content safety, RAG safety,
   red team, hallucination governance, agent sandbox, plugin/credential/local
   execution security, reverse engineering, anti-crawler, cryptography, and
   vulnerability analysis when explicit.
9. Multimedia/game/graphics/robotics: extract UE/Unity/game engine/rendering,
   Shader, Blender, VLM, multimodal, ASR, TTS, audio processing, SLAM, pose
   estimation, autonomous driving, robotics, simulation, CAD/CAE, and industrial
   control only when they are technical requirements.
10. Compound mentions: if one phrase contains multiple explicit skills, return
   multiple mentions with the shortest valid spans, e.g. "C/C++ and Python"
   should emit C/C++ or C++ plus Python according to the actual text evidence.
""".strip()


@dataclass(frozen=True, slots=True)
class SkillDictionaryEntry:
    skill_keyword: str
    normalized_skill: str
    kg_display_skill: str


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split()).strip()


def load_env_file(path: Path | None = None) -> None:
    if path is not None:
        env_path = path
    else:
        candidates = (
            DATASET_DIR / ".env",
            DATASET_DIR.parent / ".env",
            DATASET_DIR.parents[1] / ".env",
        )
        env_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
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


def split_sentences(text: str) -> list[str]:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"[\n\u3002\uff01\uff1f\uff1b;]+", text)
    return [part.strip(" \t:-\u2014\uff0c,\u3001)") for part in parts if part.strip()]


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


def is_ascii_keyword(keyword: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_+#. /-]+", keyword))


def keyword_pattern(keyword: str) -> re.Pattern[str] | None:
    keyword = clean_text(keyword)
    if not keyword:
        return None
    if is_ascii_keyword(keyword):
        escaped = re.escape(keyword)
        return re.compile(rf"(?<![A-Za-z0-9_+#.-]){escaped}(?![A-Za-z0-9_+#.-])", re.IGNORECASE)
    if len(keyword) == 1:
        return None
    return re.compile(re.escape(keyword), re.IGNORECASE)


def looks_like_broad_business_phrase(keyword: str) -> bool:
    value = clean_text(keyword)
    if not value:
        return True
    return any(pattern.search(value) for pattern in BROAD_NON_SKILL_PATTERNS)


def has_technical_context(sentence: str, start: int, end: int) -> bool:
    window = sentence[max(0, start - 18) : min(len(sentence), end + 18)]
    if any(word in window for word in TECH_ACTION_WORDS):
        return True
    return bool(re.search(r"[A-Za-z0-9+#.]", sentence[start:end]))


def should_keep_literal_match(entry: SkillDictionaryEntry, sentence: str, start: int, end: int) -> bool:
    if not looks_like_broad_business_phrase(entry.skill_keyword):
        return True
    return has_technical_context(sentence, start, end)


def load_extraction_dictionary(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Skill extraction dictionary not found: {path}")

    entries: list[SkillDictionaryEntry] = []
    by_keyword: dict[str, SkillDictionaryEntry] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"skill_keyword", "normalized_skill", "kg_display_skill"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        for row in reader:
            keyword = clean_text(row.get("skill_keyword"))
            if not keyword:
                continue
            entry = SkillDictionaryEntry(
                skill_keyword=keyword,
                normalized_skill=clean_text(row.get("normalized_skill")),
                kg_display_skill=clean_text(row.get("kg_display_skill")),
            )
            key = keyword.casefold()
            if key in by_keyword:
                continue
            by_keyword[key] = entry
            entries.append(entry)

    pattern_entries: list[tuple[re.Pattern[str], SkillDictionaryEntry]] = []
    for entry in sorted(entries, key=lambda item: (len(item.skill_keyword), item.skill_keyword.casefold()), reverse=True):
        pattern = keyword_pattern(entry.skill_keyword)
        if pattern is not None:
            pattern_entries.append((pattern, entry))

    digest_payload = [
        {
            "skill_keyword": entry.skill_keyword,
            "normalized_skill": entry.normalized_skill,
            "kg_display_skill": entry.kg_display_skill,
        }
        for entry in entries
    ]
    digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {
        "path": str(path),
        "digest": digest,
        "skills": digest_payload,
        "entries": entries,
        "by_keyword": by_keyword,
        "pattern_entries": pattern_entries,
    }


def load_gold_ontology(path: Path, max_examples: int = 50) -> dict[str, Any]:
    del max_examples
    return load_extraction_dictionary(path)


def build_semantic_gold_rules(*_: Any, **__: Any) -> list[dict[str, Any]]:
    return []


def make_candidate_fields(entry: SkillDictionaryEntry | None) -> dict[str, str]:
    if not entry:
        return {
            "dictionary_skill_keyword": "",
            "normalized_skill_candidate": "",
            "kg_display_skill_candidate": "",
        }
    return {
        "dictionary_skill_keyword": entry.skill_keyword,
        "normalized_skill_candidate": entry.normalized_skill,
        "kg_display_skill_candidate": entry.kg_display_skill,
    }


def build_dictionary_mentions(
    units: Iterable[dict[str, Any]],
    extraction_dictionary: dict[str, Any],
) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for unit in units:
        sentence_id = clean_text(unit.get("sentence_id"))
        sentence = clean_text(unit.get("text"))
        if not sentence_id or not sentence:
            continue
        occupied: list[tuple[int, int]] = []
        for pattern, entry in extraction_dictionary.get("pattern_entries", []):
            for match in pattern.finditer(sentence):
                start, end = match.span()
                if any(max(start, old_start) < min(end, old_end) for old_start, old_end in occupied):
                    continue
                if not should_keep_literal_match(entry, sentence, start, end):
                    continue
                occupied.append((start, end))
                mentions.append(
                    {
                        "sentence_id": sentence_id,
                        "span_text": match.group(0),
                        "skill_keyword": entry.skill_keyword,
                        **make_candidate_fields(entry),
                        "skill_type": "required",
                        "confidence": 1.0,
                        "reason": "dictionary_literal_match",
                        "match_method": "dictionary_literal",
                    }
                )
    return mentions


def dictionary_hints_for_units(
    extraction_dictionary: dict[str, Any],
    units: Iterable[dict[str, Any]],
    max_hints: int = 160,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    hints: list[dict[str, str]] = []
    for mention in build_dictionary_mentions(units, extraction_dictionary):
        key = mention["dictionary_skill_keyword"].casefold()
        if key in seen:
            continue
        seen.add(key)
        hints.append(
            {
                "skill_keyword": mention["dictionary_skill_keyword"],
                "kg_display_skill": mention["kg_display_skill_candidate"],
            }
        )
        if len(hints) >= max_hints:
            break
    return hints


def dictionary_category_summary(
    extraction_dictionary: dict[str, Any],
    max_categories: int = 28,
    examples_per_category: int = 14,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    seen_by_category: dict[str, set[str]] = {}
    for item in extraction_dictionary.get("skills", []):
        category = clean_text(item.get("kg_display_skill")) or "uncategorized"
        keyword = clean_text(item.get("skill_keyword"))
        if not keyword:
            continue
        grouped.setdefault(category, [])
        seen_by_category.setdefault(category, set())
        if keyword.casefold() not in seen_by_category[category]:
            seen_by_category[category].add(keyword.casefold())
            grouped[category].append(keyword)

    summary: list[dict[str, Any]] = []
    for category, keywords in sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True):
        summary.append(
            {
                "kg_display_skill": category,
                "keyword_count": len(keywords),
                "example_skill_keywords": keywords[:examples_per_category],
            }
        )
        if len(summary) >= max_categories:
            break
    return summary


def link_dictionary_entry(
    skill_keyword: str,
    span_text: str,
    extraction_dictionary: dict[str, Any],
) -> SkillDictionaryEntry | None:
    by_keyword: dict[str, SkillDictionaryEntry] = extraction_dictionary.get("by_keyword", {})
    for value in (skill_keyword, span_text):
        key = clean_text(value).casefold()
        if key in by_keyword:
            return by_keyword[key]

    span = clean_text(span_text)
    if not span:
        return None
    matches = []
    for pattern, entry in extraction_dictionary.get("pattern_entries", []):
        if pattern.search(span):
            matches.append(entry)
            if len(matches) > 1:
                break
    return matches[0] if len(matches) == 1 else None


def canonicalize_api_mention(
    mention: dict[str, Any],
    sentence: str,
    extraction_dictionary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del sentence
    result = dict(mention)
    span = clean_text(result.get("span_text"))
    skill_keyword = clean_text(result.get("skill_keyword")) or span
    result["span_text"] = span
    result["skill_keyword"] = skill_keyword
    entry = link_dictionary_entry(skill_keyword, span, extraction_dictionary) if extraction_dictionary else None
    result.update(make_candidate_fields(entry))
    result.setdefault("match_method", "llm_api_extraction")
    return result


def build_system_prompt(ontology: dict[str, Any], max_ontology_skills: int) -> str:
    compact_keywords = [
        {
            "skill_keyword": item["skill_keyword"],
            "kg_display_skill": item["kg_display_skill"],
        }
        for item in ontology.get("skills", [])[:max_ontology_skills]
    ]
    category_summary = dictionary_category_summary(ontology)
    return (
        SYSTEM_RULES
        + "\n\n"
        + CATEGORY_EXTRACTION_RULES
        + "\n\n"
        + BOUNDARY_RULES
        + "\n\nDictionary category summary. Use this as the main extraction boundary:\n"
        + json.dumps(category_summary, ensure_ascii=False, separators=(",", ":"))
        + "\n\nRepresentative broad extraction dictionary keywords:\n"
        + json.dumps(compact_keywords, ensure_ascii=False, separators=(",", ":"))
        + "\n\nThe user payload may include dictionary_hints from local literal matching. "
        + "Use them as high-confidence hints, but do not blindly copy them if the sentence is only a business scenario. "
        + "Also add new JD skills outside the dictionary when the sentence clearly supports them. "
        + "Return JSON only."
    )


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
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            ConnectionResetError,
            http.client.HTTPException,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"API request failed after {retries + 1} attempts: {last_error}")


def mention_key(mention: dict[str, Any]) -> tuple[str, str, str]:
    return (
        clean_text(mention.get("sentence_id")),
        clean_text(mention.get("span_text")).casefold(),
        clean_text(mention.get("skill_keyword")).casefold(),
    )


def dictionary_from_literal_skills(literal_skills: Iterable[str]) -> dict[str, Any]:
    entries = [
        SkillDictionaryEntry(skill_keyword=clean_text(skill), normalized_skill="", kg_display_skill="")
        for skill in literal_skills
        if clean_text(skill)
    ]
    by_keyword = {entry.skill_keyword.casefold(): entry for entry in entries}
    pattern_entries = []
    for entry in sorted(entries, key=lambda item: len(item.skill_keyword), reverse=True):
        pattern = keyword_pattern(entry.skill_keyword)
        if pattern:
            pattern_entries.append((pattern, entry))
    return {
        "path": "",
        "digest": "literal",
        "skills": [{"skill_keyword": entry.skill_keyword, "normalized_skill": "", "kg_display_skill": ""} for entry in entries],
        "entries": entries,
        "by_keyword": by_keyword,
        "pattern_entries": pattern_entries,
    }


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
    extraction_dictionary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sentence_by_id = {
        str(unit.get("sentence_id", "")): clean_text(unit.get("text"))
        for unit in user_payload.get("sentences", [])
    }
    if extraction_dictionary is None:
        extraction_dictionary = dictionary_from_literal_skills(literal_skills)

    payload = dict(user_payload)
    payload["dictionary_hints"] = dictionary_hints_for_units(
        extraction_dictionary,
        payload.get("sentences", []),
    )
    first_result = call_chat_api(
        api_key=api_key,
        model=model,
        base_url=base_url,
        system_prompt=system_prompt,
        user_payload=payload,
        timeout=timeout,
        retries=retries,
        temperature=temperature,
    )

    llm_mentions = [
        canonicalize_api_mention(mention, sentence_by_id.get(str(mention.get("sentence_id", "")), ""), extraction_dictionary)
        for mention in first_result.get("mentions", [])
    ]
    llm_mentions = [mention for mention in llm_mentions if clean_text(mention.get("span_text"))]
    dictionary_mentions = build_dictionary_mentions(payload.get("sentences", []), extraction_dictionary)

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for mention in [*dictionary_mentions, *llm_mentions]:
        key = mention_key(mention)
        if key in seen:
            continue
        seen.add(key)
        merged.append(mention)

    return {
        "mentions": merged,
        "pipeline_stats": {
            "llm_first_pass_mentions": len(llm_mentions),
            "dictionary_literal_mentions": len(dictionary_mentions),
            "final_deduped_mentions": len(merged),
            "net_new_mentions": len(merged) - len(llm_mentions),
        },
        "dictionary_added_mentions": dictionary_mentions,
    }


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
    span = clean_text(mention.get("span_text"))
    if not span:
        return None, "empty span_text"
    start = sentence.find(span)
    if start < 0:
        return None, f"span not found: {span}"
    end = start + len(span)

    skill_keyword = clean_text(mention.get("skill_keyword")) or span
    skill_type = clean_text(mention.get("skill_type")) or "required"
    if skill_type not in {"required", "preferred"}:
        skill_type = "required"
    try:
        confidence = float(mention.get("confidence") or 0.80)
    except (TypeError, ValueError):
        confidence = 0.80
    confidence = max(0.0, min(1.0, confidence))

    return (
        {
            "job_id": clean_text(job.get("job_id")),
            "job_title": clean_text(job.get("job_title")),
            "source_type": clean_text(job.get("source_type")),
            "source_name": clean_text(job.get("source_name")) or clean_text(job.get("source")),
            "skill_keyword": skill_keyword,
            "dictionary_skill_keyword": clean_text(mention.get("dictionary_skill_keyword")),
            "normalized_skill_candidate": clean_text(mention.get("normalized_skill_candidate")),
            "kg_display_skill_candidate": clean_text(mention.get("kg_display_skill_candidate")),
            "span_text": span,
            "span_start": start,
            "span_end": end,
            "skillspan_label": "knowledge",
            "skill_type": skill_type,
            "evidence_sentence": sentence,
            "evidence_field": unit["evidence_field"],
            "confidence": confidence,
            "match_method": clean_text(mention.get("match_method")) or "llm_api_extraction",
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
            row["skill_keyword"].casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def aggregate_job_skills(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        job_id = clean_text(row.get("job_id"))
        skill_keyword = clean_text(row.get("skill_keyword"))
        if not job_id or not skill_keyword:
            continue
        key = (job_id, skill_keyword.casefold())
        item = grouped.setdefault(
            key,
            {
                "job_id": job_id,
                "job_title": clean_text(row.get("job_title")),
                "source_type": clean_text(row.get("source_type")),
                "source_name": clean_text(row.get("source_name")),
                "skill_keyword": skill_keyword,
                "dictionary_skill_keyword": clean_text(row.get("dictionary_skill_keyword")),
                "normalized_skill_candidate": clean_text(row.get("normalized_skill_candidate")),
                "kg_display_skill_candidate": clean_text(row.get("kg_display_skill_candidate")),
                "skill_types": set(),
                "mentions": [],
                "evidence_seen": set(),
            },
        )
        item["skill_types"].add(clean_text(row.get("skill_type")) or "required")
        if not item["dictionary_skill_keyword"] and clean_text(row.get("dictionary_skill_keyword")):
            item["dictionary_skill_keyword"] = clean_text(row.get("dictionary_skill_keyword"))
            item["normalized_skill_candidate"] = clean_text(row.get("normalized_skill_candidate"))
            item["kg_display_skill_candidate"] = clean_text(row.get("kg_display_skill_candidate"))

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
                "skill_keyword": item["skill_keyword"],
                "dictionary_skill_keyword": item["dictionary_skill_keyword"],
                "normalized_skill_candidate": item["normalized_skill_candidate"],
                "kg_display_skill_candidate": item["kg_display_skill_candidate"],
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
    return sorted(aggregated, key=lambda item: (item["job_id"], item["skill_keyword"].casefold()))


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
        "dictionary_digest": ontology_digest,
        "units": units,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    parser = argparse.ArgumentParser(description="Extract JD skill candidates; final normalization is downstream.")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="deepseek")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input JD jsonl/csv path.")
    parser.add_argument("--jd-text", default="", help="Direct JD text. If set, --input is ignored.")
    parser.add_argument("--jd-title", default="\u65b0\u62db\u8058\u542f\u4e8b", help="Job title used with --jd-text.")
    parser.add_argument("--single-job-id", default="manual_jd_0001", help="Job id used with --jd-text.")
    parser.add_argument(
        "--dictionary",
        "--gold",
        dest="dictionary",
        type=Path,
        default=DEFAULT_EXTRACTION_DICTIONARY,
        help="Broad extraction dictionary CSV. --gold is kept as a deprecated alias.",
    )
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
    parser.add_argument("--max-gold-examples", type=int, default=50, help="Deprecated; kept for compatibility.")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--no-api", action="store_true", help="Only use local dictionary matching; do not call the LLM API.")
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

    extraction_dictionary = load_extraction_dictionary(args.dictionary)
    dictionary_digest = extraction_dictionary["digest"]
    system_prompt = build_system_prompt(extraction_dictionary, args.max_ontology_skills)
    cache = load_cache(args.cache)

    if args.dry_run:
        units = sum(len(build_units(job, args.max_sentences_per_job)) for job in jobs)
        print(
            json.dumps(
                {
                    "jobs": len(jobs),
                    "sentence_units": units,
                    "dictionary": str(args.dictionary),
                    "dictionary_keywords": len(extraction_dictionary["skills"]),
                    "dictionary_digest": dictionary_digest,
                    "provider": provider_config["provider"],
                    "model": provider_config["model"],
                    "base_url": provider_config["base_url"],
                    "api_key_env": provider_config["api_key_env"],
                    "prompt_chars": len(system_prompt),
                    "cache_entries": len(cache),
                    "no_api": args.no_api,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    api_key = os.getenv(provider_config["api_key_env"])
    if not args.no_api and not api_key:
        raise SystemExit(f"Missing API key. Set ${provider_config['api_key_env']} first, or use --no-api.")

    mentions: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    stats: Counter[str] = Counter()

    for job in jobs:
        units = build_units(job, args.max_sentences_per_job)
        if not units:
            continue
        payload = {
            "job": {
                "job_id": clean_text(job.get("job_id")),
                "job_title": clean_text(job.get("job_title")),
                "source_type": clean_text(job.get("source_type")),
                "source_name": clean_text(job.get("source_name")) or clean_text(job.get("source")),
            },
            "sentences": units,
        }

        if args.no_api:
            dict_mentions = build_dictionary_mentions(units, extraction_dictionary)
            result = {
                "mentions": dict_mentions,
                "pipeline_stats": {
                    "llm_first_pass_mentions": 0,
                    "dictionary_literal_mentions": len(dict_mentions),
                    "final_deduped_mentions": len(dict_mentions),
                    "net_new_mentions": len(dict_mentions),
                },
            }
            stats["dictionary_only_jobs"] += 1
        else:
            key = cache_key(provider_config["model"], provider_config["base_url"], units, dictionary_digest)
            if key in cache:
                result = cache[key]["result"]
                stats["cache_hit"] += 1
            else:
                result = call_skill_extraction(
                    api_key=api_key or "",
                    model=provider_config["model"],
                    base_url=provider_config["base_url"],
                    system_prompt=system_prompt,
                    user_payload=payload,
                    timeout=args.timeout,
                    retries=args.retries,
                    temperature=args.temperature,
                    extraction_dictionary=extraction_dictionary,
                )
                append_cache(
                    args.cache,
                    {
                        "cache_key": key,
                        "provider": provider_config["provider"],
                        "model": provider_config["model"],
                        "base_url": provider_config["base_url"],
                        "dictionary": str(args.dictionary),
                        "dictionary_digest": dictionary_digest,
                        "result": result,
                    },
                )
                stats["api_call"] += 1

        for stat_name, stat_value in result.get("pipeline_stats", {}).items():
            stats[f"pipeline_{stat_name}"] += int(stat_value or 0)

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
        "dictionary": str(args.dictionary),
        "provider": provider_config["provider"],
        "model": provider_config["model"],
        "base_url": provider_config["base_url"],
        "prompt_version": PROMPT_VERSION,
        "jobs": len(jobs),
        "mentions": len(mentions),
        "job_skill_candidate_pairs": len(job_skills),
        "jobs_with_skills": len({item["job_id"] for item in job_skills}),
        "stats": dict(stats),
        "outputs": {
            "mentions_csv": str(output_csv),
            "mentions_jsonl": str(output_jsonl),
            "by_job_csv": str(job_skills_csv),
            "by_job_jsonl": str(job_skills_jsonl),
        },
        "rejected_samples": rejects[:50],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
