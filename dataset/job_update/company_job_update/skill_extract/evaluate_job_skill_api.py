"""Evaluate the API skill extractor against reviewed gold spans.

The metric is strict mention-level matching:
  (sentence_id, span_start, span_end, normalized_skill)

This is harsher than just checking skill names, but it tells us whether the API
both found the right text span and normalized it to the right project skill.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import extract_job_skills_api as api  # noqa: E402


DATASET_DIR = Path(__file__).resolve().parents[1]
SKILL_EXTRACT_DIR = Path(__file__).resolve().parent
DEFAULT_GOLD = SKILL_EXTRACT_DIR / "job_skill_gold" / "job_skill_gold_clean.csv"
DEFAULT_OUTPUT_DIR = SKILL_EXTRACT_DIR / "api_eval"


def split_name(sentence_id: str) -> str:
    value = int(hashlib.md5(sentence_id.encode("utf-8")).hexdigest()[:8], 16) % 10
    if value < 8:
        return "train"
    if value == 8:
        return "dev"
    return "test"


def read_gold(path: Path) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = row["sentence_id"]
            grouped.setdefault(
                sid,
                {
                    "sentence_id": sid,
                    "job_id": row["job_id"],
                    "job_title": row["job_title"],
                    "source_type": row["source_type"],
                    "source_name": row["source_name"],
                    "evidence_field": row["evidence_field"],
                    "text": row["text"],
                    "mentions": [],
                },
            )
            grouped[sid]["mentions"].append(
                {
                    "span_start": int(row["span_start"]),
                    "span_end": int(row["span_end"]),
                    "span_text": row["span_text"],
                    "normalized_skill": row["normalized_skill"],
                    "category": row["category"],
                    "skill_type": row["skill_type"],
                }
            )
    return grouped


def build_eval_units(grouped: dict[str, dict[str, Any]], split: str, limit: int, offset: int = 0) -> list[dict[str, Any]]:
    items = [item for sid, item in grouped.items() if split_name(sid) == split]
    items.sort(key=lambda value: value["sentence_id"])
    if offset > 0:
        items = items[offset:]
    if limit > 0:
        items = items[:limit]
    return items


def build_ontology_from_split(gold_path: Path, excluded_sentence_ids: set[str], max_examples: int) -> dict[str, Any]:
    skill_counts: Counter[str] = Counter()
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples_by_skill: dict[str, list[dict[str, str]]] = defaultdict(list)
    gold_rows: list[dict[str, Any]] = []
    with gold_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["sentence_id"] in excluded_sentence_ids or split_name(row["sentence_id"]) != "train":
                continue
            skill = row["normalized_skill"]
            category = row["category"] or "未分类"
            skill_counts[skill] += 1
            category_counts[skill][category] += 1
            gold_rows.append(dict(row))
            if not examples_by_skill[skill]:
                examples_by_skill[skill].append(
                    {
                        "span_text": row["span_text"],
                        "normalized_skill": skill,
                        "category": category,
                        "sentence": row["text"][:160],
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
        "semantic_rules": api.build_semantic_gold_rules(gold_rows),
    }


def make_payload(eval_units: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    units = [
        {
            "sentence_id": item["sentence_id"],
            "evidence_field": item["evidence_field"],
            "text": item["text"],
        }
        for item in eval_units
    ]
    unit_by_id = {unit["sentence_id"]: unit for unit in units}
    payload = {
        "job": {
            "job_id": "api_eval_batch",
            "job_title": "API技能抽取评测集",
            "source_type": "gold_eval",
            "source_name": "job_skill_gold_clean",
        },
        "sentences": units,
    }
    return payload, unit_by_id


def normalize_prediction(mention: dict[str, Any], unit_by_id: dict[str, dict[str, str]]) -> tuple[tuple[str, int, int, str] | None, str | None]:
    sid = str(mention.get("sentence_id", ""))
    unit = unit_by_id.get(sid)
    if not unit:
        return None, f"unknown sentence_id: {sid}"
    mention = api.canonicalize_api_mention(mention, unit["text"])
    span = api.clean_text(mention.get("span_text"))
    if not span:
        return None, "empty span_text"
    start = unit["text"].find(span)
    if start < 0:
        return None, f"span not found: {span}"
    skill = api.clean_text(mention.get("normalized_skill"))
    if not skill:
        return None, "empty normalized_skill"
    return (sid, start, start + len(span), skill), None


def normalize_skill_prediction(mention: dict[str, Any], unit_by_id: dict[str, dict[str, str]]) -> tuple[tuple[str, str] | None, str | None]:
    sid = str(mention.get("sentence_id", ""))
    unit = unit_by_id.get(sid)
    if not unit:
        return None, f"unknown sentence_id: {sid}"
    mention = api.canonicalize_api_mention(mention, unit["text"])
    skill = api.clean_text(mention.get("normalized_skill"))
    if not skill:
        return None, "empty normalized_skill"
    return (sid, skill), None


def metrics(gold: set[tuple[str, int, int, str]], pred: set[tuple[str, int, int, str]]) -> dict[str, Any]:
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def metrics_any(gold: set[tuple[Any, ...]], pred: set[tuple[Any, ...]]) -> dict[str, Any]:
    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate API skill extraction against gold clean data.")
    parser.add_argument("--provider", choices=sorted(api.PROVIDERS), default="deepseek")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--limit", type=int, default=50, help="Number of gold sentences to evaluate. Use 0 for all split.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many sentences within the selected split.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key-env", default=None)
    parser.add_argument("--max-ontology-skills", type=int, default=260)
    parser.add_argument("--max-gold-examples", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true", help="Only report split sizes; do not call API.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api.load_env_file()
    provider_config = api.resolve_provider_config(args)
    grouped = read_gold(args.gold)
    split_counts = Counter(split_name(sid) for sid in grouped)
    eval_units = build_eval_units(grouped, args.split, args.limit, args.offset)
    excluded = {item["sentence_id"] for item in eval_units}
    ontology = build_ontology_from_split(args.gold, excluded, args.max_gold_examples)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "gold_sentences": len(grouped),
                    "split_counts": dict(split_counts),
                    "eval_split": args.split,
                    "offset": args.offset,
                    "eval_sentences": len(eval_units),
                    "eval_gold_mentions": sum(len(item["mentions"]) for item in eval_units),
                    "ontology_skills": len(ontology["skills"]),
                    "ontology_examples": len(ontology["examples"]),
                    "semantic_rules": len(ontology.get("semantic_rules", [])),
                    "semantic_gold_examples": sum(
                        len(rule.get("gold_examples", [])) for rule in ontology.get("semantic_rules", [])
                    ),
                    "provider": provider_config["provider"],
                    "model": provider_config["model"],
                    "base_url": provider_config["base_url"],
                    "api_key_env": provider_config["api_key_env"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    api_key = os.getenv(provider_config["api_key_env"])
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${provider_config['api_key_env']} first.")

    payload, unit_by_id = make_payload(eval_units)
    prompt = api.build_system_prompt(ontology, args.max_ontology_skills)
    result = api.call_skill_extraction(
        api_key=api_key,
        model=provider_config["model"],
        base_url=provider_config["base_url"],
        system_prompt=prompt,
        user_payload=payload,
        timeout=args.timeout,
        retries=args.retries,
        temperature=args.temperature,
        literal_skills=(item["normalized_skill"] for item in ontology["skills"]),
    )

    gold_set: set[tuple[str, int, int, str]] = set()
    gold_skill_set: set[tuple[str, str]] = set()
    for item in eval_units:
        for mention in item["mentions"]:
            gold_set.add((item["sentence_id"], mention["span_start"], mention["span_end"], mention["normalized_skill"]))
            gold_skill_set.add((item["sentence_id"], mention["normalized_skill"]))

    pred_set: set[tuple[str, int, int, str]] = set()
    pred_skill_set: set[tuple[str, str]] = set()
    rejected = []
    skill_rejected = []
    for mention in result.get("mentions", []):
        skill_key, skill_error = normalize_skill_prediction(mention, unit_by_id)
        if skill_error:
            skill_rejected.append({"mention": mention, "error": skill_error})
        else:
            pred_skill_set.add(skill_key)
        key, error = normalize_prediction(mention, unit_by_id)
        if error:
            rejected.append({"mention": mention, "error": error})
            continue
        pred_set.add(key)

    exact = metrics(gold_set, pred_set)
    skill_exact = metrics_any(gold_skill_set, pred_skill_set)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prompt_version = getattr(api, "PROMPT_VERSION", "prompt_unknown")
    prefix = (
        f"job_skill_api_eval_{provider_config['provider']}_{prompt_version}_"
        f"{args.split}_offset{args.offset}_{len(eval_units)}"
    )
    report_path = args.output_dir / f"{prefix}_report.json"
    pred_path = args.output_dir / f"{prefix}_predictions.jsonl"
    diff_path = args.output_dir / f"{prefix}_diff.json"

    with pred_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for mention in result.get("mentions", []):
            sid = str(mention.get("sentence_id", ""))
            if sid in unit_by_id:
                mention = api.canonicalize_api_mention(mention, unit_by_id[sid]["text"])
            handle.write(json.dumps(mention, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")

    diff = {
        "false_positive": sorted(list(pred_set - gold_set))[:200],
        "false_negative": sorted(list(gold_set - pred_set))[:200],
        "skill_false_positive": sorted(list(pred_skill_set - gold_skill_set))[:200],
        "skill_false_negative": sorted(list(gold_skill_set - pred_skill_set))[:200],
        "rejected": rejected[:100],
        "skill_rejected": skill_rejected[:100],
    }
    diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "gold": str(args.gold),
        "split": args.split,
        "offset": args.offset,
        "eval_sentences": len(eval_units),
        "eval_gold_mentions": len(gold_set),
        "pred_mentions": len(pred_set),
        "eval_gold_sentence_skills": len(gold_skill_set),
        "pred_sentence_skills": len(pred_skill_set),
        "rejected_predictions": len(rejected),
        "skill_rejected_predictions": len(skill_rejected),
        "sentence_skill": skill_exact,
        "strict_span_skill": exact,
        "provider": provider_config["provider"],
        "model": provider_config["model"],
        "base_url": provider_config["base_url"],
        "prompt_version": prompt_version,
        "pipeline_stats": result.get("pipeline_stats", {}),
        "mandatory_added_mentions": result.get("mandatory_added_mentions", [])[:100],
        "outputs": {"report": str(report_path), "predictions": str(pred_path), "diff": str(diff_path)},
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
