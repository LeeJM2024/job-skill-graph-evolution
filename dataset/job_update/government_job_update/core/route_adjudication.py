from __future__ import annotations

from typing import Any

from company_job_update.core.models import JobPosting, ScoredCandidate
from company_job_update.core.route_adjudication import RouteAdjudicationDecision, normalize_decision, truncate_text
from shared.llm_json_client import JsonLLMClient
from shared.text_utils import clean_text


GOVERNMENT_ROUTE_ADJUDICATION_PROMPT = """
你是政府计算机技术岗位招聘系统的保守型岗位路由二次裁决器。
请判断一条政府招录信息是否能归入现有的政府标准岗位。只返回 JSON：
{"route_status":"existing_job|potential_new_job|new_family","selected_standard_job":"...","selected_category":"...","confidence":0.0,"evidence":["..."],"reason":"..."}

规则：
- 职位名称向量匹配只用于产生候选；请结合职位简介、专业要求和候选词典做最终判断。
- 只有核心工作职能与一个候选岗位明确一致时，才返回 existing_job；selected_standard_job 必须完全等于候选列表中的名称。
- 候选大类相关但职能边界不清，返回 potential_new_job；明显不是现有大类，返回 new_family。
- 不得因为地区、招录机关、单位层级、科室名称、一级主任科员及以下等行政修饰把同一技术职能拆成新岗位。
- 不要用“计算机类”“软件工程”等专业名称直接替代岗位职能；它们只能作为辅助证据。
- 不确定时宁可返回 potential_new_job，不能强行写入正式政府事件流。
""".strip()


class GovernmentRouteAdjudicator:
    def __init__(self, client: JsonLLMClient) -> None:
        self.client = client

    def adjudicate(
        self,
        *,
        posting: JobPosting,
        routing_job_title: str,
        text2vec_summary: dict[str, Any],
        candidate_jobs: list[ScoredCandidate],
    ) -> RouteAdjudicationDecision:
        result = self.client.complete(
            system_prompt=GOVERNMENT_ROUTE_ADJUDICATION_PROMPT,
            payload={
                "job": {
                    "job_id": clean_text(posting.job_id),
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
        )
        return normalize_decision(result, candidate_jobs)
