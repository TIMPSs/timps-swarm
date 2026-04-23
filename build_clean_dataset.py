"""
build_clean_dataset.py — Build the training dataset for TIMPS-Coder fine-tuning.

Sources:
  1. datasets/custom/  — Your own bug-fix JSONL files (highest priority)
  2. datasets/raw/     — Raw bug-fix pairs in simplified format
  3. HuggingFace datasets (code_x_glue_cc_code_refinement, etc.)

Output: data/processed/train.jsonl  (chat template format)

Usage:
  python build_clean_dataset.py [--max-samples 5000]
"""
import argparse
import json
import os
import random
from pathlib import Path

OUTPUT_DIR = Path("data/processed")
CUSTOM_DIR = Path("datasets/custom")
RAW_DIR = Path("datasets/raw")

SYSTEM_PROMPT = (
    "You are TIMPS-Coder, an expert software engineer specialising in bug fixing. "
    "When given buggy code, you: "
    "1) Identify and explain the root cause in plain English, "
    "2) Show the complete corrected code with changes clearly marked. "
    "Be precise, concise, and educational."
)


def load_custom_datasets() -> list[dict]:
    """Load manually curated datasets from datasets/custom/"""
    samples = []
    if not CUSTOM_DIR.exists():
        return samples

    for filepath in CUSTOM_DIR.glob("*.jsonl"):
        print(f"  Loading custom: {filepath}")
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # Accept formats:
                    # {buggy_code, fixed_code, explanation}
                    # {instruction, output}
                    # {messages: [...]}
                    sample = _normalise_sample(data)
                    if sample:
                        samples.append(sample)
                except json.JSONDecodeError:
                    pass

    print(f"  Custom dataset: {len(samples)} samples")
    return samples


def load_raw_datasets() -> list[dict]:
    """Load raw bug-fix pairs from datasets/raw/"""
    samples = []
    if not RAW_DIR.exists():
        return samples

    for filepath in RAW_DIR.glob("*.jsonl"):
        print(f"  Loading raw: {filepath}")
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    sample = _normalise_sample(data)
                    if sample:
                        samples.append(sample)
                except json.JSONDecodeError:
                    pass

    print(f"  Raw dataset: {len(samples)} samples")
    return samples


def load_huggingface_datasets(max_samples: int = 2000) -> list[dict]:
    """Try to load public HuggingFace datasets."""
    samples = []
    try:
        from datasets import load_dataset

        print("  Loading HuggingFace: code_x_glue_cc_code_refinement (small)…")
        ds = load_dataset("code_x_glue_cc_code_refinement", "small", split="train", trust_remote_code=True)

        for item in list(ds)[:max_samples]:
            buggy = item.get("buggy", "")
            fixed = item.get("fixed", "")
            if not buggy or not fixed or buggy == fixed:
                continue

            samples.append({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Fix this buggy code:\n```\n{buggy}\n```"},
                    {"role": "assistant", "content": f"The bug is a logic/syntax error.\n\nFixed code:\n```\n{fixed}\n```"},
                ]
            })

        print(f"  HuggingFace: {len(samples)} samples")
    except Exception as exc:
        print(f"  HuggingFace load skipped: {exc}")

    return samples


def _normalise_sample(data: dict) -> dict | None:
    """Convert any input format to messages format."""
    # Already in messages format
    if "messages" in data and isinstance(data["messages"], list):
        # Ensure system prompt is correct
        if data["messages"] and data["messages"][0]["role"] != "system":
            data["messages"].insert(0, {"role": "system", "content": SYSTEM_PROMPT})
        elif data["messages"] and data["messages"][0]["role"] == "system":
            data["messages"][0]["content"] = SYSTEM_PROMPT
        return data

    # {instruction, output} format
    if "instruction" in data and "output" in data:
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data["instruction"]},
                {"role": "assistant", "content": data["output"]},
            ]
        }

    # {buggy_code, fixed_code} format
    if "buggy_code" in data and "fixed_code" in data:
        explanation = data.get("explanation", "The code contained a bug that has been fixed.")
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Fix this buggy code:\n```\n{data['buggy_code']}\n```"},
                {
                    "role": "assistant",
                    "content": (
                        f"**Root cause:** {explanation}\n\n"
                        f"**Fixed code:**\n```\n{data['fixed_code']}\n```"
                    ),
                },
            ]
        }

    # {input, output} format
    if "input" in data and "output" in data:
        return {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data["input"]},
                {"role": "assistant", "content": data["output"]},
            ]
        }

    return None


def validate_sample(sample: dict) -> bool:
    """Basic quality filter."""
    messages = sample.get("messages", [])
    if len(messages) < 3:
        return False

    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    assistant_msg = next((m["content"] for m in messages if m["role"] == "assistant"), "")

    if len(user_msg) < 20 or len(assistant_msg) < 20:
        return False
    if len(assistant_msg) > 8000:
        return False

    return True


def build_dataset(max_samples: int = 5000) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("\n=== Building TIMPS-Coder Dataset ===")

    all_samples = []
    all_samples.extend(load_custom_datasets())
    all_samples.extend(load_raw_datasets())
    all_samples.extend(load_huggingface_datasets(max_samples // 2))

    # Deduplicate (by first user message)
    seen = set()
    unique_samples = []
    for s in all_samples:
        msgs = s.get("messages", [])
        key = next((m["content"][:100] for m in msgs if m["role"] == "user"), "")
        if key not in seen:
            seen.add(key)
            unique_samples.append(s)

    # Validate
    valid = [s for s in unique_samples if validate_sample(s)]
    print(f"\n  Total unique samples: {len(unique_samples)}")
    print(f"  Valid samples: {len(valid)}")

    # Shuffle and cap
    random.shuffle(valid)
    final = valid[:max_samples]

    # Write output
    output_path = OUTPUT_DIR / "train.jsonl"
    with open(output_path, "w") as f:
        for sample in final:
            f.write(json.dumps(sample) + "\n")

    print(f"\n✅ Dataset saved to {output_path} ({len(final)} samples)")
    return len(final)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=5000)
    args = parser.parse_args()
    build_dataset(args.max_samples)
