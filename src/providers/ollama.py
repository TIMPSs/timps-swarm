"""Ollama local provider — always available as final fallback."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


class OllamaProvider(ProviderInterface):
    description = "Ollama (local, offline)"
    default_model = "qwen2.5-coder:7b"

    def __init__(self):
        self._reachable: Optional[bool] = None

    def is_available(self) -> bool:
        # Always return True — even if Ollama is down we return an error string
        # rather than skipping. This keeps the fallback chain intact.
        return True

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
            "messages": [
                {"role": "system", "content": system or "You are a helpful AI assistant."},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        if format_json:
            payload["format"] = "json"
        try:
            resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
            if resp.status_code == 404 and mdl != "qwen2.5-coder:7b":
                logger.warning("Ollama model %s not found — retrying with qwen2.5-coder:7b", mdl)
                payload["model"] = "qwen2.5-coder:7b"
                resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except Exception as exc:
            logger.error("Ollama call failed for model %s: %s", mdl, exc)
            return f"[ERROR] Ollama call failed: {exc}"
