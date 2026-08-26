from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Iterable

from .models import JobPosting, NormalizedSkill, SkillAdmission
from .text import clean_text


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class RoleSkillCandidateStore:
    """Keep unverified dynamic job-skill edges outside the baseline graph.

    The static event stream remains immutable.  A newly observed skill is
    accumulated here until it has repeated, time-separated evidence or is
    manually reviewed.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        min_support_jobs: int = 2,
        min_support_months: int = 2,
        expire_after_months: int = 3,
    ) -> None:
        self.database_path = database_path
        self.min_support_jobs = min_support_jobs
        self.min_support_months = min_support_months
        self.expire_after_months = expire_after_months

    def evaluate(
        self,
        *,
        posting: JobPosting,
        standard_job: str,
        skills: Iterable[NormalizedSkill],
        trusted_skills: set[str],
        evidence_by_skill: dict[str, dict[str, str]] | None = None,
        cross_role_evidence_by_skill: dict[str, dict[str, object]] | None = None,
        persist: bool,
    ) -> list[SkillAdmission]:
        evidence_by_skill = evidence_by_skill or {}
        cross_role_evidence_by_skill = cross_role_evidence_by_skill or {}
        if persist:
            self._ensure_schema()
            self.expire_stale(posting.month)
        existing = self._load_for_job(standard_job) if self.database_path.exists() else {}
        decisions: list[SkillAdmission] = []
        for skill in skills:
            name = clean_text(skill.normalized_skill)
            if not name:
                continue
            key = name.casefold()
            if key in trusted_skills:
                decisions.append(SkillAdmission(name, clean_text(skill.kg_display_skill), "verified_existing", "已存在于该岗位可信基线画像"))
                continue

            row = existing.get(key)
            if row and row["status"] == "confirmed":
                confirmation_route = clean_text(row.get("confirmation_route"))
                is_cross_role = confirmation_route == "cross_role_migration"
                decisions.append(SkillAdmission(
                    name,
                    clean_text(skill.kg_display_skill),
                    "verified_cross_role" if is_cross_role else "verified_dynamic",
                    "已通过相似岗位迁移证据交叉验证" if is_cross_role else "已通过历史动态证据交叉验证",
                    row["support_job_count"],
                    row["support_month_count"],
                    confirmation_route,
                    _as_int(row.get("cross_role_support_job_count")),
                ))
                continue

            reusable_evidence = bool(row and row["status"] == "candidate")
            job_ids = set(row["support_job_ids"]) if reusable_evidence else set()
            months = set(row["support_months"]) if reusable_evidence else set()
            job_ids.add(clean_text(posting.job_id))
            if MONTH_RE.match(clean_text(posting.month)):
                months.add(clean_text(posting.month))
            support_jobs = len([value for value in job_ids if value])
            support_months = len(months)
            becomes_confirmed = (
                support_jobs >= self.min_support_jobs
                and support_months >= self.min_support_months
            )
            evidence = evidence_by_skill.get(key, {})
            cross_role_evidence = cross_role_evidence_by_skill.get(key, {})
            has_direct_evidence = bool(clean_text(evidence.get("sentence")))
            cross_role_confirmed = bool(cross_role_evidence.get("eligible")) and has_direct_evidence
            if becomes_confirmed:
                status = "confirmed_dynamic"
                reason = "已满足双JD、跨自然月的动态交叉验证条件"
                confirmation_route = "same_role_temporal"
            elif cross_role_confirmed:
                status = "confirmed_cross_role"
                reason = "当前JD原文证据与相似岗位迁移证据共同满足交叉验证条件"
                confirmation_route = "cross_role_migration"
            else:
                status = "candidate"
                reason = "首次或证据不足的岗位新增技能，暂存候选能力池"
                confirmation_route = ""
            decision = SkillAdmission(
                name,
                clean_text(skill.kg_display_skill),
                status,
                reason,
                support_jobs,
                support_months,
                confirmation_route,
                _as_int(cross_role_evidence.get("peer_job_count")),
            )
            decisions.append(decision)
            if persist:
                self._upsert_candidate(
                    posting=posting,
                    standard_job=standard_job,
                    skill=skill,
                    status="confirmed" if status != "candidate" else "candidate",
                    job_ids=job_ids,
                    months=months,
                    evidence=evidence,
                    confirmation_reason=reason if status != "candidate" else "",
                    confirmation_route=confirmation_route,
                    cross_role_evidence=cross_role_evidence,
                )
        return decisions

    def list_candidates(self, *, status: str | None = None) -> list[dict[str, object]]:
        if not self.database_path.exists():
            return []
        self._ensure_schema()
        sql = "SELECT * FROM role_skill_candidates"
        params: tuple[str, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY updated_at DESC, standard_job, normalized_skill"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._serialize_row(dict(row)) for row in rows]

    def review_candidate(self, *, standard_job: str, skill: str, action: str) -> dict[str, object]:
        if action not in {"confirm", "reject"}:
            raise ValueError("action must be confirm or reject")
        self._ensure_schema()
        status = "confirmed" if action == "confirm" else "rejected"
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE role_skill_candidates
                SET status = ?, confirmation_reason = ?, confirmation_route = ?, confirmed_at = ?, updated_at = ?
                WHERE standard_job = ? AND skill_key = ?
                """,
                (
                    status,
                    "人工确认" if action == "confirm" else "人工驳回",
                    "manual_review" if action == "confirm" else "",
                    now if action == "confirm" else "",
                    now,
                    clean_text(standard_job),
                    clean_text(skill).casefold(),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Candidate not found: {standard_job} / {skill}")
            row = conn.execute(
                "SELECT * FROM role_skill_candidates WHERE standard_job = ? AND skill_key = ?",
                (clean_text(standard_job), clean_text(skill).casefold()),
            ).fetchone()
        return self._serialize_row(dict(row))

    def confirmed_profile_rows(self) -> list[dict[str, object]]:
        return self.list_candidates(status="confirmed")

    def expire_stale(self, as_of_month: str) -> int:
        if not MONTH_RE.match(clean_text(as_of_month)):
            return 0
        self._ensure_schema()
        expired = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT standard_job, skill_key, last_seen_month FROM role_skill_candidates WHERE status = 'candidate'"
            ).fetchall()
            for row in rows:
                last_seen = clean_text(row["last_seen_month"])
                if not MONTH_RE.match(last_seen) or _month_distance(last_seen, as_of_month) < self.expire_after_months:
                    continue
                conn.execute(
                    "UPDATE role_skill_candidates SET status = 'expired', updated_at = ? WHERE standard_job = ? AND skill_key = ?",
                    (_now(), row["standard_job"], row["skill_key"]),
                )
                expired += 1
        return expired

    def _load_for_job(self, standard_job: str) -> dict[str, dict[str, object]]:
        if not self.database_path.exists():
            return {}
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM role_skill_candidates WHERE standard_job = ?",
                    (clean_text(standard_job),),
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {
            str(row["skill_key"]): self._serialize_row(dict(row))
            for row in rows
        }

    def _upsert_candidate(
        self,
        *,
        posting: JobPosting,
        standard_job: str,
        skill: NormalizedSkill,
        status: str,
        job_ids: set[str],
        months: set[str],
        evidence: dict[str, str],
        confirmation_reason: str,
        confirmation_route: str,
        cross_role_evidence: dict[str, object],
    ) -> None:
        now = _now()
        key = clean_text(skill.normalized_skill).casefold()
        evidence_rows = self._existing_evidence(standard_job, key)
        evidence_item = {
            "job_id": clean_text(posting.job_id),
            "month": clean_text(posting.month),
            "field": clean_text(evidence.get("field")),
            "sentence": clean_text(evidence.get("sentence")),
            "confidence": evidence.get("confidence"),
        }
        if evidence_item["job_id"] and all(item.get("job_id") != evidence_item["job_id"] for item in evidence_rows):
            evidence_rows.append(evidence_item)
        evidence_rows = evidence_rows[-12:]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO role_skill_candidates
                (standard_job, skill_key, normalized_skill, kg_display_skill, skill_type, status,
                 first_seen_month, last_seen_month, support_job_ids_json, support_months_json,
                 evidence_json, cross_role_evidence_json, confirmation_reason, confirmation_route,
                 confirmed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(standard_job, skill_key) DO UPDATE SET
                    normalized_skill = excluded.normalized_skill,
                    kg_display_skill = excluded.kg_display_skill,
                    skill_type = excluded.skill_type,
                    status = excluded.status,
                    first_seen_month = CASE WHEN role_skill_candidates.status IN ('expired', 'rejected') OR role_skill_candidates.first_seen_month = '' THEN excluded.first_seen_month ELSE role_skill_candidates.first_seen_month END,
                    last_seen_month = excluded.last_seen_month,
                    support_job_ids_json = excluded.support_job_ids_json,
                    support_months_json = excluded.support_months_json,
                    evidence_json = excluded.evidence_json,
                    cross_role_evidence_json = excluded.cross_role_evidence_json,
                    confirmation_reason = CASE WHEN excluded.confirmation_reason <> '' THEN excluded.confirmation_reason ELSE role_skill_candidates.confirmation_reason END,
                    confirmation_route = CASE WHEN excluded.confirmation_route <> '' THEN excluded.confirmation_route ELSE role_skill_candidates.confirmation_route END,
                    confirmed_at = CASE WHEN excluded.status = 'confirmed' THEN excluded.confirmed_at ELSE role_skill_candidates.confirmed_at END,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_text(standard_job), key, clean_text(skill.normalized_skill), clean_text(skill.kg_display_skill),
                    clean_text(skill.skill_type), status, clean_text(posting.month), clean_text(posting.month),
                    json.dumps(sorted(value for value in job_ids if value), ensure_ascii=False),
                    json.dumps(sorted(months), ensure_ascii=False), json.dumps(evidence_rows, ensure_ascii=False),
                    json.dumps(cross_role_evidence, ensure_ascii=False), confirmation_reason, confirmation_route,
                    now if status == "confirmed" else "", now, now,
                ),
            )

    def _existing_evidence(self, standard_job: str, skill_key: str) -> list[dict[str, object]]:
        if not self.database_path.exists():
            return []
        with self._connect() as conn:
            row = conn.execute(
                "SELECT evidence_json FROM role_skill_candidates WHERE standard_job = ? AND skill_key = ?",
                (clean_text(standard_job), skill_key),
            ).fetchone()
        if row is None:
            return []
        try:
            value = json.loads(row[0] or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []

    def _serialize_row(self, row: dict[str, object]) -> dict[str, object]:
        job_ids = _json_list(row.get("support_job_ids_json"))
        months = _json_list(row.get("support_months_json"))
        evidence = _json_list(row.get("evidence_json"))
        cross_role_evidence = _json_object(row.get("cross_role_evidence_json"))
        return {
            "standard_job": clean_text(row.get("standard_job")),
            "skill": clean_text(row.get("normalized_skill")),
            "kg_display_skill": clean_text(row.get("kg_display_skill")),
            "skill_type": clean_text(row.get("skill_type")),
            "status": clean_text(row.get("status")),
            "first_seen_month": clean_text(row.get("first_seen_month")),
            "last_seen_month": clean_text(row.get("last_seen_month")),
            "support_job_ids": job_ids,
            "support_months": months,
            "support_job_count": len(job_ids),
            "support_month_count": len(months),
            "evidence": evidence,
            "cross_role_evidence": cross_role_evidence,
            "cross_role_support_job_count": _as_int(cross_role_evidence.get("peer_job_count")),
            "confirmation_reason": clean_text(row.get("confirmation_reason")),
            "confirmation_route": clean_text(row.get("confirmation_route")),
            "confirmed_at": clean_text(row.get("confirmed_at")),
            "updated_at": clean_text(row.get("updated_at")),
        }

    def _ensure_schema(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS role_skill_candidates (
                    standard_job TEXT NOT NULL,
                    skill_key TEXT NOT NULL,
                    normalized_skill TEXT NOT NULL,
                    kg_display_skill TEXT NOT NULL DEFAULT '',
                    skill_type TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('candidate', 'confirmed', 'expired', 'rejected')),
                    first_seen_month TEXT NOT NULL DEFAULT '',
                    last_seen_month TEXT NOT NULL DEFAULT '',
                    support_job_ids_json TEXT NOT NULL DEFAULT '[]',
                    support_months_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    cross_role_evidence_json TEXT NOT NULL DEFAULT '{}',
                    confirmation_reason TEXT NOT NULL DEFAULT '',
                    confirmation_route TEXT NOT NULL DEFAULT '',
                    confirmed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (standard_job, skill_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_role_skill_candidates_status ON role_skill_candidates(status, updated_at DESC)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(role_skill_candidates)").fetchall()}
            if "cross_role_evidence_json" not in columns:
                conn.execute("ALTER TABLE role_skill_candidates ADD COLUMN cross_role_evidence_json TEXT NOT NULL DEFAULT '{}'")
            if "confirmation_route" not in columns:
                conn.execute("ALTER TABLE role_skill_candidates ADD COLUMN confirmation_route TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _json_list(value: object) -> list:
    try:
        loaded = json.loads(str(value or "[]"))
        return loaded if isinstance(loaded, list) else []
    except json.JSONDecodeError:
        return []


def _json_object(value: object) -> dict[str, object]:
    try:
        loaded = json.loads(str(value or "{}"))
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _month_distance(start: str, end: str) -> int:
    start_year, start_month = (int(part) for part in start.split("-", 1))
    end_year, end_month = (int(part) for part in end.split("-", 1))
    return (end_year - start_year) * 12 + end_month - start_month


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
