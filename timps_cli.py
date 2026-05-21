#!/usr/bin/env python3
"""
timps — TIMPS Swarm universal CLI

Commands
────────
  timps connect [tool|all]   Auto-configure one or all AI coding agents
  timps status               Show which agents are connected
  timps config <tool>        Print ready-to-paste MCP config snippet
  timps list                 List every tool TIMPS supports
  timps info                 Show server path, LLM backend, installed models
  timps run <tool> <task>    Run any TIMPS agent directly from the terminal

Examples
────────
  timps connect all
  timps connect cursor
  timps config claude_code
  timps run issue_triager "Login page 500 error for 10% of users"
  timps status
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── colour helpers (no deps) ─────────────────────────────────────────────────
_NO_COLOR = not sys.stdout.isatty() or os.getenv("NO_COLOR")

def _c(text: str, code: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")
def cyan(t):   return _c(t, "36")


# ── inline config snippets (no imports needed) ───────────────────────────────

def _timps_mcp_bin() -> str:
    """Return the absolute path to timps-mcp binary."""
    found = shutil.which("timps-mcp")
    if found:
        return found
    # fall back to same Python env
    py = sys.executable
    bin_dir = Path(py).parent
    for name in ["timps-mcp", "timps-mcp.exe"]:
        p = bin_dir / name
        if p.exists():
            return str(p)
    return "timps-mcp"


TIMPS_BIN = _timps_mcp_bin()

# Config snippet templates for each tool, keyed by integration type
_SNIPPETS: Dict[str, str] = {
    # ── Standard mcpServers JSON (Claude Code, Cursor, Windsurf, Codex, Amp) ──
    "mcp_stdio": """\
{{
  "mcpServers": {{
    "timps-swarm": {{
      "type": "stdio",
      "command": "{bin}"
    }}
  }}
}}""",

    # ── VS Code workspace .vscode/mcp.json (Cline, Roo Code, Kilo Code, Copilot, Augment) ──
    "vscode_mcp": """\
// .vscode/mcp.json  (place in your project root)
{{
  "mcp": {{
    "servers": {{
      "timps-swarm": {{
        "type": "stdio",
        "command": "{bin}"
      }}
    }}
  }}
}}""",

    # ── Continue.dev ~/.continue/config.json ─────────────────────────────────
    "continue_mcp": """\
// Add inside ~/.continue/config.json → "mcpServers" array
{{
  "name": "timps-swarm",
  "command": "{bin}",
  "args": []
}}""",

    # ── Aider ~/.aider.conf.yml ───────────────────────────────────────────────
    "aider_config": """\
# ~/.aider.conf.yml
mcp-servers:
  timps-swarm:
    command: {bin}
    type: stdio""",

    # ── Goose ~/.config/goose/config.yaml ────────────────────────────────────
    "goose_extension": """\
# ~/.config/goose/config.yaml  (add to extensions list)
extensions:
  - name: timps-swarm
    type: stdio
    cmd: {bin}
    description: "TIMPS Swarm — 51 specialist AI agents"
    enabled: true""",

    # ── Gemini CLI ~/.gemini/settings.json ───────────────────────────────────
    "gemini_settings": """\
{{
  "mcpServers": {{
    "timps-swarm": {{
      "type": "stdio",
      "command": "{bin}"
    }}
  }}
}}""",

    # ── Zed ~/.config/zed/settings.json ──────────────────────────────────────
    "zed_settings": """\
// ~/.config/zed/settings.json  (merge into existing file)
{{
  "assistant": {{
    "mcp_servers": {{
      "timps-swarm": {{
        "command": "{bin}"
      }}
    }}
  }}
}}""",

    # ── Warp ~/.warp/mcp_servers.json ────────────────────────────────────────
    "warp_mcp": """\
{{
  "servers": {{
    "timps-swarm": {{
      "command": "{bin}",
      "type": "stdio"
    }}
  }}
}}""",

    # ── OpenCode ~/.config/opencode/opencode.json ─────────────────────────────
    "opencode_config": """\
{{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {{
    "timps-swarm": {{
      "type": "local",
      "command": ["{bin}"],
      "enabled": true
    }}
  }}
}}""",

    # ── Factory .factory/droids.yml ───────────────────────────────────────────
    "factory_droids": """\
