"""TIMPS-Coder fine-tuned 0.5B HuggingFace model provider."""
from __future__ import annotations

import logging
import os
from typing import Optional

from src.providers.base import ProviderInterface

logger = logging.getLogger(__name__)

TIMPS_MODEL_PATH = os.getenv("TIMPS_MODEL_PATH", "sandeeprdy1729/TIMPS-Coder-0.5B")


class TIMPSProvider(ProviderInterface):
    description = "TIMPS-Coder 0.5B (local fine-tune)"
    default_model = TIMPS_MODEL_PATH

    def __init__(self):
        self._loaded = False
        self._model = None
        self._tokenizer = None

    def is_available(self) -> bool:
        # Only consider available if HuggingFace transformers is importable
        try:
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def chat(
        self,
        user: str,
        system: str = "",
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        format_json: bool = False,
    ) -> str:
        if not self._loaded:
            self._load()
        if self._model is None:
            # Fallback to Ollama inline if model unavailable
            from src.providers.ollama import OllamaProvider
            return OllamaProvider().chat(user, system, "qwen2.5-coder:7b", temperature)

        messages = [
            {"role": "system", "content": system or "You are TIMPS-Coder. Explain the bug then show the fix."},
            {"role": "user", "content": user},
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
                temperature=temperature,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            return self._tokenizer.decode(outputs[0], skip_special_tokens=True)
        except Exception as exc:
            logger.error("TIMPS generation failed: %s", exc)
            from src.providers.ollama import OllamaProvider
            return OllamaProvider().chat(user, system, "qwen2.5-coder:7b", temperature)

    def _load(self) -> None:
        self._loaded = True
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
            logger.info("Loading TIMPS-Coder from %s …", TIMPS_MODEL_PATH)
            self._tokenizer = AutoTokenizer.from_pretrained(TIMPS_MODEL_PATH)
            self._model = AutoModelForCausalLM.from_pretrained(
                TIMPS_MODEL_PATH,
                torch_dtype=torch.float16,
                device_map="auto",
            )
            logger.info("TIMPS-Coder loaded")
        except Exception as exc:
            logger.warning("Could not load TIMPS-Coder: %s", exc)
