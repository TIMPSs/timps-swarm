"""DPDP Act Auditor — audits a codebase + org processes against India's
Digital Personal Data Protection Act, 2023.

Outputs:

* A control matrix (Section → control → status → evidence → gap).
* A list of data flows that need consent capture / re-consent.
* Retention-policy recommendations (Storage Limitation principle).
* Breach-notification readiness check.
* DPO/Data-Processor obligations.
* Concrete remediation steps per gap.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def dpdp_act_auditor(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = Path(args.get("repo_path") or ".")
    if not repo_path.is_dir():
        return {"summary": f"Repo path '{repo_path}' not found.", "error": "repo_path required",
                "controls": []}

    data_inventory = _scan_data_inventory(repo_path)
    consent_signals = _scan_consent(repo_path)
    retention_signals = _scan_retention(repo_path)
    breach_signals = _scan_breach_readiness(repo_path)
    dpo_signals = _scan_dpo(repo_path)

    control_matrix = _build_control_matrix(data_inventory, consent_signals, retention_signals, breach_signals, dpo_signals)
    remediation = _remediation(control_matrix)

    payload = {
        "summary": _summary(control_matrix, remediation),
        "repo_path": str(repo_path),
        "data_inventory": data_inventory,
        "consent_signals": consent_signals,
        "retention_signals": retention_signals,
        "breach_signals": breach_signals,
        "dpo_signals": dpo_signals,
        "control_matrix": control_matrix,
        "remediation": remediation,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", repo_path.name).strip("_")[:40] or "repo"
    _save("phase7/dpdp", f"{slug}_{_ts()}_audit.json", json.dumps(payload, indent=2))
    _record("dpdp_act_auditor", str(repo_path), f"controls={len(control_matrix)} gaps={sum(1 for c in control_matrix if c['status']=='fail')}")
    return payload


# ---------------------------------------------------------------------------
# Data-inventory heuristics
# ---------------------------------------------------------------------------

PII_PATTERNS = {
    "aadhaar":   re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan":       re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "phone":     re.compile(r"\+?91[\s-]?\d{10}\b"),
    "email":     re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "dob":       re.compile(r"\b(0?[1-9]|[12]\d|3[01])[-/](0?[1-9]|1[0-2])[-/]\d{2,4}\b"),
    "ip":        re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}


def _scan_data_inventory(root: Path) -> Dict[str, Any]:
    counts: Dict[str, int] = {k: 0 for k in PII_PATTERNS}
    sample_files: Dict[str, List[str]] = {k: [] for k in PII_PATTERNS}
    for path in root.rglob("*"):
        if not path.is_file(): continue
        if any(seg in path.parts for seg in ("node_modules", ".venv", "venv", ".git", "__pycache__", "dist", "build")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(text) > 5_000_000: continue
        for k, pat in PII_PATTERNS.items():
            hits = pat.findall(text)
            if hits:
                counts[k] += len(hits)
                if len(sample_files[k]) < 3:
                    sample_files[k].append(str(path))
    return {"counts": counts, "sample_files": sample_files}


# ---------------------------------------------------------------------------
# Signal scanners
# ---------------------------------------------------------------------------

def _scan_consent(root: Path) -> Dict[str, Any]:
    text = _read_all(root, exts=(".py", ".js", ".ts", ".tsx", ".jsx"))
    found: Dict[str, bool] = {
        "consent_banner":         bool(re.search(r"consent\s*[=:]\s*['\"]?(true|yes|1)|has_consent|consent_given|opt.?in", text, re.I)),
        "consent_text_keyword":   bool(re.search(r"\bconsent\b", text, re.I)),
        "purpose_limitation":     bool(re.search(r"purpose\s*[=:]|purpose_of_use|processing_purpose", text, re.I)),
        "data_principal_rights":  bool(re.search(r"right\s+to\s+erasure|right\s+to\s+correct|right\s+to\s+nominate|withdraw\s+consent", text, re.I)),
        "explicit_consent_ui":    bool(re.search(r"<ConsentForm|ConsentModal|CookieConsent|consent.?checkbox", text, re.I)),
    }
    return found


def _scan_retention(root: Path) -> Dict[str, Any]:
    text = _read_all(root, exts=(".py", ".js", ".ts", ".sql", ".md"))
    return {
        "retention_policy_doc": bool(re.search(r"retention\s+policy|data\s+retention\s+period|store\s+for\s+\d+\s+days|delete_after", text, re.I)),
        "auto_delete_job":     bool(re.search(r"scheduled.*delet|delete_old|expire_after|TTL\s*[:=]", text, re.I)),
        "pseudonymisation":    bool(re.search(r"pseudonym|hash.*identifier|anonymize", text, re.I)),
    }


def _scan_breach_readiness(root: Path) -> Dict[str, Any]:
    text = _read_all(root, exts=(".py", ".js", ".ts", ".md", ".yaml", ".yml", ".json"))
    return {
        "breach_runbook":        bool(re.search(r"breach\s+(runbook|response|playbook)|incident.*breach|dpdp.*breach", text, re.I)),
        "board_notification":    bool(re.search(r"72\s*hours|notify\s+(?:the\s+)?board|Data\s+Protection\s+Board", text, re.I)),
        "data_principal_notice": bool(re.search(r"notify\s+(?:affected\s+)?users|notify\s+data\s+principals|breach.*notice", text, re.I)),
        "logging":               bool(re.search(r"audit\s+log|access\s+log|security\s+log", text, re.I)),
    }


def _scan_dpo(root: Path) -> Dict[str, Any]:
    text = _read_all(root, exts=(".md", ".yaml", ".yml", ".json", ".txt"))
    return {
        "dpo_appointed":          bool(re.search(r"Data\s+Protection\s+Officer|contact\s+dpo|dpo@|DPO\s+contact", text, re.I)),
        "grievance_officer":      bool(re.search(r"Grievance\s+Officer|grievance@|grievance-redressal", text, re.I)),
        "children_data_controls": bool(re.search(r"verifiable\s+parental\s+consent|children|minors|age[_-]?gate|18\s+years", text, re.I)),
    }


def _read_all(root: Path, exts: tuple) -> str:
    chunks: List[str] = []
    for ext in exts:
        for p in root.rglob(f"*{ext}"):
            if any(seg in p.parts for seg in ("node_modules", ".venv", "venv", ".git", "__pycache__", "dist", "build")):
                continue
            try:
                chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
    return "\n".join(chunks)[:2_000_000]


# ---------------------------------------------------------------------------
# Control matrix + remediation
# ---------------------------------------------------------------------------

def _build_control_matrix(inv: Dict[str, Any], consent: Dict[str, bool], ret: Dict[str, bool], breach: Dict[str, bool], dpo: Dict[str, bool]) -> List[Dict[str, str]]:
    pii_total = sum(inv["counts"].values())
    matrix: List[Dict[str, str]] = []

    matrix.append({"control": "Lawful processing & consent capture",
                   "status": "pass" if consent["consent_banner"] or consent["explicit_consent_ui"] else "fail",
                   "evidence": f"consent_banner={consent['consent_banner']}, consent_ui={consent['explicit_consent_ui']}"})

    matrix.append({"control": "Purpose limitation (Sec. 4)",
                   "status": "pass" if consent["purpose_limitation"] else "fail",
                   "evidence": f"purpose_limitation={consent['purpose_limitation']}"})

    matrix.append({"control": "Data Principal rights (Sec. 11-14)",
                   "status": "pass" if consent["data_principal_rights"] else "fail",
                   "evidence": f"rights={consent['data_principal_rights']}"})

    matrix.append({"control": "Storage limitation / retention (Sec. 8(7))",
                   "status": "pass" if ret["retention_policy_doc"] and ret["auto_delete_job"] else ("partial" if ret["retention_policy_doc"] else "fail"),
                   "evidence": f"policy={ret['retention_policy_doc']}, auto_delete={ret['auto_delete_job']}, pseudo={ret['pseudonymisation']}"})

    matrix.append({"control": "Breach notification (Sec. 8(6)) — 72h",
                   "status": "pass" if breach["breach_runbook"] and breach["board_notification"] else "fail",
                   "evidence": f"runbook={breach['breach_runbook']}, board_72h={breach['board_notification']}, user_notice={breach['data_principal_notice']}"})

    matrix.append({"control": "Audit logging (Sec. 8(5))",
                   "status": "pass" if breach["logging"] else "fail",
                   "evidence": f"logging={breach['logging']}"})

    matrix.append({"control": "Grievance officer (Sec. 8(10))",
                   "status": "pass" if dpo["grievance_officer"] else "fail",
                   "evidence": f"officer={dpo['grievance_officer']}, dpo={dpo['dpo_appointed']}"})

    matrix.append({"control": "Children's data (Sec. 9) — verifiable parental consent",
                   "status": "pass" if dpo["children_data_controls"] else ("n/a" if pii_total < 100 else "fail"),
                   "evidence": f"children_controls={dpo['children_data_controls']}"})

    matrix.append({"control": "Data minimisation",
                   "status": "warn" if any(inv["counts"][k] > 100 for k in ("aadhaar", "pan", "credit_card")) else "pass",
                   "evidence": f"sensitive_pii_counts={inv['counts']}"})

    return matrix


def _remediation(matrix: List[Dict[str, str]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for c in matrix:
        if c["status"] in {"fail", "partial", "warn"}:
            out.append({"control": c["control"], "status": c["status"], "action": _action_for(c["control"])})
    return out


def _action_for(control: str) -> str:
    return {
        "Lawful processing & consent capture":      "Add a consent collection endpoint + UI banner; persist consent receipt with timestamp + IP.",
        "Purpose limitation (Sec. 4)":              "Maintain a per-data-point purpose registry and reject processing outside the stated purpose.",
        "Data Principal rights (Sec. 11-14)":       "Build self-service endpoints for access / correction / erasure / nomination within 72h of request.",
        "Storage limitation / retention (Sec. 8(7))":"Add a TTL on every personal-data table; run a daily cron to delete records past retention.",
        "Breach notification (Sec. 8(6)) — 72h":    "Write a breach runbook with on-call rotation, 72h DPB notification template, and user-notice template.",
        "Audit logging (Sec. 8(5))":                "Emit append-only audit logs for every read/write of personal data; ship to a tamper-evident store.",
        "Grievance officer (Sec. 8(10))":           "Appoint a Grievance Officer; publish name + contact in the privacy notice AND the website footer.",
        "Children's data (Sec. 9)":                 "Add an age-gate and verifiable parental consent flow before collecting data from minors.",
        "Data minimisation":                        "Avoid storing Aadhaar / PAN unless legally required. Tokenise, hash, or drop at the edge.",
    }.get(control, "Review and remediate.")


def _summary(matrix: List[Dict[str, str]], remediation: List[Dict[str, Any]]) -> str:
    fail = sum(1 for c in matrix if c["status"] == "fail")
    partial = sum(1 for c in matrix if c["status"] == "partial")
    warn = sum(1 for c in matrix if c["status"] == "warn")
    return f"DPDP audit: {len(matrix)} controls — {fail} fail, {partial} partial, {warn} warn. {len(remediation)} actions queued."
