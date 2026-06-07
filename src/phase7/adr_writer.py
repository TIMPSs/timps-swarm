"""ADR Writer — generates an Architecture Decision Record from a description
of the decision (and optional PR diff or design doc).

Output: a Markdown file in MADR (Markdown Architectural Decision Records)
format with the canonical sections:

* Status & date
* Context and Problem Statement
* Decision Drivers
* Considered Options (≥ 2)
* Decision Outcome (with positive/negative consequences)
* Pros and Cons of the Options
* Links

The agent is LLM-driven: the model extracts the decision, generates
plausible alternatives, and weighs pros/cons.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

DEFAULT_STATUSES = ("proposed", "accepted", "deprecated", "superseded")


def adr_writer(args: Dict[str, Any]) -> Dict[str, Any]:
    title = (args.get("title") or args.get("decision") or "").strip()
    context = (args.get("context") or args.get("request") or "").strip()
    if not context and args.get("diff"):
        context = Path(args["diff"]).read_text(encoding="utf-8", errors="ignore") if Path(args["diff"]).is_file() else args["diff"]
    if not title and context:
        title = _guess_title(context)
    if not context:
        return {"summary": "No context supplied.", "error": "context or decision is required",
                "adr_md": ""}

    status = (args.get("status") or "proposed").lower()
    if status not in DEFAULT_STATUSES:
        status = "proposed"
    supersedes = args.get("supersedes") or ""
    drivers: List[str] = args.get("drivers") or []
    decision_date = args.get("date") or str(date.today())

    adr = _compose(title, context, status, decision_date, drivers, supersedes)
    adr_path = _save_adr(adr, title, decision_date)

    payload = {
        "summary": _summary(adr, status),
        "title": title,
        "status": status,
        "date": decision_date,
        "adr_md": adr,
        "adr_path": adr_path,
        "supersedes": supersedes,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", title.lower()).strip("_")[:40] or "adr"
    _save("phase7/adr", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("adr_writer", title[:60], f"status={status} options={adr.count('### ')}")
    return payload


# ---------------------------------------------------------------------------

def _guess_title(context: str) -> str:
    first = context.strip().splitlines()[0] if context.strip() else "Untitled decision"
    return re.sub(r"\s+", " ", first).strip().rstrip(".?!")[:80]


def _compose(title: str, context: str, status: str, dt: str, drivers: List[str], supersedes: str) -> str:
    system = (
        "You are a staff software architect writing an MADR-style ADR.  Return ONLY JSON:\n"
        "{\n"
        '  "problem_statement": str,\n'
        '  "drivers":           [str],\n'
        '  "options": [\n'
        '    {"name": str, "summary": str, "pros": [str], "cons": [str]}\n'
        '  ],\n'
        '  "chosen_option":     str,\n'
        '  "positive_consequences": [str],\n'
        '  "negative_consequences": [str],\n'
        '  "follow_up_actions": [str]\n'
        "}\n\n"
        "Generate at least 3 options.  Pros/cons must be concrete (cost, latency, "
        "team size, risk).  Consequences must be realistically testable."
    )
    user = (
        f"Title: {title}\n"
        f"Context (truncated to 6000 chars):\n{context[:6000]}\n"
        f"Stated drivers: {json.dumps(drivers)}"
    )
    raw = _llm(user, system, "adr_writer")
    parsed = _parse_json(raw, fallback={
        "problem_statement": context[:400],
        "drivers": drivers or ["(unspecified)"],
        "options": [],
        "chosen_option": "",
        "positive_consequences": [],
        "negative_consequences": [],
        "follow_up_actions": [],
    })

    md = [f"# {title}", "", f"* Status: **{status}**  |  Date: {dt}"]
    if supersedes:
        md.append(f"* Supersedes: {supersedes}")
    md += ["", "## Context and Problem Statement", "", parsed.get("problem_statement") or context[:400], ""]

    if parsed.get("drivers"):
        md.append("## Decision Drivers")
        md += [f"* {d}" for d in parsed["drivers"]]
        md.append("")

    md.append("## Considered Options")
    for opt in parsed.get("options") or []:
        md.append(f"### {opt.get('name','?')}")
        if opt.get("summary"):
            md += [opt["summary"], ""]
        if opt.get("pros"):
            md.append("**Good**")
            md += [f"* {p}" for p in opt["pros"]]
        if opt.get("cons"):
            md.append("**Bad**")
            md += [f"* {c}" for c in opt["cons"]]
        md.append("")

    md.append("## Decision Outcome")
    chosen = parsed.get("chosen_option") or (parsed.get("options") or [{}])[0].get("name", "(undetermined)")
    md += [f"Chosen option: **{chosen}**", ""]
    if parsed.get("positive_consequences"):
        md.append("### Positive consequences")
        md += [f"* {c}" for c in parsed["positive_consequences"]]
    if parsed.get("negative_consequences"):
        md.append("### Negative consequences")
        md += [f"* {c}" for c in parsed["negative_consequences"]]
    if parsed.get("follow_up_actions"):
        md.append("### Follow-up actions")
        md += [f"- [ ] {a}" for a in parsed["follow_up_actions"]]
    return "\n".join(md) + "\n"


def _save_adr(adr: str, title: str, dt: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", title.lower()).strip("_")[:60] or "adr"
    out_dir = Path("generated/phase7/adr")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{dt}-{slug}.md"
    path.write_text(adr, encoding="utf-8")
    return str(path)


def _summary(adr: str, status: str) -> str:
    options = adr.count("### ")
    return f"ADR: status={status}, {options} options considered."
