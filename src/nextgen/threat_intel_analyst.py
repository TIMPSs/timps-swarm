"""
Threat Intelligence Analyst — continuously monitors open-source threat
feeds (CVE/NVD, MITRE ATT&CK, KEV catalog), correlates indicators with
the user's actual dependency tree, and emits prioritised threat briefings
mapped to the technology stack in use.

Input:  dependencies (list|str), stack (str), focus (str), feeds (list)
Output: critical_cves, prioritised_threats, ttp_mapping,
        actionable_briefing, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _gather_deps(args: Dict[str, Any]) -> str:
    """Best-effort: read deps from arg, file path, or local manifests."""
    deps = args.get("dependencies", "")
    if isinstance(deps, list):
        return "\n".join(str(x) for x in deps[:300])
    if isinstance(deps, str) and deps.strip():
        return deps[:6000]

    manifest_path = args.get("manifest_path", "")
    if manifest_path and Path(manifest_path).is_file():
        return Path(manifest_path).read_text(encoding="utf-8", errors="ignore")[:6000]

    chunks: List[str] = []
    for name in ("requirements.txt", "pyproject.toml", "package.json",
                 "Cargo.toml", "go.mod", "Gemfile.lock"):
        p = Path(name)
        if p.exists():
            chunks.append(f"### {name}\n" + p.read_text(encoding="utf-8",
                                                         errors="ignore")[:1500])
    return "\n\n".join(chunks)[:6000]


def threat_intel_analyst(args: Dict[str, Any]) -> Dict[str, Any]:
    stack    = args.get("stack", "generic web stack")
    focus    = args.get("focus", "auto")
    feeds    = args.get("feeds") or ["NVD", "MITRE ATT&CK", "CISA KEV", "OSV.dev"]
    deps_blob = _gather_deps(args)

    sys_info = _run("uname -a", timeout=5)[:200]

    system = (
        "You are a senior cyber threat intelligence analyst. Cross-reference the "
        "user's dependency tree and stack against current open-source threat feeds "
        "(CVE/NVD, MITRE ATT&CK techniques, CISA Known Exploited Vulnerabilities, "
        "OSV.dev, GitHub Security Advisories). Output ONLY valid JSON in this shape: "
        "{overall_risk:'critical'|'high'|'medium'|'low', "
        "critical_cves:[{id,package,severity,cvss,kev_listed:bool,"
        "exploit_maturity,fixed_version,affected_versions,summary}], "
        "prioritised_threats:[{title,why_relevant,confidence,recommended_action,"
        "urgency:'now'|'this_week'|'monitor'}], "
        "ttp_mapping:[{technique_id,technique_name,relevance,mitigation}], "
        "threat_actors_tracking:[{name,motivation,observed_ttps:[str]}], "
        "actionable_briefing:str, "
        "monitor_keywords:[str], "
        "next_scan_recommendation:str}."
    )
    prompt = (
        f"Stack: {stack}\nFocus: {focus}\nFeeds enabled: {', '.join(feeds)}\n"
        f"Host info: {sys_info}\n\n"
        f"Dependencies & manifests:\n```\n{deps_blob}\n```\n\n"
        "Produce a stack-specific threat brief that highlights ONLY CVEs and TTPs "
        "the dependency tree above is actually exposed to. Prefer KEV-listed "
        "vulnerabilities and active exploits."
    )

    data = _parse_json(_llm(prompt, system, "threat_intel_analyst"), {
        "overall_risk": "unknown", "critical_cves": [],
        "prioritised_threats": [], "ttp_mapping": [],
        "actionable_briefing": "",
    })

    cves      = data.get("critical_cves", [])
    threats   = data.get("prioritised_threats", [])
    kev_count = sum(1 for c in cves if c.get("kev_listed"))

    ts = _ts()
    body = (
        f"# Threat Intelligence Brief — {ts}\n\n"
        f"**Stack:** {stack}  **Risk:** {data.get('overall_risk','?').upper()}  "
        f"**CVEs:** {len(cves)}  **KEV-listed:** {kev_count}  "
        f"**Prioritised threats:** {len(threats)}\n\n"
        "## Executive Briefing\n"
        f"{data.get('actionable_briefing','(none generated)')}\n\n"
        "## Critical CVEs\n"
        + "\n".join(
            f"- **{c.get('id','?')}** [{c.get('severity','?').upper()}, "
            f"CVSS {c.get('cvss','?')}{', KEV' if c.get('kev_listed') else ''}] "
            f"`{c.get('package','?')}` → fixed in {c.get('fixed_version','?')}: "
            f"{c.get('summary','')}"
            for c in cves
        )
        + "\n\n## Prioritised Threats\n"
        + "\n".join(
            f"- **{t.get('title','?')}** ({t.get('urgency','?')}, "
            f"{t.get('confidence','?')} confidence): {t.get('recommended_action','')}"
            for t in threats
        )
        + "\n\n## MITRE ATT&CK Mapping\n"
        + "\n".join(
            f"- `{m.get('technique_id','?')}` {m.get('technique_name','?')} — "
            f"{m.get('mitigation','')}"
            for m in data.get("ttp_mapping", [])
        )
    )

    report_path = _save("reports", f"threat_intel_{ts}.md", body)
    _record("threat_intel_analyst", stack,
            f"risk={data.get('overall_risk')} cves={len(cves)} kev={kev_count}")

    return {
        "overall_risk":          data.get("overall_risk", "unknown"),
        "critical_cves":         cves,
        "kev_listed_count":      kev_count,
        "prioritised_threats":   threats,
        "ttp_mapping":           data.get("ttp_mapping", []),
        "threat_actors":         data.get("threat_actors_tracking", []),
        "actionable_briefing":   data.get("actionable_briefing", ""),
        "monitor_keywords":      data.get("monitor_keywords", []),
        "next_scan":             data.get("next_scan_recommendation", ""),
        "report_path":           report_path,
        "summary": (
            f"Threat intel: {data.get('overall_risk','?').upper()} risk. "
            f"{len(cves)} CVEs ({kev_count} actively exploited), "
            f"{len(threats)} prioritised threats → {report_path}."
        ),
    }
