"""Court Case Summarizer — reads a long judgment / court-order PDF or text
and produces a structured case summary.

Outputs:

* Case metadata (parties, court, citation, date, judges).
* Procedural history (one paragraph).
* Issues / questions of law (numbered list).
* Holding (the court's final answer per issue).
* Ratio decidendi (the binding legal reasoning).
* Obiter dicta (non-binding observations).
* Key cases cited (with one-line characterisation).
* Statutes / sections cited.
* Practical takeaways for lawyers / litigants.
* A 200-word "headnote" suitable for law-report publication.
* A short LinkedIn-style explainer for the public.

The agent is LLM-driven and works fully offline once given the text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def court_case_summarizer(args: Dict[str, Any]) -> Dict[str, Any]:
    text = (args.get("text") or args.get("judgment") or "").strip()
    if not text and args.get("path"):
        text = Path(args["path"]).read_text(encoding="utf-8", errors="ignore")
    if not text:
        return {"summary": "No judgment text supplied.", "error": "text or path is required",
                "case": {}, "headnote": ""}

    case = _analyze(text)
    headnote = _headnote(case)
    explainer = _public_explainer(case)
    cross_refs = _cross_refs(case)

    payload = {
        "summary": _summary(case),
        "case": case,
        "headnote": headnote,
        "public_explainer": explainer,
        "cross_references": cross_refs,
        "char_count": len(text),
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (case.get("case_name", "case")).lower()).strip("_")[:40] or "case"
    _save("phase7/court_case", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("court_case_summarizer", case.get("case_name", "?")[:60], f"issues={len(case.get('issues', []))}")
    return payload


# ---------------------------------------------------------------------------

def _analyze(text: str) -> Dict[str, Any]:
    system = (
        "You are an Indian / common-law senior counsel summarising a judgment.  "
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "case_name":         str,\n'
        '  "citation":          str,            // e.g. (2024) 1 SCC 123\n'
        '  "court":             str,            // e.g. Supreme Court of India\n'
        '  "date_of_judgment":  str,\n'
        '  "judges":            [str],\n'
        '  "appellant":         str,\n'
        '  "respondent":        str,\n'
        '  "procedural_history":str,            // one paragraph\n'
        '  "issues":            [str],          // questions of law\n'
        '  "holding":           [str],          // one per issue\n'
        '  "ratio_decidendi":   [str],          // binding reasoning (bullet points)\n'
        '  "obiter_dicta":      [str],          // non-binding observations\n'
        '  "cases_cited":       [str],          // key precedents\n'
        '  "statutes_cited":    [str],          // e.g. Sec. 420 IPC, Art. 21\n'
        '  "practical_takeaways":[str],\n'
        '  "verdict":           str             // e.g. Appeal allowed\n'
        "}\n"
    )
    user = f"Judgment (truncated to 12000 chars):\n```\n{text[:12000]}\n```"
    raw = _llm(user, system, "court_case_summarizer")
    return _parse_json(raw, fallback={
        "case_name": "Unknown", "citation": "", "court": "", "date_of_judgment": "",
        "judges": [], "appellant": "", "respondent": "",
        "procedural_history": "", "issues": [], "holding": [],
        "ratio_decidendi": [], "obiter_dicta": [], "cases_cited": [],
        "statutes_cited": [], "practical_takeaways": [], "verdict": "",
    })


def _headnote(case: Dict[str, Any]) -> str:
    system = "You are a law-report editor.  Write a 180-220 word headnote suitable for SCC / AIR.  Plain prose, no markdown."
    user = json.dumps(case)[:6000]
    return _llm(user, system, "court_case_summarizer").strip()


def _public_explainer(case: Dict[str, Any]) -> str:
    system = (
        "You write LinkedIn-style legal explainers for educated non-lawyers.  "
        "200-260 words.  Plain English, no jargon, no emojis, no markdown.  "
        "End with one-line 'Why it matters'."
    )
    user = json.dumps(case)[:6000]
    return _llm(user, system, "court_case_summarizer").strip()


def _cross_refs(case: Dict[str, Any]) -> List[Dict[str, str]]:
    if not case.get("cases_cited"):
        return []
    system = (
        "For each cited case, write one sentence on why it was cited (followed, "
        "distinguished, overruled, referred).  Return ONLY a JSON object: "
        "{\"refs\": [{\"case\": str, \"treatment\": str, \"one_liner\": str}]}."
    )
    user = json.dumps(case.get("cases_cited", []))
    raw = _llm(user, system, "court_case_summarizer")
    parsed = _parse_json(raw, fallback={"refs": []})
    return parsed.get("refs") or []


def _summary(case: Dict[str, Any]) -> str:
    return (f"{case.get('case_name','?')} — {case.get('court','?')}, "
            f"{case.get('date_of_judgment','?')}. "
            f"Verdict: {case.get('verdict','?')}; "
            f"{len(case.get('issues',[]))} issues, "
            f"{len(case.get('cases_cited',[]))} precedents.")
