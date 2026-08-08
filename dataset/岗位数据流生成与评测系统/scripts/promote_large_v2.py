from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FLOW_ROOT = PROJECT_ROOT
DATASET_ROOT = PROJECT_ROOT.parent
JOB_UPDATE_ROOT = DATASET_ROOT / "job_update" / "company_job_update"
if str(DATASET_ROOT / "job_update") not in sys.path:
    sys.path.insert(0, str(DATASET_ROOT / "job_update"))

from company_job_update.core.current_profile_store import CurrentProfileStore
from company_job_update.core.data_versions import LEGACY_BASE_DIR, VERSION_ROOT, resolve_company_data_paths
from company_job_update.core.database import SQLiteJobUpdateStore
from company_job_update.core.frequency_store import rebuild_frequency_table
from company_job_update.core.job_profile_store import JobProfileStore
from company_job_update.core.skill_lifecycle_store import SkillLifecycleStore
from company_job_update.core.skill_migration_store import SkillMigrationStore
from company_job_update.core.skill_pool_store import rebuild_skill_pool_table


SOURCE_STREAM = (
    DATA_FLOW_ROOT
    / "outputs"
    / "company_large_v2"
    / "job_update_event_stream_large_test_19_23_per_job_month.csv"
)
COMPANY_SKILL_DICTIONARY = JOB_UPDATE_ROOT / "skill_extract" / "company_skill_dictionary.csv"
LEGACY_VERSION = "company_base_v1"
LARGE_VERSION = "company_large_v2"

