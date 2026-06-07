"""
Log Pattern Analyzer — cross-service clustering, anomaly detection,
and root-cause hypotheses.

Where `log_detective` clusters errors in a single log stream, this agent
ingests logs from multiple sources (app, web, db, broker, infra),
normalises timestamps/levels, clusters semantically similar error
messages, detects bursts/anomalies vs. a baseline, correlates patterns
across services + time windows, and ranks root-cause hypotheses by
explanatory power.

Input:  logs_by_source (dict), window (str), baseline (str),
        services (list), known_deploys (list)
Output: clusters, anomalies, correlations, hypotheses,
        heatmap_csv, alert_recommendations, report_path
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record


def _flatten_logs(logs_by_source: Any) -> str:
    if isinstance(logs_by_source, dict):
        parts = []
        for src, txt in list(logs_by_source.items())[:8]:
            parts.append(f"### source: {src}\n" + (str(txt) or "")[:2500])
        return "\n\n".join(parts)[:8000]
    return (str(logs_by_source or "") or "")[:8000]


def log_pattern_analyzer(args: Dict[str, Any]) -> Dict[str, Any]:
    logs_by_source = args.get("logs_by_source") or args.get("logs") or {}
    window         = args.get("window", "last 1h")
    baseline       = args.get("baseline", "last 24h average")
    services       = args.get("services") or []
    known_deploys  = args.get("known_deploys") or []

    blob = _flatten_logs(logs_by_source)

    system = (
        "You are a site-reliability log analyst. Cluster semantically similar log "
        "lines (do NOT cluster on exact string match — strip numbers, IDs, UUIDs, "
        "timestamps first). Detect anomalies (statistically unusual frequency vs. "
        "baseline), correlate patterns ACROSS services and time windows, and rank "
        "root-cause HYPOTHESES by explanatory power (Occam-favoured). "
        "Output ONLY valid JSON: "
        "{services_seen:[str], time_window:str, "
        "clusters:[{cluster_id,template,severity,count,services,first_seen,"
        "last_seen,example_lines:[str]}], "
        "anomalies:[{cluster_id,baseline_rate_per_min,observed_rate_per_min,"
        "delta_pct,zscore,burst_window}], "
        "cross_service_correlations:[{cluster_ids:[str],lag_seconds,confidence,"
        "narrative}], "
        "root_cause_hypotheses:[{hypothesis,supporting_evidence:[str],"
        "contradicting_evidence:[str],probability,validation_query}], "
        "deploy_correlation:[{deploy,affected_clusters:[str],time_offset_seconds}], "
        "heatmap_csv:str, "
        "alert_recommendations:[{name,promql_or_logql_or_kql,for_minutes,"
        "severity,playbook_url}], "
        "next_diagnostic_steps:[str]}."
    )
    prompt = (
        f"Window: {window}  Baseline: {baseline}\nServices: {services}\n"
        f"Known recent deploys: {known_deploys}\n\n"
        f"LOGS:\n```\n{blob}\n```\n\n"
        "Cluster aggressively, then dedupe by template. Hypotheses must be "
        "falsifiable and include a validation query."
    )

    data = _parse_json(_llm(prompt, system, "log_pattern_analyzer"), {
        "clusters": [], "anomalies": [], "cross_service_correlations": [],
        "root_cause_hypotheses": [], "alert_recommendations": [],
    })

    ts = _ts()
    heatmap_path = ""
    if data.get("heatmap_csv"):
        heatmap_path = _save("data", f"log_heatmap_{ts}.csv", data["heatmap_csv"])

    alerts_path = _save("monitoring", f"log_alerts_{ts}.json",
                        json.dumps(data.get("alert_recommendations", []), indent=2))

    clusters = data.get("clusters", [])
    anomalies = data.get("anomalies", [])
    hyp = data.get("root_cause_hypotheses", [])

    report = (
        f"# Log Pattern Analyzer — {ts}\n\n"
        f"**Window:** {window}  **Services:** {data.get('services_seen', services)}  "
        f"**Clusters:** {len(clusters)}  **Anomalies:** {len(anomalies)}  "
        f"**Hypotheses:** {len(hyp)}\n\n"
        "## Top clusters\n"
        + "\n".join(
            f"- `{c.get('cluster_id','?')}` [{c.get('severity','?').upper()}] "
            f"×{c.get('count','?')} across {c.get('services',[])}: "
            f"_{c.get('template','?')}_"
            for c in sorted(clusters, key=lambda x: -(x.get("count") or 0))[:12]
        )
        + "\n\n## Anomalies vs. baseline\n"
        + "\n".join(
            f"- `{a.get('cluster_id','?')}` baseline "
            f"{a.get('baseline_rate_per_min','?')}/min → "
            f"{a.get('observed_rate_per_min','?')}/min "
            f"(Δ {a.get('delta_pct','?')}%, z={a.get('zscore','?')})"
            for a in anomalies
        )
        + "\n\n## Root-cause hypotheses (ranked)\n"
        + "\n".join(
            f"### {i+1}. {h.get('hypothesis','?')} (p={h.get('probability','?')})\n"
            f"_For_:\n" + "\n".join(f"  - {e}" for e in h.get("supporting_evidence", []))
            + "\n_Against_:\n"
            + "\n".join(f"  - {e}" for e in h.get("contradicting_evidence", []))
            + f"\n_Validate_: `{h.get('validation_query','')}`"
            for i, h in enumerate(hyp)
        )
        + "\n\n## Deploy correlation\n"
        + "\n".join(
            f"- {d.get('deploy','?')} → {d.get('affected_clusters',[])} "
            f"(+{d.get('time_offset_seconds','?')}s)"
            for d in data.get("deploy_correlation", [])
        )
        + "\n\n## Next diagnostic steps\n"
        + "\n".join(f"- {n}" for n in data.get("next_diagnostic_steps", []))
    )
    report_path = _save("reports", f"log_pattern_analyzer_{ts}.md", report)

    _record("log_pattern_analyzer", f"window={window}",
            f"clusters={len(clusters)} anomalies={len(anomalies)} hyp={len(hyp)}")

    return {
        "services_seen":            data.get("services_seen", services),
        "time_window":              window,
        "clusters":                 clusters,
        "anomalies":                anomalies,
        "cross_service_correlations": data.get("cross_service_correlations", []),
        "root_cause_hypotheses":    hyp,
        "deploy_correlation":       data.get("deploy_correlation", []),
        "heatmap_csv_path":         heatmap_path,
        "alert_recommendations":    data.get("alert_recommendations", []),
        "alerts_config_path":       alerts_path,
        "next_diagnostic_steps":    data.get("next_diagnostic_steps", []),
        "report_path":              report_path,
        "summary": (
            f"Found {len(clusters)} clusters, {len(anomalies)} anomalies. "
            f"Top hypothesis: "
            f"{(hyp[0].get('hypothesis') if hyp else 'none')}. → {report_path}."
        ),
    }
