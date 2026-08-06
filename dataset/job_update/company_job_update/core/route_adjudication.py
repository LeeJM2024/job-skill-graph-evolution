from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys
from pathlib import Path
from typing import Any, Protocol

from .models import JobPosting, RouteStatus, ScoredCandidate
from .text import clean_text


ROUTE_ADJUDICATION_PROMPT = """
你是中文招聘系统里的保守型岗位路由二次裁决器。
目标是判断一条招聘启事能否归入已有标准岗位。

只返回一个 JSON 对象：
{
  "route_status": "existing_job|potential_new_job|new_family",
  "selected_standard_job": "...",
  "selected_category": "...",
  "confidence": 0.0,
  "evidence": ["..."],
  "reason": "..."
}

规则：
- 只有岗位核心职业身份与某个候选标准岗位明确一致，才返回 existing_job。
- route_status 为 existing_job 时，selected_standard_job 必须完全等于候选列表里的 standard_job。
- 候选大族相关但具体岗位边界不清时，返回 potential_new_job。
- 明显不属于候选大族时，返回 new_family。
- 不要因为产品线、业务场景、地点、职级、实习、专家、负责人、单个工具或框架，把岗位拆成另一个更细岗位。
- 不要默认选择最细岗位；更细岗位只有在 JD 核心职责反复指向该方向时才能选。
- RAG、Prompt、LLM 接入和业务系统中的大模型功能落地，通常属于大模型应用工程师。
- Agent 编排、工具调用、记忆、多 Agent 工作流、Agent 平台开发，才属于 AI Agent应用工程师。
- Agent 规划、Agent 训练、Tool Use、Agent RL、多智能体算法研究，才属于 AI Agent算法工程师。
- 多模态只是技术方向时，不要自动改成多模态算法工程师；核心职责是跨模态建模/视觉语言模型/多模态生成理解时才选择。
- 搜索、广告、推荐只是业务场景时，不要自动改成搜索/广告/推荐算法工程师；核心是该业务算法体系时才选择。
- AI Infra 只覆盖训练/推理优化、模型部署、算力平台、GPU/集群、ML 系统和基础设施。
""".strip()


@dataclass(slots=True)
class RouteAdjudicationDecision:
    route_status: RouteStatus
    selected_standard_job: str = ""
    selected_category: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    reason: str = ""


class RouteAdjudicator(Protocol):
    def adjudicate(
        self,
        *,
        posting: JobPosting,
        routing_job_title: str,
        text2vec_summary: dict[str, Any],
        candidate_jobs: list[ScoredCandidate],
    ) -> RouteAdjudicationDecision:
        ...


class LLMRouteAdjudicator:
    def __init__(
        self,
        *,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout: int = 90,
        retries: int = 2,
        temperature: float = 0.0,
    ) -> None:
        _ensure_dataset_on_path()

        from skill_extract import extract_job_skills_api as api

        api.load_env_file()
        provider_config = api.PROVIDERS[provider]
        self.provider = provider
        self.model = model or os.getenv(provider_config["model_env"], provider_config["default_model"])
        self.base_url = base_url or os.getenv(provider_config["base_url_env"], provider_config["default_base_url"])
        self.api_key_env = api_key_env or provider_config["api_key_env"]
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self._api = api

    def adjudicate(
        self,
        *,
        posting: JobPosting,
        routing_job_title: str,
        text2vec_summary: dict[str, Any],
        candidate_jobs: list[ScoredCandidate],
    ) -> RouteAdjudicationDecision:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key. Set ${self.api_key_env} before route adjudication.")

        result = self._api.call_chat_api(
            api_key=api_key,
            model=self.model,
            base_url=self.base_url,
            system_prompt=ROUTE_ADJUDICATION_PROMPT,
            user_payload={
                "job": {
                    "job_id": posting.job_id,
                    "raw_job_title": clean_text(posting.job_title),
                    "cleaned_job_title": clean_text(routing_job_title),
                    "job_responsibility": truncate_text(posting.job_responsibility, 1300),
                    "job_requirement": truncate_text(posting.job_requirement, 1700),
                },
                "text2vec_summary": text2vec_summary,
                "candidate_standard_jobs": [
                    {
                        "standard_job": candidate.name,
                        "category": clean_text(candidate.metadata.get("category")),
                        "score": round(candidate.score, 6),
                        "match_keywords": clean_text(candidate.metadata.get("match_keywords")),
                    }
                    for candidate in candidate_jobs
                ],
            },
            timeout=self.timeout,
            retries=self.retries,
            temperature=self.temperature,
        )
        return normalize_decision(result, candidate_jobs)


def normalize_decision(
    result: dict[str, Any],
    candidate_jobs: list[ScoredCandidate],
) -> RouteAdjudicationDecision:
    status = clean_text(result.get("route_status"))
    if status not in {"existing_job", "potential_new_job", "new_family"}:
        status = "potential_new_job"

    selected_job = clean_text(result.get("selected_standard_job"))
    candidate_by_name = {candidate.name: candidate for candidate in candidate_jobs}
    if status == "existing_job" and selected_job not in candidate_by_name:
        status = "potential_new_job"
        selected_job = ""

    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0

    evidence = result.get("evidence") if isinstance(result.get("evidence"), list) else []
    selected_category = clean_text(result.get("selected_category"))
    if selected_job and not selected_category:
        selected_category = clean_text(candidate_by_name[selected_job].metadata.get("category"))

    return RouteAdjudicationDecision(
        route_status=status,
        selected_standard_job=selected_job,
        selected_category=selected_category,
        confidence=confidence,
        evidence=[clean_text(item) for item in evidence[:5] if clean_text(item)],
        reason=clean_text(result.get("reason")),
    )


def truncate_text(value: Any, limit: int) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _ensure_dataset_on_path() -> None:
    company_root = Path(__file__).resolve().parents[1]
    if str(company_root) not in sys.path:
        sys.path.insert(0, str(company_root))
