from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


class JsonLLMClient:
    """Shared strict JSON client backed by the project's configured LLM API."""

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
        job_update_root = Path(__file__).resolve().parents[1]
        company_root = job_update_root / "company_job_update"
        if str(company_root) not in sys.path:
            sys.path.insert(0, str(company_root))
        from skill_extract import extract_job_skills_api as api

        api.load_env_file()
        config = api.PROVIDERS[provider]
        self.model = model or os.getenv(config["model_env"], config["default_model"])
        self.base_url = base_url or os.getenv(config["base_url_env"], config["default_base_url"])
        self.api_key_env = api_key_env or config["api_key_env"]
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self._api = api

    def complete(self, *, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key. Set ${self.api_key_env} before calling the LLM.")
        result = self._api.call_chat_api(
            api_key=api_key,
            model=self.model,
            base_url=self.base_url,
            system_prompt=system_prompt,
            user_payload=payload,
            timeout=self.timeout,
            retries=self.retries,
            temperature=self.temperature,
        )
        if not isinstance(result, dict):
            raise RuntimeError("LLM did not return a JSON object")
        return result
