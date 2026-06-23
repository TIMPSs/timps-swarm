"""OpenAI / GPT provider with connection pooling."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)


def _build_session(api_key: str) -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=50, max_retries=retries)
    session.mount("https://", adapter)
    session.headers.update({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    return session


class OpenAIProvider(ProviderInterface):
    description = "OpenAI GPT (cloud)"
    _API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.default_model = os.getenv("TIMPS_OPENAI_MODEL", "gpt-4o-mini")
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = _build_session(self.api_key)
        return self._session

    def is_available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        user: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        format_json: bool = False,
    ) -> str:
        mdl = model or self.default_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload: dict = {
            "model": mdl,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if format_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            resp = self._get_session().post(
                self._API_URL,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("OpenAI call failed: %s", exc)
            return ""
