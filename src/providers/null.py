"""
NullProvider — always-available fallback that returns a graceful message
when no real LLM provider is reachable.

This ensures the provider chain never raises an exception; agents always
get something back that they can display as raw data.
"""
from __future__ import annotations

import os
from typing import Optional

from src.providers.base import ProviderInterface


class NullProvider(ProviderInterface):
    """
    Final fallback when MCP sampling, cloud APIs, and local Ollama are all
    unavailable.  Returns a clear message telling the caller no LLM is
    available, so agents know to return raw data instead of crashing.
    """
    description = "No LLM available (return raw data only)"
    default_model = "none"

    def is_available(self) -> bool:
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
        tried = []
        if not os.getenv("GEMINI_API_KEY"):
            tried.append("- Gemini: GEMINI_API_KEY not set")
        if not os.getenv("ANTHROPIC_API_KEY"):
            tried.append("- Anthropic: ANTHROPIC_API_KEY not set")
        if not os.getenv("OPENAI_API_KEY"):
            tried.append("- OpenAI: OPENAI_API_KEY not set")
        if not os.getenv("GROQ_API_KEY"):
            tried.append("- Groq: GROQ_API_KEY not set")
        tried.append("- Ollama: not running or unreachable")
        tried.append("- TIMPS-Coder: model not loaded")

        return (
            "[No LLM provider available — falling back to raw data]\n\n"
            "None of the configured LLM providers are reachable:\n"
            + "\n".join(tried) + "\n\n"
            "The agent has gathered system data / scanned files below. "
            "To enable AI-powered analysis, either:\n"
            "1. Use an MCP client that supports sampling (e.g. Claude Code)\n"
            "2. Set an API key: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, or GROQ_API_KEY\n"
            "3. Install Ollama (ollama.com) and pull a model: ollama pull qwen2.5-coder:7b\n\n"
            "Raw data follows:\n\n" + (user[:8000] if user else "")
        )
