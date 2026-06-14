"""Build the first Job-Skill graph layer for Neo4j and the local graph UI.

The script has two independent outputs:
1. Always exports a lightweight graph JSON for local UI preview.
2. Optionally imports the same Job/Skill graph into Neo4j when --import-neo4j
   is provided and the neo4j Python driver is installed.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DATASET_DIR = Path(__file__).resolve().parents[1]
DEFAULT_JOBS = DATASET_DIR / "cleaned" / "all_jobs_23714_normalized.jsonl"
DEFAULT_MENTIONS = DATASET_DIR / "structured" / "job_skill_mentions.jsonl"
DEFAULT_OUTPUT_DIR = DATASET_DIR / "graph"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\u3000", " ").split())


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc


def load_jobs(path: Path) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for record in read_jsonl(path):
        job_id = clean_text(record.get("job_id"))
        if not job_id:
            continue
        tags = record.get("tags")
        if isinstance(tags, list):
            tag_values = [clean_text(item) for item in tags if clean_text(item)]
        else:
            tag_values = [item.strip() for item in clean_text(tags).split(";") if item.strip()]
        jobs[job_id] = {
            "job_id": job_id,
            "job_title": clean_text(record.get("job_title")),
            "source_type": clean_text(record.get("source_type")),
            "source_name": clean_text(record.get("source_name")),
            "company_name": clean_text(record.get("company_name")),
            "location": clean_text(record.get("location")),
            "source_url": clean_text(record.get("source_url")),
            "tags": tag_values,
        }
    return jobs


def load_mentions(path: Path, jobs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in read_jsonl(path):
        job_id = clean_text(record.get("job_id"))
        skill = clean_text(record.get("normalized_skill"))
        evidence = clean_text(record.get("evidence_sentence"))
        relation_type = "PREFERS_SKILL" if clean_text(record.get("skill_type")) == "preferred" else "REQUIRES_SKILL"
        if not job_id or not skill or job_id not in jobs:
            continue
        key = (job_id, skill.lower(), relation_type, evidence)
        if key in seen:
            continue
        seen.add(key)
        mentions.append(
            {
                "job_id": job_id,
                "skill_name": skill,
                "relation_type": relation_type,
                "raw_skill": clean_text(record.get("raw_skill")),
                "category": clean_text(record.get("category")) or "未分类",
                "skill_type": clean_text(record.get("skill_type")) or "required",
                "evidence_sentence": evidence,
                "evidence_field": clean_text(record.get("evidence_field")),
                "span_text": clean_text(record.get("span_text")),
                "span_start": int(record.get("span_start") or 0),
                "span_end": int(record.get("span_end") or 0),
                "skillspan_label": clean_text(record.get("skillspan_label")),
                "confidence": float(record.get("confidence") or 0.0),
                "match_method": clean_text(record.get("match_method")) or "dictionary",
            }
        )
    return mentions


def select_preview_jobs(
    jobs: dict[str, dict[str, Any]],
    mentions: list[dict[str, Any]],
    max_jobs: int,
) -> set[str]:
    if max_jobs <= 0:
        return {item["job_id"] for item in mentions}
    score: Counter[str] = Counter(item["job_id"] for item in mentions)
    selected = {job_id for job_id, _ in score.most_common(max_jobs)}
    return selected


def build_graph_json(
    jobs: dict[str, dict[str, Any]],
    mentions: list[dict[str, Any]],
    max_ui_jobs: int,
) -> dict[str, Any]:
    selected_jobs = select_preview_jobs(jobs, mentions, max_ui_jobs)
    selected_mentions = [item for item in mentions if item["job_id"] in selected_jobs]

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    skill_categories: dict[str, str] = {}
    skill_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()

    for job_id in sorted(selected_jobs):
        job = jobs[job_id]
        nodes.append(
            {
                "id": f"job:{job_id}",
                "type": "Job",
                "label": job["job_title"] or job_id,
                **job,
            }
        )

    for item in selected_mentions:
        skill_categories.setdefault(item["skill_name"], item["category"])
        skill_counts[item["skill_name"]] += 1
        relation_counts[item["relation_type"]] += 1
        category_counts[item["category"]] += 1

    for skill_name in sorted(skill_categories):
        nodes.append(
            {
                "id": f"skill:{skill_name}",
                "type": "Skill",
                "label": skill_name,
                "name": skill_name,
                "category": skill_categories[skill_name],
                "job_count": skill_counts[skill_name],
            }
        )

    for index, item in enumerate(selected_mentions, start=1):
        links.append(
            {
                "id": f"rel:{index}",
                "source": f"job:{item['job_id']}",
                "target": f"skill:{item['skill_name']}",
                "type": item["relation_type"],
                **{key: value for key, value in item.items() if key not in {"job_id", "skill_name", "relation_type"}},
            }
        )

    all_jobs_with_skills = {item["job_id"] for item in mentions}
    all_skills = {item["skill_name"] for item in mentions}
    return {
        "meta": {
            "total_jobs": len(jobs),
            "jobs_with_skills": len(all_jobs_with_skills),
            "total_skill_mentions": len(mentions),
            "unique_skills": len(all_skills),
            "ui_jobs": len(selected_jobs),
            "ui_skill_mentions": len(selected_mentions),
            "ui_skills": len(skill_categories),
            "relation_counts": dict(relation_counts),
            "category_counts": dict(category_counts),
        },
        "nodes": nodes,
        "links": links,
    }


def write_cypher_template(path: Path) -> None:
    path.write_text(
        """// Job-Skill graph constraints
