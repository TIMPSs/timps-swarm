"""Web Search Agent — multi-engine web search with deduplication, optional
content extraction, and LLM-synthesised answer with citations.

Search engines supported (chosen for zero-credential access):

* `duckduckgo`  — DDG HTML endpoint (default; no key required)
* `brave`       — Brave Search API (requires `BRAVE_API_KEY` env var)
* `serpapi`     — SerpAPI (requires `SERPAPI_KEY` env var)
* `bing`        — Bing Web Search API (requires `BING_SEARCH_KEY` env var)

The agent:

1. Refines the user query (LLM suggests 1-3 alternative phrasings).
2. Fetches top results from each requested engine.
3. Deduplicates by URL (and by canonicalised URL).
4. Optionally fetches the body of each result and strips HTML.
5. Asks the LLM to synthesise a concise answer with `[N]` citations.
6. Saves a search log under `generated/web_search/<slug>/` and a
   `_summary.json` file alongside it.

If the local network is unavailable, the agent still returns a structured
result (empty `results`, an LLM-only synthesised answer, and a clear
`network_status` field) so callers can fall back gracefully.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src._helpers import _GEN, _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "nextgen"

SUPPORTED_ENGINES = ("duckduckgo", "brave", "serpapi", "bing")
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    query = (args.get("query") or args.get("request") or "").strip()
    engines = [e.lower() for e in (args.get("engines") or ["duckduckgo"]) if e.lower() in SUPPORTED_ENGINES] or ["duckduckgo"]
    max_results = int(args.get("max_results") or 10)
    recency = (args.get("recency") or "any").lower()  # 'day'|'week'|'month'|'year'|'any'
    content_type = (args.get("content_type") or "general").lower()  # 'general'|'news'|'academic'|'code'
    locale = args.get("locale") or "en-US"
    synthesize = bool(args.get("synthesize", True))
    fetch_content = bool(args.get("fetch_content", True))
    max_content_chars = int(args.get("max_content_chars") or 2400)
    max_fetch = min(int(args.get("max_fetch") or 5), max_results)

    if not query:
        return {
            "summary": "No query provided — supply a `query` argument.",
            "error": "query is required",
            "results": [],
            "answer": "",
        }

    slug = re.sub(r"[^a-z0-9_]+", "_", query.lower()).strip("_")[:60] or "search"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _GEN / "web_search" / f"{run_id}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ search
    raw_results: List[Dict[str, Any]] = []
    engine_status: Dict[str, str] = {}
    for engine in engines:
        try:
            r = _search_with_engine(engine, query, max_results, recency, content_type, locale)
            raw_results.extend(r)
            engine_status[engine] = f"ok ({len(r)})"
        except Exception as exc:
            engine_status[engine] = f"error: {type(exc).__name__}: {str(exc)[:120]}"

    # ---------------------------------------------------------------- dedupe
    seen: Dict[str, Dict[str, Any]] = {}
    for r in raw_results:
        url = r.get("url") or ""
        key = _canonical_url(url)
        if not key:
            continue
        if key not in seen or r.get("engine_priority", 0) > seen[key].get("engine_priority", 0):
            seen[key] = r
    deduped = list(seen.values())

    # Optionally re-rank with a simple score (snippet length + position)
    deduped.sort(key=lambda r: (-len(r.get("snippet") or ""), r.get("position", 999)))
    results = deduped[:max_results]

    # ---------------------------------------------------------------- fetch
    fetched_count = 0
    for r in results:
        r["content"] = ""
        if fetch_content and fetched_count < max_fetch:
            try:
                content = _fetch_url(r["url"], max_content_chars)
                if content:
                    r["content"] = content
                    fetched_count += 1
            except Exception:
                pass
        r["fetched_at"] = _ts() if r.get("content") else None

    # ---------------------------------------------------------------- refine + synthesize
    refined_queries: List[str] = []
    answer: str = ""
    citations: List[Dict[str, str]] = []
    llm_used = False
    if synthesize:
        try:
            refined_queries = _refine_query(query, content_type, locale)
        except Exception:
            refined_queries = []
        try:
            ans, cites = _synthesize_answer(query, results, content_type, locale)
            answer, citations = ans, cites
            llm_used = True
        except Exception:
            answer = ""
            citations = []

    # ---------------------------------------------------------------- save
    payload = {
        "summary": _summary(query, results, answer, llm_used, engine_status),
        "query": query,
        "refined_queries": refined_queries,
        "engines_used": engines,
        "engine_status": engine_status,
        "recency": recency,
        "content_type": content_type,
        "locale": locale,
        "max_results": max_results,
        "raw_count": len(raw_results),
        "deduped_count": len(deduped),
        "fetched_count": fetched_count,
        "results": results,
        "answer": answer,
        "citations": citations,
        "llm_used": llm_used,
        "log_dir": str(out_dir),
        "generated_at": _ts(),
    }

    log_path = out_dir / "search_log.json"
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _save("web_search", f"{run_id}_{slug}_summary.json", json.dumps(payload, indent=2))
    _record("web_search", query[:80], f"engines={','.join(engines)} results={len(results)} fetched={fetched_count}")
    return payload


# ---------------------------------------------------------------------------
# Engine adapters
# ---------------------------------------------------------------------------

def _search_with_engine(
    engine: str,
    query: str,
    max_results: int,
    recency: str,
    content_type: str,
    locale: str,
) -> List[Dict[str, Any]]:
    if engine == "duckduckgo":
        return _search_duckduckgo(query, max_results, recency, content_type, locale)
    if engine == "brave":
        return _search_brave(query, max_results, recency)
    if engine == "serpapi":
        return _search_serpapi(query, max_results)
    if engine == "bing":
        return _search_bing(query, max_results, recency)
    return []


def _search_duckduckgo(query, max_results, recency, content_type, locale) -> List[Dict[str, Any]]:
    """DuckDuckGo HTML — public, no API key required."""
    import requests
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query, "kl": _ddg_region(locale)}
    if recency in {"day", "week", "month", "year"}:
        params["df"] = recency
    resp = requests.post(url, data=params, headers={"User-Agent": DEFAULT_UA}, timeout=20)
    resp.raise_for_status()
    html = resp.text

    results: List[Dict[str, Any]] = []
    # Each result block:  <a class="result__a" href="...">title</a> ... <a class="result__snippet">...</a>
    pattern = re.compile(
        r'class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)',
        re.DOTALL | re.IGNORECASE,
    )
    for i, m in enumerate(pattern.finditer(html), start=1):
        title = _strip_html(m.group("title")).strip()
        snippet = _strip_html(m.group("snippet")).strip()
        href = _resolve_ddg_href(m.group("url"))
        if not href or not title:
            continue
        results.append({
            "title": title,
            "url": href,
            "snippet": snippet,
            "source_engine": "duckduckgo",
            "position": i,
            "engine_priority": 1,
            "content_type": content_type,
        })
        if len(results) >= max_results:
            break
    return results


def _search_brave(query, max_results, recency) -> List[Dict[str, Any]]:
    """Brave Search API. Requires BRAVE_API_KEY."""
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        raise RuntimeError("BRAVE_API_KEY not set")
    import requests
    freshness = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}.get(recency)
    params = {"q": query, "count": max_results}
    if freshness:
        params["freshness"] = freshness
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params=params,
        headers={"X-Subscription-Token": key, "Accept": "application/json", "User-Agent": DEFAULT_UA},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for i, item in enumerate((data.get("web") or {}).get("results") or [], start=1):
        out.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
            "source_engine": "brave",
            "position": i,
            "engine_priority": 2,
        })
    return out


def _search_serpapi(query, max_results) -> List[Dict[str, Any]]:
    """SerpAPI Google wrapper. Requires SERPAPI_KEY."""
    key = os.getenv("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY not set")
    import requests
    resp = requests.get(
        "https://serpapi.com/search.json",
        params={"q": query, "api_key": key, "num": max_results},
        headers={"User-Agent": DEFAULT_UA},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(data.get("organic_results") or [], start=1):
        out.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source_engine": "serpapi",
            "position": i,
            "engine_priority": 3,
        })
    return out


def _search_bing(query, max_results, recency) -> List[Dict[str, Any]]:
    """Bing Web Search API. Requires BING_SEARCH_KEY."""
    key = os.getenv("BING_SEARCH_KEY")
    if not key:
        raise RuntimeError("BING_SEARCH_KEY not set")
    import requests
    freshness = {"day": "Day", "week": "Week", "month": "Month"}.get(recency)
    params = {"q": query, "count": max_results, "mkt": "en-US"}
    if freshness:
        params["freshness"] = freshness
    resp = requests.get(
        "https://api.bing.microsoft.com/v7.0/search",
        params=params,
        headers={"Ocp-Apim-Subscription-Key": key, "User-Agent": DEFAULT_UA},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out: List[Dict[str, Any]] = []
    for i, item in enumerate((data.get("webPages") or {}).get("value") or [], start=1):
        out.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "source_engine": "bing",
            "position": i,
            "engine_priority": 2,
        })
    return out


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _resolve_ddg_href(href: str) -> str:
    """DDG wraps result URLs in /l/?uddg=<encoded>.  Unwrap if needed."""
    if "uddg=" in href:
        try:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            return qs.get("uddg", [href])[0]
        except Exception:
            return href
    return href


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url.strip())
        host = (p.netloc or "").lower().replace("www.", "")
        path = re.sub(r"/+$", "", p.path or "")
        return f"{host}{path}"
    except Exception:
        return url


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")


def _fetch_url(url: str, max_chars: int) -> str:
    import requests
    resp = requests.get(url, headers={"User-Agent": DEFAULT_UA}, timeout=15, allow_redirects=True)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        return ""
    text = _strip_html(resp.text)
    text = re.sub(r"\s{2,}", " ", text)
    return text[:max_chars]


def _ddg_region(locale: str) -> str:
    """Convert a locale like 'en-US' to a DDG `kl` value like 'us-en'."""
    try:
        lang, country = locale.split("-")
        return f"{country.lower()}-{lang.lower()}"
    except Exception:
        return "us-en"


# ---------------------------------------------------------------------------
# LLM steps
# ---------------------------------------------------------------------------

def _refine_query(query: str, content_type: str, locale: str) -> List[str]:
    system = (
        "You refine web search queries.  Return ONLY a JSON object: "
        "{\"alternates\": [str, str, str]} — at most 3 alternative phrasings "
        "that would yield better recall.  No prose, no fences."
    )
    user = (
        f"Original query: {query}\n"
        f"Content type: {content_type}\nLocale: {locale}\n"
    )
    raw = _llm(user, system, "web_search")
    parsed = _parse_json(raw, fallback={"alternates": []})
    alts = [str(x) for x in (parsed.get("alternates") or [])][:3]
    return [a for a in alts if a and a.lower() != query.lower()]


def _synthesize_answer(query: str, results: List[Dict[str, Any]], content_type: str, locale: str) -> tuple[str, List[Dict[str, str]]]:
    if not results:
        return "", []
    numbered = []
    for i, r in enumerate(results, start=1):
        body = (r.get("content") or r.get("snippet") or "")[:1500]
        numbered.append(f"[{i}] {r.get('title','')} — {r.get('url','')}\n{body}")
    system = (
        "You are a research analyst.  Using ONLY the numbered sources provided, "
        "answer the user's query.  Cite sources inline as `[N]` (and only `[N]`). "
        "If sources disagree, note the disagreement.  Keep the answer under 400 words. "
        "Return a JSON object: {\"answer\": str, \"citations\": [{\"index\": int, \"title\": str, \"url\": str}]}"
    )
    user = (
        f"Query: {query}\n"
        f"Content type: {content_type}\nLocale: {locale}\n\n"
        f"Sources:\n" + "\n\n".join(numbered)
    )
    raw = _llm(user, system, "web_search")
    parsed = _parse_json(raw, fallback={"answer": "", "citations": []})
    ans = (parsed.get("answer") or "").strip()
    cites = []
    for c in parsed.get("citations") or []:
        try:
            idx = int(c.get("index"))
            if 1 <= idx <= len(results):
                cites.append({"index": idx, "title": results[idx - 1].get("title", ""), "url": results[idx - 1].get("url", "")})
        except Exception:
            continue
    return ans, cites


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _summary(query: str, results: List[Dict[str, Any]], answer: str, llm_used: bool, engine_status: Dict[str, str]) -> str:
    engines = ", ".join(f"{k}={v}" for k, v in engine_status.items())
    if not results and not answer:
        return f"No results for '{query}' (engines: {engines})."
    if answer:
        n = len(answer)
        return (
            f"Web search for '{query}': {len(results)} results from {engines}; "
            f"synthesised {n}-char answer{'via LLM' if llm_used else ''}."
        )
    return f"Web search for '{query}': {len(results)} results from {engines}; no LLM synthesis."
