"""
TIMPS Swarm — LLM Provider Package
===================================
Plug any LLM backend into the swarm without touching agent code.

Usage
-----
    from src.providers import get_provider, list_providers

    # Auto-select best available provider
    provider = get_provider()
    response = provider.chat(system="You are helpful.", user="Hello")

    # Pick a specific provider
    provider = get_provider("groq")
    response = provider.chat(system="You are helpful.", user="Hello")

Available providers (auto-detected from env vars)
--------------------------------------------------
    mcp       — MCP sampling (caller's own LLM)
    anthropic — Claude (ANTHROPIC_API_KEY)
    openai    — GPT-4o (OPENAI_API_KEY)
    gemini    — Gemini (GEMINI_API_KEY)
    groq      — Llama/Mixtral (GROQ_API_KEY)
    ollama    — Local Ollama (auto-detected; skipped if not running)
    timps     — Fine-tuned TIMPS-Coder 0.5B (explicit opt-in)
    null      — Graceful "no LLM" fallback (returns raw data)
"""

from __future__ import annotations

import os
from typing import Optional

from src.providers.base import ProviderInterface, ProviderError
from src.providers.ollama import OllamaProvider
from src.providers.anthropic import AnthropicProvider
from src.providers.openai import OpenAIProvider
from src.providers.gemini import GeminiProvider
from src.providers.groq import GroqProvider
from src.providers.timps import TIMPSProvider
from src.providers.mcp_sampler import MCPSamplerProvider
from src.providers.null import NullProvider

__all__ = [
    "ProviderInterface",
    "ProviderError",
    "OllamaProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "GroqProvider",
    "TIMPSProvider",
    "MCPSamplerProvider",
    "NullProvider",
    "get_provider",
    "list_providers",
    "registry",
]

# ── Singleton registry ────────────────────────────────────────────────────────

class _ProviderRegistry:
    """Lazily instantiated provider singletons."""

    def __init__(self):
        self._instances: dict[str, ProviderInterface] = {}

    def get(self, name: str) -> Optional[ProviderInterface]:
        if name not in self._instances:
            self._instances[name] = self._build(name)
        return self._instances[name]

    def _build(self, name: str) -> Optional[ProviderInterface]:
        mapping = {
            "mcp":       MCPSamplerProvider,
            "anthropic": AnthropicProvider,
            "openai":    OpenAIProvider,
            "gemini":    GeminiProvider,
            "groq":      GroqProvider,
            "ollama":    OllamaProvider,
            "timps":     TIMPSProvider,
            "null":      NullProvider,
        }
        cls = mapping.get(name)
        return cls() if cls else None

    def available(self) -> list[str]:
        """Return providers that have credentials / are reachable."""
        order = ["mcp", "gemini", "anthropic", "openai", "groq", "ollama", "timps"]
        return [p for p in order if self.get(p) and self.get(p).is_available()]

    def invalidate(self, name: str) -> None:
        """Force re-instantiation on next call (e.g. after env var change)."""
        self._instances.pop(name, None)


registry = _ProviderRegistry()


def get_provider(name: Optional[str] = None) -> ProviderInterface:
    """
    Return a ready provider.

    If *name* is given, return that specific provider (raises ValueError if unknown).
    Otherwise, walk the priority chain and return the first available one.
    NullProvider is the final fallback — returns a graceful "no LLM" message.
    """
    if name:
        p = registry.get(name)
        if p is None:
            raise ValueError(f"Unknown provider '{name}'. Known: {list_providers()}")
        return p

    for pname in registry.available():
        p = registry.get(pname)
        if p and p.is_available():
            return p

    # Hard fallback — NullProvider (graceful "no LLM available" message)
    return registry.get("null")


def list_providers() -> list[dict]:
    """Return status of all providers for the dashboard / CLI."""
    order = ["mcp", "gemini", "anthropic", "openai", "groq", "ollama", "timps"]
    result = []
    for name in order:
        p = registry.get(name)
        result.append({
            "name": name,
            "available": bool(p and p.is_available()),
            "model": p.default_model if p else "—",
            "description": p.description if p else "—",
        })
    return result
