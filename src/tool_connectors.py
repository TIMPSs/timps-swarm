"""
Tool Connectors — Universal adapter layer for 22+ AI coding tools.

TIMPS Swarm works as a "backend brain" that any coding agent can call.
This module handles:
  1. Auto-detecting which tools are installed on the machine
  2. Generating the correct config file for each tool's MCP setup
  3. Providing per-tool special-case integration (Aider CLI, Goose extensions, etc.)
  4. A unified health check so you can see what's connected at a glance

Primary integration path: MCP (Model Context Protocol) over stdio.
All tools that support MCP get the same 40+ TIMPS tools automatically.

Special integrations per tool
──────────────────────────────
  Aider          → --mcp-config flag + .aider.conf.yml injection
  Goose          → Extension YAML in ~/.config/goose/config.yaml
  Gemini CLI     → ~/.gemini/settings.json mcpServers block
  OpenCode       → ~/.opencode/config.json mcpServers block
  Warp           → MCP via ~/.warp/mcp_servers.json
  Zed            → ~/.config/zed/settings.json lsp/mcp block
  Factory        → droids.yml integration spec
  Devin          → Team MCP server endpoint (cloud-hosted)
  Replit         → .replit secret + mcp_servers stanza
  v0/Vercel      → TIMPS as a Next.js API route wrapper
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HOME = Path.home()
TIMPS_MCP_CMD = "timps-mcp"   # installed by `pip install -e .`

# ─────────────────────────────────────────────────────────────────────────────
# Tool registry — one entry per supported tool
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: Dict[str, Dict[str, Any]] = {
    # ── CLI tools ─────────────────────────────────────────────────────────────
    "claude_code": {
        "display_name": "Claude Code",
        "vendor": "Anthropic",
        "type": "cli",
        "detect_cmd": "claude",
        "config_path": HOME / ".claude" / "mcp.json",
        "agents_path": HOME / ".claude" / "agents",
        "settings_path": HOME / ".claude" / "settings.json",
        "integration": "claude_code_agents",
        "docs_url": "https://docs.anthropic.com/claude/docs/claude-code",
        "icon": "🤖",
    },
    "codex_cli": {
        "display_name": "Codex CLI",
        "vendor": "OpenAI",
        "type": "cli",
        "detect_cmd": "codex",
        "config_path": HOME / ".codex" / "config.json",
        "integration": "codex_adapter",
        "docs_url": "https://github.com/openai/codex",
        "icon": "⚡",
    },
    "gemini_cli": {
        "display_name": "Gemini CLI",
        "vendor": "Google",
        "type": "cli",
        "detect_cmd": "gemini",
        "config_path": HOME / ".gemini" / "settings.json",
        "integration": "gemini_settings",
        "docs_url": "https://github.com/google-gemini/gemini-cli",
        "icon": "💎",
    },
    "opencode": {
        "display_name": "OpenCode",
        "vendor": "OpenCode",
        "type": "cli",
        "detect_cmd": "opencode",
        "config_path": HOME / ".config" / "opencode" / "config.json",
        "integration": "mcp_stdio",
        "docs_url": "https://github.com/opencodelabs/opencode",
        "icon": "🔓",
    },
    "aider": {
        "display_name": "Aider",
        "vendor": "Paul Gauthier",
        "type": "cli",
        "detect_cmd": "aider",
        "config_path": HOME / ".aider.conf.yml",
        "integration": "aider_config",
        "docs_url": "https://aider.chat/docs/config/mcp.html",
        "icon": "🎯",
    },
    "goose": {
        "display_name": "Goose",
        "vendor": "Block",
        "type": "cli",
        "detect_cmd": "goose",
        "config_path": HOME / ".config" / "goose" / "config.yaml",
        "integration": "goose_extension",
        "docs_url": "https://block.github.io/goose/docs/",
        "icon": "🦆",
    },
    "amp": {
        "display_name": "Amp",
        "vendor": "Sourcegraph",
        "type": "cli",
        "detect_cmd": "amp",
        "config_path": HOME / ".amp" / "mcp.json",
        "integration": "mcp_stdio",
        "docs_url": "https://ampcode.com/docs",
        "icon": "⚡",
    },
    "warp": {
        "display_name": "Warp",
        "vendor": "Warp",
        "type": "cli",
        "detect_cmd": "warp",
        "config_path": HOME / ".warp" / "mcp_servers.json",
        "integration": "warp_mcp",
        "docs_url": "https://docs.warp.dev/features/mcp",
        "icon": "🚀",
    },
    # ── IDE extensions ─────────────────────────────────────────────────────────
    "github_copilot": {
        "display_name": "GitHub Copilot",
        "vendor": "Microsoft / GitHub",
        "type": "ide_extension",
        "detect_paths": [
            HOME / ".vscode" / "extensions",
        ],
        "detect_pattern": "github.copilot",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://docs.github.com/en/copilot/using-github-copilot/mcp",
        "icon": "🐙",
    },
    "cline": {
        "display_name": "Cline",
        "vendor": "Cline",
        "type": "ide_extension",
        "detect_paths": [HOME / ".vscode" / "extensions"],
        "detect_pattern": "saoudrizwan.claude-dev",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://github.com/cline/cline",
        "icon": "🔌",
    },
    "continue": {
        "display_name": "Continue",
        "vendor": "Continue.dev",
        "type": "ide_extension",
        "detect_paths": [HOME / ".continue"],
        "detect_pattern": "config.json",
        "config_path": HOME / ".continue" / "config.json",
        "integration": "continue_mcp",
        "docs_url": "https://docs.continue.dev/customize/model-context-protocol",
        "icon": "▶️",
    },
    "kilo_code": {
        "display_name": "Kilo Code",
        "vendor": "Kilo Code",
        "type": "ide_extension",
        "detect_paths": [HOME / ".vscode" / "extensions"],
        "detect_pattern": "kilocode",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://kilocode.ai/docs",
        "icon": "🔢",
    },
    "roo_code": {
        "display_name": "Roo Code",
        "vendor": "Roo Code",
        "type": "ide_extension",
        "detect_paths": [HOME / ".vscode" / "extensions"],
        "detect_pattern": "roo-cline",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://github.com/RooVetGit/Roo-Cline",
        "icon": "🦘",
    },
    "augment_code": {
        "display_name": "Augment Code",
        "vendor": "Augment",
        "type": "ide_extension",
        "detect_paths": [HOME / ".vscode" / "extensions"],
        "detect_pattern": "augment",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://www.augmentcode.com/docs",
        "icon": "🔥",
    },
    # ── IDE applications ───────────────────────────────────────────────────────
    "cursor": {
        "display_name": "Cursor",
        "vendor": "Anysphere",
        "type": "ide_app",
        "detect_paths": [
            Path("/Applications/Cursor.app"),
            HOME / ".cursor",
        ],
        "config_path": HOME / ".cursor" / "mcp.json",
        "rules_dir": HOME / ".cursor" / "rules",
        "integration": "cursor_rules",
        "docs_url": "https://docs.cursor.com/advanced/model-context-protocol",
        "icon": "🖱️",
    },
    "windsurf": {
        "display_name": "Windsurf",
        "vendor": "Cognition",
        "type": "ide_app",
        "detect_paths": [
            Path("/Applications/Windsurf.app"),
            HOME / ".windsurf",
        ],
        "config_path": HOME / ".codeium" / "windsurf" / "mcp_config.json",
        "integration": "mcp_stdio",
        "docs_url": "https://docs.codeium.com/windsurf/mcp",
        "icon": "🏄",
    },
    "antigravity": {
        "display_name": "Antigravity",
        "vendor": "Google",
        "type": "ide_app",
        "detect_paths": [HOME / ".antigravity"],
        "config_path": HOME / ".antigravity" / "mcp.json",
        "integration": "mcp_stdio",
        "docs_url": "https://antigravity.google",
        "icon": "🚀",
    },
    "zed": {
        "display_name": "Zed",
        "vendor": "Zed Industries",
        "type": "ide_app",
        "detect_paths": [
            Path("/Applications/Zed.app"),
            HOME / ".config" / "zed",
        ],
        "config_path": HOME / ".config" / "zed" / "settings.json",
        "integration": "zed_settings",
        "docs_url": "https://zed.dev/docs/agent-panel#mcp",
        "icon": "⚡",
    },
    "kimi_code": {
        "display_name": "Kimi Code",
        "vendor": "Moonshot AI",
        "type": "ide_extension",
        "detect_paths": [HOME / ".vscode" / "extensions"],
        "detect_pattern": "kimi",
        "config_path": Path(".vscode") / "mcp.json",
        "integration": "vscode_mcp",
        "docs_url": "https://platform.moonshot.ai",
        "icon": "🌙",
    },
    # ── Cloud / SaaS ──────────────────────────────────────────────────────────
    "devin": {
        "display_name": "Devin",
        "vendor": "Cognition",
        "type": "cloud_saas",
        "detect_cmd": None,
        "config_path": None,
        "integration": "devin_mcp_endpoint",
        "docs_url": "https://docs.cognition.ai/docs/mcp",
        "icon": "🤖",
    },
    "factory": {
        "display_name": "Factory",
        "vendor": "Factory AI",
        "type": "cloud_saas",
        "detect_cmd": "factory",
        "config_path": Path(".factory") / "droids.yml",
        "integration": "factory_droids",
        "docs_url": "https://docs.factory.ai",
        "icon": "🏭",
    },
    "replit": {
        "display_name": "Replit Agent",
        "vendor": "Replit",
        "type": "cloud_saas",
        "detect_cmd": None,
        "config_path": Path(".replit"),
        "integration": "replit_mcp",
        "docs_url": "https://docs.replit.com/ai/agent",
        "icon": "📝",
    },
    "jules": {
        "display_name": "Jules",
        "vendor": "Google Labs",
        "type": "cloud_saas",
        "detect_cmd": None,
        "config_path": None,
        "integration": "github_app_webhook",
        "docs_url": "https://labs.google/jules",
        "icon": "🔭",
    },
    "v0": {
        "display_name": "v0",
        "vendor": "Vercel",
        "type": "cloud_saas",
        "detect_cmd": None,
        "config_path": None,
        "integration": "vercel_api_route",
        "docs_url": "https://v0.dev/docs",
        "icon": "▲",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cmd_exists(name: Optional[str]) -> bool:
    if not name:
        return False
    return shutil.which(name) is not None


def _path_exists(paths: List[Path], pattern: Optional[str] = None) -> bool:
    for p in paths:
        if p.exists():
            if pattern is None:
                return True
            # Check if any child matches the pattern
            if p.is_dir():
                matches = list(p.glob(f"*{pattern}*"))
                if matches:
                    return True
            elif pattern.lower() in p.name.lower():
                return True
    return False


def detect_installed_tools() -> Dict[str, bool]:
    """
    Returns a dict of {tool_id: is_installed} for all known tools.
    Fast — no network calls, just filesystem and PATH checks.
    """
    results: Dict[str, bool] = {}
    for tool_id, meta in TOOLS.items():
        if meta.get("detect_cmd"):
            results[tool_id] = _cmd_exists(meta["detect_cmd"])
        elif meta.get("detect_paths"):
            results[tool_id] = _path_exists(
                meta["detect_paths"], meta.get("detect_pattern")
            )
        else:
            # Cloud SaaS — can't detect locally, mark as unknown
            results[tool_id] = False
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Config generators — one per integration type
# ─────────────────────────────────────────────────────────────────────────────

def _mcp_server_block() -> Dict[str, Any]:
    """Standard MCP server JSON block for timps-swarm."""
    return {
        "timps-swarm": {
            "type": "stdio",
            "command": TIMPS_MCP_CMD,
            "description": "TIMPS Swarm — 44 specialist agents for dev and productivity tasks",
        }
    }


def _write_json_merge(config_path: Path, key: str, value: Any) -> None:
    """Merge a key into an existing JSON file, creating it if needed."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass
    existing[key] = value
    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote config: %s", config_path)


