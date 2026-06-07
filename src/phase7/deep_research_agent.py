"""Deep Research Agent — multi-hop, multi-source research planner + runner.

Wraps `web_search` with a planning → search → cross-reference → synthesis
loop that produces a sourced, multi-section research report.

Pipeline (per call):

1. Decompose the query into 3-7 sub-questions (LLM).
2. Issue one `web_search` per sub-question (calls the local nextgen agent
   via subprocess to keep dependencies clean).
3. Score + cross-reference the union of results (LLM).
4. Synthesise a multi-section report with `[N]` citations + a final
   "Bottom line" answer.
5. Save the full log under `generated/phase7/deep_research/<slug>/` and a
   `_summary.json` for cheap re-reads.

`depth` controls the breadth:

* `quick`  — 3 sub-questions, 5 results each
* `medium` — 5 sub-questions, 8 results each
* `deep`   — 7 sub-questions, 12 results each
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _GEN, _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

DEPTH_MAP = {
    "quick":  (3, 5),
    "medium": (5, 8),
    "deep":   (7, 12),
}


def deep_research_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or args.get("request") or "").strip()
    depth = (args.get("depth") or "medium").lower()
    if depth not in DEPTH_MAP:
        depth = "medium"
    max_sources = int(args.get("max_sources") or DEPTH_MAP[depth][1])
    recency = args.get("recency") or "any"
    domain_filter = args.get("domain_filter")  # optional allowlist of host suffixes

    if not query:
        return {"summary": "No query provided.", "error": "query is required", "report": "", "sources": []}

    n_sub, _ = DEPTH_MAP[depth]

    # ------------------------------------------------------------ plan
    plan = _plan_subquestions(query, n_sub, recency, domain_filter)

    # ------------------------------------------------------------ search
    all_results: List[Dict[str, Any]] = []
    for sq in plan.get("sub_questions") or [{"q": query}]:
        sub_q = sq.get("q") or query
        purpose = sq.get("purpose") or ""
        hits = _web_search(sub_q, max_sources, recency)
        for h in hits:
            h["sub_question"] = sub_q
            h["sub_purpose"] = purpose
        all_results.extend(hits)

    # ------------------------------------------------------------ dedupe + cross-ref
    seen: Dict[str, Dict[str, Any]] = {}
    for r in all_results:
        url = r.get("url") or ""
        key = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
        if key and key not in seen:
            seen[key] = r
    unique_results = list(seen.values())
    unique_results.sort(key=lambda r: (-len(r.get("content") or r.get("snippet") or ""), r.get("position", 999)))

    # ------------------------------------------------------------ synthesise
    report, citations, conflicts, consensus = _synthesise_report(
        query, plan, unique_results[:max_sources]
    )

    # ------------------------------------------------------------ save
    slug = re.sub(r"[^a-z0-9_]+", "_", query.lower()).strip("_")[:50] or "research"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _GEN / "phase7" / "deep_research" / f"{run_id}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (out_dir / "sources.json").write_text(json.dumps(unique_results, encoding="utf-8"), encoding="utf-8")

    payload = {
        "summary": _summary(query, plan, unique_results, report, depth),
        "query": query,
        "depth": depth,
        "plan": plan,
        "sources": unique_results[:max_sources],
        "source_count": len(unique_results),
        "report": report,
        "citations": citations,
        "conflicts": conflicts,
        "consensus": consensus,
        "log_dir": str(out_dir),
        "generated_at": _ts(),
    }
    _save("phase7/deep_research", f"{run_id}_{slug}_summary.json", json.dumps(payload, indent=2))
    _record("deep_research_agent", query[:80], f"depth={depth} sources={len(unique_results)} citations={len(citations)}")
    return payload


# ---------------------------------------------------------------------------

def _plan_subquestions(query: str, n: int, recency: str, domain_filter: Any) -> Dict[str, Any]:
    system = (
        "You are a research planner.  Return ONLY a JSON object:\n"
        "{\n"
        '  "rationale":  str,             // one paragraph on research approach\n'
        '  "sub_questions": [\n'
        '    {"q": str, "purpose": str, "expected_evidence": str}\n'
        '  ],\n'
        '  "search_strategy": { "primary_terms": [str], "exclude_terms": [str] }\n'
        "}\n\n"
        f"Generate exactly {n} diverse sub-questions that together cover the answer.  "
        "Order them from foundational to specific.  No prose, no fences."
    )
    user = (
        f"Research query: {query}\n"
        f"Recency filter: {recency}\n"
        f"Domain allowlist: {domain_filter or 'any'}\n"
    )
    raw = _llm(user, system, "deep_research_agent")
    parsed = _parse_json(raw, fallback={"rationale": "", "sub_questions": [], "search_strategy": {}})
    subs = parsed.get("sub_questions") or []
    if not subs:
        subs = [{"q": query, "purpose": "primary question", "expected_evidence": "direct answer"}]
    return parsed


def _web_search(query: str, max_results: int, recency: str) -> List[Dict[str, Any]]:
    """Call the nextgen web_search agent in-process.  Returns the result list."""
    try:
        from src.nextgen.web_search import web_search as _ws
        result = _ws({"query": query, "max_results": max_results, "recency": recency,
                      "synthesize": False, "fetch_content": True, "max_fetch": 3})
        return result.get("results") or []
    except Exception as exc:
        return [{"title": "search-error", "url": "", "snippet": f"web_search failed: {exc}",
                 "source_engine": "error", "position": 0, "content": ""}]


def _synthesise_report(query: str, plan: Dict[str, Any], results: List[Dict[str, Any]]) -> tuple:
    if not results:
        return _empty_report(query)

    numbered: List[str] = []
    for i, r in enumerate(results, start=1):
        body = (r.get("content") or r.get("snippet") or "")[:1800]
        numbered.append(f"[{i}] {r.get('title','')} — {r.get('url','')}\n{body}")

    system = (
        "You are a senior research analyst.  Using the numbered sources AND the "
        "research plan, write a structured deep-research report.  Return ONLY JSON:\n"
        "{\n"
        '  "report_md": str,         // full markdown report (see rules)\n'
        '  "citations": [int],       // indices of sources actually cited\n'
        '  "consensus": [str],       // points the sources agree on\n'
        '  "conflicts": [str]        // points where sources disagree\n'
        "}\n\n"
        "Report rules:\n"
        "- Open with a 2-3 sentence 'Bottom line'.\n"
        "- Then a 'Findings' section with H2 subsections aligned to the plan's sub-questions.\n"
        "- Inline citations as `[N]` referencing the source index.\n"
        "- Close with 'Open questions' and 'Recommended next steps'.\n"
        "- Total length: 600-1200 words."
    )
    user = (
        f"Query: {query}\n\n"
        f"Plan: {json.dumps(plan)[:3000]}\n\n"
        f"Sources:\n" + "\n\n".join(numbered)
    )
    raw = _llm(user, system, "deep_research_agent")
    parsed = _parse_json(raw, fallback={"report_md": "", "citations": [], "consensus": [], "conflicts": []})
    cites: List[Dict[str, str]] = []
    for idx in parsed.get("citations") or []:
        try:
            i = int(idx)
            if 1 <= i <= len(results):
                cites.append({"index": i, "title": results[i - 1].get("title", ""), "url": results[i - 1].get("url", "")})
        except Exception:
            pass
    return parsed.get("report_md", "").strip(), cites, parsed.get("conflicts") or [], parsed.get("consensus") or []


def _empty_report(query: str) -> tuple:
    return (f"# Research: {query}\n\n_No sources were found for this query._\n", [], [], [])


def _summary(query: str, plan: Dict[str, Any], results: List[Dict[str, Any]], report: str, depth: str) -> str:
    nq = len(plan.get("sub_questions") or [])
    return (
        f"Deep research on '{query}' ({depth}): {nq} sub-questions, "
        f"{len(results)} unique sources, {len(report.split())} words in report."
    )
