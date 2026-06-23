"""Anthropic / Claude provider with connection pooling."""
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
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    return session


class AnthropicProvider(ProviderInterface):
    description = "Anthropic Claude (cloud)"
    _API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.default_model = os.getenv("TIMPS_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
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
        payload: dict = {
            "model": mdl,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            payload["system"] = system
        try:
            resp = self._get_session().post(
                self._API_URL,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("content", [{}])[0].get("text", "")
        except Exception as exc:
            logger.warning("Anthropic call failed: %s", exc)
            return ""
