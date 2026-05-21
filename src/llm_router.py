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
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TIMPS_MODEL_PATH = os.getenv("TIMPS_MODEL_PATH", "sandeeprdy1729/TIMPS-Coder-0.5B")

# ── Cloud API keys (auto-detected from environment) ─────────────────────────
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")

# Gemini model used for agent calls (1.5-flash has the most generous free-tier quota)
GEMINI_MODEL    = os.getenv("TIMPS_GEMINI_MODEL",    "gemini-2.5-flash")
ANTHROPIC_MODEL = os.getenv("TIMPS_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
OPENAI_MODEL    = os.getenv("TIMPS_OPENAI_MODEL",    "gpt-4o-mini")
GROQ_MODEL      = os.getenv("TIMPS_GROQ_MODEL",      "llama-3.3-70b-versatile")

# ── MCP Sampling callback ────────────────────────────────────────────────────
# When an MCP client is connected, the server registers a callable here.
# LLMRouter.call() tries it first; falls back to cloud/Ollama when it returns None.
_MCP_SAMPLER: Optional[callable] = None


def set_mcp_sampler(fn: callable) -> None:
    """Register the MCP sampling callback (called by server.py on initialize)."""
    global _MCP_SAMPLER
    _MCP_SAMPLER = fn
    # Also register with the provider layer
    from src.providers.mcp_sampler import set_mcp_sampler as _set
    _set(fn)
    logger.warning("LLMRouter: MCP sampler registered — agents will use the caller's LLM")


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
    def __init__(self):
        self._timps_loaded = False
        self._timps_model = None
        self._timps_tokenizer = None

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
          7. Ollama         — local qwen2.5 models (fallback)
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
        if isinstance(provider, OllamaProvider):
            return provider.chat(
                prompt, system_prompt,
                model=model, temperature=temperature, format_json=format_json,
            )

        return provider.chat(
            prompt, system_prompt,
            temperature=temperature, max_tokens=8192, format_json=format_json,
        )

    # ── Gemini (Google AI) ───────────────────────────────────────────────────
    def _call_gemini(self, system: str, prompt: str) -> Optional[str]:
        """Call Google Gemini via REST API — no SDK dependency required."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system or "You are a helpful AI assistant."}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8192},
        }
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                import time
                logger.warning("Gemini rate-limited — waiting 10 s then retrying")
                time.sleep(10)
                resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
            )
        except Exception as exc:
            logger.warning("Gemini call failed: %s — falling through", exc)
            return None

    # ── Anthropic (Claude) ───────────────────────────────────────────────────
    def _call_anthropic(self, system: str, prompt: str) -> Optional[str]:
        """Call Anthropic Messages API — no SDK dependency required."""
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 8192,
                    "system": system or "You are a helpful AI assistant.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("content", [{}])[0].get("text", "")
        except Exception as exc:
            logger.warning("Anthropic call failed: %s — falling through", exc)
            return None

    # ── OpenAI ───────────────────────────────────────────────────────────────
    def _call_openai(self, system: str, prompt: str) -> Optional[str]:
        """Call OpenAI Chat Completions API — no SDK dependency required."""
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system or "You are a helpful AI assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.3,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("OpenAI call failed: %s — falling through", exc)
            return None

    # ── Ollama ────────────────────────────────────────────────────────
    def _call_ollama(
        self,
        model: str,
        system: str,
        prompt: str,
        temperature: float = 0.3,
        format_json: bool = False,
    ) -> str:
        payload: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system or "You are a helpful AI assistant."},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": temperature},
            "stream": False,
        }
        if format_json:
            payload["format"] = "json"

        try:
            resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
            if resp.status_code == 404 and model != "qwen2.5-coder:7b":
                # Requested model not installed — retry with the known-available model
                logger.warning("Ollama model %s not found — retrying with qwen2.5-coder:7b", model)
                payload["model"] = "qwen2.5-coder:7b"
                resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except Exception as exc:
            logger.error("Ollama call failed for model %s: %s", model, exc)
            return f"[ERROR] Ollama call failed: {exc}"

    # ── TIMPS-Coder (HuggingFace transformers / MLX) ─────────────────
    def _call_timps(self, prompt: str, system: str) -> str:
        if not self._timps_loaded:
            self._load_timps()

        if self._timps_model is None:
            # Fall back to Ollama coder
            logger.warning("TIMPS model not loaded — falling back to qwen2.5-coder:7b")
            return self._call_ollama("qwen2.5-coder:7b", system, prompt, 0.1)

        messages = [
            {"role": "system", "content": system or "You are TIMPS-Coder. Explain the bug cause then show the fixed code."},
            {"role": "user", "content": prompt},
        ]
        try:
            import torch
            text = self._timps_tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._timps_tokenizer(text, return_tensors="pt").to(
                self._timps_model.device
            )
            outputs = self._timps_model.generate(
                **inputs,
                max_new_tokens=1024,
                temperature=0.1,
                do_sample=True,
                pad_token_id=self._timps_tokenizer.eos_token_id,
            )
            return self._timps_tokenizer.decode(outputs[0], skip_special_tokens=True)
        except Exception as exc:
            logger.error("TIMPS generation failed: %s", exc)
            return self._call_ollama("qwen2.5-coder:7b", system, prompt, 0.1)

    def _load_timps(self):
        """Lazy-load TIMPS-Coder model."""
        self._timps_loaded = True
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            logger.info("Loading TIMPS-Coder from %s …", TIMPS_MODEL_PATH)
            self._timps_tokenizer = AutoTokenizer.from_pretrained(TIMPS_MODEL_PATH)
            self._timps_model = AutoModelForCausalLM.from_pretrained(
                TIMPS_MODEL_PATH,
                torch_dtype=torch.float16,
                device_map="auto",
            )
            logger.info("TIMPS-Coder loaded ✓")
        except Exception as exc:
            logger.warning("Could not load TIMPS-Coder: %s — using Ollama fallback", exc)
            self._timps_model = None
            self._timps_tokenizer = None


# Singleton
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
