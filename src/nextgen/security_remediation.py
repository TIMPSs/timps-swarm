"""
Security Remediation Agent — closes the loop from detection to fix.

Given a vulnerability finding (or a Security Auditor report), this agent
generates a targeted code patch, the corresponding verification test, a
git-ready commit message, and a PR description. Supports SQLi, XSS,
SSRF, hardcoded secrets, weak crypto, insecure deserialization, path
traversal, and vulnerable dependency upgrades.

Input:  findings (list|str), code (str), path (str), language (str),
        auto_pr (bool), risk_tolerance (str)
Output: patches, verification_tests, pr_description, commit_message,
        rollback_plan, branch_name, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record


def _coerce_findings(findings: Any) -> str:
    if not findings:
        return "(no structured findings provided — infer from code)"
    if isinstance(findings, list):
        return "\n".join(
            f"- {f.get('id','?')}: {f.get('title','?')} [{f.get('severity','?')}] "
            f"@ {f.get('code_location','?')} — {f.get('description','')}"
            if isinstance(f, dict) else f"- {f}"
            for f in findings
        )[:5000]
    return str(findings)[:5000]


def security_remediation(args: Dict[str, Any]) -> Dict[str, Any]:
    findings_raw   = args.get("findings", [])
    code           = args.get("code", "")
    path_str       = args.get("path", "")
    language       = args.get("language", "python")
    auto_pr        = bool(args.get("auto_pr", False))
    risk_tolerance = args.get("risk_tolerance", "conservative")

    if not code and path_str:
        p = Path(path_str)
        if p.is_file():
            code = p.read_text(encoding="utf-8", errors="ignore")
        elif p.is_dir():
            parts: List[str] = []
            for f in list(p.rglob(f"*.{ 'py' if language=='python' else language}"))[:8]:
                parts.append(f"### {f}\n" +
                             f.read_text(encoding="utf-8", errors="ignore")[:1200])
            code = "\n\n".join(parts)

    findings_str = _coerce_findings(findings_raw)

    system = (
        "You are an offensive-security engineer turned remediation specialist. "
        "For each finding you must produce a MINIMAL, REVERSIBLE patch that fixes "
        "the underlying class of bug (not just the symptom). Use OWASP-recommended "
        "patterns: parameterised queries for SQLi, contextual output encoding for "
        "XSS, allow-listed URL schemes for SSRF, secret managers for hardcoded "
        "credentials, argon2/bcrypt for password hashing, defusedxml for XML, etc. "
        "Output ONLY valid JSON: "
        "{remediation_summary:str, risk_tolerance_observed:str, "
        "patches:[{finding_id,file,language,unified_diff,explanation,"
        "owasp_pattern,risk_introduced:'none'|'low'|'medium'}], "
        "verification_tests:[{name,framework,code,asserts_what}], "
        "dependency_upgrades:[{package,from_version,to_version,breaking_changes}], "
        "branch_name:str, commit_message:str, pr_title:str, pr_description_md:str, "
        "rollback_plan:str, post_merge_monitoring:[str], "
        "unfixable_findings:[{finding_id,reason,recommended_compensating_control}]}."
    )
    prompt = (
        f"Language: {language}\nRisk tolerance: {risk_tolerance}\n"
        f"Auto-PR requested: {auto_pr}\n\n"
        f"FINDINGS:\n{findings_str}\n\n"
        f"SOURCE:\n```{language}\n{code[:6500]}\n```\n\n"
        "Produce conservative, defensible patches with corresponding tests."
    )

    data = _parse_json(_llm(prompt, system, "security_remediation"), {
        "patches": [], "verification_tests": [], "rollback_plan": "",
    })

    ts = _ts()
    patches = data.get("patches", [])
    tests   = data.get("verification_tests", [])

    patch_artifacts = []
    for i, p in enumerate(patches):
        fname = f"sec_remediation_{ts}_{i}.patch"
        patch_artifacts.append(_save("patches", fname, p.get("unified_diff", "") or ""))

    test_artifacts = []
    for i, t in enumerate(tests):
        ext = {"pytest": "py", "jest": "test.js", "go": "_test.go"}.get(
            t.get("framework", "pytest"), "py")
        fname = f"verify_{(t.get('name','test') or 'test').replace(' ','_')}_{i}.{ext}"
        test_artifacts.append(_save("tests", fname, t.get("code", "") or ""))

    branch = data.get("branch_name") or f"security/remediation-{ts[:8]}"
    pr_md = data.get("pr_description_md") or ""
    pr_path = _save("pr_drafts", f"sec_remediation_pr_{ts}.md",
                    f"# {data.get('pr_title','Security remediation')}\n\n{pr_md}")

    report = (
        f"# Security Remediation — {ts}\n\n"
        f"**Patches:** {len(patches)}  **Verification tests:** {len(tests)}  "
        f"**Dependency upgrades:** {len(data.get('dependency_upgrades',[]))}  "
        f"**Branch:** `{branch}`\n\n"
        f"## Summary\n{data.get('remediation_summary','')}\n\n"
        "## Patches\n"
        + "\n".join(
            f"### Finding {p.get('finding_id','?')} → `{p.get('file','?')}` "
            f"({p.get('owasp_pattern','?')})\n"
            f"{p.get('explanation','')}\n```diff\n{p.get('unified_diff','')}\n```"
            for p in patches
        )
        + f"\n\n## Rollback plan\n{data.get('rollback_plan','')}\n"
        + "\n## Unfixable findings\n"
        + "\n".join(
            f"- {u.get('finding_id','?')}: {u.get('reason','?')} → "
            f"compensating control: {u.get('recommended_compensating_control','')}"
            for u in data.get("unfixable_findings", [])
        )
    )
    report_path = _save("reports", f"sec_remediation_{ts}.md", report)

    _record("security_remediation",
            f"{len(patches)} patches",
            f"tests={len(tests)} branch={branch}")

    return {
        "patches":               patches,
        "verification_tests":    tests,
        "dependency_upgrades":   data.get("dependency_upgrades", []),
        "branch_name":           branch,
        "commit_message":        data.get("commit_message", ""),
        "pr_title":              data.get("pr_title", ""),
        "pr_description_md":     pr_md,
        "pr_draft_path":         pr_path,
        "rollback_plan":         data.get("rollback_plan", ""),
        "post_merge_monitoring": data.get("post_merge_monitoring", []),
        "unfixable_findings":    data.get("unfixable_findings", []),
        "patch_files":           patch_artifacts,
        "test_files":            test_artifacts,
        "report_path":           report_path,
        "summary": (
            f"Generated {len(patches)} patches + {len(tests)} verification tests "
            f"on branch `{branch}`. PR draft → {pr_path}."
        ),
    }
