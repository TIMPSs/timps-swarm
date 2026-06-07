"""Game Day Facilitator — designs and runs chaos-engineering game days.

Outputs:

* Scenario library (5-8 ready-to-run scenarios with blast-radius).
* A custom scenario for the user's service (LLM-designed).
* A runbook (timeline, roles, comms, abort criteria, success criteria).
* Comms templates (Slack, Statuspage, customer email).
* A scoring rubric (1-5 across detection, response, recovery, learning).
* A retrospective template with blameless framing.

The agent is LLM-driven and works fully offline; scenarios reference
common tools (Chaos Mesh, Litmus, Gremlin, Steadybit) but execution
itself is out of scope.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def game_day_facilitator(args: Dict[str, Any]) -> Dict[str, Any]:
    service = (args.get("service") or args.get("description") or args.get("request") or "").strip()
    if not service:
        return {"summary": "No service description supplied.", "error": "service is required",
                "scenarios": [], "runbook_md": ""}

    scope = (args.get("scope") or "production-like staging").strip()
    participants: List[str] = args.get("participants") or ["Incident Commander", "SRE on-call", "Engineering lead", "Comms lead"]
    date = args.get("date") or "TBD"

    library = _scenario_library()
    custom = _custom_scenario(service, scope)
    runbook = _runbook(service, scope, participants, date, custom)
    comms = _comms_templates(service, custom)
    scoring = _scoring_rubric()
    retro = _retro_template(custom)

    payload = {
        "summary": _summary(service, library, custom, runbook),
        "service": service,
        "scope": scope,
        "date": date,
        "participants": participants,
        "scenario_library": library,
        "custom_scenario": custom,
        "runbook_md": runbook,
        "comms_templates": comms,
        "scoring_rubric": scoring,
        "retro_template": retro,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", service.lower()).strip("_")[:40] or "gameday"
    _save("phase7/gameday", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _save("phase7/gameday", f"{slug}_{_ts()}_runbook.md", runbook)
    _record("game_day_facilitator", service[:60], f"custom_scenario={custom.get('name','?')}")
    return payload


# ---------------------------------------------------------------------------

def _scenario_library() -> List[Dict[str, Any]]:
    return [
        {"name": "Region failover",       "tool": "Chaos Mesh / AWS Fault Injection",  "blast_radius": "1 region",  "duration_min": 30,  "difficulty": "medium"},
        {"name": "DB primary kill",       "tool": "Litmus / custom",                   "blast_radius": "writes",    "duration_min": 15,  "difficulty": "high"},
        {"name": "API latency injection", "tool": "Gremlin / Toxiproxy",               "blast_radius": "1 endpoint", "duration_min": 20,  "difficulty": "low"},
        {"name": "Disk-fill on worker",   "tool": "Chaos Mesh",                         "blast_radius": "1 node",    "duration_min": 20,  "difficulty": "low"},
        {"name": "Cert expiry",           "tool": "Steadybit",                          "blast_radius": "TLS to API", "duration_min": 10,  "difficulty": "medium"},
        {"name": "DNS outage",            "tool": "Gremlin",                            "blast_radius": "1 service", "duration_min": 15,  "difficulty": "medium"},
        {"name": "Dependency 5xx storm",  "tool": "Toxiproxy",                          "blast_radius": "downstream","duration_min": 25,  "difficulty": "high"},
        {"name": "Credentials rotation",  "tool": "custom",                             "blast_radius": "1 service", "duration_min": 30,  "difficulty": "high"},
    ]


def _custom_scenario(service: str, scope: str) -> Dict[str, Any]:
    system = (
        "You design a chaos-engineering scenario for a service.  Return ONLY JSON:\n"
        "{\n"
        '  "name":         str,\n'
        '  "summary":      str,             // 1-2 sentences\n'
        '  "hypothesis":   str,             // what we expect to happen\n'
        '  "blast_radius": str,             // user-visible impact\n'
        '  "duration_min": int,\n'
        '  "tool":         str,             // Chaos Mesh | Litmus | Gremlin | Steadybit | custom\n'
        '  "preconditions":[str],           // safety preconditions\n'
        '  "abort_criteria":[str],          // conditions that force immediate rollback\n'
        '  "success_criteria": [str],\n'
        '  "rollback_plan": str,\n'
        '  "detection_signals":[str]        // what alerts / dashboards must light up\n'
        "}"
    )
    user = f"Service: {service}\nScope: {scope}\nDesign a chaos scenario that's challenging but recoverable."
    raw = _llm(user, system, "game_day_facilitator")
    return _parse_json(raw, fallback={"name": "Custom scenario", "summary": "", "hypothesis": "", "blast_radius": "1 service", "duration_min": 20, "tool": "custom", "preconditions": [], "abort_criteria": [], "success_criteria": [], "rollback_plan": "", "detection_signals": []})


def _runbook(service: str, scope: str, participants: List[str], date: str, scenario: Dict[str, Any]) -> str:
    out = [f"# Game Day — {scenario.get('name','?')}", "", f"**Service:** {service}", f"**Scope:** {scope}", f"**Date:** {date}", ""]
    out.append("## Roles")
    for p in participants: out.append(f"- {p}")
    out += ["", "## Hypothesis", scenario.get("hypothesis", ""), "",
            "## Timeline (minutes)", "",
            "| T+ | Step | Owner |",
            "|---|---|---|",
            "| 00 | Kickoff & safety check | IC |",
            f"| 05 | Inject: {scenario.get('name','?')} | SRE |",
            "| 15 | Observe detection signals | All |",
            "| 20 | Triage + mitigate | IC |",
            "| 25 | Rollback + verify | SRE |",
            "| 30 | Retro | All |",
            "",
            "## Abort criteria", ""]
    out += [f"- {c}" for c in scenario.get("abort_criteria", [])] or ["- (none)"]
    out += ["", "## Success criteria", ""]
    out += [f"- {c}" for c in scenario.get("success_criteria", [])] or ["- Service restored to baseline within rollback SLA"]
    out += ["", "## Rollback plan", "", scenario.get("rollback_plan", "(see service runbook)"), ""]
    return "\n".join(out) + "\n"


def _comms_templates(service: str, scenario: Dict[str, Any]) -> Dict[str, str]:
    return {
        "slack_start": (
            f":rotating_light: *Game day starting* — {scenario.get('name','scenario')} on *{service}*. "
            f"All hands in #gameday. No external comms yet. Abort criteria: {', '.join(scenario.get('abort_criteria', [])[:2]) or 'see runbook'}."
        ),
        "slack_progress": (
            f":mag: T+15 — investigating elevated error rates. Customer impact: {scenario.get('blast_radius','unknown')}. "
            f"ETA to resolution: ~10 min."
        ),
        "slack_end_ok": (
            f":white_check_mark: Game day complete. Hypothesis: {'CONFIRMED' if scenario.get('hypothesis') else 'N/A'}. "
            f"Service restored. Retro at 16:00 in #gameday."
        ),
        "statuspage_optional": (
            f"Optional — only if customer-impacting: 'We are conducting a planned resilience exercise on {service}. "
            f"You may see brief elevated error rates. We're monitoring closely.'"
        ),
        "customer_email": (
            f"Subject: Planned resilience test for {service} today\n\n"
            f"Hi {{{{name}}}} — we'll be running a planned resilience test on {service} between {{time}}. "
            f"You may see brief elevated error rates. No action required on your side."
        ),
    }


def _scoring_rubric() -> List[Dict[str, Any]]:
    return [
        {"category": "Detection",  "1-5": "5 = alert within 1m, accurate, page correct team. 1 = no detection, customer-reported."},
        {"category": "Response",   "1-5": "5 = IC on call in 5m, comms in 10m. 1 = no IC, confused escalation."},
        {"category": "Recovery",   "1-5": "5 = rollback < 10m, error rate < 1% in 5m. 1 = rollback failed, service degraded > 30m."},
        {"category": "Learning",   "1-5": "5 = 3+ concrete improvements captured with owners. 1 = no notes captured."},
        {"category": "Customer impact", "1-5": "5 = zero customer impact. 1 = customer-visible outage."},
    ]


def _retro_template(scenario: Dict[str, Any]) -> str:
    return (
        f"# Retrospective — {scenario.get('name','Game Day')}\n\n"
        f"_Blameless framing: we are evaluating the **system** and our **response**, not individuals._\n\n"
        f"## What went well\n- \n\n"
        f"## What didn't go well\n- \n\n"
        f"## Where we got lucky\n- \n\n"
        f"## Improvements (with owner + due date)\n"
        f"- [ ] \n- [ ] \n\n"
        f"## Hypothesis result\n- Confirmed: yes / no / partially\n- Evidence: \n\n"
        f"## Scoring\n- Detection: /5\n- Response:  /5\n- Recovery:  /5\n- Learning:  /5\n- Customer impact: /5\n"
    )


def _summary(service: str, lib: List[Dict[str, Any]], custom: Dict[str, Any], runbook: str) -> str:
    return f"Game day for '{service}': {len(lib)}-scenario library + custom '{custom.get('name','?')}'; runbook {len(runbook)} chars."
