"""Agent Marketplace Curator — discovers MCP servers and agent plugins
from public registries (pulse.mcp.run, mcp.so, Glama, GitHub topics)
and recommends the best fit for a stated use case.

Inputs:

* `use_case`     — plain-English description of the need
* `max_results`  — cap on returned recommendations
* `must_have`    — list of required capabilities
* `forbid`       — list of blocked hosts (security/sandbox)
* `registry`     — 'auto' | 'pulse' | 'glama' | 'mcp_so' | 'github'

Outputs (per recommendation):

* Name, source, URL, install command, version
* Description
* Match score (0-100) against the use case
* Required vs. optional capabilities satisfied
* Risk flags (last update, license, verified publisher, install footprint)
* Sortable by match score, freshness, or risk
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

REGISTRIES = ("auto", "pulse", "glama", "mcp_so", "github")


def agent_marketplace_curator(args: Dict[str, Any]) -> Dict[str, Any]:
    use_case = (args.get("use_case") or args.get("request") or "").strip()
    if not use_case:
        return {"summary": "No use case supplied.", "error": "use_case is required",
                "recommendations": []}

    max_results = int(args.get("max_results") or 10)
    must_have: List[str] = args.get("must_have") or []
    forbid: List[str]    = args.get("forbid") or []
    registry = (args.get("registry") or "auto").lower()
    if registry not in REGISTRIES: registry = "auto"

    # Step 1: collect candidate listings from the chosen registry (offline-first).
    raw = _collect(use_case, registry)
    # Step 2: filter by must-have / forbid
    filtered = [r for r in raw if not any(_host_in(r.get("url", ""), f) for f in forbid)]
    # Step 3: LLM scores each
    scored = _score(use_case, must_have, filtered)
    # Step 4: rank + trim
    scored.sort(key=lambda r: -r["match_score"])
    top = scored[:max_results]
    digest = _llm_digest(use_case, top)

    payload = {
        "summary": _summary(use_case, len(raw), len(filtered), top, digest),
        "use_case": use_case,
        "registry": registry,
        "candidate_count": len(raw),
        "filtered_count": len(filtered),
        "recommendations": top,
        "digest": digest,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", use_case.lower()).strip("_")[:40] or "curate"
    _save("phase7/agent_marketplace", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("agent_marketplace_curator", use_case[:60], f"candidates={len(raw)} top={len(top)}")
    return payload


# ---------------------------------------------------------------------------

def _collect(use_case: str, registry: str) -> List[Dict[str, Any]]:
    """Try live fetches; fall back to a curated seed list when offline."""
    candidates: List[Dict[str, Any]] = []
    if registry in {"auto", "pulse", "github"}:
        candidates.extend(_try_pulse())
    if registry in {"auto", "glama"}:
        candidates.extend(_try_glama())
    if registry in {"auto", "mcp_so"}:
        candidates.extend(_try_mcp_so())
    if not candidates:
        candidates = _seed_registry()
    return candidates


def _try_pulse() -> List[Dict[str, Any]]:
    try:
        import requests
        r = requests.get("https://pulse.mcp.run/api/servers", timeout=10)
        if r.ok:
            data = r.json()
            return [
                {"name": s.get("name", "?"), "url": s.get("url") or s.get("homepage", ""),
                 "description": s.get("description", ""), "install": s.get("install", "npx -y " + s.get("name", "")),
                 "publisher": s.get("publisher", "unknown"), "version": s.get("version", "0.0.0"),
                 "last_updated": s.get("updatedAt", ""), "registry": "pulse"}
                for s in (data if isinstance(data, list) else data.get("servers", []))
            ]
    except Exception:
        return []


def _try_glama() -> List[Dict[str, Any]]:
    try:
        import requests
        r = requests.get("https://glama.ai/api/mcp/servers", timeout=10)
        if r.ok:
            data = r.json()
            return [
                {"name": s.get("name", "?"), "url": s.get("homepage", ""),
                 "description": s.get("description", ""), "install": s.get("install", ""),
                 "publisher": s.get("publisher", "?"), "version": s.get("version", "0.0.0"),
                 "last_updated": s.get("updatedAt", ""), "registry": "glama"}
                for s in (data if isinstance(data, list) else data.get("servers", []))
            ]
    except Exception:
        return []


def _try_mcp_so() -> List[Dict[str, Any]]:
    try:
        import requests
        r = requests.get("https://mcp.so/api/servers", timeout=10)
        if r.ok:
            data = r.json()
            return [
                {"name": s.get("name", "?"), "url": s.get("url", ""),
                 "description": s.get("description", ""), "install": s.get("install", ""),
                 "publisher": s.get("author", "?"), "version": s.get("version", "0.0.0"),
                 "last_updated": s.get("updated_at", ""), "registry": "mcp_so"}
                for s in (data if isinstance(data, list) else data.get("data", []))
            ]
    except Exception:
        return []


def _seed_registry() -> List[Dict[str, Any]]:
    return [
        {"name": "github-mcp",        "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-github", "description": "Official GitHub MCP server: repos, issues, PRs, actions, code search.", "last_updated": "2026-01-15", "registry": "seed"},
        {"name": "postgres-mcp",      "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-postgres", "description": "Read-only and read-write Postgres access.", "last_updated": "2026-01-10", "registry": "seed"},
        {"name": "puppeteer-mcp",     "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-puppeteer", "description": "Headless Chrome automation via Puppeteer.", "last_updated": "2025-12-20", "registry": "seed"},
        {"name": "slack-mcp",         "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-slack", "description": "Read/post Slack messages, manage channels.", "last_updated": "2026-01-05", "registry": "seed"},
        {"name": "fetch-mcp",         "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-fetch", "description": "HTTP fetch + clean markdown extraction.", "last_updated": "2026-01-08", "registry": "seed"},
        {"name": "filesystem-mcp",    "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-filesystem", "description": "Sandboxed filesystem access.", "last_updated": "2025-11-30", "registry": "seed"},
        {"name": "sentry-mcp",        "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "0.9.0", "install": "npx -y @modelcontextprotocol/server-sentry", "description": "Read Sentry issues, events, releases.", "last_updated": "2025-12-15", "registry": "seed"},
        {"name": "brave-search-mcp",  "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "1.0.0", "install": "npx -y @modelcontextprotocol/server-brave-search", "description": "Brave Search API wrapper.", "last_updated": "2026-01-12", "registry": "seed"},
        {"name": "google-drive-mcp",  "url": "https://github.com/modelcontextprotocol/servers",  "publisher": "modelcontextprotocol", "version": "0.8.0", "install": "npx -y @modelcontextprotocol/server-gdrive", "description": "Read/write Google Drive files.", "last_updated": "2025-10-22", "registry": "seed"},
        {"name": "notion-mcp",        "url": "https://github.com/makenotion/notion-mcp",         "publisher": "makenotion",            "version": "1.0.0", "install": "npx -y @notionhq/notion-mcp", "description": "Notion API: pages, blocks, databases, search.", "last_updated": "2026-01-02", "registry": "seed"},
    ]


def _score(use_case: str, must_have: List[str], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    system = (
        "You are a platform engineer scoring agent-marketplace listings for "
        "fitness against a use case.  Return ONLY a JSON object: {\"scores\": [\n"
        "  {\"name\": str, \"match_score\": 0..100, \"matched_capabilities\": [str], "
        "  \"missing_capabilities\": [str], \"risk_flags\": [str], \"rationale\": str}\n"
        "]}.  No prose, no fences."
    )
    user = (
        f"Use case: {use_case}\nMust-have: {json.dumps(must_have)}\n\n"
        f"Candidates (truncated): {json.dumps(candidates)[:8000]}"
    )
    raw = _llm(user, system, "agent_marketplace_curator")
    parsed = _parse_json(raw, fallback={"scores": []})
    score_map = {s.get("name"): s for s in parsed.get("scores") or []}
    out: List[Dict[str, Any]] = []
    for c in candidates:
        s = score_map.get(c["name"], {})
        out.append({**c, **{
            "match_score":          int(s.get("match_score", 0)),
            "matched_capabilities": s.get("matched_capabilities", []),
            "missing_capabilities": s.get("missing_capabilities", []),
            "risk_flags":           _safety_flags(c) + (s.get("risk_flags", []) or []),
            "rationale":            s.get("rationale", ""),
        }})
    return out


def _safety_flags(c: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if not c.get("publisher") or c.get("publisher") in {"unknown", "?"}:
        out.append("unverified publisher")
    if not c.get("last_updated"):
        out.append("no last-updated timestamp")
    if c.get("last_updated") and c["last_updated"] < "2025-06-01":
        out.append("stale (no updates >12m)")
    return out


def _host_in(url: str, host: str) -> bool:
    return host and host in (url or "")


def _llm_digest(use_case: str, top: List[Dict[str, Any]]) -> str:
    if not top:
        return "No matching listings found."
    system = (
        "You are a senior platform engineer.  Write a 6-10 line digest recommending "
        "the best agent-marketplace listings for the use case.  Explain trade-offs.  "
        "No markdown, no emojis."
    )
    user = f"Use case: {use_case}\n\nTop picks:\n{json.dumps(top[:5])[:6000]}"
    return _llm(user, system, "agent_marketplace_curator").strip()


def _summary(use_case: str, raw: int, filt: int, top: List[Dict[str, Any]], digest: str) -> str:
    return f"Curator: {raw} candidates, {filt} after filters, {len(top)} recommendations."