def _generate_mcp_stdio(config_path: Path) -> None:
    """Generic MCP stdio config (Claude Code, Codex, Cursor, Windsurf, etc.)"""
    _write_json_merge(config_path, "mcpServers", _mcp_server_block())


def _generate_vscode_mcp(config_path: Path) -> None:
    """VS Code / Cline / Continue / Kilo Code workspace .vscode/mcp.json"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass
    existing.setdefault("mcp", {}).setdefault("servers", {}).update(
        _mcp_server_block()
    )
    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote VS Code MCP config: %s", config_path)


def _generate_aider_config(config_path: Path) -> None:
    """Aider uses YAML config with an mcp-servers key."""
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed — writing raw YAML for Aider config")
        yaml = None  # type: ignore

    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            if yaml:
                existing = yaml.safe_load(config_path.read_text()) or {}
            else:
                existing = {}
        except Exception:
            pass

    existing.setdefault("mcp-servers", {})["timps-swarm"] = {
        "command": TIMPS_MCP_CMD,
        "type": "stdio",
    }

    content = (
        yaml.dump(existing, default_flow_style=False)
        if yaml
        else json.dumps(existing, indent=2)
    )
    config_path.write_text(content)
    logger.info("Wrote Aider config: %s", config_path)


def _generate_goose_extension(config_path: Path) -> None:
    """Goose uses an extensions list in config.yaml."""
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not available — skipping Goose config")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = yaml.safe_load(config_path.read_text()) or {}
        except Exception:
            pass

    extensions: List[Dict] = existing.setdefault("extensions", [])
    # Avoid duplicates
    if not any(e.get("name") == "timps-swarm" for e in extensions):
        extensions.append({
            "name": "timps-swarm",
            "type": "stdio",
            "cmd": TIMPS_MCP_CMD,
            "description": "TIMPS Swarm specialist agents",
            "enabled": True,
        })

    config_path.write_text(yaml.dump(existing, default_flow_style=False))
    logger.info("Wrote Goose config: %s", config_path)


def _generate_gemini_settings(config_path: Path) -> None:
    """Gemini CLI uses ~/.gemini/settings.json with an mcpServers block."""
    _write_json_merge(config_path, "mcpServers", _mcp_server_block())


def _generate_continue_mcp(config_path: Path) -> None:
    """Continue.dev uses ~/.continue/config.json with a mcpServers array."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass

    servers: List[Dict] = existing.setdefault("mcpServers", [])
    if not any(s.get("name") == "timps-swarm" for s in servers):
        servers.append({
            "name": "timps-swarm",
            "command": TIMPS_MCP_CMD,
            "args": [],
        })
    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote Continue config: %s", config_path)