# .factory/droids.yml
tools:
  - name: timps-swarm
    command: {bin}
    type: mcp_stdio
    description: "44-agent swarm for SDLC, computer health, and productivity" """,

    # ── Replit .replit ────────────────────────────────────────────────────────
    "replit_mcp": """\
# .replit
[mcp]
servers = ["timps-mcp"]""",

    # ── Generic fallback ──────────────────────────────────────────────────────
    "_generic": """\
# Generic MCP stdio config — adapt to your tool's config format
{{
  "mcpServers": {{
    "timps-swarm": {{
      "type": "stdio",
      "command": "{bin}"
    }}
  }}
}}""",
}

# Map tool_id → integration type (mirrors tool_connectors.TOOLS)
_TOOL_INTEGRATION: Dict[str, str] = {
    "claude_code":    "mcp_stdio",
    "codex_cli":      "mcp_stdio",
    "gemini_cli":     "gemini_settings",
    "opencode":       "opencode_config",
    "aider":          "aider_config",
    "goose":          "goose_extension",
    "amp":            "mcp_stdio",
    "warp":           "warp_mcp",
    "github_copilot": "vscode_mcp",
    "cline":          "vscode_mcp",
    "continue":       "continue_mcp",
    "kilo_code":      "vscode_mcp",
    "roo_code":       "vscode_mcp",
    "augment_code":   "vscode_mcp",
    "cursor":         "mcp_stdio",
    "windsurf":       "mcp_stdio",
    "antigravity":    "mcp_stdio",
    "zed":            "zed_settings",
    "kimi_code":      "vscode_mcp",
    "devin":          "devin_mcp_endpoint",
    "factory":        "factory_droids",
    "replit":         "replit_mcp",
    "jules":          "github_app_webhook",
    "v0":             "vercel_api_route",
}

_TOOL_INFO: Dict[str, Dict[str, str]] = {
    "claude_code":    {"name": "Claude Code",      "icon": "🤖", "vendor": "Anthropic"},
    "codex_cli":      {"name": "Codex CLI",         "icon": "⚡", "vendor": "OpenAI"},
    "gemini_cli":     {"name": "Gemini CLI",         "icon": "💎", "vendor": "Google"},
    "opencode":       {"name": "OpenCode",           "icon": "🔓", "vendor": "OpenCode"},
    "aider":          {"name": "Aider",              "icon": "🎯", "vendor": "Paul Gauthier"},
    "goose":          {"name": "Goose",              "icon": "🦆", "vendor": "Block"},
    "amp":            {"name": "Amp",                "icon": "⚡", "vendor": "Sourcegraph"},
    "warp":           {"name": "Warp",               "icon": "🚀", "vendor": "Warp"},
    "github_copilot": {"name": "GitHub Copilot",     "icon": "🐙", "vendor": "GitHub"},
    "cline":          {"name": "Cline",              "icon": "🔌", "vendor": "Cline"},
    "continue":       {"name": "Continue",           "icon": "▶️",  "vendor": "Continue.dev"},
    "kilo_code":      {"name": "Kilo Code",          "icon": "🔢", "vendor": "Kilo Code"},
    "roo_code":       {"name": "Roo Code",           "icon": "🦘", "vendor": "Roo Code"},
    "augment_code":   {"name": "Augment Code",       "icon": "🔥", "vendor": "Augment"},
    "cursor":         {"name": "Cursor",             "icon": "🖱️", "vendor": "Anysphere"},
    "windsurf":       {"name": "Windsurf",           "icon": "🏄", "vendor": "Cognition"},
    "antigravity":    {"name": "Antigravity",        "icon": "🚀", "vendor": "Google"},
    "zed":            {"name": "Zed",                "icon": "⚡", "vendor": "Zed Industries"},
    "kimi_code":      {"name": "Kimi Code",          "icon": "🌙", "vendor": "Moonshot AI"},
    "devin":          {"name": "Devin",              "icon": "🤖", "vendor": "Cognition"},
    "factory":        {"name": "Factory",            "icon": "🏭", "vendor": "Factory AI"},
    "replit":         {"name": "Replit Agent",       "icon": "📝", "vendor": "Replit"},
    "jules":          {"name": "Jules",              "icon": "🔭", "vendor": "Google Labs"},
    "v0":             {"name": "v0",                 "icon": "▲",  "vendor": "Vercel"},
}

_MANUAL_SETUP = {"devin_mcp_endpoint", "github_app_webhook", "vercel_api_route"}


# ── subcommand: connect ───────────────────────────────────────────────────────

def cmd_connect(args: argparse.Namespace) -> None:
    target = args.tool or "all"
    dry = args.dry_run

    if dry:
        print(dim("  (dry run — no files will be written)\n"))

    if target == "all":
        # Import real connector for actual writes
        try:
            from src.tool_connectors import connect_all
            results = connect_all(dry_run=dry, installed_only=True)
        except ImportError:
            results = []
        if not results:
            print(yellow("  No installed tools detected. Install a tool then run again,"))
            print(yellow("  or specify a tool directly:  timps connect cursor"))
            return
        for r in results:
            _print_connect_result(r)
    else:
        try:
            from src.tool_connectors import connect_tool
            r = connect_tool(target, dry_run=dry)
        except ImportError:
            r = _connect_minimal(target, dry)
        _print_connect_result(r)


def _connect_minimal(tool_id: str, dry_run: bool) -> Dict[str, Any]:
    """Minimal connect when src.tool_connectors isn't importable."""
    info = _TOOL_INFO.get(tool_id)
    if not info:
        return {"status": "error", "message": f"Unknown tool: {tool_id}"}
    snippet = _get_snippet(tool_id)
    if dry_run:
        print(bold(f"\nConfig snippet for {info['icon']} {info['name']}:\n"))
        print(snippet)
        return {"status": "dry_run", "tool": info["name"], "message": "Preview only"}
    return {"status": "skipped", "tool": info["name"],
            "message": "Run 'timps config " + tool_id + "' and paste into your config file"}


