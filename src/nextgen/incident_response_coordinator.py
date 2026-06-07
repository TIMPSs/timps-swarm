"""
Incident Response Coordinator — security-incident-specific orchestrator.

Where `incident_responder` correlates logs for any production issue, this
agent activates an IR playbook: classifies the incident (data breach,
ransomware, account takeover, supply-chain, DDoS, insider), executes
containment + eradication steps, drafts regulatory-notification copy
(GDPR Art. 33, HIPAA breach rule, CCPA, SEC 8-K), and produces a full
timeline ready for the postmortem and external counsel.

Input:  alert (str|dict), severity_hint (str), affected_systems (list),
        regulatory_jurisdictions (list), known_iocs (list)
Output: classification, severity, blast_radius, playbook_steps,
        containment_actions, notification_drafts, ir_timeline, report_path
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _coerce_alert(alert: Any) -> str:
    if isinstance(alert, dict):
        return json.dumps(alert, indent=2, default=str)[:4000]
    return str(alert or "")[:4000]


def incident_response_coordinator(args: Dict[str, Any]) -> Dict[str, Any]:
    alert         = _coerce_alert(args.get("alert", ""))
    severity_hint = args.get("severity_hint", "unknown")
    affected      = args.get("affected_systems") or []
    jurisdictions = args.get("regulatory_jurisdictions") or ["EU", "US-CA"]
    iocs          = args.get("known_iocs") or []
    org_context   = args.get("org_context", "SaaS product handling user PII")

    netstat = _run("netstat -an 2>/dev/null | head -40", timeout=5)[:1500]

    system = (
        "You are a Tier-3 incident response coordinator following NIST SP 800-61r2 "
        "and the SANS PICERL model (Preparation, Identification, Containment, "
        "Eradication, Recovery, Lessons-learned). Classify the incident, derive a "
        "playbook from MITRE ATT&CK + D3FEND, and draft regulator-ready notifications. "
        "Output ONLY valid JSON: "
        "{classification:'data_breach'|'ransomware'|'account_takeover'|'supply_chain'"
        "|'ddos'|'insider'|'unknown', "
        "confidence:'high'|'medium'|'low', "
        "severity:'sev1'|'sev2'|'sev3'|'sev4', "
        "blast_radius:{users_impacted_estimate,data_categories:[str],systems:[str],"
        "regions:[str],duration_hours_estimate}, "
        "attack_chain:[{stage,mitre_technique,evidence,d3fend_countermeasure}], "
        "playbook_steps:[{phase:'identification'|'containment'|'eradication'"
        "|'recovery'|'lessons_learned',action,owner_role,sla_minutes,"
        "automation_possible:bool}], "
        "containment_commands:[{description,shell_command,risk,reversible:bool}], "
        "communication_plan:{internal_stakeholders:[str],external_stakeholders:[str],"
        "talking_points:str,war_room_channel_name:str}, "
        "notification_drafts:[{audience:'regulator'|'customer'|'press'|'board',"
        "jurisdiction,deadline_hours,draft_text}], "
        "ir_timeline:[{ts,event,actor}], "
        "evidence_to_preserve:[str], "
        "go_no_go_for_disclosure:{recommendation,reasoning}, "
        "lessons_learned_questions:[str]}."
    )
    prompt = (
        f"Severity hint: {severity_hint}\nJurisdictions: {jurisdictions}\n"
        f"Org context: {org_context}\nAffected systems: {affected}\n"
        f"Known IOCs: {iocs}\n\n"
        f"ALERT / TRIGGER:\n```\n{alert}\n```\n\n"
        f"Local network snapshot:\n```\n{netstat}\n```\n\n"
        "Build a complete, time-boxed IR plan. Containment commands MUST be safe, "
        "reversible, and explicitly labelled."
    )

    data = _parse_json(_llm(prompt, system, "incident_response_coordinator"), {
        "classification": "unknown", "severity": "sev3",
        "playbook_steps": [], "containment_commands": [],
        "notification_drafts": [], "ir_timeline": [],
    })

    ts = _ts()
    steps = data.get("playbook_steps", [])
    contains = data.get("containment_commands", [])
    notifs = data.get("notification_drafts", [])

    # Generate runnable (dry-run) containment script
    script_lines = [
        "#!/usr/bin/env bash",
        f"# IR containment script — generated {ts}",
        f"# Classification: {data.get('classification')}  Severity: {data.get('severity')}",
        "# *** REVIEW EVERY LINE BEFORE EXECUTING — DRY-RUN BY DEFAULT ***",
        "set -euo pipefail",
        "DRY_RUN=${DRY_RUN:-1}",
        "run() { if [ \"$DRY_RUN\" = \"1\" ]; then echo \"[dry-run] $*\"; else eval \"$@\"; fi; }",
        "",
    ]
    for c in contains:
        script_lines.append(f"# {c.get('description','?')} (risk={c.get('risk','?')}, "
                            f"reversible={c.get('reversible',False)})")
        script_lines.append(f"run {json.dumps(c.get('shell_command',''))}")
        script_lines.append("")
    script_path = _save("scripts", f"ir_containment_{ts}.sh", "\n".join(script_lines))

    # Save notifications as separate files for legal review
    notification_paths: List[str] = []
    for n in notifs:
        fname = (f"ir_notify_{n.get('audience','aud')}_"
                 f"{(n.get('jurisdiction','') or 'global').replace('/','_')}_{ts}.md")
        notification_paths.append(_save("notifications", fname,
            f"# Draft notification — {n.get('audience','?')} "
            f"({n.get('jurisdiction','?')}, deadline {n.get('deadline_hours','?')}h)\n\n"
            f"{n.get('draft_text','')}"))

    report = (
        f"# Incident Response Brief — {ts}\n\n"
        f"**Classification:** {data.get('classification','?')} "
        f"({data.get('confidence','?')} confidence)  "
        f"**Severity:** {data.get('severity','?').upper()}\n\n"
        f"## Blast Radius\n```json\n{json.dumps(data.get('blast_radius',{}), indent=2)}\n```\n\n"
        "## Attack Chain (MITRE ATT&CK)\n"
        + "\n".join(
            f"{i+1}. **{s.get('stage','?')}** — `{s.get('mitre_technique','?')}` → "
            f"D3FEND: {s.get('d3fend_countermeasure','?')}"
            for i, s in enumerate(data.get("attack_chain", []))
        )
        + "\n\n## Playbook\n"
        + "\n".join(
            f"- [{s.get('phase','?').upper()}] {s.get('action','?')} "
            f"(owner: {s.get('owner_role','?')}, SLA: {s.get('sla_minutes','?')}m"
            f"{', auto-run' if s.get('automation_possible') else ''})"
            for s in steps
        )
        + "\n\n## Communication\n"
        f"War room: `{data.get('communication_plan',{}).get('war_room_channel_name','#incident')}`\n\n"
        f"{data.get('communication_plan',{}).get('talking_points','')}\n\n"
        "## Notifications Drafted\n"
        + "\n".join(
            f"- {n.get('audience','?')} / {n.get('jurisdiction','?')} "
            f"(deadline {n.get('deadline_hours','?')}h) → {p}"
            for n, p in zip(notifs, notification_paths)
        )
        + "\n\n## Go / No-Go on Public Disclosure\n"
        f"**Recommendation:** {data.get('go_no_go_for_disclosure',{}).get('recommendation','?')}\n"
        f"{data.get('go_no_go_for_disclosure',{}).get('reasoning','')}"
    )
    report_path = _save("reports", f"ir_brief_{ts}.md", report)

    _record("incident_response_coordinator",
            data.get("classification", "incident"),
            f"sev={data.get('severity')} steps={len(steps)} notifs={len(notifs)}")

    return {
        "classification":           data.get("classification", "unknown"),
        "confidence":               data.get("confidence", "low"),
        "severity":                 data.get("severity", "sev3"),
        "blast_radius":             data.get("blast_radius", {}),
        "attack_chain":             data.get("attack_chain", []),
        "playbook_steps":           steps,
        "containment_commands":     contains,
        "communication_plan":       data.get("communication_plan", {}),
        "notification_drafts":      notifs,
        "notification_paths":       notification_paths,
        "ir_timeline":              data.get("ir_timeline", []),
        "evidence_to_preserve":     data.get("evidence_to_preserve", []),
        "go_no_go_for_disclosure":  data.get("go_no_go_for_disclosure", {}),
        "lessons_learned_questions": data.get("lessons_learned_questions", []),
        "containment_script_path":  script_path,
        "report_path":              report_path,
        "summary": (
            f"IR {data.get('severity','?').upper()} "
            f"{data.get('classification','?')}: {len(steps)} playbook steps, "
            f"{len(contains)} containment cmds, {len(notifs)} regulator drafts. "
            f"→ {report_path}."
        ),
    }
