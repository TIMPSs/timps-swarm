"""Google Gemini provider with connection pooling."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=50, max_retries=retries)
    session.mount("https://", adapter)
    return session


class GeminiProvider(ProviderInterface):
    description = "Google Gemini (cloud)"
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.default_model = os.getenv("TIMPS_GEMINI_MODEL", "gemini-2.5-flash")
        self._session: requests.Session | None = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = _build_session()
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
        url = f"{self._BASE_URL}/{mdl}:generateContent?key={self.api_key}"
        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system:
            payload["system_instruction"] = {
                "parts": [{"text": system}]
            }
        if format_json:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        try:
            resp = self._get_session().post(url, json=payload, timeout=120)
            if resp.status_code == 429:
                logger.warning("Gemini rate-limited — waiting 10 s")
                time.sleep(10)
                resp = self._get_session().post(url, json=payload, timeout=120)
            resp.raise_for_status()
            return (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
        except Exception as exc:
            logger.warning("Gemini call failed: %s", exc)
            return ""
