"""Contract Reviewer — reads a contract (NDA, MSA, SOW, DPA, license)
and produces:

* A plain-English summary of what the contract does.
* A clause-by-clause diff against a playbook of acceptable ranges.
* Risk flags (high / medium / low) with the offending clause quoted.
* A redline proposal for each flagged clause.

Works fully offline: it parses plain text / markdown / lightly-formatted
PDF text.  Uses the LLM to interpret ambiguous language and to generate
counter-proposals.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

CONTRACT_TYPES = ("nda", "msa", "sow", "dpa", "license", "employment", "vendor", "other")

DEFAULT_PLAYBOOK: Dict[str, Any] = {
    "nda": {
        "must_have":  ["definition of confidential information", "term of obligation", "exclusions", "return/destruction of materials"],
        "red_flags":  ["perpetual obligation", "non-solicit beyond 12 months", "injunctive relief without proof of harm", "assignment without consent"],
        "redline_defaults": {
            "term of obligation": "Cap at 3 years from disclosure.",
            "non-solicit":        "Limit to 12 months and only direct employees.",
        },
    },
    "msa": {
        "must_have":  ["scope of services", "fees and payment terms", "IP ownership", "limitation of liability", "termination", "governing law"],
        "red_flags":  ["unlimited liability", "IP assignment beyond scope", "auto-renewal > 1 yr without notice", "indemnification without cap", "unilateral price changes"],
    },
    "sow": {
        "must_have":  ["deliverables", "acceptance criteria", "timeline / milestones", "fees", "change-order process"],
        "red_flags":  ["vague acceptance (sole discretion)", "no change-order process", "fixed fee with open-ended scope"],
    },
    "dpa": {
        "must_have":  ["processing scope", "sub-processors", "security measures", "breach notification timeline", "data-subject rights assistance"],
        "red_flags":  ["breach notice > 72 hours", "no audit right", "broad sub-processor consent", "no data-localisation commitment"],
    },
    "license": {
        "must_have":  ["grant of license", "restrictions", "term and termination", "warranty disclaimer", "limitation of liability"],
        "red_flags":  ["perpetual irrevocable grant", "waiver of moral rights", "no warranty disclaimer", "field-of-use restrictions not defined"],
    },
    "employment": {
        "must_have":  ["role and duties", "compensation", "benefits", "termination conditions", "non-compete scope", "IP assignment"],
        "red_flags":  ["non-compete > 12 months", "non-compete with no geographic limit", "IP assignment of pre-existing inventions"],
    },
    "vendor": {
        "must_have":  ["services and SLAs", "fees", "data handling", "termination", "liability cap"],
        "red_flags":  ["liability cap < 1× fees", "no exit assistance", "broad data use rights"],
    },
    "other": {"must_have": [], "red_flags": []},
}


def contract_reviewer(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args.get("text") or args.get("content") or ""
    if not text and args.get("path"):
        text = Path(args["path"]).read_text(encoding="utf-8", errors="ignore")
    if not text:
        return {"summary": "No contract text supplied.", "error": "text or path is required",
                "flags": [], "redlines": []}

    contract_type = (args.get("contract_type") or _guess_type(text)).lower()
    if contract_type not in CONTRACT_TYPES:
        contract_type = "other"
    playbook = {**DEFAULT_PLAYBOOK.get(contract_type, {}), **(args.get("playbook") or {})}

    # Slice the contract into clauses
    clauses = _segment_clauses(text)
    summary = _summarise(text, contract_type)
    flags = _flag_clauses(clauses, playbook, contract_type)
    redlines = _propose_redlines(flags, contract_type)
    coverage = _coverage(playbook.get("must_have", []), clauses)

    payload = {
        "summary": _summary(contract_type, len(clauses), len(flags), coverage),
        "contract_type": contract_type,
        "char_count": len(text),
        "clause_count": len(clauses),
        "executive_summary": summary,
        "playbook_coverage": coverage,
        "flags": flags,
        "redlines": redlines,
        "must_have_found": [k for k, v in coverage.items() if v["found"]],
        "must_have_missing": [k for k, v in coverage.items() if not v["found"]],
        "red_flag_count": len(flags),
        "high_risk_count": sum(1 for f in flags if f["severity"] == "high"),
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", contract_type).strip("_") or "contract"
    _save("phase7/contract_review", f"{slug}_{_ts()}_review.json", json.dumps(payload, indent=2))
    _record("contract_reviewer", contract_type, f"clauses={len(clauses)} flags={len(flags)}")
    return payload


# ---------------------------------------------------------------------------

def _guess_type(text: str) -> str:
    t = text.lower()
    if "mutual non-disclosure" in t or ("non-disclosure" in t and "confidential" in t):
        return "nda"
    if "master services agreement" in t or "statement of work" in t or "msa" in t:
        return "msa" if "master services" in t else "sow"
    if "data processing" in t and "gdpr" in t:
        return "dpa"
    if "license agreement" in t or "grants a license" in t:
        return "license"
    if "employment" in t and ("compensation" in t or "salary" in t):
        return "employment"
    if "vendor" in t and "sla" in t:
        return "vendor"
    return "other"


def _segment_clauses(text: str) -> List[Dict[str, Any]]:
    """Split by numbered headings ('1.', '1.1', 'Section 4', 'Article V')."""
    pat = re.compile(r"(?m)^(?P<head>(?:section|article|clause)?\s*\d+(?:\.\d+)*[\.\):]?\s+[^\n]{0,80})", re.I)
    indices = [m.start() for m in pat.finditer(text)]
    if not indices:
        return [{"id": 1, "heading": "Body", "text": text}]
    out: List[Dict[str, Any]] = []
    for i, start in enumerate(indices):
        end = indices[i + 1] if i + 1 < len(indices) else len(text)
        segment = text[start:end].strip()
        head = segment.splitlines()[0] if segment else f"Clause {i+1}"
        out.append({"id": i + 1, "heading": head[:120], "text": segment})
    return out


def _summarise(text: str, contract_type: str) -> str:
    system = (
        f"You are a contracts lawyer.  Write a 3-4 sentence executive summary of this "
        f"{contract_type.upper()} contract.  Plain English, no boilerplate."
    )
    raw = _llm(text[:6000], system, "contract_reviewer")
    return raw.strip()


def _flag_clauses(clauses: List[Dict[str, Any]], playbook: Dict[str, Any], ctype: str) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    rf = [k.lower() for k in playbook.get("red_flags", [])]
    for cl in clauses:
        lc = cl["text"].lower()
        for red in rf:
            # rough semantic match
            toks = [w for w in re.findall(r"\w+", red) if len(w) > 3]
            if toks and sum(1 for t in toks if t in lc) / max(1, len(toks)) >= 0.4:
                flags.append({
                    "clause_id": cl["id"], "heading": cl["heading"],
                    "excerpt": cl["text"][:400], "matched_red_flag": red,
                    "severity": "high" if any(t in red for t in ("unlimited", "perpetual", "irrevocable")) else "medium",
                    "reason": f"Clause matches the red-flag pattern: '{red}'.",
                })
    return flags


def _propose_redlines(flags: List[Dict[str, Any]], ctype: str) -> List[Dict[str, Any]]:
    if not flags:
        return []
    system = (
        f"You are a contracts lawyer drafting redlines for a {ctype.upper()}.  "
        "For each flagged clause, propose a counter-proposal in plain English.  "
        "Return ONLY a JSON object: {\"redlines\": [{\"clause_id\": int, "
        "\"original_excerpt\": str, \"proposed_text\": str, \"rationale\": str}]}"
    )
    user = json.dumps(flags)[:6000]
    raw = _llm(user, system, "contract_reviewer")
    parsed = _parse_json(raw, fallback={"redlines": []})
    out = []
    for r in parsed.get("redlines") or []:
        try:
            cid = int(r.get("clause_id"))
            if any(f["clause_id"] == cid for f in flags):
                out.append({
                    "clause_id": cid,
                    "proposed_text": (r.get("proposed_text") or "").strip(),
                    "rationale": (r.get("rationale") or "").strip(),
                })
        except Exception:
            continue
    return out


def _coverage(must_have: List[str], clauses: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    all_text = "\n".join(c["text"] for c in clauses).lower()
    out: Dict[str, Dict[str, Any]] = {}
    for item in must_have:
        toks = [w for w in re.findall(r"\w+", item.lower()) if len(w) > 3]
        score = sum(1 for t in toks if t in all_text) / max(1, len(toks)) if toks else 0.0
        out[item] = {"found": score >= 0.5, "score": round(score, 2),
                     "matched_in_clauses": [c["id"] for c in clauses if any(t in c["text"].lower() for t in toks)][:3]}
    return out


def _summary(ctype: str, n_clauses: int, n_flags: int, coverage: Dict[str, Any]) -> str:
    missing = [k for k, v in coverage.items() if not v["found"]]
    return (f"{ctype.upper()} review: {n_clauses} clauses, {n_flags} red-flag matches, "
            f"{len(missing)} must-have items missing.")
