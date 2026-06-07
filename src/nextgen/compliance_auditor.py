"""
Compliance Auditor — automates evidence collection and gap analysis for
SOC2, GDPR, HIPAA, PCI-DSS, ISO 27001, and the EU AI Act. Scans the
codebase for compliance-relevant patterns (encryption usage, logging,
access controls, data retention, audit trails) and produces an
audit-ready evidence package.

Input:  framework (str), code (str), path (str), scope (str),
        controls_in_scope (list), org_context (str)
Output: framework, compliance_score, controls_met, controls_failed,
        gaps, evidence_package, remediation_roadmap, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record


_FRAMEWORKS = {
    "soc2":     "SOC 2 Trust Services Criteria (Security, Availability, Confidentiality, Processing Integrity, Privacy)",
    "gdpr":     "EU General Data Protection Regulation (Articles 5, 6, 17, 25, 30, 32, 33, 35)",
    "hipaa":    "HIPAA Security Rule (Administrative, Physical, Technical safeguards) + Privacy Rule",
    "pci-dss":  "PCI-DSS v4.0 (12 core requirements, especially Req 3,4,6,8,10,11)",
    "iso27001": "ISO/IEC 27001:2022 Annex A (93 controls across 4 themes)",
    "ai_act":   "EU AI Act risk categorisation and obligations for high-risk AI systems",
}


def _collect_source_sample(path_str: str, code: str) -> str:
    if code:
        return code[:8000]
    if not path_str:
        return ""
    p = Path(path_str)
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")[:8000]
    if p.is_dir():
        chunks: List[str] = []
        for f in list(p.rglob("*.py"))[:6] + list(p.rglob("*.ts"))[:4] + \
                 list(p.rglob("*.tf"))[:4] + list(p.rglob("Dockerfile"))[:2]:
            chunks.append(f"### {f}\n" +
                          f.read_text(encoding="utf-8", errors="ignore")[:1000])
        return "\n\n".join(chunks)[:8000]
    return ""


def compliance_auditor(args: Dict[str, Any]) -> Dict[str, Any]:
    framework = (args.get("framework") or "soc2").lower()
    code      = args.get("code", "")
    path_str  = args.get("path", "")
    scope     = args.get("scope", "production application")
    controls  = args.get("controls_in_scope") or []
    org_ctx   = args.get("org_context", "early-stage SaaS")

    fw_desc = _FRAMEWORKS.get(framework, framework)
    sample  = _collect_source_sample(path_str, code)

    system = (
        f"You are a compliance auditor specialised in {fw_desc}. "
        "Analyse the source/configuration evidence and produce a gap-analysis report. "
        "Map every observed pattern (or its absence) to a specific control ID. "
        "Output ONLY valid JSON: "
        "{framework:str, scope:str, audit_period:str, "
        "compliance_score:int (0-100), readiness_level:'not_ready'|'partial'|'audit_ready', "
        "controls_met:[{control_id,name,evidence,confidence:'high'|'medium'|'low'}], "
        "controls_failed:[{control_id,name,gap,severity:'critical'|'high'|'medium'|'low',"
        "remediation,estimated_effort_days,owner_role}], "
        "gaps_summary:str, "
        "evidence_package:[{artifact_name,what_it_proves,location_in_repo}], "
        "policies_required:[{policy_name,purpose,template_url_hint}], "
        "remediation_roadmap:[{phase,duration_weeks,deliverables:[str]}], "
        "auditor_questions_to_expect:[str], "
        "regulatory_notification_obligations:[str], "
        "next_audit_recommendation:str}."
    )
    prompt = (
        f"Framework: {framework}\nScope: {scope}\nOrg context: {org_ctx}\n"
        f"Controls in scope: {controls or 'all applicable'}\n\n"
        f"Evidence (source / IaC sample):\n```\n{sample}\n```\n\n"
        "Be specific and conservative: only mark controls 'met' when there is "
        "clear evidence in the sample. When evidence is missing, mark as gap."
    )

    data = _parse_json(_llm(prompt, system, "compliance_auditor"), {
        "framework": framework, "compliance_score": 0,
        "controls_met": [], "controls_failed": [], "remediation_roadmap": [],
    })

    ts = _ts()
    met    = data.get("controls_met", [])
    failed = data.get("controls_failed", [])
    critical = [f for f in failed if f.get("severity") in ("critical", "high")]

    report = (
        f"# Compliance Audit — {framework.upper()} — {ts}\n\n"
        f"**Score:** {data.get('compliance_score','?')}/100  "
        f"**Readiness:** {data.get('readiness_level','?').upper()}  "
        f"**Met:** {len(met)}  **Failed:** {len(failed)} "
        f"({len(critical)} critical/high)\n\n"
        f"## Gaps Summary\n{data.get('gaps_summary','')}\n\n"
        "## Controls Failed (sorted by severity)\n"
        + "\n".join(
            f"### [{f.get('severity','?').upper()}] {f.get('control_id','?')} "
            f"— {f.get('name','?')}\n"
            f"Gap: {f.get('gap','')}\nRemediation: {f.get('remediation','')}\n"
            f"Owner: {f.get('owner_role','?')} • "
            f"Est. effort: {f.get('estimated_effort_days','?')}d\n"
            for f in sorted(failed,
                            key=lambda x: {"critical":0,"high":1,"medium":2,"low":3}
                            .get(x.get("severity",""), 4))
        )
        + "\n## Remediation Roadmap\n"
        + "\n".join(
            f"**Phase {i+1}: {r.get('phase','?')}** ({r.get('duration_weeks','?')}w)\n"
            + "\n".join(f"- {d}" for d in r.get("deliverables", []))
            for i, r in enumerate(data.get("remediation_roadmap", []))
        )
        + "\n\n## Evidence Package\n"
        + "\n".join(
            f"- `{e.get('artifact_name','?')}` — {e.get('what_it_proves','')} "
            f"(loc: {e.get('location_in_repo','?')})"
            for e in data.get("evidence_package", [])
        )
    )
    report_path = _save("reports", f"compliance_{framework}_{ts}.md", report)

    _record("compliance_auditor", f"{framework}/{scope}",
            f"score={data.get('compliance_score')} failed={len(failed)} crit={len(critical)}")

    return {
        "framework":                data.get("framework", framework),
        "compliance_score":         data.get("compliance_score", 0),
        "readiness_level":          data.get("readiness_level", "not_ready"),
        "controls_met":             met,
        "controls_failed":          failed,
        "critical_gaps":            critical,
        "evidence_package":         data.get("evidence_package", []),
        "policies_required":        data.get("policies_required", []),
        "remediation_roadmap":      data.get("remediation_roadmap", []),
        "regulatory_obligations":   data.get("regulatory_notification_obligations", []),
        "auditor_questions":        data.get("auditor_questions_to_expect", []),
        "next_audit":               data.get("next_audit_recommendation", ""),
        "report_path":              report_path,
        "summary": (
            f"{framework.upper()} audit: {data.get('compliance_score','?')}/100, "
            f"{len(failed)} gaps ({len(critical)} critical/high). → {report_path}."
        ),
    }
