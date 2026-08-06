from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Protocol

import pandas as pd

from shared.llm_json_client import JsonLLMClient
from shared.text_utils import clean_text


GOVERNMENT_TITLE_CLEANING_PROMPT = """
你是政府技术岗招聘标题清洗器。任务是从原始政府招录岗位名称中提取用于语义匹配的岗位名称。
只返回 JSON 对象：
{"cleaned_job_title":"...","removed_parts":["..."],"reason":"..."}

规则：
1. 删除地名、城市名、地区名、招录单位的前缀；例如“景德镇调查队综合执法科一级科员”应清洗为“调查队综合执法科一级科员”。
2. 保留岗位所属的业务科室、职能词和行政职级；它们可能是政府岗位区分技术职能的重要线索。
3. 不要根据职位简介、专业要求或常识把标题映射为标准岗位；这里只能清洗，不能分类、补全或改写职能。
4. 若标题本身没有可安全删除的部分，原样返回。
5. 不得返回空标题。
""".strip()


class GovernmentTitleCleaner(Protocol):
    def clean(self, job_title: str) -> dict[str, Any]:
        ...


class LLMGovernmentTitleCleaner:
    def __init__(self, client: JsonLLMClient) -> None:
        self.client = client

    def clean(self, job_title: str) -> dict[str, Any]:
        raw_title = clean_text(job_title)
        if not raw_title:
            raise ValueError("job_title is required before title cleaning")
        result = self.client.complete(
            system_prompt=GOVERNMENT_TITLE_CLEANING_PROMPT,
            payload={"raw_job_title": raw_title},
        )
        cleaned = clean_text(result.get("cleaned_job_title"))
        if not cleaned:
            raise RuntimeError(f"Government title cleaning returned an empty title: {result}")
        removed = result.get("removed_parts")
        return {
            "cleaned_job_title": cleaned,
            "removed_parts": [clean_text(value) for value in removed] if isinstance(removed, list) else [],
            "reason": clean_text(result.get("reason")),
        }


class GovernmentRoutingTitleCleaner:
    """Service adapter: the routing engine needs the cleaned title string only."""

    def __init__(self, cleaner: LLMGovernmentTitleCleaner) -> None:
        self.cleaner = cleaner

    def clean(self, job_title: str) -> str:
        return clean_text(self.cleaner.clean(job_title)["cleaned_job_title"])


def apply_government_title_cleaning(
    postings: pd.DataFrame,
    *,
    cleaner: GovernmentTitleCleaner,
    cache_path: Path,
    progress: Callable[[int, int], None] | None = None,
    workers: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "job_title" not in postings.columns:
        raise ValueError("Government postings must include job_title")
    cache = _load_cache(cache_path)
    rows: list[dict[str, Any]] = []
    unique_titles = sorted({clean_text(value) for value in postings["job_title"] if clean_text(value)})
    missing_titles = [raw_title for raw_title in unique_titles if raw_title not in cache]
    completed = len(unique_titles) - len(missing_titles)
    if progress is not None and completed:
        progress(completed, len(unique_titles))
    if missing_titles:
        if workers < 1:
            raise ValueError("workers must be at least 1")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(cleaner.clean, raw_title): raw_title for raw_title in missing_titles}
            for future in as_completed(futures):
                cache[futures[future]] = future.result()
                completed += 1
                if progress is not None:
                    progress(completed, len(unique_titles))
    _write_cache(cache_path, cache)

    cleaned = postings.copy()
    cleaned["cleaned_job_title"] = cleaned["job_title"].map(
        lambda value: cache[clean_text(value)]["cleaned_job_title"]
    )
    for raw_title, result in sorted(cache.items()):
        rows.append(
            {
                "raw_job_title": raw_title,
                "cleaned_job_title": result["cleaned_job_title"],
                "removed_parts": json.dumps(result["removed_parts"], ensure_ascii=False),
                "reason": result["reason"],
                "posting_count": int((postings["job_title"].map(clean_text) == raw_title).sum()),
            }
        )
    return cleaned, pd.DataFrame(rows)


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        raw_title = clean_text(item.get("raw_job_title"))
        cleaned = clean_text(item.get("cleaned_job_title"))
        if raw_title and cleaned:
            cache[raw_title] = {
                "cleaned_job_title": cleaned,
                "removed_parts": item.get("removed_parts") if isinstance(item.get("removed_parts"), list) else [],
                "reason": clean_text(item.get("reason")),
            }
    return cache


def _write_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"raw_job_title": raw_title, **result}, ensure_ascii=False)
        for raw_title, result in sorted(cache.items())
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