def _generate_zed_settings(config_path: Path) -> None:
    """Zed uses ~/.config/zed/settings.json with an assistant.tools.mcp block."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass

    (existing
     .setdefault("assistant", {})
     .setdefault("mcp_servers", {})
     )["timps-swarm"] = {"command": TIMPS_MCP_CMD}

    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote Zed config: %s", config_path)


def _generate_warp_mcp(config_path: Path) -> None:
    """Warp terminal MCP servers list."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass

    existing.setdefault("servers", {})["timps-swarm"] = {
        "command": TIMPS_MCP_CMD,
        "type": "stdio",
    }
    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote Warp MCP config: %s", config_path)


def _generate_factory_droids(config_path: Path) -> None:
    """Factory droids.yml — registers TIMPS as an MCP tool provider."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# TIMPS Swarm — injected by tool_connectors.py\n"
        "tools:\n"
        "  - name: timps-swarm\n"
        f"    command: {TIMPS_MCP_CMD}\n"
        "    type: mcp_stdio\n"
        "    description: |\n"
        "      44-agent swarm for SDLC, computer health, developer, and productivity tasks.\n"
    )
    if config_path.exists():
        existing = config_path.read_text()
        if "timps-swarm" not in existing:
            config_path.write_text(existing + "\n" + content)
    else:
        config_path.write_text(content)
    logger.info("Wrote Factory droids config: %s", config_path)


def _generate_replit_mcp(config_path: Path) -> None:
    """Replit .replit file — adds timps-mcp to run config."""
    block = '\n[mcp]\nservers = ["timps-mcp"]\n'
    if config_path.exists():
        existing = config_path.read_text()
        if "timps-mcp" not in existing:
            config_path.write_text(existing + block)
    else:
        config_path.write_text(block)
    logger.info("Wrote Replit config: %s", config_path)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Universal Coding Agent Adapters
# ─────────────────────────────────────────────────────────────────────────────

_CLAUDE_CODE_AGENTS = [
    ("timps-sdlc-pipeline", "TIMPS SDLC Pipeline",
     "Full software development lifecycle: product management, architecture, code generation, review, QA, security, performance, devops, and documentation.",
     ["timps_run_task"],
     "For bulk code operations across many files, use `timps_batch` with agent_type='code_generator'."),
    ("timps-code-reviewer", "TIMPS Code Reviewer",
     "Review pull request diffs for blockers, suggestions, and nitpicks. Returns a structured review with a 0-10 score.",
     ["timps_pr_reviewer"],
     "For reviewing every file in a directory in one shot, use `timps_batch` with agent_type='pr_reviewer'."),
    ("timps-unit-test-writer", "TIMPS Unit Test Writer",
     "Analyse source code and generate comprehensive test suites with happy paths, edge cases, and error conditions.",
     ["timps_unit_test_writer"],
     "For adding tests to every module in a project, use `timps_batch` with agent_type='unit_test_writer'."),
    ("timps-docstring-generator", "TIMPS Docstring Generator",
     "Insert production-quality docstrings in Google, Sphinx, NumPy, JSDoc, or Doxygen format without changing logic.",
     ["timps_docstring_generator"],
     "For documenting every function across a codebase, use `timps_batch` with agent_type='docstring_generator'."),
    ("timps-api-designer", "TIMPS API Designer",
     "Generate complete OpenAPI 3.1 specs from natural-language descriptions with REST/GraphQL best practices.",
     ["timps_api_design_agent"], None),
    ("timps-db-architect", "TIMPS DB Architect",
     "Schema design, query optimisation, migration scripts, ER diagrams, and index recommendations.",
     ["timps_db_agent"], None),
    ("timps-dependency-auditor", "TIMPS Dependency Auditor",
     "Scan manifests for CVEs, license compliance, version pinning strategy, and safe upgrade scripts.",
     ["timps_dependency_agent", "timps_dependency_sentinel", "timps_dependency_rebel"],
     "For scanning all manifests in a monorepo, use `timps_batch` with agent_type='dependency_agent'."),
    ("timps-system-doctor", "TIMPS System Doctor",
     "Diagnose slow computers, broken dev environments, network issues, battery drain, security vulnerabilities, and privacy risks.",
     ["timps_system_optimizer", "timps_environment_doctor", "timps_network_medic",
      "timps_battery_analyst", "timps_security_guard", "timps_log_interpreter"],
     "Run `timps_full_checkup` for a comprehensive 6-agent health scan."),
    ("timps-research-assistant", "TIMPS Research Assistant",
     "Deep-dive research on any topic with multi-source synthesis, trend monitoring, and competitive analysis.",
     ["timps_research_scout", "timps_trend_monitor", "timps_competitor_tracker"], None),
    ("timps-security-auditor", "TIMPS Security Auditor",
     "Comprehensive security scanning: OWASP API Top 10, container CVEs, prompt injection, secrets detection, and compliance mapping.",
     ["timps_api_security_tester", "timps_container_image_scanner", "timps_prompt_injection_scanner",
      "timps_secrets_management", "timps_compliance_auditor"], None),
    ("timps-infra-engineer", "TIMPS Infra Engineer",
     "Kubernetes diagnostics, Docker Compose, Terraform plan review, IaC drift detection, and disaster recovery planning.",
     ["timps_kubernetes_navigator", "timps_docker_compose_architect", "timps_terraform_plan_reviewer",
      "timps_disaster_recovery"], None),
]


def _generate_claude_code_agents(config_path: Path) -> None:
    """Write Claude Code sub-agent .md files and merge MCP into settings.json."""
    # Phase 1: write .md agent files
    agents_dir = config_path.parent / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for slug, name, purpose, tools, routing_hint in _CLAUDE_CODE_AGENTS:
        lines = [
            f"# {name}",
            "",
            purpose,
            "",
            "## MCP Tools",
            "",
        ]
        for t in tools:
            lines.append(f"- `{t}`")
        if routing_hint:
            lines.extend(["", "## Routing Hint", "", routing_hint])
        lines.extend([
            "",
            "---",
            "_Managed by TIMPS Swarm tool_connectors. Remove this file and re-run connect to unregister._",
            "",
        ])
        agent_file = agents_dir / f"{slug}.md"
        agent_file.write_text("\n".join(lines))
        logger.info("Wrote Claude Code agent: %s", agent_file)

    # Phase 2: merge MCP server into settings.json
    settings_path = config_path.parent / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except Exception:
            pass
    existing.setdefault("mcpServers", {})["timps-swarm"] = {
        "command": TIMPS_MCP_CMD,
        "env": {"OLLAMA_HOST": "http://localhost:11434"},
    }
    settings_path.write_text(json.dumps(existing, indent=2))
    logger.info("Merged Claude Code settings: %s", settings_path)


def _generate_cursor_rules(config_path: Path) -> None:
    """Write .cursorrules and .cursor/rules/*.mdc files for Cursor."""
    cursor_dir = config_path.parent
    rules_dir = cursor_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    # .cursorrules (user-level)
    rules_content = """# TIMPS Swarm — AI Agent Toolkit
# Managed by TIMPS Swarm tool_connectors
#
# Cursor can call any timps_* tool directly. Categories:

## SDLC Pipeline
- `timps_run_task` — Full 10-agent SDLC pipeline
- `timps_pr_reviewer` — Structured PR review with 0-10 score
- `timps_unit_test_writer` — Generate test suites
- `timps_docstring_generator` — Insert docstrings
- `timps_refactoring_agent` — Detect code smells and refactor

## API & Database
- `timps_api_design_agent` — Generate OpenAPI 3.1 specs
- `timps_db_agent` — Schema design, migrations, ER diagrams
- `timps_sql_optimizer` — Analyse slow queries

## Code Quality & Security
- `timps_dependency_agent` — CVE scan, license check, upgrade script
- `timps_security_guard` — Open ports, permissions scan
- `timps_api_security_tester` — OWASP API Top-10 audit

## Computer Health
- `timps_system_optimizer` — Diagnose slow laptop
- `timps_environment_doctor` — Fix broken dev environments
- `timps_network_medic` — Diagnose WiFi drops, DNS failures
- `timps_full_checkup` — Run all health agents

## Infrastructure
- `timps_kubernetes_navigator` — Diagnose K8s workloads
- `timps_docker_compose_architect` — Production compose files
- `timps_terraform_plan_reviewer` — Review terraform plans

## Bulk Operations
- `timps_batch` — Decompose a bulk task into parallel sub-tasks
"""
    rules_path = cursor_dir / ".cursorrules"
    rules_path.write_text(rules_content)
    logger.info("Wrote .cursorrules: %s", rules_path)

    # .mdc rule files
    mdc_templates = {
        "timps-sdlc.mdc": (
            "---\ndescription: TIMPS SDLC Pipeline\nglobs: **/*.{py,js,ts,jsx,tsx,go,java,rs}\n---\n"
            "When writing code, use these TIMPS tools:\n"
            "- `timps_run_task` — Full SDLC pipeline\n"
            "- `timps_unit_test_writer` — Generate test suites\n"
            "- `timps_docstring_generator` — Add docstrings\n"
            "- `timps_pr_reviewer` — Review code changes\n"
            "- `timps_refactoring_agent` — Refactor code\n"
        ),
        "timps-security.mdc": (
            "---\ndescription: TIMPS Security Agents\nglobs: **/*\n---\n"
            "Security checks available via TIMPS:\n"
            "- `timps_dependency_agent` — CVE scan manifests\n"
            "- `timps_api_security_tester` — OWASP API Top-10 audit\n"
            "- `timps_security_guard` — Local security scan\n"
            "- `timps_secrets_management` — Detect hardcoded secrets\n"
            "- `timps_compliance_auditor` — SOC 2 / ISO 27001 / HIPAA / PCI-DSS / GDPR\n"
        ),
        "timps-infra.mdc": (
            "---\ndescription: TIMPS Infrastructure & DevOps Agents\nglobs: **/*.{yml,yaml,tf,tfvars,dockerfile,json,toml}\n---\n"
            "Infrastructure tasks via TIMPS:\n"
            "- `timps_kubernetes_navigator` — Diagnose K8s workloads\n"
            "- `timps_docker_compose_architect` — Create compose files\n"
            "- `timps_terraform_plan_reviewer` — Review terraform plans\n"
            "- `timps_iac_drift_detector` — Detect IaC drift\n"
            "- `timps_disaster_recovery` — Design DR plans\n"
        ),
        "timps-database.mdc": (
            "---\ndescription: TIMPS Database & Query Agents\nglobs: **/*.{sql,py,js,ts}\n---\n"
            "Database tasks via TIMPS:\n"
            "- `timps_db_agent` — Schema design, migrations, ER diagrams\n"
            "- `timps_sql_optimizer` — Analyse slow queries\n"
            "- `timps_db_migration_pilot` — Zero-downtime migration planning\n"
        ),
    }
    for filename, content in mdc_templates.items():
        mdc_path = rules_dir / filename
        mdc_path.write_text(content)
        logger.info("Wrote .mdc rule: %s", mdc_path)


