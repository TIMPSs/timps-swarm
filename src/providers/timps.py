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
        # Only available when the model files are actually cached locally
        # AND transformers is importable. This prevents the provider from
        # being selected when it will just fall through to Ollama anyway.
        try:
            import transformers  # noqa: F401
            from huggingface_hub import snapshot_download
            import os
            # Check if model is cached locally (don't trigger a download)
            model_path = os.getenv("TIMPS_MODEL_PATH", "sandeeprdy1729/TIMPS-Coder-0.5B")
            local_path = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
            if os.path.exists(local_path) and model_path.replace("/", "--") in " ".join(os.listdir(local_path)) if os.path.isdir(local_path) else False:
                return True
            # Model not cached — don't report as available (would fail or trigger download)
            return False
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
            return "[TIMPS-Coder model not available]"

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
