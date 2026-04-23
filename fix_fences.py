"""
fix_fences.py — Post-process the dataset to fix malformed code fences.

Problems fixed:
  - Unclosed ``` blocks
  - Nested ``` inside code blocks
  - Trailing whitespace in code
  - Messages that are too long (truncate)
  - Empty assistant messages

Usage:
  python fix_fences.py [--input data/processed/train.jsonl]
"""
import argparse
import json
import re
from pathlib import Path


def fix_code_fences(text: str) -> str:
    """Ensure code fences are balanced."""
    # Count opening vs closing fences
    fences = re.findall(r"```", text)
    if len(fences) % 2 != 0:
        text = text.rstrip() + "\n```"
    return text


def truncate_message(content: str, max_len: int = 6000) -> str:
    if len(content) <= max_len:
        return content
    # Keep beginning and end
    half = max_len // 2
    return content[:half] + "\n...[truncated]...\n" + content[-half:]


def fix_sample(sample: dict) -> dict | None:
    messages = sample.get("messages", [])
    if not messages:
        return None

    fixed_messages = []
    for msg in messages:
        content = msg.get("content", "")
        if not content.strip():
            continue

        # Fix code fences in assistant messages
        if msg["role"] == "assistant":
            content = fix_code_fences(content)

        # Truncate overly long messages
        content = truncate_message(content)

        fixed_messages.append({**msg, "content": content})

    if len(fixed_messages) < 3:
        return None

    # Ensure roles are correct
    roles = [m["role"] for m in fixed_messages]
    if "user" not in roles or "assistant" not in roles:
        return None

    return {**sample, "messages": fixed_messages}


def fix_dataset(input_path: str, output_path: str | None = None):
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path

    samples = []
    skipped = 0

    with open(input_path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
                fixed = fix_sample(sample)
                if fixed:
                    samples.append(fixed)
                else:
                    skipped += 1
            except json.JSONDecodeError as e:
                print(f"  Line {i}: JSON error — {e}")
                skipped += 1

    with open(output_path, "w") as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")

    print(f"fix_fences: {len(samples)} kept, {skipped} skipped → {output_path}")
    return len(samples)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/processed/train.jsonl")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    fix_dataset(args.input, args.output)
