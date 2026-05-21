"""MCP Sampling provider — uses the calling client's own LLM when available."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)

# Module-level callback — set by mcp_server/server.py on client initialize
_SAMPLER_FN: Optional[Callable[[str, str, int], Optional[str]]] = None


def set_mcp_sampler(fn: Callable[[str, str, int], Optional[str]]) -> None:
    global _SAMPLER_FN
    _SAMPLER_FN = fn
    logger.info("MCPSamplerProvider: sampler registered")


def clear_mcp_sampler() -> None:
    global _SAMPLER_FN
    _SAMPLER_FN = None


class MCPSamplerProvider(ProviderInterface):
    """
    Delegates inference back to the MCP client's own LLM via
    sampling/createMessage.  Only active when an MCP client is connected
    and advertises sampling capability.
    """
    description = "MCP Sampling (caller's LLM)"
    default_model = "mcp-client"

    def is_available(self) -> bool:
        return _SAMPLER_FN is not None

    def chat(
        self,
        user: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        format_json: bool = False,
    ) -> str:
        if not _SAMPLER_FN:
            return ""
        try:
            result = _SAMPLER_FN(system or "You are a helpful AI assistant.", user, max_tokens)
            return result or ""
        except Exception as exc:
            logger.warning("MCP sampling failed: %s", exc)
            return ""
