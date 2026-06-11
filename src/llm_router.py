"""
LLM Router — routes agent requests to the appropriate model.

This module is now a thin façade over src.providers.ProviderInterface.
All provider logic lives in src/providers/*.py.

Priority (highest → lowest):
  1. MCP sampling     — use the calling tool's own LLM (if it supports sampling)
  2. Gemini API       — if GEMINI_API_KEY is set
  3. Anthropic API    — if ANTHROPIC_API_KEY is set
  4. OpenAI API       — if OPENAI_API_KEY is set
  5. Groq API         — if GROQ_API_KEY is set
  6. TIMPS-Coder      — fine-tuned 0.5B HuggingFace model for bug patterns
  7. Ollama           — local qwen2.5 models (fallback)
"""
import logging
import os
from typing import Optional

from src.providers.base import ProviderError

logger = logging.getLogger(__name__)

# ── MCP Sampling callback ────────────────────────────────────────────────────
# When an MCP client is connected, the server registers a callable here.
# LLMRouter.call() tries it first; falls back to cloud/Ollama when it returns None.
_MCP_SAMPLER: Optional[callable] = None


def set_mcp_sampler(fn: callable, supports_sampling: bool = False) -> None:
    """Register the MCP sampling callback (called by server.py on initialize)."""
    global _MCP_SAMPLER
    _MCP_SAMPLER = fn
    # Also register with the provider layer
    from src.providers.mcp_sampler import set_mcp_sampler as _set
    _set(fn, supports_sampling=supports_sampling)
    if supports_sampling:
        logger.warning("LLMRouter: MCP sampler registered — agents will use the caller's LLM")
    else:
        logger.warning("LLMRouter: MCP sampler registered but client does NOT support sampling — will fall through")


def clear_mcp_sampler() -> None:
    global _MCP_SAMPLER
    _MCP_SAMPLER = None

# Map agent name → (model, temperature)
AGENT_MODEL_MAP = {
    # ── SDLC pipeline (10 agents) ────────────────────────────────────────────
    "orchestrator":           ("qwen2.5:14b",       0.2),
    "product_manager":        ("qwen2.5:7b",        0.3),
    "architect":              ("qwen2.5:14b",       0.2),
    "code_generator":         ("qwen2.5-coder:7b",  0.1),
    "code_reviewer":          ("qwen2.5:7b",        0.2),
    "qa_tester":              ("qwen2.5-coder:7b",  0.1),
    "security_auditor":       ("qwen2.5:7b",        0.1),
    "performance_optimizer":  ("qwen2.5:7b",        0.2),
    "documentation_writer":   ("qwen2.5:3b",        0.4),
    "devops":                 ("qwen2.5:7b",        0.1),

    # ── Computer Health pipeline (12 agents) ────────────────────────────────
    # Needs deeper reasoning → 14b/7b models
    "system_optimizer":       ("qwen2.5:7b",        0.2),
    "file_organizer":         ("qwen2.5:7b",        0.3),
    "environment_doctor":     ("qwen2.5-coder:7b",  0.1),
    "security_guard":         ("qwen2.5:7b",        0.1),
    "network_medic":          ("qwen2.5:7b",        0.2),
    "battery_analyst":        ("qwen2.5:3b",        0.2),
    "update_manager":         ("qwen2.5:7b",        0.2),
    "log_interpreter":        ("qwen2.5:14b",       0.1),  # crash logs need max context
    "privacy_cleaner":        ("qwen2.5:3b",        0.3),
    "media_librarian":        ("qwen2.5:7b",        0.3),
    "backup_sentinel":        ("qwen2.5:7b",        0.2),
    "context_switcher":       ("qwen2.5:7b",        0.3),

    # ── Context & Kernel agents ───────────────────────────────────────────────
    "context_keeper":         ("qwen2.5:14b",       0.1),  # needs full context window

    # ── Expert / Deep-Diagnostic agents ─────────────────────────────────────
    "dependency_rebel":          ("qwen2.5-coder:7b", 0.1),
    "merge_conflict_predictor":  ("qwen2.5:7b",       0.2),
    "tech_debt_quantifier":      ("qwen2.5:14b",      0.2),
    "migration_pilot":           ("qwen2.5:14b",      0.2),
    "flaky_test_detective":      ("qwen2.5-coder:7b", 0.1),
    "onboarding_mentor":         ("qwen2.5:14b",      0.3),
    "incident_responder":        ("qwen2.5:14b",      0.1),
    "cloud_cost_auditor":        ("qwen2.5:7b",       0.2),
    "certificate_rotator":       ("qwen2.5:7b",       0.1),
    "terraform_plan_reviewer":   ("qwen2.5:7b",       0.1),
    "dotfile_doctor":            ("qwen2.5:7b",       0.2),
    "disk_space_prophet":        ("qwen2.5:3b",       0.2),

    # ── Developer Swarm agents (src/developer_swarm_agents.py) ──────────────
    "issue_triager":             ("qwen2.5:7b",        0.2),
    "boilerplate_architect":     ("qwen2.5:14b",       0.2),
    "pr_reviewer":               ("qwen2.5:7b",        0.2),
    "dependency_sentinel":       ("qwen2.5-coder:7b",  0.1),
    "unit_test_writer":          ("qwen2.5-coder:7b",  0.1),
    "docstring_generator":       ("qwen2.5:3b",        0.3),
    "log_detective":             ("qwen2.5:14b",       0.1),
    "sql_optimizer":             ("qwen2.5:14b",       0.1),
    "sprint_reporter":           ("qwen2.5:3b",        0.4),
    "flaky_test_hunter":         ("qwen2.5-coder:7b",  0.1),
    "api_contract_auditor":      ("qwen2.5:14b",       0.1),
    "content_multiplier":        ("qwen2.5:7b",        0.5),

    # ── Knowledge Worker agents (src/knowledge_swarm_agents.py) ─────────────
    "inbox_gatekeeper":          ("qwen2.5:7b",        0.3),
    "meeting_condenser":         ("qwen2.5:7b",        0.3),
    "calendar_tetris":           ("qwen2.5:3b",        0.2),
    "research_scout":            ("qwen2.5:14b",       0.2),
    "trend_monitor":             ("qwen2.5:7b",        0.3),
    "data_wrangler":             ("qwen2.5-coder:7b",  0.1),
    "expense_auditor":           ("qwen2.5:7b",        0.1),
    "reference_checker":         ("qwen2.5:14b",       0.2),
    "client_liaison":            ("qwen2.5:7b",        0.3),
    "competitor_tracker":        ("qwen2.5:14b",       0.2),

    # ── NEW priority agents (Phase 3) ────────────────────────────────────────
    "research_agent":            ("qwen2.5:14b",       0.2),   # web research before coding
    "api_design_agent":          ("qwen2.5:14b",       0.1),   # OpenAPI spec generation
    "db_agent":                  ("qwen2.5:14b",       0.1),   # schema design + query opt
    "dependency_agent":          ("qwen2.5-coder:7b",  0.1),   # pip-audit / npm audit
    "n8n_workflow_agent":        ("qwen2.5:14b",       0.3),   # n8n JSON workflow gen
}


