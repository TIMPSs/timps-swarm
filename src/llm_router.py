"""
LLM Router — routes agent requests to the appropriate model.

Hierarchy:
  - TIMPS-Coder (0.5B via HuggingFace/MLX) → bug fixes
  - qwen2.5:14b  (Ollama)                   → orchestrator, architect
  - qwen2.5:7b   (Ollama)                   → reviewers, QA, security
  - qwen2.5-coder:7b (Ollama)               → general code generation
  - qwen2.5:3b   (Ollama)                   → documentation
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
TIMPS_MODEL_PATH = os.getenv("TIMPS_MODEL_PATH", "sandeeprdy1729/TIMPS-Coder-0.5B")

# Map agent name → (model, temperature)
AGENT_MODEL_MAP = {
    "orchestrator":           ("qwen2.5:14b", 0.2),
    "product_manager":        ("qwen2.5:7b",  0.3),
    "architect":              ("qwen2.5:14b", 0.2),
    "code_generator":         ("qwen2.5-coder:7b", 0.1),
    "code_reviewer":          ("qwen2.5:7b",  0.2),
    "qa_tester":              ("qwen2.5-coder:7b", 0.1),
    "security_auditor":       ("qwen2.5:7b",  0.1),
    "performance_optimizer":  ("qwen2.5:7b",  0.2),
    "documentation_writer":   ("qwen2.5:3b",  0.4),
    "devops":                 ("qwen2.5:7b",  0.1),
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
        """Route call to the correct model."""
        if use_timps:
            return self._call_timps(prompt, system_prompt)

        model, temperature = AGENT_MODEL_MAP.get(agent_name, ("qwen2.5:7b", 0.3))
        return self._call_ollama(model, system_prompt, prompt, temperature, format_json)

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
            resp = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=120,
            )
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
