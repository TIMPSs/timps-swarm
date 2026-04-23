"""
Adapter Router — dynamically selects the best TIMPS-Coder LoRA adapter
based on the bug pattern described in the prompt.
"""
import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BASE_MODEL_PATH = os.getenv("TIMPS_MODEL_PATH", "sandeeprdy1729/TIMPS-Coder-0.5B")
ADAPTERS_DIR = os.getenv("ADAPTERS_DIR", "adapters")

# Keyword → adapter directory mapping
ADAPTER_MAP: dict[str, str] = {
    # Java
    "nullpointerexception":         "timps-java_npe",
    "null pointer":                 "timps-java_npe",
    "npe":                          "timps-java_npe",
    "indexoutofbounds":             "timps-java_ioob",
    "arrayindexoutofbounds":        "timps-java_ioob",
    "concurrentmodification":       "timps-java_concurrent",
    "thread":                       "timps-java_concurrent",
    "deadlock":                     "timps-java_concurrent",
    # Python
    "keyerror":                     "timps-python_keyerror",
    "key error":                    "timps-python_keyerror",
    "typeerror":                    "timps-python_typeerror",
    "type error":                   "timps-python_typeerror",
    "recursionerror":               "timps-python_recursion",
    "maximum recursion":            "timps-python_recursion",
    "asyncio":                      "timps-python_async",
    "event loop":                   "timps-python_async",
    "logic error":                  "timps-python_logic",
    "wrong output":                 "timps-python_logic",
    # JavaScript
    "undefined is not":             "timps-javascript_null",
    "cannot read properties":       "timps-javascript_null",
    "scope":                        "timps-javascript_scope",
    "closure":                      "timps-javascript_scope",
    "promise":                      "timps-javascript_async",
    "unhandled rejection":          "timps-javascript_async",
    # C++
    "segmentation fault":           "timps-cpp_memory",
    "segfault":                     "timps-cpp_memory",
    "memory leak":                  "timps-cpp_memory",
    "buffer overflow":              "timps-cpp_bounds",
    "stack overflow":               "timps-cpp_bounds",
    # Go / Rust
    "goroutine":                    "timps-go_routine",
    "channel":                      "timps-go_routine",
    "borrow checker":               "timps-rust_borrow",
    "lifetime":                     "timps-rust_borrow",
    # Security
    "sql injection":                "timps-sql_injection",
    "sqli":                         "timps-sql_injection",
    "xss":                          "timps-xss_vuln",
    "cross-site scripting":         "timps-xss_vuln",
    "authentication":               "timps-auth_bypass",
    "session":                      "timps-auth_bypass",
    "jwt":                          "timps-auth_bypass",
    # Performance / API
    "slow":                         "timps-performance_slow",
    "timeout":                      "timps-performance_slow",
    "n+1":                          "timps-performance_slow",
    "api design":                   "timps-api_design",
    "rest endpoint":                "timps-api_design",
    "openapi":                      "timps-api_design",
}


class AdapterRouter:
    """
    Selects and hot-swaps LoRA adapters on TIMPS-Coder at inference time.
    Falls back to base model if no adapter matches or adapter file is missing.
    """

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._current_adapter: Optional[str] = None
        self._loaded = False

    # ── Public API ────────────────────────────────────────────────────
    def select_adapter(self, prompt: str) -> Optional[str]:
        """Return adapter name for prompt, or None for base model."""
        prompt_lower = prompt.lower()
        best_adapter: Optional[str] = None
        best_score = 0

        for keyword, adapter in ADAPTER_MAP.items():
            # Count keyword occurrences as confidence score
            score = len(re.findall(re.escape(keyword), prompt_lower))
            if score > best_score:
                best_score = score
                best_adapter = adapter

        if best_score == 0:
            return None

        # Verify adapter directory exists
        path = os.path.join(ADAPTERS_DIR, best_adapter)
        if not os.path.isdir(path):
            logger.debug("Adapter dir missing: %s — using base model", path)
            return None

        return best_adapter

    def generate(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        """Select best adapter and generate output."""
        adapter = self.select_adapter(prompt)
        logger.debug("Selected adapter: %s", adapter or "base")

        self._ensure_loaded()

        if self._model is None:
            # No model available — return a placeholder
            return "[TIMPS-Coder not loaded — install transformers and a GPU/MPS device]"

        self._swap_adapter(adapter)

        messages = [
            {
                "role": "system",
                "content": system or "You are TIMPS-Coder. Explain the bug cause, then show the complete corrected code.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            import torch

            text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=0.1,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            return self._tokenizer.decode(outputs[0], skip_special_tokens=True)
        except Exception as exc:
            logger.error("Adapter generation error: %s", exc)
            return f"[ERROR] {exc}"

    # ── Private helpers ───────────────────────────────────────────────
    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            self._tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_PATH)
            self._model = AutoModelForCausalLM.from_pretrained(
                BASE_MODEL_PATH, torch_dtype=torch.float16, device_map="auto"
            )
        except Exception as exc:
            logger.warning("AdapterRouter: could not load base model: %s", exc)

    def _swap_adapter(self, adapter_name: Optional[str]):
        if adapter_name == self._current_adapter:
            return
        if self._model is None:
            return

        try:
            if adapter_name is None:
                if hasattr(self._model, "disable_adapters"):
                    self._model.disable_adapters()
            else:
                path = os.path.join(ADAPTERS_DIR, adapter_name)
                if hasattr(self._model, "load_adapter"):
                    self._model.load_adapter(path, adapter_name=adapter_name)
                    self._model.set_adapter(adapter_name)
            self._current_adapter = adapter_name
        except Exception as exc:
            logger.warning("Adapter swap failed (%s): %s — using current adapter", adapter_name, exc)


# Singleton
_adapter_router: Optional[AdapterRouter] = None


def get_adapter_router() -> AdapterRouter:
    global _adapter_router
    if _adapter_router is None:
        _adapter_router = AdapterRouter()
    return _adapter_router
