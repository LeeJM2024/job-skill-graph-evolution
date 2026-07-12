import csv
import json
from collections import Counter
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT = BASE_DIR / "job_skill_gold_ai_reviewed_all.csv"
OUTPUT_CSV = BASE_DIR / "job_skill_gold_clean.csv"
OUTPUT_JSONL = BASE_DIR / "job_skill_gold_clean.jsonl"
REPORT = BASE_DIR / "job_skill_gold_clean_report.json"

FIELDS = [
    "annotation_id",
    "sentence_id",
    "job_id",
    "job_title",
    "source_type",
    "source_name",
    "evidence_field",
    "text",
    "span_text",
    "span_start",
    "span_end",
    "label",
    "normalized_skill",
    "category",
    "skill_type",
    "decision",
]


def clean(value):
    return "" if value is None else str(value)


rows = []
stats = Counter()
offset_errors = []
duplicate_keys = set()
duplicates = 0

with INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
    reader = csv.DictReader(handle)
    for row in reader:
        stats["source_rows"] += 1
        decision = clean(row.get("decision"))
        if decision == "REJECT":
            stats["rejected_rows"] += 1
            continue

        span = clean(row.get("gold_span_text"))
        skill = clean(row.get("gold_normalized_skill"))
        if not span or not skill:
            stats["missing_gold_rows"] += 1
            continue

        text = clean(row.get("text"))
        start = int(row["gold_start"])
        end = int(row["gold_end"])
        if text[start:end] != span:
            offset_errors.append(
                {
                    "annotation_id": row.get("annotation_id"),
                    "sentence_id": row.get("sentence_id"),
                    "span_text": span,
                    "slice": text[start:end],
                }
            )
            continue

        key = (row["sentence_id"], start, end, skill)
        if key in duplicate_keys:
            duplicates += 1
            continue
        duplicate_keys.add(key)

        rows.append(
            {
                "annotation_id": clean(row.get("annotation_id")),
                "sentence_id": clean(row.get("sentence_id")),
                "job_id": clean(row.get("job_id")),
                "job_title": clean(row.get("job_title")),
                "source_type": clean(row.get("source_type")),
                "source_name": clean(row.get("source_name")),
                "evidence_field": clean(row.get("evidence_field")),
                "text": text,
                "span_text": span,
                "span_start": start,
                "span_end": end,
                "label": clean(row.get("gold_label")) or "knowledge",
                "normalized_skill": skill,
                "category": clean(row.get("gold_category")) or "未分类",
                "skill_type": clean(row.get("gold_skill_type")) or "required",
                "decision": decision,
            }
        )

if offset_errors:
    raise SystemExit(f"offset errors: {offset_errors[:5]}")

with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

with OUTPUT_JSONL.open("w", encoding="utf-8-sig", newline="\n") as handle:
    for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")

report = {
    "input": str(INPUT),
    "outputs": {"csv": str(OUTPUT_CSV), "jsonl": str(OUTPUT_JSONL), "report": str(REPORT)},
    "source_rows": stats["source_rows"],
    "rejected_rows_excluded": stats["rejected_rows"],
    "missing_gold_rows_excluded": stats["missing_gold_rows"],
    "duplicate_rows_excluded": duplicates,
    "clean_rows": len(rows),
    "offset_errors": 0,
    "fields": FIELDS,
    "top_skills": Counter(row["normalized_skill"] for row in rows).most_common(30),
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
