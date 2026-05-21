"""
Priority Agents — Phase 3 additions to the TIMPS Swarm.

Five high-value agents:
  1. Research Agent       — web research before coding begins
  2. API Design Agent     — OpenAPI 3.1 spec from natural language
  3. DB Agent             — schema design, migration scripts, query optimisation
  4. Dependency Agent     — CVE scanning, license compliance, upgrade scripts
  5. n8n Workflow Agent   — generates n8n workflow JSON from plain English

All agents follow the same pattern as developer_swarm_agents.py:
  - Accept a dict of kwargs that matches the MCP tool inputSchema
  - Return a structured dict (MCP handler renders it as Markdown)
  - Use get_router().call() for LLM inference (auto-selects best provider)
  - Use AgentComputer for real web research / filesystem ops
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(os.getenv("GENERATED_DIR", "generated"))
REPORTS_DIR   = GENERATED_DIR / "reports"
SPECS_DIR     = GENERATED_DIR / "specs"
SCRIPTS_DIR   = GENERATED_DIR / "scripts"


# ── Helpers ──────────────────────────────────────────────────────────────────

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
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=60, cwd=cwd or os.getcwd()
        )
        return (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "Command timed out after 60 s"
    except Exception as exc:
        return f"Error: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# 1 — RESEARCH AGENT
# Runs before any coding task. Gathers context so every downstream agent
# has grounded, up-to-date information instead of hallucinating.
# ─────────────────────────────────────────────────────────────────────────────

def research_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search documentation, GitHub issues, Stack Overflow, and the web
    for context on a topic.

    Args:
        args: {topic, depth, sources}

    Returns:
        {summary, key_findings, gotchas, recommended_approach,
         sources_consulted, raw_research, report_path}
    """
    topic  = args.get("topic", "")
    depth  = args.get("depth", "medium")
    sources = args.get("sources") or ["docs", "github", "stackoverflow"]

    logger.info("[ResearchAgent] Researching: %s (depth=%s)", topic, depth)

    follow_links = {"quick": 0, "medium": 1, "deep": 3}.get(depth, 1)

    computer = _computer("research_agent")

    # Primary web research
    raw_research = computer.research_sync(topic, follow_links=follow_links)

    # GitHub issues search
    github_context = ""
    if "github" in sources:
        gh_query = f"site:github.com issues {topic}"
        github_context = computer.research_sync(gh_query, follow_links=0)[:2000]

    # Stack Overflow
    so_context = ""
    if "stackoverflow" in sources:
        so_query = f"site:stackoverflow.com {topic}"
        so_context = computer.research_sync(so_query, follow_links=0)[:2000]

    combined = (
        f"Web research:\n{raw_research[:4000]}\n\n"
        f"GitHub issues:\n{github_context}\n\n"
        f"Stack Overflow:\n{so_context}"
    )

    system = (
        "You are TIMPS Research Agent. Synthesise technical research into a structured brief. "
        "Format as JSON with keys: summary, key_findings (list), gotchas (list), "
        "recommended_approach, sources_consulted (list of URLs or site names). "
        "Be specific and cite evidence. Output ONLY valid JSON."
    )
    prompt = (
        f"Topic: {topic}\n\n"
        f"Research gathered:\n{combined[:6000]}\n\n"
        "Produce the JSON brief."
    )

    raw = _router().call("research_agent", prompt, system, format_json=True)

    try:
        brief = json.loads(raw)
    except Exception:
        brief = {
            "summary": raw[:1000],
            "key_findings": [],
            "gotchas": [],
            "recommended_approach": "See summary",
            "sources_consulted": [],
        }

    report_path = _save(
        "reports",
        f"research_{topic[:40].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        f"# Research Brief: {topic}\n\n"
        f"**Summary:** {brief.get('summary', '')}\n\n"
        f"**Key Findings:**\n" + "\n".join(f"- {f}" for f in brief.get("key_findings", [])) + "\n\n"
        f"**Gotchas:**\n" + "\n".join(f"- {g}" for g in brief.get("gotchas", [])) + "\n\n"
        f"**Recommended Approach:** {brief.get('recommended_approach', '')}\n\n"
        f"**Sources:** {', '.join(brief.get('sources_consulted', []))}\n"
    )

    return {
        "summary": brief.get("summary", ""),
        "key_findings": brief.get("key_findings", []),
        "gotchas": brief.get("gotchas", []),
        "recommended_approach": brief.get("recommended_approach", ""),
        "sources_consulted": brief.get("sources_consulted", []),
        "report_path": report_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2 — API DESIGN AGENT
# Generates a complete OpenAPI 3.1 spec from natural language.
# Runs BEFORE the code generator so contracts are locked in first.
# ─────────────────────────────────────────────────────────────────────────────

def api_design_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate an OpenAPI 3.1 YAML spec + design rationale.

    Args:
        args: {description, style, version, auth_scheme}

    Returns:
        {spec_yaml, design_rationale, endpoints_summary, spec_path}
    """
    description  = args.get("description", "")
    style        = args.get("style", "rest")
    version      = args.get("version", "1.0.0")
    auth_scheme  = args.get("auth_scheme", "jwt")

    logger.info("[APIDesignAgent] Designing API: %s", description[:80])

    # Research best practices first
    computer = _computer("api_design_agent")
    research = computer.research_sync(
        f"{description} OpenAPI 3.1 REST API design best practices {auth_scheme} auth 2024",
        follow_links=1,
    )

    system = (
        "You are TIMPS API Design Agent. Generate a complete, production-quality "
        f"OpenAPI 3.1 spec in YAML for a {style.upper()} API. "
        f"Use {auth_scheme.upper()} authentication. "
        "Follow RESTful naming conventions, include all request/response schemas, "
        "error responses (400, 401, 403, 404, 422, 500), "
        "and security schemes. Output ONLY valid YAML — no markdown fences."
    )
    prompt = (
        f"API Description: {description}\n"
        f"API Version: {version}\n"
        f"Auth: {auth_scheme}\n\n"
        f"Best practices research:\n{research[:3000]}\n\n"
        "Generate the complete OpenAPI 3.1 YAML spec."
    )
    spec_yaml = _router().call("api_design_agent", prompt, system)

    # Strip accidental markdown fences
    spec_yaml = re.sub(r"^```[a-z]*\n", "", spec_yaml, flags=re.MULTILINE)
    spec_yaml = re.sub(r"\n```$", "", spec_yaml, flags=re.MULTILINE)

    # Rationale
    rationale_system = (
        "You are a senior API architect. Write a concise design rationale "
        "(max 400 words) for this API spec: explain the key design decisions, "
        "authentication choice, resource naming, and versioning strategy."
    )
    rationale_prompt = f"API: {description}\n\nSpec:\n{spec_yaml[:3000]}"
    rationale = _router().call("api_design_agent", rationale_prompt, rationale_system)

    # Extract endpoint summary from spec
    endpoints = re.findall(r"^  (/[^\n]+):", spec_yaml, re.MULTILINE)
    endpoints_summary = endpoints[:20]  # first 20 paths

    spec_path = _save("specs", f"openapi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml", spec_yaml)
    rationale_path = _save("reports", f"api_design_rationale_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                           f"# API Design Rationale\n\n{rationale}")

    return {
        "spec_yaml": spec_yaml[:2000] + ("\n… (truncated, full spec saved to file)" if len(spec_yaml) > 2000 else ""),
        "design_rationale": rationale,
        "endpoints_summary": endpoints_summary,
        "spec_path": spec_path,
        "rationale_path": rationale_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3 — DB AGENT
# Schema design, query optimisation, and migration scripts.
# Pairs with the sql_injection LoRA adapter for secure query generation.
# ─────────────────────────────────────────────────────────────────────────────

def db_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Design a database schema, generate DDL, ER diagram, indexes, and migration.

    Args:
        args: {description, db_engine, migration_tool, existing_schema}

    Returns:
        {ddl_sql, er_diagram_mermaid, indexes, migration_script,
         query_templates, schema_path}
    """
    description     = args.get("description", "")
    db_engine       = args.get("db_engine", "postgresql")
    migration_tool  = args.get("migration_tool", "alembic")
    existing_schema = args.get("existing_schema", "")

    logger.info("[DBAgent] Designing schema for: %s", description[:80])

    computer = _computer("db_agent")
    research = computer.research_sync(
        f"{db_engine} schema design {description} best practices normalization indexing",
        follow_links=1,
    )

    is_migration = bool(existing_schema)
    action = "migration from existing schema" if is_migration else "new schema design"

    system = (
        f"You are TIMPS DB Agent. Produce a complete {db_engine.upper()} {action}. "
        "Output a JSON object with keys:\n"
        "  ddl_sql: complete CREATE TABLE statements\n"
        "  er_diagram_mermaid: Mermaid ER diagram syntax\n"
        "  indexes: list of CREATE INDEX statements\n"
        f"  migration_script: {migration_tool} migration code\n"
        "  query_templates: dict of common query names → SQL\n"
        "  design_notes: list of key design decisions\n"
        "Output ONLY valid JSON."
    )

    existing_ctx = f"\nExisting schema to migrate from:\n{existing_schema[:2000]}" if existing_schema else ""
    prompt = (
        f"Data model description: {description}\n"
        f"Database: {db_engine}\n"
        f"Migration tool: {migration_tool}{existing_ctx}\n\n"
        f"Research context:\n{research[:2000]}\n\n"
        "Generate the complete schema design."
    )

    raw = _router().call("db_agent", prompt, system, format_json=True)

    try:
        result = json.loads(raw)
    except Exception:
        result = {
            "ddl_sql": raw[:2000],
            "er_diagram_mermaid": "",
            "indexes": [],
            "migration_script": "",
            "query_templates": {},
            "design_notes": [],
        }

    schema_path = _save(
        "specs",
        f"db_schema_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql",
        result.get("ddl_sql", ""),
    )
    migration_path = _save(
        "scripts",
        f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py",
        result.get("migration_script", ""),
    ) if result.get("migration_script") else ""

    return {
        "ddl_sql": result.get("ddl_sql", "")[:1500],
        "er_diagram_mermaid": result.get("er_diagram_mermaid", ""),
        "indexes": result.get("indexes", []),
        "migration_script": result.get("migration_script", "")[:800],
        "query_templates": result.get("query_templates", {}),
        "design_notes": result.get("design_notes", []),
        "schema_path": schema_path,
        "migration_path": migration_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4 — DEPENDENCY AGENT
# CVE scanning, license compliance, version pinning, upgrade scripts.
# Runs pip-audit / npm audit / cargo audit as real subprocesses.
# ─────────────────────────────────────────────────────────────────────────────

def dependency_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scan dependencies for CVEs and outdated packages.

    Args:
        args: {manifest, ecosystem, fix}

    Returns:
        {cve_report, license_issues, upgrade_script,
         critical_count, high_count, report_path}
    """
    manifest   = args.get("manifest", "")
    ecosystem  = args.get("ecosystem", "auto")
    fix        = bool(args.get("fix", True))

    logger.info("[DependencyAgent] Scanning dependencies (ecosystem=%s)", ecosystem)

    # Auto-detect ecosystem from manifest content
    if ecosystem == "auto":
        if "dependencies" in manifest and "{" in manifest:
            ecosystem = "node"
        elif "[package]" in manifest or "Cargo.toml" in manifest:
            ecosystem = "rust"
        elif "module " in manifest and "require (" in manifest:
            ecosystem = "go"
        else:
            ecosystem = "python"

    # Run real audit tools if available
    audit_output = ""
    if ecosystem == "python":
        # Write manifest to temp file and run pip-audit
        tmp = Path("/tmp/timps_requirements_check.txt")
        tmp.write_text(manifest)
        audit_output = _run(f"pip-audit -r {tmp} --format json 2>&1 || pip-audit -r {tmp} 2>&1")
        if not audit_output or "command not found" in audit_output:
            audit_output = _run(f"safety check -r {tmp} 2>&1 || echo 'pip-audit/safety not installed'")

    elif ecosystem == "node":
        tmp_dir = Path("/tmp/timps_npm_audit")
        tmp_dir.mkdir(exist_ok=True)
        (tmp_dir / "package.json").write_text(manifest)
        audit_output = _run("npm audit --json 2>&1", cwd=str(tmp_dir))

    elif ecosystem == "rust":
        audit_output = _run("cargo audit 2>&1 || echo 'cargo-audit not installed'")

    elif ecosystem == "go":
        audit_output = _run("govulncheck ./... 2>&1 || echo 'govulncheck not installed'")

    # Use LLM to parse audit output + manifest and produce structured report
    system = (
        "You are TIMPS Dependency Agent. Analyse dependency audit output and the manifest. "
        "Return a JSON object with keys:\n"
        "  cve_report: list of {package, version, cve_id, severity, description, fix_version}\n"
        "  license_issues: list of {package, license, issue}\n"
        "  upgrade_script: shell script with safe upgrade commands (pip install --upgrade / npm update etc)\n"
        "  critical_count: int\n"
        "  high_count: int\n"
        "  medium_count: int\n"
        "  summary: one-paragraph executive summary\n"
        "Output ONLY valid JSON."
    )

    manifest_preview = manifest[:3000]
    audit_preview = audit_output[:2000] if audit_output else "No audit tool output available."

    prompt = (
        f"Ecosystem: {ecosystem}\n\n"
        f"Manifest:\n{manifest_preview}\n\n"
        f"Audit tool output:\n{audit_preview}\n\n"
        "Analyse all dependencies and produce the security + license report."
    )

    raw = _router().call("dependency_agent", prompt, system, format_json=True)

    try:
        result = json.loads(raw)
    except Exception:
        result = {
            "cve_report": [],
            "license_issues": [],
            "upgrade_script": "",
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "summary": raw[:1000],
        }

    report_path = _save(
        "reports",
        f"dependency_audit_{ecosystem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        f"# Dependency Audit — {ecosystem}\n\n"
        f"**Critical:** {result.get('critical_count', 0)} | "
        f"**High:** {result.get('high_count', 0)} | "
        f"**Medium:** {result.get('medium_count', 0)}\n\n"
        f"## Summary\n{result.get('summary', '')}\n\n"
        f"## CVE Report\n" + json.dumps(result.get("cve_report", []), indent=2) + "\n\n"
        f"## License Issues\n" + json.dumps(result.get("license_issues", []), indent=2) + "\n\n"
        f"## Upgrade Script\n```bash\n{result.get('upgrade_script', '')}\n```\n"
    )

    script_path = ""
    if fix and result.get("upgrade_script"):
        script_path = _save(
            "scripts",
            f"dependency_upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sh",
            "#!/usr/bin/env bash\n# TIMPS Dependency Agent — Upgrade Script (review before running)\nset -e\n\n"
            + result["upgrade_script"],
        )

    return {
        "summary": result.get("summary", ""),
        "critical_count": result.get("critical_count", 0),
        "high_count": result.get("high_count", 0),
        "medium_count": result.get("medium_count", 0),
        "cve_report": result.get("cve_report", [])[:10],  # top 10
        "license_issues": result.get("license_issues", []),
        "upgrade_script": result.get("upgrade_script", "")[:800],
        "report_path": report_path,
        "script_path": script_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5 — n8n WORKFLOW AGENT
# Converts plain-English task descriptions into complete n8n workflow JSON.
# The unfair advantage: maps directly to the YouTube channel and Fiverr niche.
# ─────────────────────────────────────────────────────────────────────────────

# Known n8n node types — used to constrain the LLM
N8N_CORE_NODES = [
    "n8n-nodes-base.webhook", "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.cron", "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.emailTrigger", "n8n-nodes-base.gmailTrigger",
    "n8n-nodes-base.gmail", "n8n-nodes-base.slack",
    "n8n-nodes-base.github", "n8n-nodes-base.githubTrigger",
    "n8n-nodes-base.notion", "n8n-nodes-base.airtable",
    "n8n-nodes-base.googleSheets", "n8n-nodes-base.postgres",
    "n8n-nodes-base.mysql", "n8n-nodes-base.redis",
    "n8n-nodes-base.if", "n8n-nodes-base.switch",
    "n8n-nodes-base.merge", "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.set", "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem", "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.wait", "n8n-nodes-base.noOp",
    "n8n-nodes-base.respondToWebhook",
    "n8n-nodes-base.openAi", "n8n-nodes-base.telegram",
    "n8n-nodes-base.discord", "n8n-nodes-base.twitter",
    "n8n-nodes-base.jira", "n8n-nodes-base.linear",
    "n8n-nodes-base.trello", "n8n-nodes-base.asana",
    "n8n-nodes-base.dropbox", "n8n-nodes-base.googleDrive",
    "n8n-nodes-base.s3", "n8n-nodes-base.stripe",
    "n8n-nodes-base.sendGrid", "n8n-nodes-base.mailchimp",
]


def n8n_workflow_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a complete, importable n8n workflow JSON from plain English.

    Args:
        args: {description, trigger, integrations}

    Returns:
        {workflow_json, node_summary, import_instructions, workflow_path}
    """
    description  = args.get("description", "")
    trigger      = args.get("trigger", "auto")
    integrations = args.get("integrations") or []

    logger.info("[n8nWorkflowAgent] Building workflow: %s", description[:80])

    computer = _computer("n8n_workflow_agent")
    research = computer.research_sync(
        f"n8n workflow {description} {' '.join(integrations)} example JSON",
        follow_links=1,
    )

    integrations_hint = ", ".join(integrations) if integrations else "auto-detect from description"

    system = (
        "You are TIMPS n8n Workflow Agent. You are an expert in n8n workflow automation. "
        "Generate a complete, valid n8n workflow JSON that can be imported directly. "
        "\n\nn8n workflow JSON structure:\n"
        "{\n"
        '  "name": "Workflow Name",\n'
        '  "nodes": [ {nodeObjects} ],\n'
        '  "connections": { "NodeName": { "main": [[{node, type, index}]] } },\n'
        '  "active": false,\n'
        '  "settings": {},\n'
        '  "id": "workflow-1"\n'
        "}\n\n"
        f"Available node types: {', '.join(N8N_CORE_NODES[:20])}\n\n"
        "Each node must have: id, name, type, typeVersion, position [x,y], parameters.\n"
        "Output ONLY valid JSON — no markdown, no comments."
    )

    prompt = (
        f"Build an n8n workflow for:\n{description}\n\n"
        f"Trigger type: {trigger}\n"
        f"Integrations to use: {integrations_hint}\n\n"
        f"Reference examples from research:\n{research[:2000]}\n\n"
        "Generate the complete n8n workflow JSON with all nodes connected."
    )

    raw = _router().call("n8n_workflow_agent", prompt, system, format_json=True)

    # Strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\n```$", "", raw, flags=re.MULTILINE)

    try:
        workflow = json.loads(raw)
        workflow_json = json.dumps(workflow, indent=2)
    except Exception:
        workflow = {}
        workflow_json = raw

    # Build human-readable node summary
    nodes = workflow.get("nodes", [])
    node_summary = [
        {"name": n.get("name"), "type": n.get("type"), "position": n.get("position")}
        for n in nodes
    ]

    workflow_path = _save(
        "specs",
        f"n8n_workflow_{description[:30].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        workflow_json,
    )

    import_instructions = (
        "To import this workflow into n8n:\n"
        "1. Open n8n → Workflows → Import from File\n"
        f"2. Select: {workflow_path}\n"
        "3. Review and activate the workflow\n"
        "4. Configure credentials for each integration node"
    )

    return {
        "workflow_json": workflow_json[:3000] + ("\n… (truncated, full workflow saved to file)" if len(workflow_json) > 3000 else ""),
        "node_count": len(nodes),
        "node_summary": node_summary,
        "import_instructions": import_instructions,
        "workflow_path": workflow_path,
    }


# ── Agent dispatch map ────────────────────────────────────────────────────────

PRIORITY_AGENTS: Dict[str, Any] = {
    "research_agent":      research_agent,
    "api_design_agent":    api_design_agent,
    "db_agent":            db_agent,
    "dependency_agent":    dependency_agent,
    "n8n_workflow_agent":  n8n_workflow_agent,
}
