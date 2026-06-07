"""MCP Sampling provider — uses the calling client's own LLM when available."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)

# Module-level callback — set by mcp_server/server.py on client initialize
_SAMPLER_FN: Optional[Callable[[str, str, int], Optional[str]]] = None
# Tracks whether the connected MCP client actually supports sampling
_CLIENT_SUPPORTS_SAMPLING: bool = False


def set_mcp_sampler(
    fn: Callable[[str, str, int], Optional[str]],
    supports_sampling: bool = False,
) -> None:
    """Register the MCP sampling callback and whether the client supports it."""
    global _SAMPLER_FN, _CLIENT_SUPPORTS_SAMPLING
    _SAMPLER_FN = fn
    _CLIENT_SUPPORTS_SAMPLING = supports_sampling
    if supports_sampling:
        logger.info("MCPSamplerProvider: sampler registered (client supports sampling)")
    else:
        logger.warning("MCPSamplerProvider: sampler callback set but client does NOT support sampling — provider will be skipped")


def clear_mcp_sampler() -> None:
    global _SAMPLER_FN, _CLIENT_SUPPORTS_SAMPLING
    _SAMPLER_FN = None
    _CLIENT_SUPPORTS_SAMPLING = False


class MCPSamplerProvider(ProviderInterface):
    """
    Delegates inference back to the MCP client's own LLM via
    sampling/createMessage.  Only active when an MCP client is connected
    and advertises sampling capability.
    """
    description = "MCP Sampling (caller's LLM)"
    default_model = "mcp-client"

    def is_available(self) -> bool:
        """Only available when sampler is registered AND client supports sampling."""
        return _SAMPLER_FN is not None and _CLIENT_SUPPORTS_SAMPLING

    def chat(
        self,
        user: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        format_json: bool = False,
    ) -> str:
        if not _SAMPLER_FN or not _CLIENT_SUPPORTS_SAMPLING:
            return ""
        try:
            result = _SAMPLER_FN(system or "You are a helpful AI assistant.", user, max_tokens)
            return result or ""
        except Exception as exc:
            logger.warning("MCP sampling failed: %s", exc)
            return ""