def _print_connect_result(r: Dict[str, Any]) -> None:
    status = r.get("status", "")
    tool   = r.get("tool", r.get("id", "?"))
    msg    = r.get("message", "")
    path   = r.get("config_path") or r.get("would_write", "")
    icons  = {"ok": green("✓"), "skipped": yellow("○"), "error": red("✗"),
              "dry_run": cyan("◎")}
    icon = icons.get(status, "?")
    print(f"  {icon}  {bold(tool):30s}  {dim(msg)}")
    if path:
        print(f"       {dim('→')} {dim(path)}")


# ── subcommand: status ────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    try:
        from src.tool_connectors import status_report
        report = status_report()
    except ImportError:
        _status_minimal()
        return

    print(f"\n{bold('TIMPS Swarm — Integration Status')}\n")
    print(f"  Server binary : {cyan(TIMPS_BIN)}")
    print(f"  LLM backend   : {cyan(_detect_llm_backend())}\n")

    if report.get("connected"):
        print(bold(f"  Connected ({len(report['connected'])})"))
        for t in report["connected"]:
            print(f"    {green('✓')}  {t.get('icon','')} {t['name']}")

    if report.get("detected_not_configured"):
        print(bold(f"\n  Detected — not yet connected ({len(report['detected_not_configured'])})"))
        for t in report["detected_not_configured"]:
            print(f"    {yellow('○')}  {t.get('icon','')} {t['name']}"
                  f"  {dim('→ run: timps connect ' + t.get('id', t['name'].lower().replace(' ', '_')))}")

    if report.get("cloud_tools"):
        print(bold(f"\n  Cloud tools (manual setup required)"))
        for t in report["cloud_tools"]:
            print(f"    {cyan('☁')}  {t['name']}  {dim(t.get('docs',''))}")

    not_n = len(report.get("not_installed", []))
    print(dim(f"\n  {not_n} supported tools not currently installed on this machine"))
    print()


def _status_minimal() -> None:
    print(f"\n{bold('TIMPS Swarm')}")
    print(f"  Server : {cyan(TIMPS_BIN)}")
    print(f"  LLM    : {cyan(_detect_llm_backend())}")
    print(f"  To connect: timps connect <tool>\n")


def _detect_llm_backend() -> str:
    parts = []
    if os.getenv("GEMINI_API_KEY"):
        parts.append("Gemini")
    if os.getenv("ANTHROPIC_API_KEY"):
        parts.append("Anthropic")
    if os.getenv("OPENAI_API_KEY"):
        parts.append("OpenAI")
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.ok:
            models = [m["name"] for m in r.json().get("models", [])]
            parts.append(f"Ollama ({', '.join(models[:2])})")
    except Exception:
        pass
    return " → ".join(parts) if parts else "none detected (set GEMINI_API_KEY)"


# ── subcommand: config ────────────────────────────────────────────────────────

