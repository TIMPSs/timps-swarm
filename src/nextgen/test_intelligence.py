"""
Test Intelligence — go beyond happy-path test generation.

For a given module / function this agent does THREE things that the
existing unit_test_writer doesn't:
  1. Mines git history (`git log -p`) for past bug fixes that touched the
     same file and writes regression tests that would have caught them.
  2. Generates property-based tests (hypothesis / fast-check) for any
     data-heavy function it identifies.
  3. Drafts mutation-testing config (mutmut / Stryker / Pitest) and
     surfaces an "untested branches" report based on AST analysis.

Input:  source_code (str), path (str), language (str), repo_path (str),
        framework (str), coverage_target (int)
Output: regression_tests, property_tests, mutation_config,
        untested_branches, bug_history_insights, report_path
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _bug_history(repo_path: str, file_rel: str) -> str:
    if not repo_path or not file_rel:
        return ""
    log = _run(
        f"git log --follow --pretty=format:'%h|%ai|%s' -- {file_rel} 2>/dev/null | head -40",
        cwd=repo_path, timeout=10)
    lines = [l for l in log.splitlines() if l.strip()]
    bug_lines = [l for l in lines if re.search(
        r"\b(fix|bug|regression|hotfix|patch|crash|race|leak|null|nil|undefined)\b",
        l, re.IGNORECASE)]
    return "\n".join(bug_lines[:20])


def _untested_branches_py(code: str) -> List[str]:
    """Return a list of branch descriptors from AST (best-effort)."""
    branches: List[str] = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                branches.append(f"if @ line {node.lineno}")
            elif isinstance(node, (ast.Try,)):
                branches.append(f"try/except @ line {node.lineno}")
            elif isinstance(node, ast.For):
                branches.append(f"for-loop @ line {node.lineno}")
            elif isinstance(node, ast.While):
                branches.append(f"while @ line {node.lineno}")
            elif isinstance(node, ast.Match):
                branches.append(f"match @ line {node.lineno}")
    except Exception:
        pass
    return branches[:50]


def test_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    code            = args.get("source_code") or args.get("code") or ""
    path_str        = args.get("path", "")
    language        = args.get("language", "python")
    repo_path       = args.get("repo_path", "")
    framework       = args.get("framework", "auto")
    coverage_target = int(args.get("coverage_target", 85))

    file_rel = ""
    if path_str:
        p = Path(path_str)
        if p.is_file():
            if not code:
                code = p.read_text(encoding="utf-8", errors="ignore")
            try:
                file_rel = str(p.resolve().relative_to(Path(repo_path or ".").resolve()))
            except Exception:
                file_rel = p.name

    history = _bug_history(repo_path, file_rel) if file_rel else ""
    branches = _untested_branches_py(code) if language == "python" else []

    system = (
        "You are an expert test engineer who writes regression-driven, "
        "property-based, and mutation-aware test suites. For the source below, "
        "you must produce: "
        "(1) REGRESSION tests derived from past bug-fix commits — each test must "
        "name the fixed bug (commit sha) in its docstring; "
        "(2) PROPERTY tests using the language's idiomatic library "
        "(hypothesis for Python, fast-check for JS/TS, proptest for Rust); "
        "(3) MUTATION-testing config for mutmut/Stryker/Pitest with file globs and "
        "score thresholds; "
        "(4) a list of branches/conditions still uncovered. "
        "Output ONLY JSON: "
        "{language:str, framework:str, coverage_target:int, "
        "regression_tests:[{name,for_bug_sha,reasoning,code}], "
        "property_tests:[{name,property_statement,code}], "
        "mutation_config:{tool,config_yaml,score_threshold}, "
        "untested_branches:[{location,description,suggested_test_idea}], "
        "bug_history_insights:[{theme,frequency,countermeasure}], "
        "ci_integration_snippet:str, "
        "estimated_coverage_after:int}."
    )
    prompt = (
        f"Language: {language}\nFramework hint: {framework}\n"
        f"Coverage target: {coverage_target}%\nRepo file: {file_rel or '(unknown)'}\n\n"
        f"Bug-fix history for this file (commit log):\n```\n{history or '(none)'}\n```\n\n"
        f"AST-derived branches (Python only):\n{branches}\n\n"
        f"SOURCE:\n```{language}\n{code[:6500]}\n```\n\n"
        "Write tests that would have caught the historical bugs. Be specific."
    )

    data = _parse_json(_llm(prompt, system, "test_intelligence"), {
        "regression_tests": [], "property_tests": [],
        "mutation_config": {}, "untested_branches": [],
    })

    ts = _ts()
    ext_map = {"python": "py", "javascript": "test.js", "typescript": "test.ts",
               "rust": "rs", "go": "_test.go"}
    ext = ext_map.get(language, "txt")

    regression_paths: List[str] = []
    for r in data.get("regression_tests", []):
        fname = f"regression_{(r.get('name','test') or 'test').replace(' ','_')}_{ts}.{ext}"
        regression_paths.append(_save("tests", fname, r.get("code", "") or ""))

    property_paths: List[str] = []
    for r in data.get("property_tests", []):
        fname = f"property_{(r.get('name','prop') or 'prop').replace(' ','_')}_{ts}.{ext}"
        property_paths.append(_save("tests", fname, r.get("code", "") or ""))

    mut_cfg = data.get("mutation_config", {})
    mut_path = ""
    if mut_cfg.get("config_yaml"):
        mut_path = _save("tests", f"mutation_{mut_cfg.get('tool','mut')}_{ts}.yaml",
                         mut_cfg["config_yaml"])

    report = (
        f"# Test Intelligence — {ts}\n\n"
        f"**Language:** {language}  **Target coverage:** {coverage_target}%  "
        f"**Projected after:** {data.get('estimated_coverage_after','?')}%\n\n"
        f"**Regression tests:** {len(regression_paths)}  "
        f"**Property tests:** {len(property_paths)}  "
        f"**Untested branches:** {len(data.get('untested_branches',[]))}\n\n"
        "## Bug History Insights\n"
        + "\n".join(
            f"- **{b.get('theme','?')}** (×{b.get('frequency','?')}): "
            f"{b.get('countermeasure','?')}"
            for b in data.get("bug_history_insights", [])
        )
        + "\n\n## Untested Branches\n"
        + "\n".join(
            f"- `{u.get('location','?')}` — {u.get('description','')} "
            f"→ {u.get('suggested_test_idea','')}"
            for u in data.get("untested_branches", [])
        )
        + f"\n\n## CI integration\n```yaml\n{data.get('ci_integration_snippet','')}\n```"
    )
    report_path = _save("reports", f"test_intelligence_{ts}.md", report)

    _record("test_intelligence", file_rel or "module",
            f"regression={len(regression_paths)} property={len(property_paths)} "
            f"cov={data.get('estimated_coverage_after','?')}%")

    return {
        "language":               language,
        "framework":              data.get("framework", framework),
        "coverage_target":        coverage_target,
        "estimated_coverage_after": data.get("estimated_coverage_after", coverage_target),
        "regression_tests":       data.get("regression_tests", []),
        "property_tests":         data.get("property_tests", []),
        "mutation_config":        mut_cfg,
        "mutation_config_path":   mut_path,
        "untested_branches":      data.get("untested_branches", []),
        "bug_history_insights":   data.get("bug_history_insights", []),
        "ci_integration_snippet": data.get("ci_integration_snippet", ""),
        "regression_test_paths":  regression_paths,
        "property_test_paths":    property_paths,
        "report_path":            report_path,
        "summary": (
            f"Generated {len(regression_paths)} regression + "
            f"{len(property_paths)} property tests targeting "
            f"{data.get('estimated_coverage_after','?')}% coverage. → {report_path}."
        ),
    }
