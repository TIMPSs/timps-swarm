"""Ollama local provider — always available as final fallback."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.providers.base import ProviderInterface, ProviderError

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

_MODEL_TIMEOUTS = {
    "14b": 240,
    "7b": 120,
    "3b": 60,
    "0.5b": 30,
}


def _timeout_for_model(model: str) -> int:
    for suffix, t in _MODEL_TIMEOUTS.items():
        if suffix in model:
            return t
    return 120


def _build_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(pool_maxsize=8, max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class OllamaProvider(ProviderInterface):
    description = "Ollama (local, offline — only used when actually running)"
    default_model = "qwen2.5-coder:7b"

    def __init__(self):
        self._reachable: Optional[bool] = None
        self._session = _build_session()

    def is_available(self) -> bool:
        """Return True only if Ollama server is actually reachable."""
        if self._reachable is None:
            try:
                resp = self._session.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
                self._reachable = resp.ok
            except Exception:
                self._reachable = False
        return self._reachable

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
        timeout = _timeout_for_model(mdl)
        payload: dict = {
            "model": mdl,
            "messages": [
                {"role": "system", "content": system or "You are a helpful AI assistant."},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        if format_json:
            payload["format"] = "json"

        last_exc = None
        for attempt in range(3):
            try:
                resp = self._session.post(
                    f"{OLLAMA_HOST}/api/chat", json=payload, timeout=timeout
                )
                if resp.status_code == 404 and mdl != "qwen2.5-coder:7b":
                    logger.warning("Ollama model %s not found — retrying with qwen2.5-coder:7b", mdl)
                    payload["model"] = "qwen2.5-coder:7b"
                    resp = self._session.post(
                        f"{OLLAMA_HOST}/api/chat", json=payload, timeout=timeout
                    )
                resp.raise_for_status()
                return resp.json().get("message", {}).get("content", "")
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Ollama call failed for model %s (attempt %d/3): %s",
                    mdl, attempt + 1, exc,
                )
                if attempt < 2:
                    time.sleep(1.0 * (2 ** attempt))

        self._reachable = False
        raise ProviderError(f"Ollama call failed for model {mdl}: {last_exc}")
