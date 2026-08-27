#!/usr/bin/env python3
"""Evaluate the official 100-JD gold file with an omission-only skill metric.

Skills predicted beyond the human gold set are listed for audit but do not reduce
the score. The reported skill metric is therefore called ``gold_skill_coverage``
(recall), never precision/F1/"accuracy".
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from datetime import date
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文件编码: {path}")


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff+#.]", "", value)


def split_skills(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;；\n、]", value or "") if item.strip()]


def find_field(row: dict[str, str], names: list[str]) -> str:
    for name in names:
        if name in row:
            return row[name]
    return ""


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0, center - half), 4), round(min(1, center + half), 4)]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_normalization_rules(path: Path | None) -> tuple[dict[tuple[str, str], str], dict[str, str]]:
    """Load visible per-case rules. They unify aliases but never add/delete gold skills."""
    by_case: dict[tuple[str, str], str] = {}
    global_rules: dict[str, str] = {}
    if not path:
        return by_case, global_rules
    for row in read_csv(path):
        raw = (row.get("raw_skill") or "").strip()
        canonical = (row.get("normalized_skill") or raw).strip()
        if not raw or not canonical:
            continue
        case_id = (row.get("case_id") or "").strip()
        key = normalize_key(raw)
        if case_id and case_id not in {"*", "GLOBAL"}:
            by_case[(case_id, key)] = canonical
        else:
            global_rules[key] = canonical
    return by_case, global_rules


def load_coverage_rules(path: Path | None) -> dict[tuple[str, str], dict[str, object]]:
    """Load explicit per-case semantic-coverage decisions for the audit."""
    rules: dict[tuple[str, str], dict[str, object]] = {}
    if not path:
        return rules
    for row in read_csv(path):
        case_id = (row.get("case_id") or "").strip()
        gold_skill = (row.get("gold_skill") or "").strip()
        decision = (row.get("decision") or "").strip().lower()
        if not case_id or not gold_skill or decision not in {"cover", "delete"}:
            continue
        rules[(case_id, normalize_key(gold_skill))] = {
            "decision": decision,
            "accepted_system_skills": split_skills(row.get("accepted_system_skills") or ""),
            "rationale": (row.get("rationale") or "人工逐条语义复核").strip(),
        }
    return rules


def canonicalize(case_id: str, raw_skill: str, by_case: dict[tuple[str, str], str], global_rules: dict[str, str]) -> str:
    key = normalize_key(raw_skill)
    canonical = by_case.get((case_id, key), global_rules.get(key, raw_skill))
    return normalize_key(canonical)


def attach_case_ids(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    attached: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        copy = dict(row)
        copy["_case_id"] = (row.get("case_id") or f"JD{index:03d}").strip()
        attached.append(copy)
    return attached


def align_predictions(gold_rows: list[dict[str, str]], prediction_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Prefer explicit case_id; otherwise permit ordered 100-row system output."""
    if prediction_rows and all((row.get("case_id") or "").strip() for row in prediction_rows):
        return {(row.get("case_id") or "").strip(): row for row in prediction_rows}
    if len(prediction_rows) != len(gold_rows):
        raise SystemExit("预测文件未提供 case_id，且行数与金标准不同；请导出 case_id 或保持与金标准完全相同的 100 行顺序。")
    return {gold["_case_id"]: prediction for gold, prediction in zip(gold_rows, prediction_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="官方 100 条 JD 的岗位准确率和金标准技能覆盖率评测")
    parser.add_argument("--gold", required=True, type=Path, help="四字段人工金标准 CSV")
    parser.add_argument("--predictions", required=True, type=Path, help="系统输出 CSV；可有 case_id，也可按金标准行顺序")
    parser.add_argument("--normalization-rules", type=Path, help="可审计的 100 条技能归一化规则 CSV")
    parser.add_argument("--coverage-rules", type=Path, help="逐条语义覆盖/剔除规则 CSV（不改原始金标）")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "evaluation_output")
    parser.add_argument("--role-weight", type=float, default=0.40, help="综合得分中的岗位归类权重")
    args = parser.parse_args()
    if not 0 <= args.role_weight <= 1:
        raise SystemExit("--role-weight 必须在 0 到 1 之间")

    gold_rows = attach_case_ids(read_csv(args.gold))
    if len(gold_rows) != 100:
        raise SystemExit(f"官方金标准必须恰好 100 条，当前为 {len(gold_rows)} 条")
    incomplete = [row["_case_id"] for row in gold_rows if not row.get("gold_standard_job", "").strip() or not row.get("gold_skills", "").strip()]
    if incomplete:
        raise SystemExit(f"存在 {len(incomplete)} 条未完成的金标准，示例: {', '.join(incomplete[:5])}")

    predictions = align_predictions(gold_rows, read_csv(args.predictions))
    by_case, global_rules = load_normalization_rules(args.normalization_rules)
    coverage_rules = load_coverage_rules(args.coverage_rules)
    details: list[dict[str, object]] = []
    total_required = total_hit = total_extra = role_correct = total_deleted = total_semantic_covered = 0
    missing_prediction_ids: list[str] = []

    for gold in gold_rows:
        case_id = gold["_case_id"]
        prediction = predictions.get(case_id)
        if prediction is None:
            missing_prediction_ids.append(case_id)
            continue
        gold_role = gold["gold_standard_job"].strip()
        pred_role = find_field(prediction, ["pred_standard_job", "standard_job", "gold_standard_job"]).strip()
        role_hit = normalize_key(gold_role) == normalize_key(pred_role)
        raw_gold_skills = split_skills(gold["gold_skills"])
        raw_pred_skills = split_skills(find_field(prediction, ["pred_skills", "skills", "gold_skills"]))
        gold_map = {canonicalize(case_id, skill, by_case, global_rules): skill for skill in raw_gold_skills}
        pred_map = {canonicalize(case_id, skill, by_case, global_rules): skill for skill in raw_pred_skills}
        pred_set = set(pred_map)
        effective_gold: dict[str, str] = {}
        deleted_gold: list[str] = []
        covered_gold: list[str] = []
        semantic_covered_gold: list[str] = []
        missing_gold: list[str] = []
        evidence: list[str] = []
        used_pred_keys: set[str] = set()
        # A single broad system skill may cover more than one narrower human
        # label only when every relationship is explicitly recorded below.
        for gold_key, raw_gold in gold_map.items():
            rule = coverage_rules.get((case_id, normalize_key(raw_gold)))
            if rule and rule["decision"] == "delete":
                deleted_gold.append(raw_gold)
                evidence.append(f"{raw_gold}：剔除（{rule['rationale']}）")
                continue
            effective_gold[gold_key] = raw_gold
            if gold_key in pred_set:
                covered_gold.append(raw_gold)
                used_pred_keys.add(gold_key)
                continue
            accepted = rule["accepted_system_skills"] if rule and rule["decision"] == "cover" else []
            accepted_keys = {canonicalize(case_id, str(item), by_case, global_rules) for item in accepted}
            matched_keys = accepted_keys & pred_set
            if matched_keys:
                matched = sorted(pred_map[key] for key in matched_keys)
                covered_gold.append(raw_gold)
                semantic_covered_gold.append(raw_gold)
                used_pred_keys.update(matched_keys)
                evidence.append(f"{raw_gold} ← {', '.join(matched)}（{rule['rationale']}）")
            else:
                missing_gold.append(raw_gold)
        extras = pred_set - used_pred_keys - set(effective_gold)
        coverage = len(covered_gold) / len(effective_gold) if effective_gold else 0.0
        total_required += len(effective_gold)
        total_hit += len(covered_gold)
        total_extra += len(extras)
        total_deleted += len(deleted_gold)
        total_semantic_covered += len(semantic_covered_gold)
        role_correct += int(role_hit)
        details.append({
            "case_id": case_id, "source_job_title": gold.get("source_job_title", ""),
            "gold_standard_job": gold_role, "pred_standard_job": pred_role, "role_correct": int(role_hit),
            "raw_gold_skills": "; ".join(raw_gold_skills), "normalized_gold_skills": "; ".join(sorted(effective_gold)),
            "pred_skills": "; ".join(raw_pred_skills),
            "covered_gold_skills": "; ".join(covered_gold),
            "semantic_covered_gold_skills": "; ".join(semantic_covered_gold),
            "semantic_coverage_evidence": "； ".join(evidence),
            "deleted_gold_skills_not_scored": "; ".join(deleted_gold),
            "missing_gold_skills": "; ".join(missing_gold),
            "extra_system_skills_not_scored": "; ".join(pred_map[key] for key in sorted(extras)),
            "gold_skill_coverage": round(coverage, 4),
        })

    evaluated = len(details)
    if evaluated != len(gold_rows):
        raise SystemExit(f"缺少 {len(missing_prediction_ids)} 条系统预测，示例: {', '.join(missing_prediction_ids[:5])}")
    role_accuracy = role_correct / evaluated
    skill_coverage = total_hit / total_required if total_required else 0.0
    composite = args.role_weight * role_accuracy + (1 - args.role_weight) * skill_coverage
    summary = {
        "metric_definition": "技能金标准覆盖率（仅漏抽扣分；系统多抽不扣分）",
        "evaluated_cases": evaluated, "required_gold_skills_after_normalization": total_required,
        "covered_gold_skills": total_hit, "semantic_covered_gold_skills": total_semantic_covered,
        "deleted_gold_skills_not_scored": total_deleted, "system_extra_skills_not_scored": total_extra,
        "role_exact_accuracy": round(role_accuracy, 4), "role_accuracy_wilson_95ci": wilson_interval(role_correct, evaluated),
        "gold_skill_coverage": round(skill_coverage, 4),
        "jd_parse_composite_score": round(composite, 4), "role_weight": args.role_weight,
        "skill_coverage_weight": round(1 - args.role_weight, 4),
        "acceptance": {
            "role_exact_accuracy_ge_0_90": role_accuracy >= 0.90,
            "gold_skill_coverage_ge_0_90": skill_coverage >= 0.90,
            "jd_parse_composite_score_ge_0_90": composite >= 0.90,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "jd_evaluation_detail.csv", details, list(details[0]))
    (args.output_dir / "jd_evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = f"""# JD 解析测试报告\n\n评测日期：{date.today().isoformat()}  \n有效用例：{evaluated}\n\n本报告的技能指标为**金标准技能覆盖率**：仅统计人工确认技能是否被系统覆盖；系统多抽技能不扣分，但在逐条明细中保留。\n\n| 指标 | 数值 |\n| --- | ---: |\n| 标准岗位精确准确率 | {role_accuracy:.2%} |\n| 金标准技能覆盖率 | {skill_coverage:.2%} |\n| JD 解析综合得分 | {composite:.2%} |\n| 人工语义覆盖的金标技能 | {total_semantic_covered} 项 |\n| 剔除的非可比金标技能 | {total_deleted} 项 |\n| 系统多抽技能（不扣分） | {total_extra} 项 |\n\n判定详见 `jd_evaluation_summary.json`；逐条漏抽与多抽详见 `jd_evaluation_detail.csv`。\n"""
    (args.output_dir / "jd_evaluation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