def _generate_codex_adapter(config_path: Path) -> None:
    """Generate ~/.codex/config.json with TIMPS MCP server and sub-agent descriptions."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text())
        except Exception:
            pass

    existing.setdefault("mcpServers", {})["timps-swarm"] = {
        "command": TIMPS_MCP_CMD,
        "type": "stdio",
        "description": "TIMPS Swarm — 160+ specialist agents",
        "env": {
            "TIMPS_API_URL": "http://localhost:8000",
            "OLLAMA_HOST": "http://localhost:11434",
        },
    }

    existing.setdefault("agents", {})
    for slug, name, _purpose, tools, _hint in _CLAUDE_CODE_AGENTS:
        existing["agents"][slug] = {
            "description": name,
            "tools": tools,
        }

    config_path.write_text(json.dumps(existing, indent=2))
    logger.info("Wrote Codex config: %s", config_path)


# ─────────────────────────────────────────────────────────────────────────────
# Integration-type dispatch table
# ─────────────────────────────────────────────────────────────────────────────

_GENERATORS = {
    "mcp_stdio":            _generate_mcp_stdio,
    "vscode_mcp":           _generate_vscode_mcp,
    "aider_config":         _generate_aider_config,
    "goose_extension":      _generate_goose_extension,
    "gemini_settings":      _generate_gemini_settings,
    "continue_mcp":         _generate_continue_mcp,
    "zed_settings":         _generate_zed_settings,
    "warp_mcp":             _generate_warp_mcp,
    "factory_droids":       _generate_factory_droids,
    "replit_mcp":           _generate_replit_mcp,
    # Phase 3 — Universal Coding Agent Adapters
    "claude_code_agents":   _generate_claude_code_agents,
    "cursor_rules":         _generate_cursor_rules,
    "codex_adapter":        _generate_codex_adapter,
    # Cloud SaaS — can't auto-configure, just skip
    "devin_mcp_endpoint":   None,
    "github_app_webhook":   None,
    "vercel_api_route":     None,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def connect_tool(tool_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Configure a single tool to connect to the TIMPS Swarm MCP server.

    Returns:
        {status: 'ok'|'skipped'|'error', config_path, message}
    """
    meta = TOOLS.get(tool_id)
    if not meta:
        return {"status": "error", "message": f"Unknown tool: {tool_id}"}

    integration = meta.get("integration")
    config_path = meta.get("config_path")
    generator = _GENERATORS.get(integration)

    if generator is None:
        return {
            "status": "skipped",
            "tool": meta["display_name"],
            "message": f"Manual setup required — see {meta.get('docs_url', 'docs')}",
        }

    if config_path is None:
        return {"status": "skipped", "tool": meta["display_name"],
                "message": "No local config path for this tool type"}

    if dry_run:
        return {
            "status": "dry_run",
            "tool": meta["display_name"],
            "would_write": str(config_path),
            "integration": integration,
        }

    try:
        generator(Path(config_path))
        return {
            "status": "ok",
            "tool": meta["display_name"],
            "config_path": str(config_path),
            "message": f"timps-swarm MCP server added to {meta['display_name']}",
        }
    except Exception as exc:
        logger.error("[Connector] Failed to configure %s: %s", tool_id, exc)
        return {"status": "error", "tool": meta["display_name"], "message": str(exc)}


