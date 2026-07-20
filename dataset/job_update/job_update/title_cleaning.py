from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol

from .text import clean_text


class TitleCleaner(Protocol):
    def clean(self, job_title: str) -> str:
        ...


TITLE_CLEANING_PROMPT = """
你是招聘岗位名称清洗器。你的任务是从原始招聘标题中抽取“主岗位名称”，用于岗位语义匹配。

只删除不会改变岗位本身的修饰信息，例如：
- 产品名、项目名、游戏名、业务线名、公司名、部门名；
- 地点、招聘人数、薪资、编号、急招、外包、校招/社招、实习/兼职等招聘属性；
- 括号、书名号、破折号、斜杠前后的非岗位前后缀。

必须保留会改变岗位方向的技术或职能限定，例如：
- 大模型、AIGC、AI Infra、算法、推荐、搜索、数据、云原生、嵌入式、客户端、前端、后端、测试开发等；
- 语言、平台、端类型、工程方向等岗位核心限定。

不要把岗位名称映射成标准词典里的另一个岗位；只做清洗，不做归一化。
输出必须是 JSON，格式为：
{"cleaned_job_title":"...","removed_parts":["..."],"reason":"..."}
""".strip()


class LLMTitleCleaner:
    def __init__(
        self,
        *,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout: int = 60,
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

    def clean(self, job_title: str) -> str:
        raw_title = clean_text(job_title)
        if not raw_title:
            raise ValueError("job_title is required before title cleaning")

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key. Set ${self.api_key_env} before title cleaning.")

        result = self._api.call_chat_api(
            api_key=api_key,
            model=self.model,
            base_url=self.base_url,
            system_prompt=TITLE_CLEANING_PROMPT,
            user_payload={"raw_job_title": raw_title},
            timeout=self.timeout,
            retries=self.retries,
            temperature=self.temperature,
        )
        cleaned = clean_text(result.get("cleaned_job_title"))
        if not cleaned:
            raise RuntimeError(f"title cleaning returned empty cleaned_job_title. Result: {result}")
        return cleaned


def _ensure_dataset_on_path() -> None:
    dataset_dir = Path(__file__).resolve().parents[2]
    if str(dataset_dir) not in sys.path:
        sys.path.insert(0, str(dataset_dir))
