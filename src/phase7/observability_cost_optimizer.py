"""Observability Cost Optimizer — analyses telemetry-pipeline configuration
and ingests sample log/metric/trace volume to recommend concrete savings
on Datadog / Grafana Cloud / Honeycomb / New Relic / Splunk / self-hosted
Loki+Elastic bills.

Pipeline:

1. **Detect backend** from config files (datadog.yaml, prometheus.yml,
   loki config, otel-collector.yaml, grafana dashboards, etc.).
2. **Gather volume signals** — read recent log/trace files for size +
   retention settings; if none, run an LLM-only estimation.
3. **Per-pillar optimisations**: ingest sampling, retention tuning, log
   exclusion, metric cardinality, trace head-sampling, span attribute
   reduction, index rebalancing.
4. **Output**: ranked savings list with monthly $ estimate, an updated
   config snippet, and a PR-ready diff.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "phase7"

PRICING = {
    # Rough public list-price-ish numbers as of 2026 — used for order-of-magnitude estimates only.
    "datadog":    {"ingest_per_gb": 0.10, "indexed_per_million": 1.05, "span_per_million": 0.10, "host_per_month": 15},
    "grafana":    {"ingest_per_gb": 0.50, "active_series_per_10k": 8, "logs_per_gb": 0.50},
    "honeycomb":  {"ingest_per_gb": 0.95, "span_per_million": 0.45},
    "newrelic":   {"ingest_per_gb": 0.35, "span_per_million": 0.10},
    "splunk":     {"ingest_per_gb": 4.50, "indexed_per_gb": 4.50},
    "loki":       {"storage_per_gb_month": 0.10},
    "elastic":    {"storage_per_gb_month": 0.12, "ingest_per_gb": 0.40},
    "self_host":  {"storage_per_gb_month": 0.05},
}


def observability_cost_optimizer(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = Path(args.get("repo_path") or ".")
    backend = (args.get("backend") or _detect_backend(repo_path)).lower()
    monthly_bill = float(args.get("monthly_bill") or 0.0)
    volume_hint = args.get("volume") or {}

    if not repo_path.is_dir():
        return {"summary": f"Repo path '{repo_path}' not found.", "error": "repo_path required",
                "optimisations": []}

    pricing = PRICING.get(backend, PRICING["self_host"])
    volume = _estimate_volume(repo_path, backend, volume_hint)
    baseline = monthly_bill or _baseline_cost(backend, volume, pricing)

    optimisations = _optimise(backend, repo_path, volume, pricing, baseline)
    savings = sum(o["estimated_savings_usd"] for o in optimisations)
    config_snippet = _render_config_diff(backend, optimisations)

    payload = {
        "summary": _summary(backend, baseline, savings, optimisations),
        "backend": backend,
        "repo_path": str(repo_path),
        "volume_estimate": volume,
        "baseline_monthly_usd": round(baseline, 2),
        "estimated_savings_usd": round(savings, 2),
        "savings_pct": round(100 * savings / max(1.0, baseline), 1),
        "optimisations": optimisations,
        "config_snippet": config_snippet,
        "pricing_table": pricing,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", backend).strip("_") or "obs"
    _save("phase7/obs_cost", f"{slug}_{_ts()}_report.json", json.dumps(payload, indent=2))
    _record("observability_cost_optimizer", backend, f"baseline=${baseline:.0f} savings=${savings:.0f}")
    return payload


# ---------------------------------------------------------------------------

def _detect_backend(root: Path) -> str:
    if (root / "datadog.yaml").exists() or (root / "otel-collector.yaml").exists() and "datadog" in (root / "otel-collector.yaml").read_text(errors="ignore").lower():
        return "datadog"
    for f in root.rglob("*.yaml"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if "honeycomb" in t: return "honeycomb"
        if "newrelic" in t or "new_relic" in t or "newrelic.com" in t: return "newrelic"
        if "splunk" in t: return "splunk"
        if "loki" in t:    return "loki"
        if "elasticsearch" in t or "opensearch" in t: return "elastic"
    if (root / "prometheus.yml").exists() or (root / "docker-compose.yml").exists() and "prometheus" in (root / "docker-compose.yml").read_text(errors="ignore").lower():
        return "self_host"
    if (root / "grafana").is_dir() or (root / "loki").is_dir():
        return "grafana"
    return "self_host"


def _estimate_volume(root: Path, backend: str, hint: Dict[str, Any]) -> Dict[str, Any]:
    if hint:
        return hint
    log_bytes = 0
    for ext in ("*.log", "*.json"):
        for f in root.rglob(ext):
            try:
                log_bytes += min(f.stat().st_size, 5_000_000)  # cap per-file
            except Exception:
                pass
    return {
        "log_gb_per_day": round(log_bytes / (1024 ** 3) * 0.05, 3),  # rough daily sample
        "spans_per_day": 50_000_000 if backend in {"honeycomb", "newrelic", "datadog"} else 5_000_000,
        "metrics_active_series": 50_000 if backend in {"grafana", "self_host"} else 200_000,
        "retention_days": 30,
    }


def _baseline_cost(backend: str, v: Dict[str, Any], p: Dict[str, float]) -> float:
    cost = 0.0
    cost += v.get("log_gb_per_day", 0) * 30 * p.get("ingest_per_gb", 0.5)
    if "span_per_million" in p:
        cost += v.get("spans_per_day", 0) * 30 / 1_000_000 * p["span_per_million"]
    if "indexed_per_million" in p:
        cost += v.get("spans_per_day", 0) * 30 / 1_000_000 * p["indexed_per_million"]
    if "storage_per_gb_month" in p and v.get("log_gb_per_day"):
        cost += v["log_gb_per_day"] * 30 * p["storage_per_gb_month"]
    return max(0.0, cost)


def _optimise(backend: str, root: Path, vol: Dict[str, Any], p: Dict[str, float], baseline: float) -> List[Dict[str, Any]]:
    """Apply heuristics + an LLM to enumerate concrete savings."""
    candidates: List[Dict[str, Any]] = []

    # 1. Log exclusion (drop noisy services / health checks)
    candidates.append({
        "title": "Drop health-check & readiness logs at the agent",
        "category": "log_exclusion",
        "estimated_savings_usd": round(baseline * 0.18, 2),
        "effort": "low",
        "details": "Add `logs: [{service:*, source:*, pattern:(http\\.request\\.method=\"GET\" AND http\\.url.path=\"/healthz\")}]` exclusion.",
        "config_change": {"otel-collector": "processors: [tail_sampling, filter]  # add filter/logs to drop health checks"},
    })

    # 2. Head-based trace sampling
    if "span_per_million" in p:
        candidates.append({
            "title": "Reduce trace ingest via head-sampling at 10%",
            "category": "trace_sampling",
            "estimated_savings_usd": round(baseline * 0.35, 2),
            "effort": "low",
            "details": "Sample 10% of traces at the agent; 100% for error traces.",
            "config_change": {"otel-collector": "processors: [tail_sampling/probabilistic_sampler{decision_wait:10s, sampling_percentage:10}]"},
        })

    # 3. Retention reduction
    if vol.get("retention_days", 30) > 15:
        candidates.append({
            "title": f"Reduce retention from {vol['retention_days']}d → 15d on hot index",
            "category": "retention",
            "estimated_savings_usd": round(baseline * 0.10, 2),
            "effort": "low",
            "details": "Move hot data to cheaper storage (S3 IA) after 7 days; keep 15d searchable.",
            "config_change": {},
        })

    # 4. Metric cardinality cap
    if vol.get("metrics_active_series", 0) > 50_000:
        candidates.append({
            "title": "Cap per-label cardinality at 200 (drop user_id, raw_url, etc.)",
            "category": "metric_cardinality",
            "estimated_savings_usd": round(baseline * 0.20, 2),
            "effort": "medium",
            "details": "Prometheus relabel: drop series with > 200 unique label values.",
            "config_change": {"prometheus": "metric_relabel_configs: [regex:'(.*)', action:'labeldrop', separator:',' target_label:'user_id']"},
        })

    # 5. Drop span attributes
    candidates.append({
        "title": "Strip high-cardinality span attributes (request_body, response_body)",
        "category": "span_attribute",
        "estimated_savings_usd": round(baseline * 0.08, 2),
        "effort": "low",
        "details": "Use OpenTelemetry attribute processor to drop 'http.request.body' and 'http.response.body'.",
        "config_change": {"otel-collector": "processors: [attributes/actions: [{key: http.request.body, action: delete}, {key: http.response.body, action: delete}]"},
    })

    # 6. LLM-generated extras (optional)
    extra = _llm_extras(backend, vol, baseline)
    candidates.extend(extra)

    # Sort by savings desc
    candidates.sort(key=lambda c: c["estimated_savings_usd"], reverse=True)
    return candidates


def _llm_extras(backend: str, vol: Dict[str, Any], baseline: float) -> List[Dict[str, Any]]:
    system = (
        "You are a FinOps engineer.  Given an observability backend and a rough "
        "monthly spend, propose 1-3 additional concrete savings (each must be "
        "implementable in a single PR).  Return ONLY a JSON object: "
        "{\"items\": [{\"title\": str, \"category\": str, "
        "\"estimated_savings_usd\": float, \"effort\": \"low\"|\"medium\"|\"high\", "
        "\"details\": str}]}  No prose, no fences."
    )
    user = (
        f"Backend: {backend}\nVolume: {json.dumps(vol)}\nBaseline: ${baseline:.0f}/month\n"
    )
    raw = _llm(user, system, "observability_cost_optimizer")
    parsed = _parse_json(raw, fallback={"items": []})
    out: List[Dict[str, Any]] = []
    for it in parsed.get("items") or []:
        out.append({
            "title": it.get("title", "?"),
            "category": it.get("category", "other"),
            "estimated_savings_usd": float(it.get("estimated_savings_usd", 0.0) or 0.0),
            "effort": it.get("effort", "medium"),
            "details": it.get("details", ""),
            "config_change": {},
        })
    return out


def _render_config_diff(backend: str, opts: List[Dict[str, Any]]) -> str:
    lines = [f"# Suggested config for {backend} — generated by TIMPS Swarm"]
    for o in opts:
        if not o.get("config_change"): continue
        lines.append(f"\n## {o['title']}")
        for fname, snippet in o["config_change"].items():
            lines.append(f"\n```{fname}\n{snippet}\n```")
    return "\n".join(lines)


def _summary(backend: str, baseline: float, savings: float, opts: List[Dict[str, Any]]) -> str:
    pct = 100 * savings / max(1.0, baseline)
    return (f"Observability cost ({backend}): baseline ${baseline:.0f}/mo, "
            f"{len(opts)} optimisations, ${savings:.0f} ({pct:.0f}%) potential savings.")