CREATE CONSTRAINT job_id_unique IF NOT EXISTS
FOR (j:Job) REQUIRE j.job_id IS UNIQUE;

CREATE CONSTRAINT skill_name_unique IF NOT EXISTS
FOR (s:Skill) REQUIRE s.name IS UNIQUE;

// Example checks after import
MATCH (j:Job)-[r]->(s:Skill)
RETURN labels(j) AS job_labels, type(r) AS relation, labels(s) AS skill_labels, count(*) AS count
ORDER BY count DESC;

MATCH (j:Job)-[r]->(s:Skill)
RETURN j.job_title AS job, type(r) AS relation, s.name AS skill, r.evidence_sentence AS evidence
LIMIT 20;
""",
        encoding="utf-8",
    )


def import_to_neo4j(
    jobs: dict[str, dict[str, Any]],
    mentions: list[dict[str, Any]],
    uri: str,
    user: str,
    password: str,
    database: str | None,
) -> None:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: neo4j. Install it with `python -m pip install neo4j` "
            "or run without --import-neo4j to export UI JSON only."
        ) from exc

    skill_category: dict[str, str] = {}
    for item in mentions:
        skill_category.setdefault(item["skill_name"], item["category"])

    job_rows = list(jobs.values())
    skill_rows = [{"name": name, "category": category} for name, category in skill_category.items()]

    driver = GraphDatabase.driver(uri, auth=(user, password))
    session_kwargs = {"database": database} if database else {}
    with driver.session(**session_kwargs) as session:
        session.run("CREATE CONSTRAINT job_id_unique IF NOT EXISTS FOR (j:Job) REQUIRE j.job_id IS UNIQUE")
        session.run("CREATE CONSTRAINT skill_name_unique IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE")
        session.run(
            """
            UNWIND $rows AS row
            MERGE (j:Job {job_id: row.job_id})
            SET j.job_title = row.job_title,
                j.source_type = row.source_type,
                j.source_name = row.source_name,
                j.company_name = row.company_name,
                j.location = row.location,
                j.source_url = row.source_url,
                j.tags = row.tags
            """,
            rows=job_rows,
        )
        session.run(
            """
            UNWIND $rows AS row
            MERGE (s:Skill {name: row.name})
            SET s.category = row.category
            """,
            rows=skill_rows,
        )
        for relation_type in ("REQUIRES_SKILL", "PREFERS_SKILL"):
            rows = [item for item in mentions if item["relation_type"] == relation_type]
            if not rows:
                continue
            session.run(
                f"""
                UNWIND $rows AS row
                MATCH (j:Job {{job_id: row.job_id}})
                MATCH (s:Skill {{name: row.skill_name}})
                MERGE (j)-[r:{relation_type} {{
                    raw_skill: row.raw_skill,
                    evidence_sentence: row.evidence_sentence,
                    span_start: row.span_start,
                    span_end: row.span_end
                }}]->(s)
                SET r.evidence_field = row.evidence_field,
                    r.span_text = row.span_text,
                    r.skillspan_label = row.skillspan_label,
                    r.confidence = row.confidence,
                    r.match_method = row.match_method
                """,
                rows=rows,
            )
    driver.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    parser.add_argument("--mentions", type=Path, default=DEFAULT_MENTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-ui-jobs", type=int, default=120, help="0 exports every Job node to graph JSON")
    parser.add_argument("--import-neo4j", action="store_true", help="Import graph into Neo4j after JSON export")
    parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    jobs = load_jobs(args.jobs)
    mentions = load_mentions(args.mentions, jobs)
    graph = build_graph_json(jobs, mentions, args.max_ui_jobs)

    graph_path = args.output_dir / "job_skill_graph.json"
    cypher_path = args.output_dir / "neo4j_job_skill_constraints.cypher"
    report_path = args.output_dir / "job_skill_graph_report.json"

    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    write_cypher_template(cypher_path)
    report_path.write_text(json.dumps(graph["meta"], ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Jobs: {len(jobs)}")
    print(f"Skill mentions: {len(mentions)}")
    print(f"UI graph nodes: {len(graph['nodes'])}")
    print(f"UI graph links: {len(graph['links'])}")
    print(f"Graph JSON: {graph_path}")
    print(f"Report: {report_path}")
    print(f"Cypher helper: {cypher_path}")

    if args.import_neo4j:
        import_to_neo4j(
            jobs=jobs,
            mentions=mentions,
            uri=args.neo4j_uri,
            user=args.neo4j_user,
            password=args.neo4j_password,
            database=args.neo4j_database or None,
        )
        print(f"Neo4j import completed: {args.neo4j_uri} / database={args.neo4j_database or '(default)'}")


if __name__ == "__main__":
    main()
