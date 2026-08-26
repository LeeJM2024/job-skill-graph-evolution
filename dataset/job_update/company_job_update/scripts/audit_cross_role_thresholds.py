"""Read-only sensitivity audit for cross-role similarity thresholds.

The report counts potential *new* job-skill edges supported by the existing
skill migration/spread data.  It does not write CSV files or SQLite data.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_versions import resolve_company_data_paths
from core.similarity import Text2VecSimilarity
from core.taxonomy import JobTaxonomy
from core.text import clean_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit cross-role evidence sensitivity without modifying data.")
    parser.add_argument("--thresholds", default="0.80,0.85,0.90", help="Comma-separated role similarity thresholds.")
    parser.add_argument("--recent-months", type=int, default=6)
    args = parser.parse_args()
    thresholds = sorted({float(value.strip()) for value in args.thresholds.split(",") if value.strip()})
    paths = resolve_company_data_paths()
    taxonomy = JobTaxonomy.from_csv(paths.title_dictionary)
    spread = pd.read_csv(paths.spread, dtype=str, encoding="utf-8-sig").fillna("")
    migration = pd.read_csv(paths.migration, dtype=str, encoding="utf-8-sig").fillna("")
    observed_month = max(spread["month"].astype(str))
    peer_evidence = _confirmed_recent_evidence(spread, observed_month, args.recent_months)

    similarity = Text2VecSimilarity()
    job_scores = _same_category_job_scores(taxonomy, similarity)
    results = [
        _evaluate_threshold(
            threshold=threshold,
            taxonomy=taxonomy,
            job_scores=job_scores,
            peer_evidence=peer_evidence,
        )
        for threshold in thresholds
    ]
    print(
        json.dumps(
            {
                "data_version": paths.version,
                "observed_month": observed_month,
                "recent_months": args.recent_months,
                "definition": "候选边指当前岗位尚未出现该技能、但相似岗位存在近期已确认技能证据的岗位—技能组合；不等于最终自动入图数量，最终仍要求当前JD原文证据。",
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _confirmed_recent_evidence(spread: pd.DataFrame, observed_month: str, recent_months: int) -> dict[str, dict[str, int]]:
    frame = spread.copy()
    frame["skill"] = frame["skill"].map(clean_text)
    frame["standard_job"] = frame["standard_job"].map(clean_text)
    frame["month"] = frame["month"].map(clean_text)
    frame["monthly_skill_count"] = pd.to_numeric(frame["monthly_skill_count"], errors="coerce").fillna(0).astype(int)
    frame["cumulative_skill_count"] = pd.to_numeric(frame["cumulative_skill_count"], errors="coerce").fillna(0).astype(int)
    output: dict[str, dict[str, int]] = defaultdict(dict)
    for (skill, job), group in frame.groupby(["skill", "standard_job"], sort=False):
        active = group[group["monthly_skill_count"] > 0].sort_values("month")
        confirmed = group[group["cumulative_skill_count"] >= 2].sort_values("month")
        if active.empty or confirmed.empty:
            continue
        last_seen = str(active.iloc[-1]["month"])
        if _month_distance(last_seen, observed_month) > recent_months:
            continue
        output[skill][job] = int(confirmed.iloc[-1]["cumulative_skill_count"])
    return output


def _same_category_job_scores(taxonomy: JobTaxonomy, similarity: Text2VecSimilarity) -> dict[str, dict[str, float]]:
    """Encode every standard job once, then calculate the pairwise score matrix."""
    jobs = taxonomy.jobs
    embeddings = similarity.model.encode([job.title for job in jobs])
    scores: dict[str, dict[str, float]] = {}
    for index, job in enumerate(jobs):
        scores[job.title] = {
            peer.title: Text2VecSimilarity._cosine(embeddings[index], embeddings[peer_index])
            for peer_index, peer in enumerate(jobs)
            if peer.title != job.title and peer.category == job.category
        }
    return scores


def _evaluate_threshold(*, threshold: float, taxonomy: JobTaxonomy, job_scores: dict[str, dict[str, float]], peer_evidence: dict[str, dict[str, int]]) -> dict[str, object]:
    regular = 0
    strong = 0
    total = 0
    for job in taxonomy.jobs:
        scores = job_scores[job.title]
        for skill, evidence_by_job in peer_evidence.items():
            if job.title in evidence_by_job:
                continue
            peers = [
                (peer, score, evidence_by_job[peer])
                for peer, score in scores.items()
                if score >= threshold and peer in evidence_by_job
            ]
            if len(peers) >= 2:
                regular += 1
                total += 1
            elif any(score >= 0.92 and mentions >= 3 for _, score, mentions in peers):
                strong += 1
                total += 1
    return {
        "similarity_threshold": threshold,
        "potential_cross_role_edges": total,
        "two_or_more_peer_jobs": regular,
        "single_strong_peer": strong,
    }


def _month_distance(start: str, end: str) -> int:
    start_year, start_month = (int(part) for part in start.split("-", 1))
    end_year, end_month = (int(part) for part in end.split("-", 1))
    return (end_year - start_year) * 12 + end_month - start_month


if __name__ == "__main__":
    main()
