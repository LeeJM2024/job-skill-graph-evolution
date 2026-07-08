"""Run BM25 Top200 retrieval, BGE-M3 reranking, and silver-label generation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
DATASET_DIR = SCRIPT_DIR.parent
REPO_ROOT = DATASET_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend-src"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.chinese_bm25_service import ChineseBM25Service  # noqa: E402


DEFAULT_RESUMES = DATASET_DIR / "annotations" / "pilot_resumes_30.jsonl"
DEFAULT_OUTPUT = DATASET_DIR / "retrieval" / "test_30"
DEFAULT_FAMILY_KEYWORDS = DATASET_DIR / "config" / "job_family_keywords.json"
DEFAULT_RESUME_MASTER = DATASET_DIR / "resume" / "synthetic_detailed_resumes.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_flat_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "resume_id",
        "target_job_family",
        "job_id",
        "job_title",
        "company_name",
        "location",
        "source_type",
        "bm25_rank",
        "bm25_score",
        "semantic_rank",
        "semantic_score",
        "silver_grade",
        "silver_score",
        "family_match",
        "skill_coverage",
        "matched_skills",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = dict(row)
            output["matched_skills"] = ";".join(row.get("matched_skills", []))
            writer.writerow(output)


def load_resume_skills(path: Path) -> dict[str, list[str]]:
    skills: dict[str, list[str]] = {}
    for record in read_jsonl(path):
        skills[record["resume_id"]] = record.get("skills_normalized", [])
    return skills


def compact_job(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": hit["job_id"],
        "job_title": hit.get("job_title", ""),
        "company_name": hit.get("company_name", ""),
        "location": hit.get("location", ""),
        "source_type": hit.get("source_type", ""),
        "tags": hit.get("tags", []),
        "job_description": hit.get("job_description", ""),
        "source_url": hit.get("source_url", ""),
        "bm25_rank": hit["rank"],
        "bm25_score": round(float(hit["score"]), 6),
    }


def build_job_text(job: dict[str, Any]) -> str:
    tags = job.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    return "。".join(
        part
        for part in [
            f"岗位名称：{job.get('job_title', '')}",
            f"单位：{job.get('company_name', '')}",
            f"地点：{job.get('location', '')}",
            f"标签：{'、'.join(tags)}" if tags else "",
            f"岗位职责与要求：{job.get('job_description', '')}",
        ]
        if part
    )


def run_bm25(
    resumes: list[dict[str, Any]],
    output_path: Path,
    es_url: str,
    index_name: str,
    top_k: int,
    source_type: str | None,
) -> dict[str, Any]:
    from elasticsearch import Elasticsearch

    client = Elasticsearch(es_url, request_timeout=120)
    if not client.ping():
        raise ConnectionError(f"Cannot connect to Elasticsearch: {es_url}")
    service = ChineseBM25Service(client, index_name=index_name)

    started = time.perf_counter()
    records = []
    latencies = []
    for index, resume in enumerate(resumes, start=1):
        result = service.search(
            query_text=resume["profile_text"],
            size=top_k,
            source_type=source_type,
            exclude_duplicates=True,
        )
        candidates = [compact_job(hit) for hit in result["hits"]]
        latencies.append(result["took_ms"])
        records.append(
            {
                "resume_id": resume["resume_id"],
                "target_job_family": resume["target_job_family"],
                "profile_text": resume["profile_text"],
                "retrieval": {
                    "index_name": index_name,
                    "source_type": source_type,
                    "requested_top_k": top_k,
                    "returned": len(candidates),
                    "total_hits": result["total"],
                    "took_ms": result["took_ms"],
                },
                "candidates": candidates,
            }
        )
        print(f"BM25 {index:02d}/{len(resumes)}: {resume['resume_id']} -> {len(candidates)}")

    write_jsonl(output_path, records)
    elapsed = time.perf_counter() - started
    return {
        "resume_count": len(records),
        "candidate_pairs": sum(len(item["candidates"]) for item in records),
        "wall_seconds": round(elapsed, 3),
        "latency_ms": summarize_numbers(latencies),
    }


def percentile(values: list[float], percent: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percent))


def summarize_numbers(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 4),
        "mean": round(sum(values) / len(values), 4),
        "p50": round(percentile(values, 50), 4),
        "p95": round(percentile(values, 95), 4),
        "max": round(max(values), 4),
    }


def encode_texts(
    texts: list[str],
    model_name: str,
    batch_size: int,
    max_length: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    started = time.perf_counter()
    model_source = model_name
    if not Path(model_name).exists():
        model_source = snapshot_download(repo_id=model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_source)
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModel.from_pretrained(model_source, torch_dtype=dtype)
    model.to(device)
    model.eval()

    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode():
            output = model(**encoded)
            embeddings = output.last_hidden_state[:, 0]
            embeddings = torch.nn.functional.normalize(embeddings.float(), p=2, dim=1)
        vectors.append(embeddings.cpu().numpy())
        del output, embeddings, encoded
        if device == "cuda":
            torch.cuda.empty_cache()
        done = min(start + batch_size, len(texts))
        print(f"BGE-M3 encoded {done}/{len(texts)}")

    matrix = np.vstack(vectors)
    return matrix, {
        "model_name": model_name,
        "model_source": str(model_source),
        "device": device,
        "dtype": str(dtype),
        "max_length": max_length,
        "batch_size": batch_size,
        "embedding_dimension": int(matrix.shape[1]),
        "encoded_texts": len(texts),
        "wall_seconds": round(time.perf_counter() - started, 3),
    }


def contains_term(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def family_match_score(
    family: str,
    job: dict[str, Any],
    family_keywords: dict[str, list[str]],
) -> tuple[float, list[str]]:
    title = job.get("job_title", "")
    description = job.get("job_description", "")
    terms = family_keywords.get(family, [])
    title_matches = [term for term in terms if contains_term(title, term)]
    description_matches = [term for term in terms if contains_term(description, term)]
    family_core = family.replace("工程师", "").replace("开发", "")
    if contains_term(title, family) or (family_core and contains_term(title, family_core)):
        return 1.0, sorted(set(title_matches + [family_core]))
    if title_matches:
        return 0.8, title_matches
    if description_matches:
        return 0.4, description_matches[:10]
    return 0.0, []


def skill_overlap(skills: list[str], job_text: str) -> tuple[float, list[str]]:
    if not skills:
        return 0.0, []
    matched = [skill for skill in skills if contains_term(job_text, skill)]
    return len(matched) / len(skills), matched


def silver_grade(
    silver_score: float,
    family_match: float,
    skill_coverage: float,
) -> int:
    if silver_score >= 0.75 and family_match >= 0.8:
        return 3
    if silver_score >= 0.55 and (family_match >= 0.4 or skill_coverage >= 0.2):
        return 2
    if silver_score >= 0.35:
        return 1
    return 0


def run_rerank_and_silver(
    bm25_path: Path,
    reranked_path: Path,
    silver_path: Path,
    flat_csv_path: Path,
    summary_path: Path,
    resume_master_path: Path,
    family_keywords_path: Path,
    model_name: str,
    batch_size: int,
    max_length: int,
) -> dict[str, Any]:
    bm25_records = read_jsonl(bm25_path)
    resume_skills = load_resume_skills(resume_master_path)
    family_keywords = json.loads(family_keywords_path.read_text(encoding="utf-8"))

    unique_jobs: dict[str, dict[str, Any]] = {}
    for record in bm25_records:
        for job in record["candidates"]:
            unique_jobs.setdefault(job["job_id"], job)

    resume_texts = [record["profile_text"] for record in bm25_records]
    job_ids = list(unique_jobs)
    job_texts = [build_job_text(unique_jobs[job_id]) for job_id in job_ids]
    all_texts = resume_texts + job_texts
    embeddings, model_stats = encode_texts(
        all_texts,
        model_name=model_name,
        batch_size=batch_size,
        max_length=max_length,
    )
    resume_vectors = embeddings[: len(resume_texts)]
    job_vectors = embeddings[len(resume_texts) :]
    job_vector_map = {job_id: job_vectors[index] for index, job_id in enumerate(job_ids)}

    reranked_records = []
    silver_records = []
    flat_rows = []
    rank_changes = []
    top10_overlaps = []
    semantic_scores = []
    grade_counts: Counter[int] = Counter()

    for resume_index, record in enumerate(bm25_records):
        candidates = []
        resume_vector = resume_vectors[resume_index]
        for job in record["candidates"]:
            candidate = dict(job)
            candidate["semantic_score"] = round(
                float(np.dot(resume_vector, job_vector_map[job["job_id"]])), 6
            )
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-item["semantic_score"], item["bm25_rank"]))

        bm25_top10 = {item["job_id"] for item in record["candidates"][:10]}
        semantic_top10 = {item["job_id"] for item in candidates[:10]}
        top10_overlaps.append(len(bm25_top10 & semantic_top10) / 10)

        skills = resume_skills.get(record["resume_id"], [])
        candidate_count = max(len(candidates), 1)
        for semantic_rank, candidate in enumerate(candidates, start=1):
            candidate["semantic_rank"] = semantic_rank
            rank_changes.append(abs(candidate["bm25_rank"] - semantic_rank))
            semantic_scores.append(candidate["semantic_score"])
            job_text = build_job_text(candidate)
            coverage, matched_skills = skill_overlap(skills, job_text)
            family_score, family_terms = family_match_score(
                record["target_job_family"], candidate, family_keywords
            )
            bm25_percentile = 1.0 - (candidate["bm25_rank"] - 1) / candidate_count
            semantic_percentile = 1.0 - (semantic_rank - 1) / candidate_count
            score = (
                0.45 * semantic_percentile
                + 0.20 * bm25_percentile
                + 0.20 * coverage
                + 0.15 * family_score
            )
            grade = silver_grade(score, family_score, coverage)
            grade_counts[grade] += 1
            candidate.update(
                {
                    "silver_score": round(score, 6),
                    "silver_grade": grade,
                    "family_match": family_score,
                    "family_match_terms": family_terms,
                    "skill_coverage": round(coverage, 6),
                    "matched_skills": matched_skills,
                }
            )
            silver_record = {
                "resume_id": record["resume_id"],
                "target_job_family": record["target_job_family"],
                **candidate,
                "silver_method": "bm25_bge_m3_family_skill_v1",
                "silver_is_gold": False,
            }
            silver_records.append(silver_record)
            flat_rows.append(silver_record)

        reranked_records.append(
            {
                "resume_id": record["resume_id"],
                "target_job_family": record["target_job_family"],
                "profile_text": record["profile_text"],
                "model": model_name,
                "candidates": candidates,
            }
        )

    summary = {
        "experiment": "30_resume_bm25_bge_m3_v1",
        "resume_count": len(bm25_records),
        "candidate_pairs": len(silver_records),
        "unique_candidate_jobs": len(unique_jobs),
        "bm25": {
            "candidate_pairs": sum(len(record["candidates"]) for record in bm25_records),
            "latency_ms": summarize_numbers(
                [record["retrieval"]["took_ms"] for record in bm25_records]
            ),
        },
        "model": model_stats,
        "semantic_score": summarize_numbers(semantic_scores),
        "absolute_rank_change": summarize_numbers(rank_changes),
        "bm25_semantic_top10_overlap": summarize_numbers(top10_overlaps),
        "silver_grade_counts": {str(key): grade_counts[key] for key in range(4)},
        "silver_formula": {
            "semantic_rank_percentile": 0.45,
            "bm25_rank_percentile": 0.20,
            "resume_skill_coverage_in_jd": 0.20,
            "target_job_family_match": 0.15,
        },
        "silver_grade_rules": {
            "3": "score>=0.75 and family_match>=0.8",
            "2": "score>=0.55 and (family_match>=0.4 or skill_coverage>=0.2)",
            "1": "score>=0.35",
            "0": "otherwise",
        },
    }
    write_jsonl(reranked_path, reranked_records)
    write_jsonl(silver_path, silver_records)
    write_flat_csv(flat_csv_path, flat_rows)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resumes", type=Path, default=DEFAULT_RESUMES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resume-master", type=Path, default=DEFAULT_RESUME_MASTER)
    parser.add_argument("--family-keywords", type=Path, default=DEFAULT_FAMILY_KEYWORDS)
    parser.add_argument("--es-url", default="http://127.0.0.1:9200")
    parser.add_argument("--index", default=ChineseBM25Service.DEFAULT_INDEX_NAME)
    parser.add_argument("--source-type", default="enterprise")
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--stage", choices=["all", "bm25", "rerank"], default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    bm25_path = output_dir / "bm25_top200_30.jsonl"
    reranked_path = output_dir / "bge_m3_reranked_top200_30.jsonl"
    silver_path = output_dir / "resume_job_silver_30.jsonl"
    flat_csv_path = output_dir / "resume_job_rankings_30.csv"
    summary_path = output_dir / "experiment_summary.json"

    resumes = read_jsonl(args.resumes.resolve())
    if len(resumes) != 30:
        raise ValueError(f"Expected 30 pilot resumes, found {len(resumes)}")

    experiment_started = time.perf_counter()
    bm25_stats = None
    if args.stage in {"all", "bm25"}:
        bm25_stats = run_bm25(
            resumes=resumes,
            output_path=bm25_path,
            es_url=args.es_url,
            index_name=args.index,
            top_k=args.top_k,
            source_type=args.source_type or None,
        )
        print(json.dumps({"bm25": bm25_stats}, ensure_ascii=False, indent=2))

    if args.stage in {"all", "rerank"}:
        if not bm25_path.exists():
            raise FileNotFoundError(f"BM25 result not found: {bm25_path}")
        summary = run_rerank_and_silver(
            bm25_path=bm25_path,
            reranked_path=reranked_path,
            silver_path=silver_path,
            flat_csv_path=flat_csv_path,
            summary_path=summary_path,
            resume_master_path=args.resume_master.resolve(),
            family_keywords_path=args.family_keywords.resolve(),
            model_name=args.model,
            batch_size=args.batch_size,
            max_length=args.max_length,
        )
        if bm25_stats:
            summary["bm25"] = bm25_stats
        summary["total_wall_seconds"] = round(time.perf_counter() - experiment_started, 3)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
