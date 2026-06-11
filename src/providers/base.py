"""
ProviderInterface — abstract base class every LLM provider must implement.

All providers expose a single .chat() method. Agent code never needs to
know which backend is active — it just calls get_provider().chat(...).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ProviderError(Exception):
    """Raised when an LLM provider fails irrecoverably.

    Callers should catch this and handle gracefully (fall through to next
    provider, return raw data, etc.). The message should be user-facing.
    """


class ProviderInterface(ABC):
    """Minimal contract for every LLM provider."""

    # Human-readable description shown in `timps list-providers`
    description: str = "LLM Provider"
    # Default model name for this provider
    default_model: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider can be used right now (key set, server up, etc.)."""

    @abstractmethod
    def chat(
        self,
        user: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        format_json: bool = False,
    ) -> str:
        """
        Send a chat message and return the assistant's reply.

        Parameters
        ----------
        user        : The user turn content.
        system      : Optional system / instruction preamble.
        model       : Override the default model for this call.
        temperature : Sampling temperature (0 = deterministic).
        max_tokens  : Maximum response length in tokens.
        format_json : Hint to the provider that JSON output is expected.

        Note: format_json is fully supported by OllamaProvider and
        GeminiProvider. Other cloud providers (Anthropic, OpenAI, Groq)
        may ignore this hint — callers should not rely on it for structured
        output from those backends.

        Returns
        -------
        str — the assistant's response text (never None; empty string on error).
        """

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.default_model}, available={self.is_available()})"
