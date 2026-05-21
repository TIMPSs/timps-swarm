"""OpenAI / GPT provider."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)


class OpenAIProvider(ProviderInterface):
    description = "OpenAI GPT (cloud)"
    _API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.default_model = os.getenv("TIMPS_OPENAI_MODEL", "gpt-4o-mini")

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
            resp = requests.post(
                self._API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("OpenAI call failed: %s", exc)
            return ""
