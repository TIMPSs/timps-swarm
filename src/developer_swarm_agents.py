"""
Developer Swarm Agents — 12 atomic specialist agents for the full SDLC.

Each agent owns exactly one narrow domain, does real computer-use work
(git, filesystem, web search), and returns a clean structured output.

Agents
------
  Issue Triager         — deduplicate, label, and rank new bug reports
  Boilerplate Architect — scaffold folder structures + hello-world stubs
  PR Reviewer           — style, logic smells, coverage gaps on pull requests
  Dependency Sentinel   — CVE scan + outdated-package detection → update PRs
  Unit Test Writer      — analyse a function and generate edge-case test suites
  Docstring Generator   — read raw code, write JSDoc / Sphinx / Doxygen docs
  Log Detective         — cluster production errors → root-cause summary
  SQL Optimizer         — slow-query analysis + index recommendations
  Scaffold Agent        — generate microservice/module boilerplate on demand
  Sprint Reporter       — pull GitHub/Linear tasks → daily standup markdown
  Flaky Test Hunter     — identify non-deterministic tests from CI history
  API Contract Auditor  — diff OpenAPI specs, flag breaking changes
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(os.getenv("GENERATED_DIR", "generated"))
REPORTS_DIR   = GENERATED_DIR / "reports"
SCRIPTS_DIR   = GENERATED_DIR / "scripts"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _router():
    from src.llm_router import LLMRouter
    return LLMRouter()


def _computer(agent_id: str):
    from src.computer_use import get_agent_computer
    return get_agent_computer(agent_id)


def _save(subdir: str, filename: str, content: str) -> str:
    path = GENERATED_DIR / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def _run(cmd: str, cwd: Optional[str] = None) -> str:
    """Run a shell command and return combined stdout+stderr."""
    try:
        args = shlex.split(cmd)
        result = subprocess.run(
            args, capture_output=True, text=True,
            timeout=60, cwd=cwd or os.getcwd()
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 s"
    except Exception as exc:
        return f"Error running command: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# 1 — ISSUE TRIAGER
# Input : raw issue text (title + body)
# Output: severity label, duplicate status, suggested assignee, next action
# ─────────────────────────────────────────────────────────────────────────────

def issue_triager(request: str, repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Scan new bug reports, remove duplicates, assign severity, suggest owner.

    Args:
        request: raw issue text (title and body)
        repo_path: local git repo path for scanning existing issues

    Returns:
        dict with keys: severity, is_duplicate, suggested_labels,
                        suggested_assignee, next_action, summary
    """
    logger.info("[IssueTriage] Processing issue: %.80s…", request)

    # Gather existing issues from git log / README for dedup context
    existing_context = ""
    if repo_path and Path(repo_path).exists():
        existing_context = _run("git log --oneline -50", cwd=repo_path)

    computer = _computer("issue_triager")
    web_context = computer.research_sync(
        f"similar issues {request[:120]} github bug severity", follow_links=0
    )

    system = (
        "You are a senior engineering triage bot. Analyse the issue report and return "
        "a JSON object with exactly these keys:\n"
        "  severity        : 'critical' | 'high' | 'medium' | 'low'\n"
        "  is_duplicate    : true | false\n"
        "  suggested_labels: list[str] (e.g. ['bug', 'backend', 'auth'])\n"
        "  suggested_assignee: 'backend' | 'frontend' | 'devops' | 'security' | 'unassigned'\n"
        "  next_action     : one sentence on what to do next\n"
        "  summary         : two-sentence plain-English summary of the issue\n"
        "Output ONLY valid JSON — no prose, no markdown fences."
    )
    prompt = (
        f"Issue report:\n{request}\n\n"
        f"Recent git history (for duplicate detection):\n{existing_context[:800]}\n\n"
        f"Web context:\n{web_context[:1000]}"
    )
    raw = _router().call("issue_triager", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"summary": raw, "severity": "medium"}

    result["_agent"] = "issue_triager"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2 — BOILERPLATE ARCHITECT
