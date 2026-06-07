"""
Visual Regression Detective — perceptual-diff visual QA.

Compares "before" and "after" representations of a UI (URLs,
screenshots, HTML/CSS, or component source) and reports meaningful
visual changes (layout shifts, colour drift, font/typography swaps,
spacing regressions, hidden/missing elements). Classifies each change
as intentional or unintentional based on co-supplied PR title /
description, generates a Playwright visual-diff test scaffolding, and
emits a "review-needed" gate for CI.

Input:  before (str: URL|HTML|description), after (str), pr_context (str),
        breakpoints (list), threshold (float)
Output: differences, severity_rank, intent_classification,
        playwright_visual_test, ci_gate_yaml, report_path
"""
from __future__ import annotations

from typing import Any, Dict

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _maybe_fetch(maybe_url: str) -> str:
    if not isinstance(maybe_url, str) or not maybe_url.startswith(("http://", "https://")):
        return ""
    return _run(
        f"curl -sL --max-time 10 {maybe_url} 2>/dev/null | head -c 6000",
        timeout=12)[:6000]


def visual_regression_detective(args: Dict[str, Any]) -> Dict[str, Any]:
    before        = args.get("before", "")
    after         = args.get("after", "")
    pr_context    = args.get("pr_context", "")
    breakpoints   = args.get("breakpoints") or [375, 768, 1280, 1920]
    threshold     = float(args.get("threshold", 0.02))
    framework     = args.get("framework", "playwright")

    before_blob = _maybe_fetch(before) or before
    after_blob  = _maybe_fetch(after)  or after

    system = (
        "You are a visual-regression QA specialist. Compare BEFORE and AFTER UI "
        "snapshots (markup, screenshot descriptions, or URLs) and surface "
        "MEANINGFUL visual differences only — ignore anti-aliasing and dynamic "
        "data placeholders. For every diff: classify as INTENTIONAL (matches PR "
        "context) or UNINTENTIONAL (potential regression), assign severity, and "
        "describe the visual delta in plain language. Then output a Playwright "
        "visual-diff test scaffold and a CI gate that blocks merges when "
        "unintentional unintentional changes exceed threshold. "
        "Output ONLY JSON: "
        "{summary:str, total_differences:int, "
        "differences:[{element_selector,kind:'layout_shift'|'colour_drift'|"
        "'typography'|'spacing'|'hidden'|'new'|'image',description,"
        "intent:'intentional'|'unintentional'|'unclear',severity:'critical'"
        "|'high'|'medium'|'low',breakpoints_affected:[int]}], "
        "ci_gate_decision:'pass'|'review_needed'|'fail', "
        "unintentional_change_ratio:float, "
        "playwright_visual_test:{filename,content}, "
        "ci_gate_yaml:str, "
        "human_review_summary_md:str, "
        "screenshots_to_capture:[str], "
        "tolerance_recommendation:{per_breakpoint:object,reasoning:str}}."
    )
    prompt = (
        f"PR context: {pr_context or '(none)'}\n"
        f"Breakpoints: {breakpoints}  Threshold: {threshold}\n"
        f"Framework: {framework}\n\n"
        f"BEFORE:\n```\n{before_blob[:5000]}\n```\n\n"
        f"AFTER:\n```\n{after_blob[:5000]}\n```\n\n"
        "Be conservative. Mark INTENTIONAL only when the PR context clearly "
        "explains the change."
    )

    data = _parse_json(_llm(prompt, system, "visual_regression_detective"), {
        "differences": [], "ci_gate_decision": "review_needed",
        "playwright_visual_test": {}, "ci_gate_yaml": "",
    })

    ts = _ts()
    test_path = ""
    test = data.get("playwright_visual_test", {})
    if test.get("content"):
        fname = test.get("filename") or f"visual_diff_{ts}.spec.ts"
        test_path = _save("tests", fname, test["content"])

    ci_path = ""
    if data.get("ci_gate_yaml"):
        ci_path = _save("ci", f"visual_diff_gate_{ts}.yml", data["ci_gate_yaml"])

    diffs = data.get("differences", [])
    unintentional = [d for d in diffs if d.get("intent") == "unintentional"]

    report = (
        f"# Visual Regression Detective — {ts}\n\n"
        f"**Total differences:** {data.get('total_differences', len(diffs))}  "
        f"**Unintentional ratio:** {data.get('unintentional_change_ratio','?')}  "
        f"**CI gate:** **{data.get('ci_gate_decision','?').upper()}**\n\n"
        f"## Summary\n{data.get('summary','')}\n\n"
        "## Differences (unintentional first)\n"
        + "\n".join(
            f"- [{d.get('severity','?').upper()}/{d.get('intent','?')}] "
            f"`{d.get('element_selector','?')}` ({d.get('kind','?')}, "
            f"bp {d.get('breakpoints_affected',[])}) — {d.get('description','')}"
            for d in sorted(diffs,
                            key=lambda x: 0 if x.get("intent") == "unintentional" else 1)
        )
        + "\n\n## Human-review summary\n" + (data.get("human_review_summary_md","") or "")
        + "\n\n## Screenshots to capture\n"
        + "\n".join(f"- {s}" for s in data.get("screenshots_to_capture", []))
    )
    report_path = _save("reports", f"visual_regression_{ts}.md", report)

    _record("visual_regression_detective", pr_context[:120] or "diff",
            f"diffs={len(diffs)} unintentional={len(unintentional)} "
            f"gate={data.get('ci_gate_decision')}")

    return {
        "total_differences":          data.get("total_differences", len(diffs)),
        "differences":                diffs,
        "unintentional_count":        len(unintentional),
        "unintentional_change_ratio": data.get("unintentional_change_ratio"),
        "ci_gate_decision":           data.get("ci_gate_decision"),
        "playwright_visual_test_path": test_path,
        "ci_gate_path":               ci_path,
        "human_review_summary_md":    data.get("human_review_summary_md", ""),
        "screenshots_to_capture":     data.get("screenshots_to_capture", []),
        "tolerance_recommendation":   data.get("tolerance_recommendation", {}),
        "report_path":                report_path,
        "summary": (
            f"{len(diffs)} visual diffs ({len(unintentional)} unintentional). "
            f"CI gate: {data.get('ci_gate_decision','?')}. → {report_path}."
        ),
    }
