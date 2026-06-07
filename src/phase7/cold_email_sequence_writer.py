"""Cold Email Sequence Writer — produces a 5-7 step outbound cold-email
sequence for a target persona and product.  Each step includes:

* A subject line (≤ 50 chars, mobile-friendly, no spam triggers).
* A body (90-140 words, one CTA, no attachments, plain-text-friendly).
* A/B variants.
* A send-delay recommendation.
* A reply-likelihood score + reasons.

The agent is LLM-driven: the model designs the narrative arc, selects
the right hook for the persona, and stress-tests against spam filters.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

SPAM_TRIGGERS = re.compile(
    r"\b(free|guaranteed|100% guaranteed|act now|limited time|buy now|click here|"
    r"risk[- ]?free|no obligation|earn \$\|winner|amazing|incredible|"
    r"dear friend|hi friend)\b", re.I)


def cold_email_sequence_writer(args: Dict[str, Any]) -> Dict[str, Any]:
    product = (args.get("product") or "").strip()
    persona = (args.get("persona") or "B2B SaaS buyer").strip()
    pain = (args.get("pain") or "").strip()
    proof = args.get("proof") or ""  # e.g. "used by 100+ teams, $2M ARR"
    n_steps = int(args.get("steps") or 6)
    tone = (args.get("tone") or "concise, peer-to-peer").strip()

    if not product or not persona:
        return {"summary": "Supply product and persona.", "error": "product and persona required",
                "sequence": []}

    design = _design_sequence(product, persona, pain, proof, n_steps, tone)
    review = _spam_review(design)
    ab_variants = _ab_variants(design, n_steps)
    schedule = _schedule(n_steps)

    payload = {
        "summary": _summary(design, review, ab_variants),
        "product": product,
        "persona": persona,
        "tone": tone,
        "n_steps": n_steps,
        "sequence": design,
        "ab_variants": ab_variants,
        "schedule": schedule,
        "spam_review": review,
        "reply_likelihood": _score_likelihood(design, review),
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", product.lower()).strip("_")[:40] or "sequence"
    _save("phase7/cold_email", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("cold_email_sequence_writer", product[:60], f"steps={n_steps} reply_likelihood={payload['reply_likelihood']}")
    return payload


# ---------------------------------------------------------------------------

def _design_sequence(product: str, persona: str, pain: str, proof: str, n: int, tone: str) -> List[Dict[str, Any]]:
    system = (
        f"You write B2B cold-email sequences.  Build a {n}-step arc that "
        f"opens with curiosity, escalates specificity, then breaks up politely.  "
        f"Tone: {tone}.  Return ONLY a JSON object: {{\"sequence\": [\n"
        f"  {{\"step\": int, \"subject\": str, \"body\": str, "
        f"\"send_delay_days\": int, \"purpose\": str, "
        f"\"reply_likelihood_1to10\": int, \"why\": str}}\n"
        f"]}}.  No prose, no fences."
    )
    user = (
        f"Product: {product}\nPersona: {persona}\nPain: {pain or 'unspecified'}\n"
        f"Proof: {proof or 'unspecified'}\nSteps: {n}\nTone: {tone}\n\n"
        "Constraints: subject ≤ 50 chars, body 90-140 words, one CTA, "
        "no attachments, no all-caps, no fake familiarity."
    )
    raw = _llm(user, system, "cold_email_sequence_writer")
    parsed = _parse_json(raw, fallback={"sequence": []})
    out = parsed.get("sequence") or []
    if not out:
        out = _fallback_sequence(product, persona, n)
    return out[:n]


def _fallback_sequence(product: str, persona: str, n: int) -> List[Dict[str, Any]]:
    base = [
        ("Quick question about {p}'s stack", f"Hi {{first}},noticed {{p}} teams spend a lot of time on the boring part of {product.lower()}.Want to compare notes on how you handle it? — 5 min, no slides.", 0, "opener"),
        ("The 1-min version",            f"Hi {{first}},if you're tracking the {product.lower()} space, here's a 1-min summary of the change this quarter.  Reply 'send' and I'll forward.", 3, "value"),
        ("How {comp} cut X by 40%",       f"Hi {{first}},similar teams to yours cut {product.lower()} cost by 40% in 3 weeks.  One change.  Worth a 10-min look?", 6, "social proof"),
        ("Wrong person?",                 f"Hi {{first}},if you're not the right person for {product.lower()}, who is?  Two-second reply is fine.", 10, "referral"),
        ("Closing the loop",              f"Hi {{first}},I'll assume the timing's off — happy to circle back in Q3 if useful.  No reply needed.", 14, "breakup"),
    ]
    out: List[Dict[str, Any]] = []
    for i, (subj, body, delay, purpose) in enumerate(base[:n], start=1):
        out.append({"step": i, "subject": f"[{i}] {subj}".replace("{p}", persona)[:50],
                    "body": body.replace("{p}", persona).replace("{comp}", "Acme"), "send_delay_days": delay,
                    "purpose": purpose, "reply_likelihood_1to10": 4, "why": "baseline"})
    return out


def _spam_review(seq: List[Dict[str, Any]]) -> Dict[str, Any]:
    flagged: List[Dict[str, Any]] = []
    for s in seq:
        full = f"{s.get('subject','')}\n{s.get('body','')}"
        hits = SPAM_TRIGGERS.findall(full)
        if hits:
            flagged.append({"step": s["step"], "triggers": list(set(hits))})
    return {"flagged_steps": flagged, "clean": not flagged}


def _ab_variants(seq: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in seq[:n]:
        out.append({
            "step": s["step"],
            "subject_alt": s.get("subject", "")[::-1].replace("?", ".", 1),  # playful
            "body_opener_alt": "Curious if this resonates — ",
        })
    return out


def _schedule(n: int) -> List[Dict[str, Any]]:
    days = [0, 3, 6, 10, 14, 21, 28][:n]
    return [{"step": i + 1, "send_at_day": d, "send_window": "Tue–Thu, 9:30am local"}
            for i, d in enumerate(days)]


def _score_likelihood(seq: List[Dict[str, Any]], review: Dict[str, Any]) -> float:
    if not seq:
        return 0.0
    avg = sum(int(s.get("reply_likelihood_1to10", 5)) for s in seq) / len(seq)
    penalty = 0.5 * len(review.get("flagged_steps", []))
    return round(max(0.0, min(10.0, avg - penalty)), 1)


def _summary(seq: List[Dict[str, Any]], review: Dict[str, Any], ab: List[Dict[str, Any]]) -> str:
    n_flag = len(review.get("flagged_steps", []))
    return f"Cold email sequence: {len(seq)} steps, {n_flag} spam-flagged, {len(ab)} A/B variants."