def connect_all(dry_run: bool = False, installed_only: bool = True) -> List[Dict[str, Any]]:
    """
    Configure every detected tool to connect to TIMPS Swarm.

    Args:
        dry_run: preview only — don't write any files
        installed_only: skip tools that aren't detected on this machine

    Returns:
        list of result dicts from connect_tool()
    """
    detected = detect_installed_tools()
    results = []

    for tool_id in TOOLS:
        if installed_only and not detected.get(tool_id, False):
            continue
        result = connect_tool(tool_id, dry_run=dry_run)
        results.append(result)

    return results


def generate_all_configs(base_dir: Optional[str] = None) -> Dict[str, List[str]]:
    """
    Generate all MCP configuration files for every supported tool at once.

    This is the Phase 3 universal config generator. It writes:
      - MCP server configs for 22+ tools (Claude, Cursor, VS Code, etc.)
      - Claude Code sub-agent .md files with routing hints
      - Cursor .cursorrules + .mdc rule files
      - Codex CLI config with sub-agent descriptions

    Args:
        base_dir: Optional project root. If set, writes repo-local .vscode/mcp.json
                  and .cursor/ rules into the project directory.

    Returns:
        {tool_id: [list of written file paths]}
    """
    results: Dict[str, List[str]] = {}

    for tool_id, meta in TOOLS.items():
        integration = meta.get("integration")
        config_path = meta.get("config_path")
        generator = _GENERATORS.get(integration)

        if generator is None:
            continue

        try:
            if base_dir and tool_id in ("cursor", "vscode_mcp"):
                # Write into project directory
                project_path = Path(base_dir) / meta.get("config_path", "")
                generator(project_path)
                results.setdefault(tool_id, []).append(str(project_path))
            elif config_path:
                generator(Path(config_path))
                results.setdefault(tool_id, []).append(str(config_path))
            else:
                logger.warning("No config path for %s, skipping", tool_id)
        except Exception as exc:
            logger.error("Failed to generate config for %s: %s", tool_id, exc)

    return results