# These source strings are aliases in the maintained company ontology. The
# large generated stream may contain both the long and short forms, so the
# normalization must happen before rebuilding any time-series tables.
ALIASES = {
    "\u591a\u6e90\u4fe1\u606f\u878d\u5408SLAM": "SLAM",
    "\u5927\u6a21\u578bASR": "\u6a21\u578bASR",
    "\u5927\u6a21\u578b\u504f\u597d\u6570\u636e": "\u6a21\u578b\u504f\u597d\u6570\u636e",
    "\u5927\u6a21\u578b\u540e\u8bad\u7ec3": "\u6a21\u578b\u540e\u8bad\u7ec3",
    "\u5927\u6a21\u578b\u5b89\u5168": "\u5927\u6a21\u578b\u5b89\u5168",
    "\u6a21\u578b\u5b89\u5168": "\u5927\u6a21\u578b\u5b89\u5168",
    "\u5927\u6a21\u578b\u5f3a\u5316": "\u6a21\u578b\u5f3a\u5316",
    "\u5927\u6a21\u578b\u5fae\u8c03": "\u6a21\u578b\u5fae\u8c03",
    "\u5927\u6a21\u578b\u8bad\u7ec3": "\u6a21\u578b\u8bad\u7ec3",
    "\u5927\u6a21\u578b\u8bc4\u6d4b": "\u6a21\u578b\u8bc4\u6d4b",
    "\u5927\u6a21\u578b\u8c03\u4f18": "\u6a21\u578b\u8c03\u4f18",
    "\u5927\u6a21\u578b\u9884\u8bad\u7ec3": "\u6a21\u578b\u9884\u8bad\u7ec3",
    "agent": "Agent",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the independent company_large_v2 data version.")
    parser.add_argument("--replace-target", action="store_true")
    args = parser.parse_args()

    print("promotion: ensuring immutable company_base_v1 snapshot", flush=True)
    _seed_legacy_version()
    target_dir = VERSION_ROOT / LARGE_VERSION
    if target_dir.exists():
        if not args.replace_target:
            raise FileExistsError(f"Target version already exists: {target_dir}. Use --replace-target to rebuild it.")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=False)

    print("promotion: loading source large event stream and legacy skill pool", flush=True)
    legacy_pool = _read_csv(LEGACY_BASE_DIR / "skill_pool.csv")
    legacy_skills = set(legacy_pool["normalized_skill"].astype(str).str.strip())
    source = _read_csv(SOURCE_STREAM)
    cleaned, report = _clean_stream(source, legacy_skills)
    print(f"promotion: cleaned {len(source)} source events into {len(cleaned)} retained events", flush=True)
    cleaned.to_csv(target_dir / "job_update_event_stream.csv", index=False, encoding="utf-8-sig")

    shutil.copy2(LEGACY_BASE_DIR / "standard_job_title_dictionary.csv", target_dir / "standard_job_title_dictionary.csv")
    print("promotion: building retained skill universe", flush=True)
    skill_universe = _build_skill_universe(cleaned, legacy_pool)
    title_dictionary = _read_csv(target_dir / "standard_job_title_dictionary.csv")
    categories = dict(zip(title_dictionary["standard_job_title"], title_dictionary["standard_category"]))
    print("promotion: rebuilding monthly and cumulative skill frequency", flush=True)
    frequency = rebuild_frequency_table(cleaned)
    print(f"promotion: frequency rows={len(frequency)}", flush=True)
    skill_pool = rebuild_skill_pool_table(
        cleaned,
        standard_job_categories=categories,
        skill_universe=skill_universe,
        source=LARGE_VERSION,
    )

    paths = resolve_company_data_paths(LARGE_VERSION)
    frequency.to_csv(paths.frequency, index=False, encoding="utf-8-sig")
    skill_pool.to_csv(paths.skill_pool, index=False, encoding="utf-8-sig")
    print("promotion: rebuilding skill pool and lifecycle", flush=True)
    lifecycle = SkillLifecycleStore(paths.lifecycle).rebuild(
        frequency=frequency, skill_pool=skill_pool, write=False
    )
    lifecycle.to_csv(paths.lifecycle, index=False, encoding="utf-8-sig")
    print("promotion: rebuilding skill migration", flush=True)
    migration, spread = SkillMigrationStore(paths.migration, paths.spread).rebuild(
        frequency=frequency, skill_pool=skill_pool, write=False
    )
    migration.to_csv(paths.migration, index=False, encoding="utf-8-sig")
    spread.to_csv(paths.spread, index=False, encoding="utf-8-sig")
    print("promotion: rebuilding job profile snapshots and diffs", flush=True)
    snapshots, diffs = JobProfileStore(paths.profile_snapshots, paths.profile_diff).rebuild(
        frequency=frequency, skill_pool=skill_pool, write=False
    )
    snapshots.to_csv(paths.profile_snapshots, index=False, encoding="utf-8-sig")
    diffs.to_csv(paths.profile_diff, index=False, encoding="utf-8-sig")
    print("promotion: rebuilding current job profiles", flush=True)
    current = CurrentProfileStore(paths.current_profile).rebuild(snapshots=snapshots, write=False)
    current.to_csv(paths.current_profile, index=False, encoding="utf-8-sig")
    print("promotion: initializing isolated SQLite database", flush=True)
    counts = SQLiteJobUpdateStore(paths.database).initialize_from_csv(
        title_dictionary_path=paths.title_dictionary,
        event_stream_path=paths.event_stream,
        frequency_path=paths.frequency,
        skill_pool_path=paths.skill_pool,
        lifecycle_path=paths.lifecycle,
        migration_path=paths.migration,
        spread_path=paths.spread,
        profile_snapshot_path=paths.profile_snapshots,
        profile_diff_path=paths.profile_diff,
    )
    manifest = {
        "version": LARGE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "company_generated_market_based_baseline",
        "source_event_stream": str(SOURCE_STREAM.relative_to(DATASET_ROOT)),
        "source_event_rows": len(source),
        "event_rows": len(cleaned),
        "dropped_empty_skill_events": report["dropped_empty_skill_events"],
        "removed_non_pool_skill_values": report["removed_non_pool_skill_values"],
        "removed_skill_mentions": report["removed_skill_mentions"],
        "normalized_aliases": report["normalized_aliases"],
        "standard_job_count": int(cleaned["standard_job"].nunique()),
        "month_count": int(cleaned["month"].nunique()),
        "skill_count": int(skill_pool["normalized_skill"].nunique()),
        "database_counts": counts,
        "selection": "Set COMPANY_DATA_VERSION=company_large_v2 before starting the company CLI or Web backend.",
    }
    paths.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _seed_legacy_version() -> None:
    legacy_target = VERSION_ROOT / LEGACY_VERSION
    if legacy_target.exists():
        return
    if not LEGACY_BASE_DIR.exists():
        raise FileNotFoundError(f"Legacy company base directory is missing: {LEGACY_BASE_DIR}")
    VERSION_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(LEGACY_BASE_DIR, legacy_target)
    (legacy_target / "version_manifest.json").write_text(
        json.dumps(
            {
                "version": LEGACY_VERSION,
                "kind": "company_legacy_baseline",
                "source": "copied unchanged from the company_base_v1 reference data before versioned baselines were introduced",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _clean_stream(source: pd.DataFrame, legacy_skills: set[str]) -> tuple[pd.DataFrame, dict[str, object]]:
    removed_values: Counter[str] = Counter()
    aliases: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    for row in source.to_dict(orient="records"):
        skills: list[str] = []
        for raw in str(row.get("skills") or "").split(";"):
            raw = raw.strip()
            if not raw:
                continue
            normalized = ALIASES.get(raw, raw)
            if raw in ALIASES:
                aliases[f"{raw} -> {normalized}"] += 1
            elif raw not in legacy_skills:
                removed_values[raw] += 1
                continue
            if normalized not in skills:
                skills.append(normalized)
        if not skills:
            continue
        row["skills"] = "; ".join(skills)
        rows.append({key: str(value or "") for key, value in row.items()})
    cleaned = pd.DataFrame(rows, columns=source.columns)
    if cleaned["job_id"].duplicated().any():
        raise ValueError("Cleaned large event stream has duplicate job_id values")
    return cleaned, {
        "dropped_empty_skill_events": int(len(source) - len(cleaned)),
        "removed_non_pool_skill_values": sorted(removed_values),
        "removed_skill_mentions": int(sum(removed_values.values())),
        "normalized_aliases": dict(aliases),
    }


def _build_skill_universe(events: pd.DataFrame, legacy_pool: pd.DataFrame) -> pd.DataFrame:
    dictionary = _read_csv(COMPANY_SKILL_DICTIONARY)
    display_by_skill = {
        str(row["normalized_skill"]).strip(): (str(row["kg_display_skill"]).strip(), str(row["skill_type"]).strip())
        for _, row in legacy_pool.iterrows()
        if str(row["normalized_skill"]).strip() and str(row["kg_display_skill"]).strip()
    }
    for _, row in dictionary.iterrows():
        normalized = str(row.get("normalized_skill") or "").strip()
        display = str(row.get("kg_display_skill") or "").strip()
        if normalized and display:
            display_by_skill.setdefault(normalized, (display, ""))

    rows: list[dict[str, str]] = []
    for event in events.to_dict(orient="records"):
        job = str(event["standard_job"]).strip()
        for skill in (value.strip() for value in str(event["skills"]).split(";")):
            display, skill_type = display_by_skill.get(skill, ("", ""))
            if not display:
                raise ValueError(f"No kg_display_skill for retained skill: {skill}")
            rows.append(
                {
                    "standard_job": job,
                    "skill": skill,
                    "kg_display_skill": display,
                    "skill_stage": skill_type,
                }
            )
    return pd.DataFrame(rows).drop_duplicates(["standard_job", "skill"]).reset_index(drop=True)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")


if __name__ == "__main__":
    main()
