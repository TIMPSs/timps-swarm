"""Win/Loss Analyst — produces a battlecard from a single sales call
transcript OR from a set of CRM notes / call recordings.

Outputs:

* Decision: Win / Loss / No-decision.
* Top 3 reasons cited (for/against).
* Competitors mentioned + how we were positioned.
* Pricing objections + recommended responses.
* A short battlecard snippet for the sales team.
* An interview script to use with the buyer for the next win/loss call.

The agent is LLM-driven: it interprets natural-language transcripts and
emits structured fields.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def win_loss_analyst(args: Dict[str, Any]) -> Dict[str, Any]:
    transcript = (args.get("transcript") or args.get("text") or args.get("request") or "").strip()
    if not transcript and args.get("path"):
        transcript = Path(args["path"]).read_text(encoding="utf-8", errors="ignore")
    if not transcript:
        return {"summary": "No transcript supplied.", "error": "transcript or path is required",
                "battlecard": ""}

    deal_size = args.get("deal_size")
    stage = args.get("stage") or "unknown"
    product = args.get("product") or "our product"

    analysis = _analyze(transcript, product, stage, deal_size)
    battlecard = _render_battlecard(analysis, product)
    interview = _render_interview_script(analysis, product)

    payload = {
        "summary": _summary(analysis),
        "product": product,
        "stage": stage,
        "deal_size": deal_size,
        "analysis": analysis,
        "battlecard": battlecard,
        "interview_script": interview,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", product.lower()).strip("_")[:40] or "deal"
    _save("phase7/win_loss", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("win_loss_analyst", product[:60], f"verdict={analysis.get('verdict', '?')}")
    return payload


# ---------------------------------------------------------------------------

def _analyze(transcript: str, product: str, stage: str, deal_size: Any) -> Dict[str, Any]:
    system = (
        "You are a RevOps analyst reviewing a sales call transcript.  Return ONLY JSON:\n"
        "{\n"
        '  "verdict": "win"|"loss"|"no_decision",\n'
        '  "verdict_confidence": 0..1,\n'
        '  "decision_drivers":   [str],   // top reasons for the decision\n'
        '  "competitors_mentioned": [str],\n'
        '  "competitor_positioning": [str],\n'
        '  "pricing_objections": [str],\n'
        '  "objection_responses": [str],  // suggested counter-responses\n'
        '  "champion_identified": bool,\n'
        '  "next_steps_agreed": [str],\n'
        '  "executive_summary":   str,    // 2-3 sentences\n'
        '  "improvement_actions": [str]   // concrete actions for the team\n'
        "}"
    )
    user = (
        f"Product: {product}\nStage: {stage}\nDeal size: {deal_size or 'unspecified'}\n\n"
        f"Transcript:\n```\n{transcript[:8000]}\n```"
    )
    raw = _llm(user, system, "win_loss_analyst")
    parsed = _parse_json(raw, fallback={
        "verdict": "no_decision", "verdict_confidence": 0.0, "decision_drivers": [],
        "competitors_mentioned": [], "competitor_positioning": [],
        "pricing_objections": [], "objection_responses": [], "champion_identified": False,
        "next_steps_agreed": [], "executive_summary": "", "improvement_actions": [],
    })
    return parsed


def _render_battlecard(a: Dict[str, Any], product: str) -> str:
    lines = [f"# Battlecard — {product}\n", f"**Verdict:** {a.get('verdict','?').upper()} "
             f"(confidence {a.get('verdict_confidence', 0)})\n"]
    lines.append("\n## Why we won/lost\n")
    for d in a.get("decision_drivers") or []:
        lines.append(f"- {d}")
    if a.get("competitors_mentioned"):
        lines.append("\n## Competitors\n")
        for c in a.get("competitors_mentioned") or []:
            lines.append(f"- **{c}**")
        for p in a.get("competitor_positioning") or []:
            lines.append(f"  - {p}")
    if a.get("pricing_objections"):
        lines.append("\n## Pricing objections + responses\n")
        for o, r in zip(a.get("pricing_objections") or [], a.get("objection_responses") or []):
            lines.append(f"- **{o}**\n  - _{r}_")
    if a.get("improvement_actions"):
        lines.append("\n## What we'll do differently\n")
        for x in a["improvement_actions"]:
            lines.append(f"- [ ] {x}")
    return "\n".join(lines)


def _render_interview_script(a: Dict[str, Any], product: str) -> str:
    verdict = a.get("verdict", "no_decision")
    questions = [
        "Walk me through the moment you decided to move forward (or not).",
        "Who else was involved in the decision and what did they care most about?",
        "Which competitors did you evaluate, and what stood out about each?",
        "What was the single biggest concern we didn't fully address?",
        "On a scale of 1-10, how clearly did we articulate the value? Why that number?",
        "If you could change one thing about how we sell, what would it be?",
        "Would you recommend us to a peer in a similar situation? Why or why not?",
    ]
    if verdict == "win":
        questions.append("What almost made you choose a competitor instead?")
    else:
        questions.append("What would have made you choose us?")
    out = [f"# Win/Loss Interview — {product}\n", f"_Verdict: {verdict}_\n"]
    for i, q in enumerate(questions, start=1):
        out.append(f"{i}. {q}")
    return "\n".join(out)


def _summary(a: Dict[str, Any]) -> str:
    return (f"Win/Loss: {a.get('verdict','?').upper()} "
            f"(conf {a.get('verdict_confidence',0):.1f}); "
            f"{len(a.get('decision_drivers',[]))} drivers, "
            f"{len(a.get('competitors_mentioned',[]))} competitors, "
            f"{len(a.get('pricing_objections',[]))} pricing objections.")