def status_report() -> Dict[str, Any]:
    """
    Return a health report of all tools: detected, configured, and disconnected.
    """
    detected = detect_installed_tools()
    report: Dict[str, Any] = {
        "connected": [],
        "detected_not_configured": [],
        "not_installed": [],
        "cloud_tools": [],
    }

    for tool_id, meta in TOOLS.items():
        tool_type = meta.get("type", "")
        is_installed = detected.get(tool_id, False)
        config_path = meta.get("config_path")

        if tool_type == "cloud_saas":
            report["cloud_tools"].append({
                "id": tool_id,
                "name": meta["display_name"],
                "docs": meta.get("docs_url", ""),
                "setup": "manual — see docs",
            })
            continue

        is_configured = False
        if config_path and Path(config_path).exists():
            try:
                content = Path(config_path).read_text()
                is_configured = "timps-swarm" in content or "timps-mcp" in content
            except Exception:
                pass

        entry = {
            "id": tool_id,
            "name": meta["display_name"],
            "icon": meta.get("icon", ""),
            "config_path": str(config_path) if config_path else None,
        }

        if is_installed and is_configured:
            report["connected"].append(entry)
        elif is_installed:
            report["detected_not_configured"].append(entry)
        else:
            report["not_installed"].append(entry)

    return report


