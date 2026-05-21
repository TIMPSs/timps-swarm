"""Anthropic / Claude provider."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)


class AnthropicProvider(ProviderInterface):
    description = "Anthropic Claude (cloud)"
    _API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.default_model = os.getenv("TIMPS_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

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
            resp = requests.post(
                self._API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("content", [{}])[0].get("text", "")
        except Exception as exc:
            logger.warning("Anthropic call failed: %s", exc)
            return ""