def cmd_config(args: argparse.Namespace) -> None:
    tool_id = args.tool
    snippet = _get_snippet(tool_id)
    info    = _TOOL_INFO.get(tool_id, {"name": tool_id, "icon": "⚙️"})

    print(f"\n{bold(info['icon'] + '  ' + info['name'])} — MCP config snippet\n")
    print(f"  Server binary: {cyan(TIMPS_BIN)}\n")
    print("  " + "─" * 60)
    for line in snippet.splitlines():
        print("  " + line)
    print("  " + "─" * 60)
    print()
    _print_config_hint(tool_id, info)


def _get_snippet(tool_id: str) -> str:
    integration = _TOOL_INTEGRATION.get(tool_id, "_generic")
    tmpl = _SNIPPETS.get(integration) or _SNIPPETS["_generic"]
    return tmpl.format(bin=TIMPS_BIN)


def _print_config_hint(tool_id: str, info: Dict) -> None:
    home = Path.home()
    hints = {
        "claude_code":    f"  Paste into {dim('~/.claude/mcp.json')}",
        "codex_cli":      f"  Paste into {dim('~/.codex/config.json')}",
        "gemini_cli":     f"  Paste into {dim('~/.gemini/settings.json')}",
        "opencode":       f"  Paste into {dim('~/.config/opencode/opencode.json')}",
        "cursor":         f"  Paste into {dim('~/.cursor/mcp.json')}",
        "windsurf":       f"  Paste into {dim('~/.codeium/windsurf/mcp_config.json')}",
        "aider":          f"  Paste into {dim('~/.aider.conf.yml')}",
        "goose":          f"  Paste into {dim('~/.config/goose/config.yaml')}",
        "zed":            f"  Merge into {dim('~/.config/zed/settings.json')}",
        "warp":           f"  Paste into {dim('~/.warp/mcp_servers.json')}",
        "continue":       f"  Add to {dim('~/.continue/config.json')} mcpServers array",
        "github_copilot": f"  Place at {dim('.vscode/mcp.json')} in your project root",
        "cline":          f"  Place at {dim('.vscode/mcp.json')} in your project root",
        "roo_code":       f"  Place at {dim('.vscode/mcp.json')} in your project root",
        "kilo_code":      f"  Place at {dim('.vscode/mcp.json')} in your project root",
        "augment_code":   f"  Place at {dim('.vscode/mcp.json')} in your project root",
        "amp":            f"  Paste into {dim('~/.amp/mcp.json')}",
        "factory":        f"  Place at {dim('.factory/droids.yml')} in your project root",
        "replit":         f"  Add to {dim('.replit')} in your Repl root",
        "devin":          f"  {yellow('Cloud tool')} — host timps-mcp on a server, register URL in Devin team settings",
        "jules":          f"  {yellow('Cloud tool')} — add as GitHub App with MCP webhook",
        "v0":             f"  {yellow('Cloud tool')} — wrap timps-mcp as a Next.js API route and register in Vercel",
        "kimi_code":      f"  Place at {dim('.vscode/mcp.json')} in your project root",
    }
    hint = hints.get(tool_id, f"  Add to your {info['name']} MCP config file")
    print(hint)
    print(dim(f"\n  Or run: {bold('timps connect ' + tool_id)}  to auto-write this file\n"))


# ── subcommand: list ──────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> None:
    print(f"\n{bold('TIMPS Swarm — Supported AI Coding Agents')}\n")

    categories = {
        "CLI Tools":       ["claude_code", "codex_cli", "gemini_cli", "opencode", "aider", "goose", "amp", "warp"],
        "IDE Extensions":  ["github_copilot", "cline", "continue", "kilo_code", "roo_code", "augment_code", "kimi_code"],
        "IDE Apps":        ["cursor", "windsurf", "zed", "antigravity"],
        "Cloud / SaaS":    ["devin", "factory", "replit", "jules", "v0"],
    }

    for cat, ids in categories.items():
        print(f"  {bold(cat)}")
        for tid in ids:
            info = _TOOL_INFO.get(tid, {"name": tid, "icon": "⚙️", "vendor": ""})
            installed = _is_installed(tid)
            mark = green("●") if installed else dim("○")
            print(f"    {mark}  {info['icon']}  {info['name']:20s}  {dim(info.get('vendor',''))}")
        print()

    print(dim("  ● installed on this machine   ○ not detected"))
    print(dim(f"\n  To connect all detected tools: {bold('timps connect all')}"))
    print(dim(f"  To see config snippet:         {bold('timps config <tool_id>')}"))
    print()