def print_status() -> None:
    """Pretty-print the connection status to stdout."""
    report = status_report()

    print("\n╔══════════════════════════════════════════╗")
    print("║         TIMPS Swarm — Tool Status         ║")
    print("╚══════════════════════════════════════════╝\n")

    if report["connected"]:
        print(f"✅  Connected ({len(report['connected'])})")
        for t in report["connected"]:
            print(f"    {t['icon']}  {t['name']}")

    if report["detected_not_configured"]:
        print(f"\n⚠️   Detected but not configured ({len(report['detected_not_configured'])})")
        for t in report["detected_not_configured"]:
            print(f"    {t['icon']}  {t['name']}  →  run: timps connect {t['id']}")

    if report["cloud_tools"]:
        print(f"\n☁️   Cloud tools (manual setup) ({len(report['cloud_tools'])})")
        for t in report["cloud_tools"]:
            print(f"    {t['name']}  →  {t['docs']}")

    not_installed_count = len(report["not_installed"])
    if not_installed_count:
        print(f"\n○  Not installed: {not_installed_count} tools")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]

    if not args or args[0] == "status":
        print_status()

    elif args[0] == "connect":
        tool_id = args[1] if len(args) > 1 else None
        dry = "--dry-run" in args

        if tool_id and tool_id != "all":
            result = connect_tool(tool_id, dry_run=dry)
            print(json.dumps(result, indent=2))
        else:
            results = connect_all(dry_run=dry, installed_only=False)
            for r in results:
                status_icon = {"ok": "✅", "skipped": "⏭️", "error": "❌", "dry_run": "👀"}.get(
                    r.get("status", ""), "?"
                )
                print(f"{status_icon}  {r.get('tool', r.get('id', '?'))}: {r.get('message', '')}")

    elif args[0] == "list":
        detected = detect_installed_tools()
        for tool_id, meta in TOOLS.items():
            installed = "✅" if detected.get(tool_id) else "○ "
            print(f"  {installed}  {meta['display_name']:25s}  ({meta['vendor']})")

    else:
        print("Usage: python -m src.tool_connectors [status|connect [tool_id|all]|list]")
        print("       Add --dry-run to preview without writing files")
