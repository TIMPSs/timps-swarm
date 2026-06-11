"""
Shared helpers used by every agent package.
Import with: from src._helpers import _ts, _llm, _strip_fences, _save, _run
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_GEN = Path(os.getenv("GENERATED_DIR", "generated"))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _llm(prompt: str, system: str, agent: str = "default") -> str:
    try:
        from src.llm_router import LLMRouter
        return LLMRouter().call(agent, prompt, system)
    except Exception as exc:
        logger.error("LLM error [%s]: %s", agent, exc)
        return (
            "[No LLM provider available — raw data follows]\n\n"
            f"Agent `{agent}` could not reach any LLM. "
            "The agent has gathered data below. "
            "To enable AI analysis, connect via an MCP client that supports sampling "
            "(e.g. Claude Code), or set an API key (GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.).\n\n"
            f"{prompt[:5000]}"
        )


def _strip_fences(text: str, lang: str = "") -> str:
    pattern = rf"```{re.escape(lang)}\s*([\s\S]*?)```"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else text.strip()


def _save(sub: str, name: str, content: str) -> str:
    path = _GEN / sub / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run(cmd: str, cwd: Optional[str] = None, timeout: int = 60) -> str:
    try:
        args = shlex.split(cmd)
        r = subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, cwd=cwd or os.getcwd()
        )
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as exc:
        return f"Error: {exc}"


def _parse_json(raw: str, fallback: Any = None) -> Any:
    try:
        return json.loads(_strip_fences(raw, "json"))
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else {}


def _record(agent_name: str, request: str, summary: str) -> None:
    try:
        from src.memory import record_run
        record_run(agent_name=agent_name, request=request, summary=summary[:500])
    except Exception:
        pass
