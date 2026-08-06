from __future__ import annotations

from pathlib import Path
from typing import Any

from company_job_update.core.skill_extraction import ExistingSkillExtractAdapter


GOVERNMENT_EXTRACTION_PROMPT_APPENDIX = """
Government technical-posting domain rules:
1. This is a Chinese government, public-security, public-institution, or public-service technical posting. Extract
   only explicit information and computing technical skills. Treat qualifications, responsibilities, and requirements
   as evidence only when they state a concrete technical field, method, platform, system, tool, protocol, or capability.
2. Typical in-scope skills include government information systems and digital-government platforms; data governance,
   data catalogues, data exchange, data quality, databases, statistics/data analysis when technical; network, system,
   cloud, communications, and operations work; cybersecurity, cryptography, classified-protection, incident response,
   electronic forensics; GIS, remote sensing, intelligence technology, AI, automation, and IoT.
3. Never extract administrative work as a technical skill: comprehensive coordination, policy research, drafting official
   documents, organizational management, public communication, law enforcement, case handling, public service,
   inspection, supervision, campaign work, confidentiality awareness, political quality, or generic work experience.
4. A government business domain is not itself a skill. For example, extract an explicit database, data-governance
   platform, GIS, encryption technology, or electronic-forensics technique, but not merely public security, taxation,
   market regulation, investigation, statistics reporting, or digital-government service.
5. Do not infer skills from an agency name, department name, job rank, or job title alone. Every output must have a
   directly supported technical evidence span in the JD.
6. Split an explicit compound technical capability into its reusable components when both are stated. For example,
   "信息系统建设与运维" should yield information-system construction and system operations/maintenance; "网络与信息
   安全基础" should yield information security. Words such as "基础", "熟悉", and "了解" describe proficiency and
   must not become part of the normalized skill name.
""".strip()


GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX = """
Government technical-skill normalization rules:
1. Normalize only skills that describe reusable information/communications/security/data/AI/spatial-information
   technologies or methods used in government technical work.
2. Reject administrative, legal-enforcement, policy, document-writing, organizational, public-affairs, and generic
   professional-quality phrases. They are job duties, not technology KG nodes.
3. When a phrase is only a government domain or agency function, reject it unless the evidence names a concrete
   technical system, method, platform, protocol, standard, tool, or technical discipline.
4. Prefer an existing government normalized skill whenever it is genuinely equivalent. A new skill may be proposed
   only when it is a stable, reusable government-relevant technical node and must remain a review candidate.
5. Normalize "信息系统建设" to "信息化建设", and operations/maintenance wording to "系统运维" when supported by
   the evidence. Normalize "网络与信息安全" to "信息安全". Do not preserve qualifiers such as "基础" in a skill name.
""".strip()


class GovernmentSkillExtractAdapter(ExistingSkillExtractAdapter):
    """Use the shared LLM extraction pipeline with government-only dictionaries."""

    def __init__(
        self,
        *,
        extraction_dictionary: Path,
        cache_path: Path,
        normalization_cache_path: Path,
        provider: str = "deepseek",
        **config_overrides: Any,
    ) -> None:
        super().__init__(
            provider=provider,
            gold_path=extraction_dictionary,
            extraction_dictionary=extraction_dictionary,
            cache_path=cache_path,
            normalization_cache_path=normalization_cache_path,
            system_prompt_appendix=GOVERNMENT_EXTRACTION_PROMPT_APPENDIX,
            normalization_prompt_appendix=GOVERNMENT_NORMALIZATION_PROMPT_APPENDIX,
            **config_overrides,
        )