# Input : project description + language/framework
# Output: folder tree + starter files
# ─────────────────────────────────────────────────────────────────────────────

def boilerplate_architect(request: str, language: str = "python") -> Dict[str, Any]:
    """
    Generate a production-grade folder structure and stub files for a new project.

    Returns a dict with 'folder_tree' (str), 'files' (dict[path → content]),
    and 'setup_commands' (list[str]).
    """
    logger.info("[Boilerplate] Scaffolding project: %.80s…", request)

    computer = _computer("boilerplate_architect")
    research = computer.research_sync(
        f"best project structure {language} {request} 2025 production", follow_links=1
    )

    system = (
        "You are a senior software architect. Generate a complete project scaffold. "
        "Return a JSON object with:\n"
        "  folder_tree    : ASCII tree of the project structure\n"
        "  files          : dict mapping relative-path → file-content (key stubs only, max 40 lines each)\n"
        "  setup_commands : list of shell commands to initialise the project\n"
        "  description    : two-sentence description of the architecture decisions\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Project request: {request}\n"
        f"Primary language: {language}\n\n"
        f"Best-practice research:\n{research[:2000]}"
    )
    raw = _router().call("boilerplate_architect", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        scaffold: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        scaffold = {"folder_tree": raw}

    # Write stub files to generated/code/
    for rel_path, content in scaffold.get("files", {}).items():
        safe_path = rel_path.lstrip("/").replace("..", "")
        _save("code", safe_path, content)

    scaffold["_agent"] = "boilerplate_architect"
    scaffold["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return scaffold


# ─────────────────────────────────────────────────────────────────────────────
# 3 — PR REVIEWER
# Input : diff text or PR description
# Output: review comments grouped by category
# ─────────────────────────────────────────────────────────────────────────────

def pr_reviewer(diff_or_description: str, style_guide: str = "") -> Dict[str, Any]:
    """
    Review a pull request diff for style, logic bugs, security issues, and
    test coverage gaps.

    Returns dict with 'blockers', 'suggestions', 'nitpicks', 'score' (0-10).
    """
    logger.info("[PRReview] Reviewing diff (%d chars)", len(diff_or_description))

    system = (
        "You are a principal engineer doing a thorough code review. "
        "Return a JSON object with:\n"
        "  blockers    : list of critical issues that MUST be fixed (logic bugs, security, data loss)\n"
        "  suggestions : list of important improvements (performance, readability, test coverage)\n"
        "  nitpicks    : list of minor style/formatting comments\n"
        "  score       : integer 0-10 (10 = ship it, 0 = rewrite)\n"
        "  verdict     : 'approve' | 'request_changes' | 'comment'\n"
        "  summary     : three-sentence plain-English review summary\n"
        "Output ONLY valid JSON."
    )
    style_context = f"\nProject style guide:\n{style_guide[:500]}" if style_guide else ""
    prompt = (
        f"Pull request diff / description:\n{diff_or_description[:4000]}"
        f"{style_context}"
    )
    raw = _router().call("pr_reviewer", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        review: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        review = {"summary": raw, "verdict": "comment"}

    path = _save("reports", "pr_review.md", json.dumps(review, indent=2))
    review["_report_path"] = path
    review["_agent"] = "pr_reviewer"
    review["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return review


# ─────────────────────────────────────────────────────────────────────────────
# 4 — DEPENDENCY SENTINEL
# Input : requirements.txt / package.json / go.mod / Cargo.toml / pom.xml
# Output: CVE findings, outdated packages, upgrade path
# ─────────────────────────────────────────────────────────────────────────────

def dependency_sentinel(manifest_content: str, manifest_type: str = "auto") -> Dict[str, Any]:
    """
    Scan a dependency manifest for known CVEs and outdated packages.
    Returns a structured report with severity-ranked findings and upgrade commands.
    """
    logger.info("[DepSentinel] Scanning manifest (%s, %d chars)", manifest_type, len(manifest_content))

    # Auto-detect manifest type
    if manifest_type == "auto":
        if "import" in manifest_content and "=" in manifest_content:
            manifest_type = "requirements.txt"
        elif '"dependencies"' in manifest_content:
            manifest_type = "package.json"
        elif "module " in manifest_content:
            manifest_type = "go.mod"
        else:
            manifest_type = "unknown"

    computer = _computer("dependency_sentinel")
    cve_context = computer.research_sync(
        f"CVE vulnerabilities {manifest_type} 2025 security advisories", follow_links=0
    )

    system = (
        "You are a supply-chain security engineer. Analyse the dependency manifest for:\n"
        "1. Known CVEs and CVSS scores\n"
        "2. Severely outdated packages (major version behind)\n"
        "3. Abandoned packages (no release in 2+ years)\n"
        "Return a JSON object with:\n"
        "  critical_cves  : list of {package, cve_id, cvss, description, fix_version}\n"
        "  outdated       : list of {package, current_version, latest_version, major_behind}\n"
        "  abandoned      : list of package names\n"
        "  upgrade_script : shell commands to upgrade everything safely\n"
        "  risk_score     : 'critical' | 'high' | 'medium' | 'low'\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Manifest type: {manifest_type}\n\n"
        f"Manifest content:\n{manifest_content[:3000]}\n\n"
        f"CVE research context:\n{cve_context[:1000]}"
    )
    raw = _router().call("dependency_sentinel", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        report: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        report = {"summary": raw}

    path = _save("reports", "dependency_sentinel.md", json.dumps(report, indent=2))
    report["_report_path"] = path
    report["_agent"] = "dependency_sentinel"
    report["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return report


# ─────────────────────────────────────────────────────────────────────────────
# 5 — UNIT TEST WRITER
# Input : source code of a function or class
# Output: complete test file with edge-case coverage
# ─────────────────────────────────────────────────────────────────────────────

def unit_test_writer(
    source_code: str,
    language: str = "python",
    framework: str = "auto",
) -> Dict[str, Any]:
    """
    Analyse source code and generate a comprehensive test suite covering
    happy paths, edge cases, and error conditions.

    Returns dict with 'test_code', 'test_file_path', 'coverage_summary'.
    """
    logger.info("[TestWriter] Generating tests for %s (%d chars)", language, len(source_code))

    if framework == "auto":
        framework_map = {
            "python": "pytest",
            "javascript": "jest",
            "typescript": "jest",
            "java": "junit5",
            "go": "testing",
            "rust": "cargo test",
        }
        framework = framework_map.get(language.lower(), "pytest")

    system = (
        f"You are a test engineering expert specialising in {framework}. "
        "Write a comprehensive test suite for the provided code. "
        "Include: happy paths, edge cases, boundary conditions, error handling tests, "
        "and at least one property-based test if the framework supports it. "
        "Return a JSON object with:\n"
        "  test_code        : the complete test file as a string\n"
        "  test_count       : number of test functions written\n"
        "  coverage_summary : what branches and paths are covered\n"
        "  run_command      : shell command to run the tests\n"
        "Output ONLY valid JSON."
    )
    prompt = f"Language: {language}\nFramework: {framework}\n\nSource code:\n{source_code[:4000]}"
    raw = _router().call("unit_test_writer", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"test_code": raw}

    test_code = result.get("test_code", "")
    if test_code:
        ext_map = {"python": "py", "javascript": "js", "typescript": "ts",
                   "java": "java", "go": "go", "rust": "rs"}
        ext = ext_map.get(language.lower(), "py")
        path = _save("code", f"test_generated.{ext}", test_code)
        result["test_file_path"] = path

    result["_agent"] = "unit_test_writer"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6 — DOCSTRING GENERATOR
# Input : raw code (function / class / module)
# Output: code with inline docstrings inserted
# ─────────────────────────────────────────────────────────────────────────────

def docstring_generator(
    source_code: str,
    language: str = "python",
    doc_style: str = "google",
) -> Dict[str, Any]:
    """
    Read raw source code and insert production-quality docstrings.
    Supports Google, Sphinx, NumPy, JSDoc, and Doxygen formats.

    Returns dict with 'documented_code', 'functions_documented', 'style'.
    """
    logger.info("[DocGen] Documenting %s code (%d chars)", language, len(source_code))

    style_descriptions = {
        "google":  "Google-style Python docstrings (Args:, Returns:, Raises:)",
        "sphinx":  "Sphinx-style with :param:, :type:, :returns:",
        "numpy":   "NumPy/SciPy docstring format",
        "jsdoc":   "JSDoc format (@param, @returns, @throws)",
        "doxygen": "Doxygen format (/**  @brief, @param, @return */)",
    }
    style_desc = style_descriptions.get(doc_style, doc_style)

    system = (
        f"You are a technical writer who specialises in {style_desc}. "
        "Add comprehensive docstrings to every function, method, and class in the code. "
        "Do NOT change any logic — only add or improve documentation. "
        "Return a JSON object with:\n"
        "  documented_code     : the full source code with docstrings added\n"
        "  functions_documented: list of function/class names that were documented\n"
        "  style               : the doc style used\n"
        "Output ONLY valid JSON."
    )
    prompt = f"Language: {language}\nDoc style: {doc_style}\n\nSource:\n{source_code[:5000]}"
    raw = _router().call("docstring_generator", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"documented_code": source_code, "note": raw}

    doc_code = result.get("documented_code", "")
    if doc_code:
        ext_map = {"python": "py", "javascript": "js", "typescript": "ts", "java": "java"}
        ext = ext_map.get(language.lower(), "py")
        path = _save("code", f"documented.{ext}", doc_code)
        result["output_path"] = path

    result["_agent"] = "docstring_generator"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 7 — LOG DETECTIVE
# Input : log snippet (plain text or JSON lines)
# Output: clustered errors, root-cause hypothesis, suggested fix
# ─────────────────────────────────────────────────────────────────────────────

def log_detective(log_content: str, service_name: str = "app") -> Dict[str, Any]:
    """
    Cluster error messages, identify root cause, and suggest a fix.
    Handles stack traces, structured JSON logs, syslog, and journald output.
    """
    logger.info("[LogDetective] Analysing %d chars of logs for '%s'", len(log_content), service_name)

    system = (
        "You are a senior SRE specialised in production incident analysis. "
        "Analyse the log output and return a JSON object with:\n"
        "  error_clusters : list of {pattern, count, first_occurrence, severity, example_line}\n"
        "  root_cause     : the most likely root cause in plain English\n"
        "  affected_component: which service/module is failing\n"
        "  blast_radius   : 'contained' | 'degraded' | 'outage'\n"
        "  suggested_fix  : concrete steps to resolve the issue\n"
        "  escalate_to    : 'backend' | 'infra' | 'security' | 'database' | 'none'\n"
        "Output ONLY valid JSON."
    )
    prompt = f"Service: {service_name}\n\nLog output:\n{log_content[:5000]}"
    raw = _router().call("log_detective", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"root_cause": raw}

    path = _save("reports", "log_detective.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "log_detective"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 8 — SQL OPTIMIZER
# Input : slow SQL query + optional EXPLAIN output
# Output: optimised query + index recommendations
# ─────────────────────────────────────────────────────────────────────────────

def sql_optimizer(
    query: str,
    explain_output: str = "",
    db_engine: str = "postgresql",
) -> Dict[str, Any]:
    """
    Analyse a slow SQL query and suggest indexes, rewrites, and query hints.
    Supports PostgreSQL, MySQL, SQLite, and MSSQL.
    """
    logger.info("[SQLOpt] Optimising %s query (%d chars)", db_engine, len(query))

    computer = _computer("sql_optimizer")
    research = computer.research_sync(
        f"{db_engine} query optimization indexing strategies 2025", follow_links=0
    )

    system = (
        f"You are a database performance expert for {db_engine}. "
        "Analyse the slow query and return a JSON object with:\n"
        "  problem_identified : what makes this query slow\n"
        "  optimised_query    : the rewritten, faster version of the query\n"
        "  index_recommendations : list of {table, columns, index_type, reason, create_sql}\n"
        "  estimated_speedup  : rough speedup estimate (e.g. '10x', '2-5x')\n"
        "  warnings           : list of any destructive changes to be aware of\n"
        "  explanation        : plain-English walkthrough of the changes\n"
        "Output ONLY valid JSON."
    )
    explain_section = f"\nEXPLAIN output:\n{explain_output[:1000]}" if explain_output else ""
    prompt = (
        f"Database: {db_engine}\n\n"
        f"Slow query:\n{query}\n"
        f"{explain_section}\n\n"
        f"Optimisation research:\n{research[:800]}"
    )
    raw = _router().call("sql_optimizer", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"explanation": raw}

    path = _save("reports", "sql_optimizer.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "sql_optimizer"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 9 — SPRINT REPORTER
# Input : GitHub/Linear tasks completed since last standup
# Output: formatted daily standup markdown
# ─────────────────────────────────────────────────────────────────────────────

def sprint_reporter(
    completed_tasks: List[str],
    in_progress_tasks: List[str],
    blockers: List[str],
    team_member: str = "Developer",
) -> Dict[str, Any]:
    """
    Compile a daily standup report from task lists.
    Works with GitHub Issues, Linear tickets, or plain text descriptions.
    """
    logger.info("[SprintReporter] Generating standup for %s", team_member)

    system = (
        "You are a technical project manager. Write a concise, professional daily standup "
        "report. Be specific about what was accomplished — avoid vague summaries. "
        "Return a JSON object with:\n"
        "  standup_markdown : formatted markdown standup (Yesterday / Today / Blockers)\n"
        "  key_accomplishments : list of up to 3 highlights from yesterday\n"
        "  risk_flags       : any items that look at risk of missing the sprint\n"
        "  suggested_focus  : what to prioritise today based on the blockers\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Team member: {team_member}\n\n"
        f"Completed tasks:\n" + "\n".join(f"- {t}" for t in completed_tasks) + "\n\n"
        f"In progress:\n" + "\n".join(f"- {t}" for t in in_progress_tasks) + "\n\n"
        f"Blockers:\n" + ("\n".join(f"- {b}" for b in blockers) if blockers else "None")
    )
    raw = _router().call("sprint_reporter", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"standup_markdown": raw}

    result["_agent"] = "sprint_reporter"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 10 — FLAKY TEST HUNTER
# Input : CI test history (list of test run results)
# Output: ranked list of flaky tests with suspected causes
# ─────────────────────────────────────────────────────────────────────────────

def flaky_test_hunter(ci_history: str, repo_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Identify non-deterministic tests by analysing CI run history.
    Looks for tests that flip between pass/fail without code changes.
    """
    logger.info("[FlakyHunter] Analysing CI history (%d chars)", len(ci_history))

    git_context = ""
    if repo_path and Path(repo_path).exists():
        git_context = _run(
            "git log --oneline --format='%h %s' -30", cwd=repo_path
        )

    system = (
        "You are a testing infrastructure specialist. Identify flaky tests from the CI history. "
        "Return a JSON object with:\n"
        "  flaky_tests : list of {test_name, flakiness_score (0-1), likely_cause, "
        "                          suggested_fix, times_failed, times_passed}\n"
        "  common_root_causes : list of systemic issues causing flakiness\n"
        "  stability_score    : overall test suite stability 0-100\n"
        "  top_priority_fix   : single most impactful fix to make\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"CI test history:\n{ci_history[:4000]}\n\n"
        f"Recent commits:\n{git_context[:500]}"
    )
    raw = _router().call("flaky_test_hunter", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"top_priority_fix": raw}

    path = _save("reports", "flaky_test_hunter.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "flaky_test_hunter"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 11 — API CONTRACT AUDITOR
# Input : two OpenAPI / AsyncAPI spec files (old vs new)
# Output: list of breaking changes, deprecations, new endpoints
# ─────────────────────────────────────────────────────────────────────────────

def api_contract_auditor(
    old_spec: str,
    new_spec: str,
    spec_format: str = "openapi",
) -> Dict[str, Any]:
    """
    Diff two API specs and flag breaking changes that would break clients.
    Supports OpenAPI 3.x, Swagger 2.0, and AsyncAPI 2.x/3.x.
    """
    logger.info("[APIAudit] Diffing %s specs", spec_format)

    system = (
        "You are an API governance engineer. Compare the old and new API specs and "
        "return a JSON object with:\n"
        "  breaking_changes : list of {endpoint, change_type, description, impact}\n"
        "  deprecations     : list of {endpoint, reason, replacement}\n"
        "  new_endpoints    : list of new endpoints added\n"
        "  backward_compatible_changes : list of safe additions\n"
        "  semver_recommendation : 'patch' | 'minor' | 'major'\n"
        "  migration_guide  : markdown guide for clients to migrate\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Spec format: {spec_format}\n\n"
        f"OLD spec:\n{old_spec[:2500]}\n\n"
        f"NEW spec:\n{new_spec[:2500]}"
    )
    raw = _router().call("api_contract_auditor", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"migration_guide": raw}

    path = _save("reports", "api_contract_auditor.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "api_contract_auditor"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 12 — CONTENT MULTIPLIER (Dev edition)
# Input : technical blog post or release notes
# Output: tweet thread, LinkedIn post, changelog entry, short docs blurb
# ─────────────────────────────────────────────────────────────────────────────

def content_multiplier(
    long_form_content: str,
    tone: str = "technical",
) -> Dict[str, Any]:
    """
    Take one long-form article/post and generate multiple short-form formats.
    Ideal for release announcements, feature docs, or blog posts.
    """
    logger.info("[ContentMultiplier] Transforming %d chars (%s tone)", len(long_form_content), tone)

    system = (
        "You are a developer advocate and technical writer. Transform the content into "
        "multiple formats. Return a JSON object with:\n"
        "  tweet_thread     : list of 5-8 tweets for a thread (each ≤ 280 chars)\n"
        "  linkedin_post    : a professional LinkedIn post (3-5 paragraphs)\n"
        "  changelog_entry  : concise markdown changelog entry (for CHANGELOG.md)\n"
        "  docs_blurb       : 2-sentence description for documentation\n"
        "  hacker_news_title: a punchy, non-clickbait HN submission title\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Tone: {tone}\n\n"
        f"Source content:\n{long_form_content[:4000]}"
    )
    raw = _router().call("content_multiplier", prompt, system)

    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"docs_blurb": raw}

    result["_agent"] = "content_multiplier"
    result["_timestamp"] = datetime.now(timezone.utc).isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Registry — for the MCP server and swarm dispatcher
# ─────────────────────────────────────────────────────────────────────────────

DEVELOPER_AGENTS: Dict[str, Any] = {
    "issue_triager":        issue_triager,
    "boilerplate_architect": boilerplate_architect,
    "pr_reviewer":          pr_reviewer,
    "dependency_sentinel":  dependency_sentinel,
    "unit_test_writer":     unit_test_writer,
    "docstring_generator":  docstring_generator,
    "log_detective":        log_detective,
    "sql_optimizer":        sql_optimizer,
    "sprint_reporter":      sprint_reporter,
    "flaky_test_hunter":    flaky_test_hunter,
    "api_contract_auditor": api_contract_auditor,
    "content_multiplier":   content_multiplier,
}
