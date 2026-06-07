"""
Accessibility Tester — automated WCAG 2.2 AA / AAA audit.

Given URL, HTML markup, or React/Vue/Svelte component source, this agent
maps every observed pattern to a specific WCAG 2.2 success criterion,
flags violations with axe-core-style rule IDs, generates an
accessibility statement page, and emits a remediation patch (ARIA
attributes, semantic HTML, focus management, colour-contrast fixes).

Input:  url (str), html (str), component_code (str), framework (str),
        level (str), include_statement (bool)
Output: wcag_findings, axe_rule_violations, contrast_issues,
        keyboard_nav_issues, remediation_patch, accessibility_statement,
        report_path
"""
from __future__ import annotations

from typing import Any, Dict

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def accessibility_tester(args: Dict[str, Any]) -> Dict[str, Any]:
    url               = args.get("url", "")
    html              = args.get("html", "")
    component_code    = args.get("component_code", "")
    framework         = args.get("framework", "react")
    level             = args.get("level", "AA")  # AA | AAA
    include_statement = bool(args.get("include_statement", True))

    # Best-effort live fetch — silently ignored if curl/timeout missing
    fetched = ""
    if url and not html:
        fetched = _run(
            f"curl -sL --max-time 10 -A 'Mozilla/5.0 TIMPS-A11y' {url} 2>/dev/null | head -c 12000",
            timeout=12)[:12000]

    source_blob = html or fetched or component_code or ""

    system = (
        f"You are a senior accessibility engineer (WCAG 2.2 {level}). Audit the "
        "supplied markup or component and produce: per-finding mapping to the "
        "exact WCAG success criterion, axe-core rule IDs, severity, an explicit "
        "fix with the corrected code snippet, and an end-of-report Accessibility "
        "Statement page. Cover: semantic landmarks, heading order, alt text, "
        "form-control labels, keyboard navigation/focus order, ARIA roles/states, "
        "colour contrast (compute approximate ratios when colours are visible), "
        "motion-reduce preferences, time limits, and parsing/name-role-value. "
        "Output ONLY JSON: "
        "{level:'AA'|'AAA', total_violations:int, score_0_100:int, "
        "wcag_findings:[{sc_id,sc_name,severity:'critical'|'serious'|'moderate'"
        "|'minor',rule_id_axe,element_selector,description,fix_code_snippet,"
        "wcag_url}], "
        "contrast_issues:[{element_selector,fg,bg,ratio,required_ratio,fix}], "
        "keyboard_nav_issues:[{selector,problem,fix}], "
        "screen_reader_issues:[{selector,problem,aria_fix}], "
        "remediation_patch:{language,unified_diff,explanation}, "
        "accessibility_statement_md:str, "
        "manual_test_checklist:[str], "
        "ci_integration:{tool:'axe-playwright'|'pa11y'|'lighthouse-ci',"
        "yaml_snippet}}."
    )
    prompt = (
        f"URL: {url or '(none)'}\nFramework: {framework}\n"
        f"Level: {level}  Include statement: {include_statement}\n\n"
        f"MARKUP / COMPONENT SOURCE:\n```\n{source_blob[:8000]}\n```\n\n"
        "Be specific and quote selectors. Provide a working remediation diff."
    )

    data = _parse_json(_llm(prompt, system, "accessibility_tester"), {
        "wcag_findings": [], "contrast_issues": [],
        "keyboard_nav_issues": [], "remediation_patch": {},
    })

    ts = _ts()
    findings = data.get("wcag_findings", [])
    critical = [f for f in findings if f.get("severity") in ("critical", "serious")]

    patch_path = ""
    patch = data.get("remediation_patch", {})
    if patch.get("unified_diff"):
        patch_path = _save("patches", f"a11y_remediation_{ts}.patch",
                           patch["unified_diff"])

    statement_path = ""
    if include_statement and data.get("accessibility_statement_md"):
        statement_path = _save("a11y", f"accessibility_statement_{ts}.md",
                               data["accessibility_statement_md"])

    ci_snippet_path = ""
    ci = data.get("ci_integration", {})
    if ci.get("yaml_snippet"):
        ci_snippet_path = _save("a11y", f"a11y_ci_{ci.get('tool','axe')}_{ts}.yml",
                                ci["yaml_snippet"])

    report = (
        f"# Accessibility Audit (WCAG 2.2 {level}) — {ts}\n\n"
        f"**Score:** {data.get('score_0_100','?')}/100  "
        f"**Violations:** {data.get('total_violations', len(findings))} "
        f"({len(critical)} critical/serious)\n\n"
        "## WCAG Findings\n"
        + "\n".join(
            f"- [{f.get('severity','?').upper()}] **{f.get('sc_id','?')}** "
            f"{f.get('sc_name','?')} (`{f.get('rule_id_axe','?')}`) on "
            f"`{f.get('element_selector','?')}` — {f.get('description','')}"
            for f in findings
        )
        + "\n\n## Contrast issues\n"
        + "\n".join(
            f"- `{c.get('element_selector','?')}` fg `{c.get('fg','?')}` / "
            f"bg `{c.get('bg','?')}` ratio {c.get('ratio','?')} "
            f"(needs {c.get('required_ratio','?')}) → {c.get('fix','')}"
            for c in data.get("contrast_issues", [])
        )
        + "\n\n## Keyboard navigation issues\n"
        + "\n".join(
            f"- `{k.get('selector','?')}` — {k.get('problem','')} → {k.get('fix','')}"
            for k in data.get("keyboard_nav_issues", [])
        )
        + "\n\n## Screen-reader issues\n"
        + "\n".join(
            f"- `{s.get('selector','?')}` — {s.get('problem','')} → "
            f"`{s.get('aria_fix','')}`"
            for s in data.get("screen_reader_issues", [])
        )
        + "\n\n## Manual test checklist\n"
        + "\n".join(f"- [ ] {m}" for m in data.get("manual_test_checklist", []))
    )
    report_path = _save("reports", f"a11y_audit_{ts}.md", report)

    _record("accessibility_tester", url or framework,
            f"score={data.get('score_0_100','?')} violations={len(findings)} "
            f"critical={len(critical)}")

    return {
        "level":                     level,
        "score_0_100":               data.get("score_0_100"),
        "total_violations":          data.get("total_violations", len(findings)),
        "wcag_findings":             findings,
        "critical_findings_count":   len(critical),
        "contrast_issues":           data.get("contrast_issues", []),
        "keyboard_nav_issues":       data.get("keyboard_nav_issues", []),
        "screen_reader_issues":      data.get("screen_reader_issues", []),
        "remediation_patch_path":    patch_path,
        "accessibility_statement_path": statement_path,
        "ci_integration_path":       ci_snippet_path,
        "manual_test_checklist":     data.get("manual_test_checklist", []),
        "report_path":               report_path,
        "summary": (
            f"A11y (WCAG 2.2 {level}) score "
            f"{data.get('score_0_100','?')}/100, {len(findings)} violations "
            f"({len(critical)} critical/serious). → {report_path}."
        ),
    }