class LLMRouter:
    def call(
        self,
        agent_name: str,
        prompt: str,
        system_prompt: str = "",
        use_timps: bool = False,
        format_json: bool = False,
    ) -> str:
        """Route call to the correct model via the provider abstraction layer.

        Priority:
          1. MCP sampling   — delegate to calling tool's own LLM (if supported)
          2. Gemini API     — if GEMINI_API_KEY is in the environment
          3. Anthropic API  — if ANTHROPIC_API_KEY is in the environment
          4. OpenAI API     — if OPENAI_API_KEY is in the environment
          5. Groq API       — if GROQ_API_KEY is in the environment
          6. TIMPS-Coder    — fine-tuned 0.5B model for bug patterns (opt-in)
          7. Ollama         — local qwen2.5 models (only if actually running)
          8. NullProvider   — graceful "no LLM available" message (always available)
        """
        from src.providers import get_provider, registry

        # TIMPS-Coder explicit opt-in bypasses the normal priority chain
        if use_timps:
            return registry.get("timps").chat(prompt, system_prompt, format_json=format_json)

        # Walk the provider priority chain via ProviderInterface
        model, temperature = AGENT_MODEL_MAP.get(agent_name, ("qwen2.5-coder:7b", 0.3))
        provider = get_provider()  # auto-selects best available

        # For Ollama we pass the agent-specific model; other providers use their defaults
        from src.providers.ollama import OllamaProvider
        try:
            if isinstance(provider, OllamaProvider):
                return provider.chat(
                    prompt, system_prompt,
                    model=model, temperature=temperature, format_json=format_json,
                )
            return provider.chat(
                prompt, system_prompt,
                temperature=temperature, max_tokens=8192, format_json=format_json,
            )
        except ProviderError as exc:
            logger.warning("Provider error for %s: %s", agent_name, exc)
            return f"[No LLM provider available — {exc}]"

# Singleton
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
