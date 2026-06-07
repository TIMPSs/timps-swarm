"""Phishing Simulator — generates a realistic phishing simulation campaign
for security-awareness training.

Outputs:

* A campaign plan (target audience, schedule, scenario).
* A set of phishing email templates (3 variants: credential-harvest,
  malware-attach, OAuth-consent).
* A landing page (HTML) for credential-harvest simulations that captures
  (and reports) submissions.
* A reporting dashboard spec (PostHog / Mixpanel / Looker events).
* A "what to do if you clicked" educational email for those who fail.
* A metrics plan: click rate, report rate, repeat-offender rate.

The agent is LLM-driven; landing-page HTML is generated without LLMs
to avoid surprises in the template.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

SCENARIOS = ("package", "invoice", "shared_doc", "password_reset", "bonus", "zoom_invite", "it_helpdesk")


def phishing_simulator(args: Dict[str, Any]) -> Dict[str, Any]:
    scenario = (args.get("scenario") or "shared_doc").lower()
    if scenario not in SCENARIOS:
        scenario = "shared_doc"
    audience = (args.get("audience") or "all employees").strip()
    company = (args.get("company") or "Acme Corp").strip()
    sender_domain = (args.get("sender_domain") or f"{company.lower().replace(' ', '')}-portal.com").strip()
    track = (args.get("track") or "post_hog").lower()

    emails = _emails(scenario, audience, company, sender_domain)
    landing = _landing_page(scenario, sender_domain, track)
    dashboard = _dashboard_spec(track)
    follow_up = _follow_up_email(audience, company)
    metrics = _metrics_plan()

    payload = {
        "summary": _summary(scenario, audience, emails, landing),
        "scenario": scenario,
        "audience": audience,
        "company": company,
        "sender_domain": sender_domain,
        "emails": emails,
        "landing_page_html": landing,
        "follow_up_email": follow_up,
        "dashboard_spec": dashboard,
        "metrics_plan": metrics,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", scenario).strip("_") or "phish"
    _save("phase7/phishing", f"{slug}_emails.json", json.dumps(emails, indent=2))
    _save("phase7/phishing", f"{slug}_landing.html", landing)
    _save("phase7/phishing", f"{slug}_summary.json", json.dumps(payload, indent=2))
    _record("phishing_simulator", scenario, f"emails={len(emails)}")
    return payload


# ---------------------------------------------------------------------------

def _emails(scenario: str, audience: str, company: str, domain: str) -> List[Dict[str, Any]]:
    system = (
        "You write 3 phishing-simulation email templates.  Each must look like a real "
        "internal/external email but be clearly watermarked '// SIMULATION //' in the "
        "subject and footer.  Return ONLY JSON: {\"emails\": [\n"
        "  {\"name\": str, \"subject\": str, \"preheader\": str, \"body_text\": str, "
        "\"sender_name\": str, \"sender_email\": str, \"link_label\": str, \"landing_path\": str}\n"
        "]}.  No prose, no fences."
    )
    user = (
        f"Scenario: {scenario}\nAudience: {audience}\nCompany: {company}\n"
        f"Sender domain: {domain}\n"
        "Vary the pretexts across 3 templates.  Each body_text ≤ 200 words."
    )
    raw = _llm(user, system, "phishing_simulator")
    parsed = _parse_json(raw, fallback={"emails": []})
    out = parsed.get("emails") or []
    for e in out:
        e.setdefault("subject", f"// SIMULATION // {scenario} — action required")
        e.setdefault("body_text", "(template unavailable — populate manually)")
        e.setdefault("sender_email", f"no-reply@{domain}")
        e.setdefault("link_label", "Open document")
        e.setdefault("landing_path", f"/sim/{scenario}")
    return out[:3]


def _landing_page(scenario: str, domain: str, track: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><title>// SIMULATION // {domain}</title>
<meta name="robots" content="noindex">
<style>
  body{{font-family:system-ui;background:#f5f6f8;margin:0;display:grid;place-items:center;height:100vh}}
  .card{{background:#fff;max-width:420px;width:90%;padding:32px;border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.1)}}
  h1{{color:#b00;font-size:18px;margin:0 0 8px}}  p{{color:#333;line-height:1.45}}
  input,button{{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #ccc}}
  button{{background:#0a66c2;color:#fff;border:0;cursor:pointer}}
  .wm{{color:#999;font-size:12px;text-align:center;margin-top:12px}}
</style></head>
<body><div class="card">
  <h1>// SIMULATION //</h1>
  <p>This is a security-awareness phishing simulation.  No credentials are stored.  Your interaction (timestamp, anonymised user-agent, and whether you submitted the form) is reported to {track} for training metrics only.</p>
  <form onsubmit="event.preventDefault();fetch('/sim/report',{{method:'POST',body:JSON.stringify({{scenario:'{scenario}',submitted:true,ts:Date.now()}})}}).finally(()=>alert('Reported (simulation).'))">
    <input type="email" placeholder="you@{domain.replace('-portal.com','')}.com" required>
    <input type="password" placeholder="Password" required>
    <button type="submit">Sign in</button>
  </form>
  <div class="wm">// SIMULATION END //</div>
</div></body></html>
"""


def _dashboard_spec(track: str) -> Dict[str, Any]:
    return {
        "platform": track,
        "events": [
            {"name": "phish_email_sent",   "props": ["scenario", "variant", "recipient_dept"]},
            {"name": "phish_email_opened", "props": ["scenario", "variant"]},
            {"name": "phish_link_clicked", "props": ["scenario", "variant"]},
            {"name": "phish_form_submitted", "props": ["scenario", "variant", "fields_entered"]},
            {"name": "phish_reported",     "props": ["scenario", "variant", "report_channel"]},
        ],
        "widgets": [
            {"name": "Click-through rate",        "sql": "phish_link_clicked / phish_email_sent"},
            {"name": "Report rate",               "sql": "phish_reported / phish_email_sent"},
            {"name": "Credential submission rate", "sql": "phish_form_submitted / phish_email_sent"},
            {"name": "Repeat offenders",           "sql": "COUNT(DISTINCT user_id) HAVING count(phish_form_submitted) > 1"},
        ],
    }


def _follow_up_email(audience: str, company: str) -> Dict[str, str]:
    return {
        "subject": "// SIMULATION // What to do if you think you clicked",
        "body": (
            f"Hi team,\n\nThis was a phishing simulation. If you clicked or entered "
            f"credentials, here's what to do for real:\n\n"
            f"1. Change your password immediately (and any reused passwords).\n"
            f"2. Enable MFA on every account that supports it.\n"
            f"3. Report to {company} IT — we will never blame you for asking.\n\n"
            f"Reminder: legitimate IT will never ask for your password by email.\n"
        ),
    }


def _metrics_plan() -> List[Dict[str, str]]:
    return [
        {"name": "Click-through rate",  "target_industry_pct": 15, "target_internal_pct": 5,  "owner": "Security Awareness"},
        {"name": "Report rate",         "target_industry_pct": 30, "target_internal_pct": 60, "owner": "Security Awareness"},
        {"name": "Time-to-first-report","target_industry_min": 60, "target_internal_min": 15, "owner": "SOC"},
        {"name": "Repeat-offender rate","target_industry_pct": 8,  "target_internal_pct": 3,  "owner": "Security Awareness"},
    ]


def _summary(scenario: str, audience: str, emails: List[Dict[str, Any]], landing: str) -> str:
    return f"Phishing sim ({scenario}) for {audience}: {len(emails)} email variants, landing page {len(landing)} chars."