def _is_installed(tool_id: str) -> bool:
    try:
        from src.tool_connectors import detect_installed_tools
        return detect_installed_tools().get(tool_id, False)
    except ImportError:
        return False


# ── subcommand: info ──────────────────────────────────────────────────────────

def cmd_info(args: argparse.Namespace) -> None:
    print(f"\n{bold('TIMPS Swarm — Server Info')}\n")

    # Binary
    print(f"  {bold('Binary')}       {cyan(TIMPS_BIN)}")
    exists = Path(TIMPS_BIN).exists() if Path(TIMPS_BIN).is_absolute() else bool(shutil.which("timps-mcp"))
    print(f"  {'Installed':<14}{green('yes') if exists else red('no — run: pip install -e .')}")

    # Protocol
    print(f"  {'Protocol':<14}{cyan('MCP JSON-RPC 2.0 over stdio')}")
    print(f"  {'Transport':<14}{cyan('stdio (compatible with all MCP clients)')}")

    # Agents
    print(f"\n  {bold('Agent Counts')}")
    categories = [
        ("SDLC pipeline",     10),
        ("Computer health",   12),
        ("Developer swarm",   12),
        ("Knowledge workers", 10),
        ("Expert/diagnostic", 12),
        ("Connector tools",    2),
    ]
    total = sum(n for _, n in categories)
    for name, n in categories:
        bar = "█" * (n // 2)
        print(f"    {name:<24}  {cyan(str(n)):>3}  {dim(bar)}")
    print(f"    {'Total':<24}  {bold(cyan(str(total)))}")

    # LLM backend
    print(f"\n  {bold('LLM Backend')}  (priority order)")
    backends = [
        ("MCP sampling",    bool(False),                       "used when calling client supports it"),
        ("Gemini API",      bool(os.getenv("GEMINI_API_KEY")), "GEMINI_API_KEY"),
        ("Anthropic API",   bool(os.getenv("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY"),
        ("OpenAI API",      bool(os.getenv("OPENAI_API_KEY")), "OPENAI_API_KEY"),
    ]
    for name, active, note in backends:
        mark = green("✓ active") if active else dim("○ not set")
        print(f"    {name:<20}  {mark}   {dim(note)}")

    # Ollama
    try:
        import requests as req
        r = req.get("http://localhost:11434/api/tags", timeout=2)
        if r.ok:
            models = [m["name"] for m in r.json().get("models", [])]
            print(f"    {'Ollama':<20}  {green('✓ running')}  {dim(', '.join(models))}")
        else:
            print(f"    {'Ollama':<20}  {dim('○ not running')}")
    except Exception:
        print(f"    {'Ollama':<20}  {dim('○ not running')}")

    print()


# ── subcommand: run ───────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    agent = args.agent
    task  = " ".join(args.task)

    # Map common short names to MCP tool names
    _aliases = {
        "issue_triager":        "issue_triager",
        "triager":              "issue_triager",
        "pr_reviewer":          "pr_reviewer",
        "unit_test_writer":     "unit_test_writer",
        "docstring_generator":  "docstring_generator",
        "log_detective":        "log_detective",
        "sql_optimizer":        "sql_optimizer",
        "sprint_reporter":      "sprint_reporter",
        "system_optimizer":     "system_optimizer",
        "network_medic":        "network_medic",
        "battery_analyst":      "battery_analyst",
        "environment_doctor":   "environment_doctor",
        "security_guard":       "security_guard",
        "research_scout":       "research_scout",
        "meeting_condenser":    "meeting_condenser",
        "dispatch":             "dispatch",
    }
    agent_key = _aliases.get(agent, agent)

    try:
        from src.developer_swarm_agents import DEVELOPER_AGENTS
        from src.knowledge_swarm_agents import KNOWLEDGE_AGENTS
        all_agents = {**DEVELOPER_AGENTS, **KNOWLEDGE_AGENTS}

        if agent_key in all_agents:
            fn = all_agents[agent_key]
            # Most agents accept (request, ...) — call with just the task string
            import inspect
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
            if params:
                result = fn(task)
            else:
                result = fn()

            if isinstance(result, dict):
                print(json.dumps(result, indent=2))
            else:
                print(result)
            return
    except ImportError:
        pass

    # Fall back: call via LLMRouter directly
    try:
        from src.llm_router import LLMRouter
        router = LLMRouter()
        result = router.call(
            agent_key,
            task,
            f"You are a specialist AI agent: {agent_key}. "
            "Complete the user's task thoroughly and concisely.",
        )
        print(result)
    except Exception as exc:
        print(red(f"Error: {exc}"))
        sys.exit(1)


# ── subcommand: install (print install instructions) ─────────────────────────

def cmd_install(args: argparse.Namespace) -> None:
    print(f"\n{bold('TIMPS Swarm — Install Guide')}\n")
    print(f"  {bold('Step 1: Install')}")
    print(f"    {cyan('pip install timps-swarm-mcp')}")
    print(f"    {dim('or from source:')}")
    print(f"    {cyan('git clone https://github.com/Sandeeprdy1729/timps-swarm')}")
    print(f"    {cyan('cd timps-swarm && pip install -e .')}")
    print()
    print(f"  {bold('Step 2: Set your LLM API key')}")
    print(f"    {cyan('export GEMINI_API_KEY=your_key      # Gemini (recommended — free tier)')}")
    print(f"    {cyan('export ANTHROPIC_API_KEY=your_key   # Claude')}")
    print(f"    {cyan('export OPENAI_API_KEY=your_key      # GPT')}")
    print(f"    {dim('Or install Ollama for fully local inference (no API key needed)')}")
    print()
    print(f"  {bold('Step 3: Connect to your coding agent')}")
    print(f"    {cyan('timps connect all          # auto-detect and configure all installed tools')}")
    print(f"    {cyan('timps connect cursor        # connect a specific tool')}")
    print(f"    {cyan('timps config claude_code    # print ready-to-paste config snippet')}")
    print()
    print(f"  {bold('Step 4: Use from any agent')}")
    print(f"    {dim('Example in OpenCode:')}")
    print(f"    {cyan('opencode run \"Use timps_pr_reviewer to review this diff: ...\"')}")
    print(f"    {dim('Example in Claude Code:')}")
    print(f"    {cyan('claude \"use timps_unit_test_writer to write tests for src/auth.py\"')}")
    print()
    print(f"  {dim('Full docs: https://github.com/Sandeeprdy1729/timps-swarm')}")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="timps",
        description="TIMPS Swarm — 51 specialist AI agents, plug into any coding tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  timps connect all                      # connect every installed coding tool
  timps connect cursor                   # connect Cursor IDE
  timps config claude_code               # print config snippet for Claude Code
  timps status                           # show what's connected
  timps list                             # list all supported tools
  timps info                             # show server info + LLM backend
  timps run issue_triager "bug title"    # run an agent directly
  timps install                          # show full install guide
""",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    # connect
    p_connect = sub.add_parser("connect", help="Configure a coding tool to use TIMPS")
    p_connect.add_argument("tool", nargs="?", default="all",
                           help="Tool id (e.g. cursor, claude_code) or 'all'")
    p_connect.add_argument("--dry-run", action="store_true",
                           help="Preview only — don't write any files")
    p_connect.set_defaults(func=cmd_connect)

    # status
    p_status = sub.add_parser("status", help="Show connection status for all tools")
    p_status.set_defaults(func=cmd_status)

    # config
    p_config = sub.add_parser("config", help="Print ready-to-paste config snippet")
    p_config.add_argument("tool", help="Tool id (e.g. cursor, opencode, claude_code)")
    p_config.set_defaults(func=cmd_config)

    # list
    p_list = sub.add_parser("list", help="List all supported AI coding tools")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = sub.add_parser("info", help="Show server info, agent counts, LLM backend")
    p_info.set_defaults(func=cmd_info)

    # run
    p_run = sub.add_parser("run", help="Run a TIMPS agent directly from the terminal")
    p_run.add_argument("agent", help="Agent name (e.g. issue_triager, pr_reviewer)")
    p_run.add_argument("task", nargs=argparse.REMAINDER, help="Task description")
    p_run.set_defaults(func=cmd_run)

    # install
    p_install = sub.add_parser("install", help="Show installation guide")
    p_install.set_defaults(func=cmd_install)

    args = parser.parse_args()
    if not args.command:
        # Default: show a compact dashboard
        cmd_info(args)
        print(dim(f"  Run {bold('timps --help')} for all commands\n"))
        return

    args.func(args)


if __name__ == "__main__":
    main()
