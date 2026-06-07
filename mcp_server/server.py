#!/usr/bin/env python3
"""
TIMPS Swarm MCP Server
======================

Implements the Model Context Protocol (MCP) so any MCP-aware client
(Claude Code, GitHub Copilot in VS Code, Cursor, Windsurf, Kimi Code,
Codex CLI, Continue.dev, …) can call the full TIMPS agent swarm as tools.

Protocol: JSON-RPC 2.0 over stdio (the MCP standard transport).

Tools exposed
─────────────
  Code / SDLC pipeline:
    timps_run_task          — full 10-agent SDLC pipeline

  Computer health (12 agents):
    timps_system_optimizer   — slow laptop / startup bloat / thermal
    timps_file_organizer     — downloads chaos / duplicates / large files
    timps_environment_doctor — broken Python/Node/Docker/PATH
    timps_security_guard     — open ports / camera-mic permissions
    timps_network_medic      — WiFi drops / DNS / latency
    timps_battery_analyst    — energy drainers / battery health
    timps_update_manager     — OS / brew / pip / npm updates
    timps_log_interpreter    — crash logs → plain English
    timps_privacy_cleaner    — browser cookies / app permissions
    timps_media_librarian    — photos / videos / screenshots
    timps_backup_sentinel    — Time Machine / git uncommitted
    timps_context_switcher   — tabs / focus / distractions

  Meta:
    timps_dispatch           — auto-routes any request to the right agent
    timps_full_checkup       — run 6 agents for a comprehensive health scan
    timps_list_agents        — list all available agents + status
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Allow running from repo root without installing ──────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("timps-mcp")

# ── MCP Sampling state ───────────────────────────────────────────────────────
# Set once the client connects; lets agents use the caller's LLM instead of Ollama.
_CLIENT_NAME: str = "unknown"
_CLIENT_SUPPORTS_SAMPLING: bool = False
_STDIN_BUF: Optional[Any] = None
_STDOUT_BUF: Optional[Any] = None
_SAMPLE_COUNTER: int = 0


def _mcp_sample(system: str, user_prompt: str, max_tokens: int = 8192) -> Optional[str]:
    """Send sampling/createMessage to the MCP client; return response text or None.

    Returns None when:
    - The client doesn't advertise sampling support
    - The round-trip fails for any reason
    The caller (LLMRouter) falls back to local Ollama in those cases.
    """
    global _SAMPLE_COUNTER
    if not _CLIENT_SUPPORTS_SAMPLING or _STDOUT_BUF is None or _STDIN_BUF is None:
        return None

    _SAMPLE_COUNTER += 1
    sample_id = f"smpl-{_SAMPLE_COUNTER}"

    request = {
        "jsonrpc": "2.0",
        "id": sample_id,
        "method": "sampling/createMessage",
        "params": {
            "messages": [
                {"role": "user", "content": {"type": "text", "text": user_prompt}}
            ],
            "systemPrompt": system or "You are a helpful AI assistant.",
            "maxTokens": max_tokens,
            "includeContext": "none",
        },
    }
    try:
        _STDOUT_BUF.write((json.dumps(request) + "\n").encode())
        _STDOUT_BUF.flush()
        # Read back the response; skip notifications (they have no "id")
        for _ in range(20):
            raw = _STDIN_BUF.readline()
            if not raw:
                return None
            resp = json.loads(raw.strip())
            if "id" not in resp:
                continue  # notification — ignore and keep reading
            if resp.get("id") != sample_id:
                continue  # out-of-order — shouldn't happen but be safe
            if "error" in resp:
                logger.error("Sampling error from %s: %s", _CLIENT_NAME, resp["error"])
                return None
            content = resp.get("result", {}).get("content", {})
            if isinstance(content, dict):
                return content.get("text") or ""
            return str(content)
    except Exception as exc:
        logger.error("MCP sampling round-trip failed: %s", exc)
    return None


# ── Lazy imports so the server starts even if heavy deps are missing ──────────

def _import_agents():
    from src.computer_agents import (
        system_optimizer_node, file_organizer_node, environment_doctor_node,
        security_guard_node, network_medic_node, battery_analyst_node,
        update_manager_node, log_interpreter_node, privacy_cleaner_node,
        media_librarian_node, backup_sentinel_node, context_switcher_node,
    )
    return {
        "system_optimizer":   system_optimizer_node,
        "file_organizer":     file_organizer_node,
        "environment_doctor": environment_doctor_node,
        "security_guard":     security_guard_node,
        "network_medic":      network_medic_node,
        "battery_analyst":    battery_analyst_node,
        "update_manager":     update_manager_node,
        "log_interpreter":    log_interpreter_node,
        "privacy_cleaner":    privacy_cleaner_node,
        "media_librarian":    media_librarian_node,
        "backup_sentinel":    backup_sentinel_node,
        "context_switcher":   context_switcher_node,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: List[Dict[str, Any]] = [
    # ── Meta ──────────────────────────────────────────────────────────────────
    {
        "name": "timps_list_agents",
        "description": (
            "List all 22 TIMPS Swarm agents with their purpose, "
            "so you can choose the right one for the user's request."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_dispatch",
        "description": (
            "Auto-detect the best TIMPS agent for any plain-English request "
            "and run it immediately. Use this when unsure which agent to pick. "
            "Examples: 'my wifi keeps dropping', 'why is my laptop slow', "
            "'broken python environment', 'organize my downloads'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The user's plain-English request or complaint.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "timps_full_checkup",
        "description": (
            "Run a comprehensive computer health scan across 6 agents: "
            "system optimizer, battery analyst, security guard, network medic, "
            "backup sentinel, and update manager. Returns a combined health score "
            "and prioritised action list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional hint to customise the checkup (e.g. 'focus on performance').",
                },
            },
            "required": [],
        },
    },
    # ── SDLC pipeline ─────────────────────────────────────────────────────────
    {
        "name": "timps_run_task",
        "description": (
            "Run the full 10-agent SDLC pipeline (product manager → architect → "
            "code generator → reviewer → QA → security → performance → devops → docs). "
            "Use for software development tasks: writing code, fixing bugs, building APIs, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The development task, e.g. 'Write a REST API for user auth in Python'.",
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (default: python).",
                    "default": "python",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum pipeline iterations (default: 10).",
                    "default": 10,
                },
            },
            "required": ["request"],
        },
    },
    # ── 12 Computer Health agents ─────────────────────────────────────────────
    {
        "name": "timps_system_optimizer",
        "description": (
            "Diagnose why a computer is slow. Scans: top CPU/RAM processes, "
            "startup items, thermal throttling, memory pressure. "
            "Returns a report with specific processes to kill and startup items to disable. "
            "Generates a dry-run cleanup shell script."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Optional: extra context like 'laptop fan running loudly since update'.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_file_organizer",
        "description": (
            "Scan Downloads and Desktop for clutter: duplicates, large files, "
            "unnamed junk. Generates a folder organisation plan and a move script "
            "(dry-run — no files moved until user approves)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional: custom directory to scan (default: ~/Downloads and ~/Desktop).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_environment_doctor",
        "description": (
            "Diagnose broken development environments. Checks Python, Node.js, "
            "Docker, Git, PATH integrity, shell config conflicts. "
            "Returns exact terminal commands to fix each issue."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional: 'python', 'node', 'docker', 'git', or 'all' (default: all).",
                    "default": "all",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_security_guard",
        "description": (
            "Security scan: open network ports, running process anomalies, "
            "app camera/microphone/location permissions (macOS TCC). "
            "Returns CVSS-rated findings and mitigation commands."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_network_medic",
        "description": (
            "Diagnose network problems: ping internet/Cloudflare, DNS resolution, "
            "WiFi signal, traceroute, open ports. Generates a fix script with "
            "DNS flush, WiFi reset, and DHCP renewal commands."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Hostname or IP to ping/trace (default: 8.8.8.8).",
                    "default": "8.8.8.8",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_battery_analyst",
        "description": (
            "Identify battery drainers. Reads battery %, health cycle count, "
            "and ranks processes by CPU usage (proxy for energy drain). "
            "Generates kill commands for the top energy vampires."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_update_manager",
        "description": (
            "Check for pending updates: macOS/Linux OS, Homebrew packages, "
            "global npm packages, pip packages. Returns a prioritised update plan "
            "(security first) with a safe ordered shell script."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_log_interpreter",
        "description": (
            "Read crash logs and system logs, extract stack traces, and explain "
            "each crash in plain English. Classifies as app bug / OS bug / hardware / user error. "
            "Pass a log file path to analyse a specific log."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_path": {
                    "type": "string",
                    "description": "Optional: absolute path to a specific log file to analyse.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_privacy_cleaner",
        "description": (
            "Privacy audit: count cookies per browser (Chrome, Firefox, Edge, Brave), "
            "list macOS app permissions (camera, mic, location, contacts). "
            "Returns a cleanup manifest — no data is deleted until user reviews."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_media_librarian",
        "description": (
            "Scan Photos, Downloads, Desktop for media chaos: unnamed photos, "
            "screenshot backlog, oversized videos. Suggests a date-based rename plan "
            "and generates ffmpeg compression commands (dry-run)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional: directory to scan (default: ~/Pictures, ~/Downloads, ~/Desktop).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_backup_sentinel",
        "description": (
            "Audit backup health: Time Machine last backup time, all local git repos "
            "with uncommitted/unpushed changes, large files on Desktop/Documents "
            "not tracked by git or cloud. Returns a risk score and backup script."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "timps_context_switcher",
        "description": (
            "Analyse current work context: active apps, estimated browser tabs, "
            "current git branch and recent commits. Identifies distraction apps "
            "and generates a focus-mode script to quit them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # ── Context Keeper & Agent Kernel ─────────────────────────────────────────
    {
        "name": "timps_context_briefing",
        "description": (
            "Get a 3-sentence resumption briefing from the Context Keeper: what you were working on, "
            "current state (uncommitted changes, broken tests), and recommended next step. "
            "Use when the user says 'what was I doing' or 'catch me up'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "refresh": {
                    "type": "boolean",
                    "description": "Force refresh even if cache is fresh (default: false).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "timps_delegate",
        "description": (
            "Delegate a multi-step goal to the TIMPS Agent Kernel. The kernel plans, "
            "routes to specialist agents, and returns a structured result. "
            "Use for complex goals like 'fix the auth bug and ensure 80% test coverage'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The high-level goal to accomplish.",
                },
                "context": {
                    "type": "object",
                    "description": "Optional metadata: repo_path, branch, language, etc.",
                },
            },
            "required": ["goal"],
        },
    },
    {
        "name": "timps_kernel_status",
        "description": "Check the status of a previously delegated kernel run by its run_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "The run_id returned by timps_delegate.",
                },
            },
            "required": ["run_id"],
        },
    },
    # ── Expert / Deep-Diagnostic agents ──────────────────────────────────────
    {
        "name": "timps_dependency_rebel",
        "description": "Detect dependency conflicts, vulnerabilities, and outdated packages across Python and Node. Returns a fix plan and remediation script.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string", "description": "Path to repo (defaults to cwd)"}}, "required": []},
    },
    {
        "name": "timps_merge_conflict_predictor",
        "description": "Predict merge conflicts between two branches before merging, with file-level and line-level overlap analysis.",
        "inputSchema": {"type": "object", "properties": {"branch_a": {"type": "string"}, "branch_b": {"type": "string"}, "repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_tech_debt_quantifier",
        "description": "Scan codebase for TODO/FIXME density, cyclomatic complexity hotspots, and deprecated patterns. Returns a prioritised debt repayment plan.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_migration_pilot",
        "description": "Analyse a codebase for breaking-change APIs given a target library/framework upgrade. Returns a step-by-step migration checklist.",
        "inputSchema": {"type": "object", "properties": {"goal": {"type": "string", "description": "e.g. 'migrate from React 17 to React 18'"}, "repo_path": {"type": "string"}}, "required": ["goal"]},
    },
    {
        "name": "timps_flaky_test_detective",
        "description": "Identify flaky tests by scanning for timing dependencies, random data, and external HTTP calls. Reads pytest failure cache for history.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_onboarding_mentor",
        "description": "Generate a customised onboarding guide: most-touched files, architecture overview, key modules, recent PR walkthroughs.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_incident_responder",
        "description": "Multi-source log correlation for production incidents. Gathers Docker + app logs, builds a timeline, and generates a triage report.",
        "inputSchema": {"type": "object", "properties": {"window_minutes": {"type": "integer", "description": "How many minutes back to look (default 30)"}, "repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_cloud_cost_auditor",
        "description": "Scan Terraform configs for waste (over-provisioned instances, missing deletion protection) and check AWS CLI for idle resources.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": []},
    },
    {
        "name": "timps_certificate_rotator",
        "description": "Check TLS certificate expiry for all hosts found in config files. Warns 30 days before expiry and generates certbot renewal commands.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}, "hosts": {"type": "array", "items": {"type": "string"}}}, "required": []},
    },
    {
        "name": "timps_terraform_plan_reviewer",
        "description": "Review terraform plan output for destructive changes. Requires explicit approval before allowing apply on high-risk plans.",
        "inputSchema": {"type": "object", "properties": {"repo_path": {"type": "string"}, "plan_text": {"type": "string", "description": "Raw output of 'terraform plan' (optional — will run it if omitted)"}}, "required": []},
    },
    {
        "name": "timps_dotfile_doctor",
        "description": "Detect errors and performance issues in shell config files (.zshrc, .bashrc, .gitconfig). Finds slow evals, duplicate PATH entries, syntax errors.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "timps_disk_space_prophet",
        "description": "Predict disk usage trends, identify cache directories safe to prune, and warn before 'no space left on device' events.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },

    # ── Developer Swarm agents ─────────────────────────────────────────────────
    {
        "name": "timps_issue_triager",
        "description": (
            "Triage a bug report or GitHub issue: detect duplicates, assign severity "
            "(critical/high/medium/low), suggest labels and owner. "
            "Pass the raw issue title and body text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Raw issue title + body text"},
                "repo_path": {"type": "string", "description": "Optional: local repo for duplicate detection"},
            },
            "required": ["request"],
        },
    },
    {
        "name": "timps_boilerplate_architect",
        "description": (
            "Scaffold a new project: folder structure, stub files, setup commands. "
            "Supports any language or framework — describe what you're building."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Project description"},
                "language": {"type": "string", "description": "Primary language (default: python)", "default": "python"},
            },
            "required": ["request"],
        },
    },
    {
        "name": "timps_pr_reviewer",
        "description": (
            "Review a pull request diff for blockers, suggestions, and nitpicks. "
            "Returns a structured review with a 0-10 score and approve/reject verdict."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "The PR diff or description text"},
                "style_guide": {"type": "string", "description": "Optional: project style guide context"},
            },
            "required": ["diff"],
        },
    },
    {
        "name": "timps_dependency_sentinel",
        "description": (
            "Scan a dependency manifest (requirements.txt, package.json, go.mod, Cargo.toml) "
            "for CVEs and severely outdated packages. Returns a severity-ranked report "
            "with upgrade commands."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest": {"type": "string", "description": "Full content of the manifest file"},
                "manifest_type": {"type": "string", "description": "'requirements.txt'|'package.json'|'go.mod'|'auto'", "default": "auto"},
            },
            "required": ["manifest"],
        },
    },
    {
        "name": "timps_unit_test_writer",
        "description": (
            "Analyse source code and generate a comprehensive test suite: "
            "happy paths, edge cases, error conditions. "
            "Returns a complete test file ready to run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_code": {"type": "string", "description": "The function or class source code to test"},
                "language": {"type": "string", "description": "Programming language", "default": "python"},
                "framework": {"type": "string", "description": "Test framework (auto-detected if omitted)", "default": "auto"},
            },
            "required": ["source_code"],
        },
    },
    {
        "name": "timps_docstring_generator",
        "description": (
            "Read raw source code and insert production-quality docstrings in your "
            "preferred format (Google, Sphinx, NumPy, JSDoc, Doxygen). "
            "Logic is never changed — only documentation is added."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_code": {"type": "string", "description": "Source code to document"},
                "language": {"type": "string", "description": "Programming language", "default": "python"},
                "doc_style": {"type": "string", "description": "'google'|'sphinx'|'numpy'|'jsdoc'|'doxygen'", "default": "google"},
            },
            "required": ["source_code"],
        },
    },
    {
        "name": "timps_log_detective",
        "description": (
            "Cluster production log errors, identify root cause, and suggest a fix. "
            "Handles stack traces, JSON logs, syslog, and journald output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "logs": {"type": "string", "description": "Raw log output (paste or file content)"},
                "service": {"type": "string", "description": "Service name for context", "default": "app"},
            },
            "required": ["logs"],
        },
    },
    {
        "name": "timps_sql_optimizer",
        "description": (
            "Analyse a slow SQL query and return: the optimised rewrite, "
            "index recommendations with CREATE INDEX SQL, and an estimated speedup. "
            "Supports PostgreSQL, MySQL, SQLite, MSSQL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The slow SQL query"},
                "explain_output": {"type": "string", "description": "Optional: output of EXPLAIN or EXPLAIN ANALYZE"},
                "db_engine": {"type": "string", "description": "'postgresql'|'mysql'|'sqlite'|'mssql'", "default": "postgresql"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "timps_sprint_reporter",
        "description": (
            "Generate a formatted daily standup report from task lists. "
            "Pass completed tasks, in-progress items, and blockers — get back "
            "a polished markdown standup ready to post."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "completed": {"type": "array", "items": {"type": "string"}, "description": "Tasks completed since last standup"},
                "in_progress": {"type": "array", "items": {"type": "string"}, "description": "Currently in progress"},
                "blockers": {"type": "array", "items": {"type": "string"}, "description": "Current blockers"},
                "team_member": {"type": "string", "description": "Name for the standup", "default": "Developer"},
            },
            "required": ["completed", "in_progress"],
        },
    },
    {
        "name": "timps_flaky_test_hunter",
        "description": (
            "Find non-deterministic tests from CI run history. "
            "Returns ranked list of flaky tests, suspected causes, and fix suggestions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ci_history": {"type": "string", "description": "CI test run history (paste from CI logs)"},
                "repo_path": {"type": "string", "description": "Optional: local repo for git context"},
            },
            "required": ["ci_history"],
        },
    },
    {
        "name": "timps_api_contract_auditor",
        "description": (
            "Diff two API specs (OpenAPI/AsyncAPI) and flag breaking changes, "
            "deprecations, and safe additions. Returns a semver recommendation "
            "and a migration guide for clients."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_spec": {"type": "string", "description": "Old API spec (YAML or JSON)"},
                "new_spec": {"type": "string", "description": "New API spec (YAML or JSON)"},
                "format": {"type": "string", "description": "'openapi'|'asyncapi'", "default": "openapi"},
            },
            "required": ["old_spec", "new_spec"],
        },
    },
    {
        "name": "timps_content_multiplier",
        "description": (
            "Transform a long-form technical post into multiple short-form formats: "
            "tweet thread, LinkedIn post, changelog entry, docs blurb, and HN title."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The long-form post or release notes"},
                "tone": {"type": "string", "description": "'technical'|'casual'|'marketing'", "default": "technical"},
            },
            "required": ["content"],
        },
    },

    # ── Knowledge Worker agents ───────────────────────────────────────────────
    {
        "name": "timps_inbox_gatekeeper",
        "description": (
            "Triage a batch of emails: flag urgent ones, draft routine replies, "
            "identify newsletters to unsubscribe from. "
            "Pass a list of email objects with 'from', 'subject', 'body'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "emails": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of {from, subject, body} email objects",
                },
                "context": {"type": "string", "description": "Optional user context (role, priorities)"},
            },
            "required": ["emails"],
        },
    },
    {
        "name": "timps_meeting_condenser",
        "description": (
            "Extract action items, decisions, and open questions from a meeting transcript. "
            "Returns a structured summary with owners and deadlines."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript": {"type": "string", "description": "Raw meeting transcript text"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Optional: list of attendee names"},
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "timps_research_scout",
        "description": (
            "Deep-dive research on any topic. Returns a structured brief: "
            "key findings, consensus view, controversies, recommended actions, and sources. "
            "Depth options: quick, medium (default), deep."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Research topic or question"},
                "depth": {"type": "string", "description": "'quick'|'medium'|'deep'", "default": "medium"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "timps_trend_monitor",
        "description": (
            "Monitor keywords across Hacker News, Reddit, GitHub, and Dev.to for "
            "spikes in interest. Returns trend direction, sentiment, and a digest summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords to track"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "Optional: specific sources to watch"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "timps_data_wrangler",
        "description": (
            "Clean and normalise messy data: CSV, JSON, PDF extracts, copy-pasted tables. "
            "Returns cleaned records, a quality score, and SQL insert hint."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Raw messy data (paste content)"},
                "target_schema": {"type": "object", "description": "Optional: {field_name: type} target schema"},
                "format": {"type": "string", "description": "Input format hint ('csv'|'json'|'text'|'auto')", "default": "auto"},
            },
            "required": ["data"],
        },
    },
    {
        "name": "timps_competitor_tracker",
        "description": (
            "Monitor competitors for pricing changes, new features, job postings, "
            "and public sentiment. Returns a competitive intelligence brief."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "competitors": {"type": "array", "items": {"type": "string"}, "description": "Competitor names or URLs"},
                "focus_areas": {"type": "array", "items": {"type": "string"}, "description": "Optional: ['pricing','features','hiring','reviews']"},
            },
            "required": ["competitors"],
        },
    },

    # ── NEW Priority Agents (Phase 3) ─────────────────────────────────────────
    {
        "name": "timps_research_agent",
        "description": (
            "Research Agent — runs BEFORE any coding task. Searches documentation, "
            "GitHub issues, Stack Overflow, and the web to gather context so all "
            "downstream agents have grounded information. "
            "Returns a structured brief: findings, gotchas, recommended approach, sources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to research (e.g. 'FastAPI JWT auth best practices 2024')"},
                "depth": {"type": "string", "description": "'quick'|'medium'|'deep'", "default": "medium"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "Optional: specific sources to search (docs, github, stackoverflow)"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "timps_api_design_agent",
        "description": (
            "API Design Agent — generates a complete OpenAPI 3.1 spec (YAML) "
            "from a natural-language description. Enforces REST/GraphQL best practices, "
            "versioning strategy, and consistent naming BEFORE code generation starts. "
            "Returns the spec + a design rationale document."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Plain-English API description, e.g. 'User auth API with JWT, refresh tokens, and role-based access'"},
                "style": {"type": "string", "description": "'rest'|'graphql'|'grpc'", "default": "rest"},
                "version": {"type": "string", "description": "API version string", "default": "1.0.0"},
                "auth_scheme": {"type": "string", "description": "'jwt'|'oauth2'|'api_key'|'none'", "default": "jwt"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "timps_db_agent",
        "description": (
            "DB Agent — schema design, query optimisation, and migration scripts. "
            "Given a description of your data model it produces: "
            "CREATE TABLE SQL, an ER diagram in Mermaid, index recommendations, "
            "a migration script (Alembic / Flyway / raw SQL), and query templates. "
            "Pairs with the sql_injection LoRA for secure query generation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Data model description, e.g. 'Multi-tenant SaaS with users, teams, projects, and tasks'"},
                "db_engine": {"type": "string", "description": "'postgresql'|'mysql'|'sqlite'|'mongodb'", "default": "postgresql"},
                "migration_tool": {"type": "string", "description": "'alembic'|'flyway'|'raw_sql'", "default": "alembic"},
                "existing_schema": {"type": "string", "description": "Optional: existing DDL or schema JSON for ALTER TABLE migrations"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "timps_dependency_agent",
        "description": (
            "Dependency Agent — runs pip-audit / npm audit / cargo audit after "
            "code generation. Produces: a CVE severity report, a license compliance "
            "check, a version pinning strategy, and a safe upgrade script. "
            "Security-conscious devs' favourite agent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest": {"type": "string", "description": "Content of requirements.txt, package.json, Cargo.toml, go.mod, or a directory path"},
                "ecosystem": {"type": "string", "description": "'python'|'node'|'rust'|'go'|'auto'", "default": "auto"},
                "fix": {"type": "boolean", "description": "Generate a fix script for vulnerabilities", "default": True},
            },
            "required": ["manifest"],
        },
    },
    {
        "name": "timps_n8n_workflow_agent",
        "description": (
            "n8n Workflow Agent — converts a plain-English task description into a "
            "complete, importable n8n workflow JSON. Knows all n8n core nodes, "
            "integrations (Slack, Gmail, GitHub, Notion, Airtable, HTTP Request, "
            "Webhook, Cron, etc.), and expression syntax. "
            "Returns the workflow JSON + a visual description of every node."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Plain-English workflow description, e.g. 'When a GitHub issue is labeled urgent, post it to Slack #dev and create a Notion page'"},
                "trigger": {"type": "string", "description": "Trigger type hint: 'webhook'|'cron'|'email'|'github'|'manual'|'auto'", "default": "auto"},
                "integrations": {"type": "array", "items": {"type": "string"}, "description": "Optional: list of services to include (slack, gmail, github, notion, airtable, etc.)"},
            },
            "required": ["description"],
        },
    },
    # ── More agents (v2.1) ────────────────────────────────────────────────────
    {
        "name": "timps_refactoring_agent",
        "description": "Detect code smells and produce a fully refactored version with a diff summary, complexity scores, and improvement list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":     {"type": "string", "description": "Source code to refactor"},
                "language": {"type": "string", "description": "Programming language", "default": "python"},
                "goals":    {"type": "array", "items": {"type": "string"},
                             "description": "Refactoring goals e.g. ['reduce_complexity', 'extract_functions']"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "timps_test_data_agent",
        "description": "Generate realistic, edge-case-covering seed / fixture data for any JSON schema, SQL DDL, or plain-text description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema": {"type": "string", "description": "JSON schema, SQL DDL, or description"},
                "count":  {"type": "integer", "description": "Number of records (default 20)"},
                "format": {"type": "string", "enum": ["json", "csv", "sql", "yaml", "python_dict"], "default": "json"},
                "locale": {"type": "string", "description": "Locale e.g. en_US, de_DE, ja_JP", "default": "en_US"},
            },
            "required": ["schema"],
        },
    },
    {
        "name": "timps_monitoring_agent",
        "description": "Generate Prometheus metric definitions, Grafana dashboard JSON, alerting rules, and instrumentation code snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_description": {"type": "string"},
                "language":            {"type": "string", "default": "python"},
                "slos":                {"type": "array", "items": {"type": "string"},
                                        "description": "e.g. ['p99 < 200ms', 'error_rate < 0.1%']"},
                "alerting_platform":   {"type": "string", "enum": ["alertmanager", "pagerduty", "opsgenie"], "default": "alertmanager"},
            },
            "required": ["service_description"],
        },
    },
    {
        "name": "timps_ui_ux_agent",
        "description": "Generate a UI component spec, implementation code, Storybook story, design tokens, and WCAG accessibility audit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description":          {"type": "string"},
                "framework":            {"type": "string", "enum": ["react", "vue", "svelte", "html"], "default": "react"},
                "design_system":        {"type": "string", "enum": ["tailwind", "material", "chakra", "custom"], "default": "tailwind"},
                "accessibility_level":  {"type": "string", "enum": ["AA", "AAA"], "default": "AA"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "timps_i18n_agent",
        "description": "Extract translatable strings from source code, generate translation JSON files for multiple locales, and flag RTL/cultural issues.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code":            {"type": "string", "description": "Source code to scan"},
                "source_locale":   {"type": "string", "default": "en"},
                "target_locales":  {"type": "array", "items": {"type": "string"},
                                    "description": "e.g. ['fr', 'de', 'ja', 'ar']"},
                "i18n_framework":  {"type": "string", "default": "auto"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "timps_cost_optimizer",
        "description": "Estimate monthly/annual cloud cost for an architecture and generate a prioritised list of savings optimisations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "architecture":      {"type": "string"},
                "provider":          {"type": "string", "enum": ["aws", "gcp", "azure", "multi"], "default": "aws"},
                "monthly_requests":  {"type": "integer", "default": 1000000},
                "regions":           {"type": "array", "items": {"type": "string"}},
            },
            "required": ["architecture"],
        },
    },
    {
        "name": "timps_self_critic_agent",
        "description": (
            "Score any agent's output on a 1–10 quality scale, identify weaknesses, and automatically "
            "re-run the originating agent with an improved prompt until the score meets the threshold. "
            "This closes the quality feedback loop across the entire swarm."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content":      {"type": "string", "description": "The output to critique"},
                "agent":        {"type": "string", "description": "Which agent produced it"},
                "task":         {"type": "string", "description": "The original task/requirement"},
                "threshold":    {"type": "integer", "description": "Re-run if score < threshold (default 7)"},
                "max_retries":  {"type": "integer", "description": "Max re-run attempts (default 2)"},
            },
            "required": ["content", "agent", "task"],
        },
    },

    # ── NEW domain agents (intelligence/aiml/india/domain/business/infra/emerging) ──
    # Generated from the HTML agent catalogue — 47 agents across 7 packages.
    *[
        {
            "name": f"timps_{name}",
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "Plain-English task or context for the agent."},
                    "language": {"type": "string", "description": "Primary programming language (default: python).", "default": "python"},
                },
                "required": [],
            },
        }
        for name, desc in [
            # Intelligence
            ("code_archaeology",  "Analyse git history to build an AST import graph, risk map, and tribal knowledge document."),
            ("pattern_detector",  "Detect duplicate code blocks, god classes, magic numbers, and anti-patterns in a codebase."),
            ("technical_debt",    "Quantify technical debt via radon complexity + git churn + TODO density; output a debt roadmap."),
            ("memory_agent",      "Store, recall, and manage TIMPS run history and contextual memory."),
            ("learning_agent",    "Analyse past successful runs and distil prompt improvements for all agents."),
            ("agent_composer",    "Generate a new fully-functional Python agent file from a natural-language description."),
            # AI/ML
            ("prompt_engineer",   "Rewrite prompts with Chain-of-Thought, XML tags, and few-shot examples for better LLM output."),
            ("dataset_agent",     "Validate and clean ML training datasets; generate data cards and quality reports."),
            ("model_evaluator",   "Create evaluation harnesses, adversarial test inputs, and RAGAS config for LLM models."),
            ("rag_designer",      "Design chunking/embedding/retrieval/reranking RAG pipelines for LlamaIndex or LangChain."),
            ("finetuning_agent",  "Generate complete LoRA/MLX/Axolotl/Unsloth fine-tuning pipelines with push-to-hub scripts."),
            ("ai_safety_agent",   "Audit LLM applications against OWASP LLM Top 10 (LLM01-LLM10) with mitigations."),
            ("vector_db_agent",   "Design Qdrant/Pinecone/Weaviate/pgvector schemas and integration code."),
            # India
            ("gst_compliance",    "Generate GSTR-1/3B filings, e-invoice XML, ITC reconciliation reports (India GST)."),
            ("abdm_agent",        "Implement ABHA enrollment, HIP/HIU flows, FHIR R4 bundles, and consent workflows (India ABDM)."),
            ("upi_agent",         "Generate UPI deep links, QR codes, Razorpay/Cashfree webhook handlers (India UPI)."),
            ("digilocker_agent",  "Implement DigiLocker OAuth, document pull, Aadhaar OTP, PAN verify, and eKYC flows (India)."),
            ("indiehacker_agent", "India GTM plan: INR pricing tiers, Razorpay integration, GST invoice generation."),
            # Domain
            ("web_scraping",      "Generate Playwright/Scrapy/httpx scrapers with anti-bot config and data extraction logic."),
            ("data_pipeline",     "Design dbt/Airflow/Prefect/Dagster ETL/ELT pipelines with monitoring and lineage."),
            ("realtime_agent",    "Build WebSocket/SSE/Redis Pub-Sub/Kafka server+client real-time systems."),
            ("mobile_agent",      "Scaffold React Native/Flutter/Expo apps with push notifications and deep links."),
            ("browser_automation","Generate Playwright E2E tests with page objects, fixtures, and CI config."),
            ("graphql_agent",     "Write GraphQL SDL schemas, resolvers, DataLoader, subscriptions, and federation config."),
            ("cli_tool_agent",    "Generate Click/Cobra/Commander CLI tools with shell completions and release workflows."),
            ("embedded_agent",    "Create Arduino/ESP32/RPi firmware, HAL headers, CMakeLists, and OTA update scripts."),
            # Business
            ("analytics_agent",   "Set up PostHog/Mixpanel/Amplitude event tracking, funnels, and dashboards."),
            ("ab_testing_agent",  "Design A/B tests with Welch's t-test power analysis and GrowthBook configuration."),
            ("monetization_agent","Configure Stripe/LemonSqueezy products, checkout flows, webhooks, and dunning emails."),
            ("seo_agent",         "Run Lighthouse CI, generate schema.org JSON-LD, fix Core Web Vitals, build sitemaps."),
            ("postmortem_agent",  "Write blameless postmortems: 5 Whys, root causes, P0-P2 action items, runbooks."),
            ("sprint_planning_agent", "Decompose epics into sprint tickets with estimates, dependencies, and GitHub Issues payload."),
            # Infra
            ("load_testing",      "Generate k6/Artillery/Locust load test scripts with ramp-up plans and Grafana dashboards."),
            ("feature_flag",      "Design feature flags with LaunchDarkly/Flagsmith/GrowthBook targeting rules and rollout plans."),
            ("disaster_recovery", "Design RTO/RPO-aware DR plans, failover runbooks, and DR test scripts for cloud systems."),
            ("finops_agent",      "Analyse cloud costs with Infracost, generate rightsizing recommendations and budget alerts."),
            ("secrets_management","Scan for hardcoded secrets, generate Vault/AWS Secrets Manager migration code and pre-commit hooks."),
            ("edge_agent",        "Generate Cloudflare Workers/Vercel Edge/Fastly code with KV storage and geo-routing."),
            # Emerging
            ("robotics_agent",    "Generate ROS2 nodes, URDF descriptions, motion planning config, and ISO 10218-1 safety analysis."),
            ("web3_agent",        "Audit smart contracts with Slither/Mythril patterns; generate Solidity code with gas optimisation."),
            ("federated_learning","Design Flower/FedAvg/PySyft FL pipelines with differential privacy and aggregation strategies."),
            ("quantum_ready",     "Identify quantum-vulnerable algorithms, generate Qiskit circuits, and produce NIST PQC migration plans."),
        ]
    ],

    # ── NEW nextgen agents (Phase 6 — 21 agents across 8 categories) ────────────
    # Generated from the TIMPS Swarm Deep Research Report — closes gaps in security
    # ops, K8s, accessibility, release engineering, MLOps, and emerging tech.
    *[
        {
            "name": f"timps_{name}",
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "Plain-English task or context for the agent."},
                    "language": {"type": "string", "description": "Primary programming language (default: python).", "default": "python"},
                },
                "required": [],
            },
        }
        for name, desc in [
            # Security
            ("threat_intel_analyst",         "Ingest threat feeds (CVE, MITRE ATT&CK, CISA KEV) and produce a threat brief with detection rules and prioritised mitigations."),
            ("security_remediation",         "Convert a security finding (CVE, SAST, secret, misconfig) into a step-by-step patch plan with a working code diff and rollback."),
            ("compliance_auditor",           "Map a codebase + infra config against SOC 2 / ISO 27001 / HIPAA / PCI-DSS / GDPR controls; produce an evidence pack and gap report."),
            ("incident_response_coordinator","Turn an active incident (SIEM alert, customer report, CVE disclosure) into a play-by-play response with comms, containment, and a postmortem stub."),
            # DevOps & Infrastructure
            ("kubernetes_navigator",         "Diagnose Kubernetes workloads: pods, services, ingress, RBAC, resources, network policies. Outputs fix YAML and Helm/Kustomize patches."),
            ("pipeline_healer",              "Read a failing CI/CD run and produce a minimal diff to make it green: cache tweaks, image bumps, secret injection, retry policies."),
            ("docker_compose_architect",     "Compose a production-grade multi-service docker-compose (or compose.yaml) for a project: env, healthchecks, volumes, networks, profiles."),
            # Code Quality
            ("test_intelligence",            "Analyse test suite + git bug history to find untested code paths, suggest property-based tests, and propose a mutation-testing config."),
            ("changelog_generator",          "Generate a Conventional Commits changelog from commit history, PRs, and issues; supports semver bump recommendation."),
            # Data & Analytics
            ("db_migration_pilot",           "Plan a zero-downtime database migration: expand-contract phases, backfill scripts, dual-write strategy, kill-switches, rollback plan."),
            ("log_pattern_analyzer",         "Cluster production log errors, identify root cause, suggest a fix. Handles stack traces, JSON logs, syslog, and journald output."),
            ("api_perf_profiler",            "Profile an API from access logs / traces — p50/p95/p99 by endpoint, slow query, N+1 detection, and concrete optimisations."),
            # User Experience
            ("accessibility_tester",         "Audit a frontend (HTML / React / Vue) for WCAG 2.2 AA & AAA issues — colour contrast, ARIA, keyboard nav, focus order, screen reader hints."),
            ("visual_regression_detective",  "Diff design tokens / Storybook / screenshot baselines and surface unintended visual changes with root-cause hints."),
            # Business & Productivity
            ("release_manager",              "Produce a release plan: SemVer bump, release notes, rollout/canary strategy, rollback gate, customer-comms draft, and stakeholder checklist."),
            ("tech_writer_assistant",        "Refresh a project README, write ADRs, generate a 'Getting Started' guide, an FAQ, and a reference page from the codebase."),
            # MLOps
            ("model_perf_monitor",           "Monitor an ML model in production: drift, accuracy decay, latency, and cost — with alerting thresholds and a re-training trigger plan."),
            # Emerging Technology
            ("mcp_server_generator",         "Scaffold a complete Model Context Protocol (MCP) server: tools, resources, prompts, server.py, pyproject, smoke-test client, README."),
            ("ai_workflow_orchestrator",     "Turn a plain-English multi-step workflow into executable code for LangGraph, Temporal, or Claude-Flow — plus a Mermaid diagram and tests."),
            ("local_rag_builder",            "Build a fully-local RAG pipeline (Ollama embeddings + Chroma/FAISS + reranker + chat) from a corpus description. Emits ingest, retrieve, generate, evaluate, Dockerfile, Makefile."),
            ("git_workflow_automator",       "Generate an opinionated git workflow: pre-commit hooks, commitlint, lefthook, semantic-release / release-please config, PR template, branch-protection policy, CODEOWNERS."),
            ("web_search",                   "Multi-engine web search (DuckDuckGo / Brave / SerpAPI / Bing) with deduplication, content extraction, and LLM-synthesised answer with [N] citations. Use for live lookups, news, vendor docs, and competitive intel."),
        ]
    ],

    # ── NEW phase7 agents (Phase 7 — 32 agents across 9 categories) ─────────────
    # Expansion pack covering security & offensive testing, compliance & legal,
    # DevOps & reliability, research & intel, data & forecasting, productivity,
    # content & creative, sales/voice, and ML/AI ops.
    *[
        {
            "name": f"timps_{name}",
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "string", "description": "Plain-English task or context for the agent."},
                    "language": {"type": "string", "description": "Primary programming language (default: python).", "default": "python"},
                },
                "required": [],
            },
        }
        for name, desc in [
            # Security & Offensive Testing
            ("red_team_agent",                "Plan and execute an OWASP-style red-team engagement: threat model, adversarial test cases, payloads, runnable exploit harness, and a remediation checklist."),
            ("prompt_injection_scanner",      "Scan prompts, system messages, and tool schemas for prompt-injection / jailbreak / data-exfiltration risk. Produces a severity-rated report and hardened prompt rewrites."),
            ("phishing_simulator",            "Generate a realistic, organisation-tailored phishing simulation: emails, landing pages, payload tracking, and a click-through metrics plan. Strictly for authorised training use."),
            ("api_security_tester",           "Run an OWASP API Security Top-10 (2023) audit against an OpenAPI spec or live endpoint — broken auth, BOLA, mass assignment, rate-limit, SSRF, injection — with a runnable test harness."),
            ("container_image_scanner",       "Scan a container image / Dockerfile for CVEs, misconfigurations, and supply-chain risk. Wraps trivy/grype/syft when present; falls back to static analysis of the Dockerfile."),
            # Compliance & Legal
            ("contract_reviewer",             "Review a contract (MSA, NDA, SaaS, vendor agreement) for red-flags: indemnification, liability caps, IP, data, termination, SLAs. Returns a clause-by-clause scorecard and a redline."),
            ("dpdp_act_auditor",              "Audit a system or data flow against India's Digital Personal Data Protection Act 2023: consent, notice, data-principal rights, breach, penalties, and a remediation roadmap."),
            ("fssai_compliance_agent",        "Assess an F&B product / packaging against India's FSSAI regulations: license type, label checklist, additive and claim restrictions, and a submission-ready checklist."),
            # DevOps & Reliability
            ("observability_cost_optimizer",  "Analyse your observability bill (Datadog / New Relic / Grafana Cloud / Splunk) and recommend cardinality pruning, sampling, log-volume cuts, and tier migrations with projected savings."),
            ("service_mesh_configurator",     "Generate production-grade service-mesh config (Istio / Linkerd / Consul) — mTLS, traffic policies, retries, circuit-breakers, observability, multi-cluster, and a migration plan."),
            ("iac_drift_detector",            "Detect drift between Terraform / Pulumi / CloudFormation state and live cloud — produces a ranked diff, blast-radius estimate, and a safe `terraform plan` review."),
            ("sbom_generator",                "Generate a CycloneDX / SPDX Software Bill of Materials from a project tree + manifests, integrate syft/trivy if available, and flag license and supply-chain risks."),
            ("license_compliance_scanner",    "Scan source + manifests for OSS license usage (GPL/AGPL/LGPL/SSPL/Commercial), produce a per-dependency report, and a copyleft-compatibility matrix for your distribution model."),
            # Research & Intel
            ("deep_research_agent",           "Multi-hop, multi-source research planner: decomposes a query, runs parallel web searches, cross-references, and returns a sourced report with [N] citations and a bottom-line answer."),
            ("agent_marketplace_curator",     "Curate the best AI agent / MCP / LLM-tool marketplaces and recommend picks by use-case. Tracks pulse.mcp.run, glama.ai, mcp.so, OpenAI GPT Store, Claude tool directory."),
            ("adr_writer",                    "Turn a technical decision into a Michael Nygard-style Architecture Decision Record: context, options matrix, decision, consequences, and a rendered Markdown file."),
            # Data & Forecasting
            ("churn_predictor",               "Score accounts/users for churn risk from behavioural signals, build a survival-curve forecast, segment at-risk cohorts, and recommend save plays per segment."),
            ("demand_forecaster",             "Produce a SKU/location-level demand forecast with seasonality, promotions, and trend. Returns intervals, backtest MAPE/MASE, and an ordering recommendation."),
            ("agri_commodity_forecaster",     "Forecast Indian agri-commodity prices (mandi arrivals, MSP, weather, festival demand). Returns direction, confidence, and a hedge recommendation for farmers / FPOs / traders."),
            # Productivity & Wellness
            ("calendar_optimizer",            "Re-design a noisy calendar: time-block deep work, batch meetings, protect maker time, add commute/exercise buffers, and emit an ICS patch and a focus-mode script."),
            ("wearable_health_coach",         "Interpret wearable / fitness data (HRV, sleep, RHR, steps, SpO2) into an actionable, evidence-based weekly coaching plan with safety guardrails."),
            ("game_day_facilitator",          "Plan and run a chaos-engineering game-day: hypothesis, blast radius, rollback, comms tree, inject schedule, success criteria, and a blameless retrospective template."),
            # Content & Creative
            ("cold_email_sequence_writer",    "Write a 5-7 step cold-outreach email sequence for a persona + offer, with subject A/B variants, social proof, objection handling, and a reply-promise CTA. Spam-safe."),
            ("demo_video_script_writer",      "Write a punchy 60-90s product demo video script: hook, problem, demo beats, payoff, CTA — with storyboard, B-roll suggestions, and on-screen copy."),
            ("podcast_show_notes_writer",     "Turn a podcast transcript / outline into SEO-friendly show notes: title, summary, chapter timestamps, key quotes, links, guest bio, and 3 tweet drafts."),
            ("storybook_story_generator",     "Generate an original illustrated children's story for a target age, theme, and moral: outline, full prose, page breaks, illustration prompts, and a printable PDF layout spec."),
            # Sales, Voice & Legal-adjacent
            ("win_loss_analyst",              "Analyse a set of won/lost deals to surface the real reasons — pricing, champion, timing, competitor, fit — and recommend sales-coaching and product fixes."),
            ("voice_agent_designer",          "Design a production voice / phone agent: persona, system prompt, SSML, tool calls, barge-in handling, escalation rules, latency budget, and test utterances."),
            ("court_case_summarizer",         "Summarise a court judgment / order: bench, facts, issues, holdings, reasoning, ratio, and citations in a structured brief. For legal research, not legal advice."),
            # ML / AI Ops
            ("rag_evaluator",                 "Run a RAGAS-style evaluation of a RAG pipeline: context precision/recall, faithfulness, answer relevance, MRR/NDCG, with a runnable eval harness and an improvement plan."),
            ("computer_use_agent",            "Plan a GUI / computer-use task and emit OS-specific step scripts (cliclick / xdotool / PowerShell) with safety approval gates. Pairs with the runtime computer_use tools."),
            ("tracing_emitter",               "Generate an OpenTelemetry tracing bootstrap: service name, resource attributes, auto-instrumentation, sampling, span/metric/log pipeline, and exporter config."),
        ]
    ],

    # ── Provider status ────────────────────────────────────────────────────────
    {
        "name": "timps_list_providers",
        "description": (
            "Show all configured LLM providers and which one is currently active. "
            "Useful for debugging which model is handling agent calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },

    # ── Tool connector ─────────────────────────────────────────────────────────
    {
        "name": "timps_connect_tools",
        "description": (
            "Auto-configure TIMPS Swarm as an MCP server in every AI coding tool "
            "installed on this machine (Cursor, Windsurf, GitHub Copilot, Cline, "
            "Continue, Aider, Goose, OpenCode, Gemini CLI, and more). "
            "Use --dry-run to preview what would change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_id": {"type": "string", "description": "Specific tool to configure, or 'all' (default: all detected)"},
                "dry_run": {"type": "boolean", "description": "Preview only — don't write any files", "default": False},
            },
            "required": [],
        },
    },
    {
        "name": "timps_tool_status",
        "description": (
            "Show which AI coding tools are installed and which ones are already "
            "connected to the TIMPS Swarm MCP server."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Tool handlers
# ─────────────────────────────────────────────────────────────────────────────

AGENT_DESCRIPTIONS = {
    # SDLC
    "orchestrator":          "Routes and coordinates the 10-agent SDLC pipeline",
    "product_manager":       "Writes PRDs and breaks down requirements",
    "architect":             "Designs system architecture and tech stack",
    "code_generator":        "Writes production-quality code",
    "code_reviewer":         "Reviews code for correctness and style",
    "qa_tester":             "Writes and runs automated tests",
    "security_auditor":      "Audits code for OWASP vulnerabilities",
    "performance_optimizer": "Identifies and fixes performance bottlenecks",
    "documentation_writer":  "Writes README, docstrings, API docs",
    "devops":                "Creates Dockerfile, CI/CD, deployment configs",
    # Computer Health
    "system_optimizer":      "Diagnoses slow laptop — CPU hogs, startup bloat, thermal",
    "file_organizer":        "Organises Downloads/Desktop — duplicates, large files, junk",
    "environment_doctor":    "Fixes broken Python/Node/Docker/PATH environments",
    "security_guard":        "Scans open ports, camera/mic permissions, suspicious processes",
    "network_medic":         "Diagnoses WiFi drops, DNS failures, high latency",
    "battery_analyst":       "Identifies energy vampire processes, checks battery health",
    "update_manager":        "Lists pending OS/brew/pip/npm updates, generates safe update script",
    "log_interpreter":       "Reads crash logs and explains them in plain English",
    "privacy_cleaner":       "Audits browser cookies and macOS app permissions",
    "media_librarian":       "Organises photos/videos — rename plan, compression script",
    "backup_sentinel":       "Checks Time Machine, git uncommitted/unpushed, at-risk files",
    "context_switcher":      "Analyses open apps/tabs, generates focus-mode script",
}


def _format_result(result: Dict[str, Any]) -> str:
    """Format an agent result dict as a clean Markdown string for the LLM."""
    agent = result.get("agent", "unknown").replace("_", " ").title()
    report = result.get("report", "")
    report_path = result.get("report_path", "")
    script_path = result.get("script_path", "")
    raw = result.get("raw_data", {})

    lines = [f"# TIMPS {agent} Report\n"]
    lines.append(report)

    if raw:
        lines.append("\n---\n**Quick Stats:**")
        for k, v in raw.items():
            lines.append(f"- `{k}`: {v}")

    if report_path:
        lines.append(f"\n**Full report saved:** `{report_path}`")
    if script_path:
        lines.append(f"**Action script saved:** `{script_path}` (dry-run — review before executing)")

    return "\n".join(lines)


def _handle_list_agents(_args: Dict) -> str:
    lines = ["# TIMPS Swarm — Available Agents\n",
             "## SDLC Pipeline (10 agents) — use `timps_run_task`\n"]
    sdlc = [k for k in AGENT_DESCRIPTIONS if k in {
        "orchestrator", "product_manager", "architect", "code_generator",
        "code_reviewer", "qa_tester", "security_auditor",
        "performance_optimizer", "documentation_writer", "devops",
    }]
    for name in sdlc:
        lines.append(f"- **{name}**: {AGENT_DESCRIPTIONS[name]}")

    lines.append("\n## Computer Health Agents (12 agents)\n")
    health = [k for k in AGENT_DESCRIPTIONS if k not in sdlc]
    for name in health:
        lines.append(f"- **`timps_{name}`**: {AGENT_DESCRIPTIONS[name]}")

    # Domain package agents
    for pkg, label, names in [
        ("intelligence", "Intelligence (6)", ["code_archaeology", "pattern_detector", "technical_debt", "memory_agent", "learning_agent", "agent_composer"]),
        ("aiml",         "AI/ML (7)",        ["prompt_engineer", "dataset_agent", "model_evaluator", "rag_designer", "finetuning_agent", "ai_safety_agent", "vector_db_agent"]),
        ("india",        "India (5)",        ["gst_compliance", "abdm_agent", "upi_agent", "digilocker_agent", "indiehacker_agent"]),
        ("domain",       "Domain (8)",       ["web_scraping", "data_pipeline", "realtime_agent", "mobile_agent", "browser_automation", "graphql_agent", "cli_tool_agent", "embedded_agent"]),
        ("business",     "Business (6)",     ["analytics_agent", "ab_testing_agent", "monetization_agent", "seo_agent", "postmortem_agent", "sprint_planning_agent"]),
        ("infra",        "Infra (6)",        ["load_testing", "feature_flag", "disaster_recovery", "finops_agent", "secrets_management", "edge_agent"]),
        ("emerging",     "Emerging (4)",     ["robotics_agent", "web3_agent", "federated_learning", "quantum_ready"]),
        ("nextgen",      "NextGen (22)",     ["threat_intel_analyst", "security_remediation", "compliance_auditor", "incident_response_coordinator",
                                              "kubernetes_navigator", "pipeline_healer", "docker_compose_architect",
                                              "test_intelligence", "changelog_generator",
                                              "db_migration_pilot", "log_pattern_analyzer", "api_perf_profiler",
                                              "accessibility_tester", "visual_regression_detective",
                                              "release_manager", "tech_writer_assistant",
                                              "model_perf_monitor",
                                              "mcp_server_generator", "ai_workflow_orchestrator", "local_rag_builder", "git_workflow_automator",
                                              "web_search"]),
        ("phase7",       "Phase 7 (32)",     ["red_team_agent", "prompt_injection_scanner", "phishing_simulator",
                                              "api_security_tester", "container_image_scanner",
                                              "contract_reviewer", "dpdp_act_auditor", "fssai_compliance_agent",
                                              "observability_cost_optimizer", "service_mesh_configurator",
                                              "iac_drift_detector", "sbom_generator", "license_compliance_scanner",
                                              "deep_research_agent", "agent_marketplace_curator", "adr_writer",
                                              "churn_predictor", "demand_forecaster", "agri_commodity_forecaster",
                                              "calendar_optimizer", "wearable_health_coach", "game_day_facilitator",
                                              "cold_email_sequence_writer", "demo_video_script_writer",
                                              "podcast_show_notes_writer", "storybook_story_generator",
                                              "win_loss_analyst", "voice_agent_designer", "court_case_summarizer",
                                              "rag_evaluator", "computer_use_agent", "tracing_emitter"]),
    ]:
        lines.append(f"\n## {label} — `src/{pkg}/`\n")
        for name in names:
            lines.append(f"- **`timps_{name}`**")

    return "\n".join(lines)


def _handle_dispatch(args: Dict) -> str:
    from src.computer_agents import dispatch
    request = args.get("request", "")
    result = dispatch(request, {"user_request": request})
    return _format_result(result)


def _handle_full_checkup(args: Dict) -> str:
    from src.computer_health_graph import run_health_task
    request = args.get("focus") or "full system checkup"
    result = run_health_task(request, multi_agent=True)

    lines = ["# TIMPS Full System Checkup\n"]
    if result.get("health_summary"):
        lines.append("## Overall Health Summary\n")
        lines.append(result["health_summary"])

    lines.append(f"\n## Agents Run: {', '.join(result.get('agents_run', []))}\n")

    for r in result.get("reports", []):
        agent = r.get("agent", "").replace("_", " ").title()
        report = (r.get("report") or "")[:600]
        lines.append(f"\n### {agent}\n{report}\n…")
        if r.get("report_path"):
            lines.append(f"_Full report: `{r['report_path']}`_")

    if result.get("action_scripts"):
        lines.append("\n## Action Scripts (dry-run, review before executing):")
        for s in result["action_scripts"]:
            lines.append(f"- `{s}`")

    if result.get("errors"):
        lines.append("\n## Errors:")
        for e in result["errors"]:
            lines.append(f"- {e}")

    return "\n".join(lines)


def _handle_run_task(args: Dict) -> str:
    import asyncio
    from src.layer2_swarm_bridge import get_swarm_bridge
    bridge = get_swarm_bridge()
    request = args.get("request", "")
    language = args.get("language", "python")
    max_iter = int(args.get("max_iterations", 10))

    async def _run():
        return await bridge.run_swarm_task(
            request=request, language=language,
            max_iterations=max_iter, wait_for_completion=True,
        )

    task = asyncio.run(_run())
    lines = [f"# TIMPS SDLC Task: {request}\n",
             f"**Status:** {task.status}\n"]
    for key in ["requirements", "architecture_plan", "test_results",
                "security_report", "documentation", "final_deliverable"]:
        val = task.results.get(key, "") if task.results else ""
        if val:
            lines.append(f"## {key.replace('_', ' ').title()}\n{val[:800]}\n")
    if task.artifacts:
        lines.append(f"## Artifacts\n" + "\n".join(f"- {a}" for a in task.artifacts))
    if task.error:
        lines.append(f"## Error\n{task.error}")
    return "\n".join(lines)


def _handle_context_briefing(args: Dict) -> str:
    from src.context_keeper import get_briefing
    refresh = bool(args.get("refresh", False))
    return get_briefing(regenerate=refresh)


def _handle_delegate(args: Dict) -> str:
    from src.agent_kernel import delegate
    goal = args.get("goal", "")
    context = args.get("context") or {}
    result = delegate(goal, context)
    lines = [
        f"# TIMPS Kernel Run: {result['run_id']}",
        f"**Status:** {result['status']}",
        f"**Tasks:** {result['tasks_done']}/{result['tasks_total']} done, {result['tasks_failed']} failed",
        "",
        result.get("final_report", ""),
    ]
    if result.get("artifacts"):
        lines.append("\n**Artifacts:** " + ", ".join(f"`{a}`" for a in result["artifacts"]))
    return "\n".join(lines)


def _handle_kernel_status(args: Dict) -> str:
    import json
    from pathlib import Path
    run_id = args.get("run_id", "")
    board_path = Path("generated/kernel") / f"run_{run_id}.json"
    if not board_path.exists():
        return f"No kernel run found with id: {run_id}"
    data = json.loads(board_path.read_text())
    done = sum(1 for t in data.get("tasks", []) if t["status"] == "done")
    total = len(data.get("tasks", []))
    report_snippet = (data.get("final_report") or "In progress…")[:1000]
    return f"Run `{run_id}`: status={data['status']}, tasks={done}/{total} done\n\n{report_snippet}"


def _handle_health_agent(agent_name: str, args: Dict) -> str:
    agents = _import_agents()
    node_fn = agents[agent_name]
    state: Dict[str, Any] = {"user_request": args.get("context") or args.get("focus") or ""}
    if args.get("log_path"):
        state["user_request"] = args["log_path"]
    if args.get("path"):
        # Override default scan path by injecting into state
        state["_scan_path"] = args["path"]
    result = node_fn(state)
    return _format_result(result)


def _handle_expert_agent(agent_name: str, args: Dict) -> str:
    from src.expert_agents import EXPERT_AGENT_MAP
    node_fn = EXPERT_AGENT_MAP[agent_name]
    state: Dict[str, Any] = {
        "user_request": args.get("goal") or args.get("context") or "",
        "repo_path": args.get("repo_path") or "",
        "plan_text": args.get("plan_text") or "",
        "window_minutes": args.get("window_minutes") or 30,
    }
    if args.get("hosts"):
        state["_extra_hosts"] = args["hosts"]
    if args.get("branch_a"):
        state["user_request"] = f"predict conflicts between {args['branch_a']} and {args.get('branch_b', 'main')}"
    result = node_fn(state)
    return _format_result(result)


def _handle_dev_agent(agent_name: str, args: Dict) -> str:
    """Dispatch to developer_swarm_agents functions."""
    from src.developer_swarm_agents import DEVELOPER_AGENTS
    fn = DEVELOPER_AGENTS[agent_name]
    # Map MCP argument names to function signatures
    arg_map = {
        "issue_triager":        lambda a: fn(a.get("request", ""), a.get("repo_path")),
        "boilerplate_architect": lambda a: fn(a.get("request", ""), a.get("language", "python")),
        "pr_reviewer":          lambda a: fn(a.get("diff", ""), a.get("style_guide", "")),
        "dependency_sentinel":  lambda a: fn(a.get("manifest", ""), a.get("manifest_type", "auto")),
        "unit_test_writer":     lambda a: fn(a.get("source_code", ""), a.get("language", "python"), a.get("framework", "auto")),
        "docstring_generator":  lambda a: fn(a.get("source_code", ""), a.get("language", "python"), a.get("doc_style", "google")),
        "log_detective":        lambda a: fn(a.get("logs", ""), a.get("service", "app")),
        "sql_optimizer":        lambda a: fn(a.get("query", ""), a.get("explain_output", ""), a.get("db_engine", "postgresql")),
        "sprint_reporter":      lambda a: fn(a.get("completed", []), a.get("in_progress", []), a.get("blockers", []), a.get("team_member", "Developer")),
        "flaky_test_hunter":    lambda a: fn(a.get("ci_history", ""), a.get("repo_path")),
        "api_contract_auditor": lambda a: fn(a.get("old_spec", ""), a.get("new_spec", ""), a.get("format", "openapi")),
        "content_multiplier":   lambda a: fn(a.get("content", ""), a.get("tone", "technical")),
    }
    result = arg_map[agent_name](args)
    # Format the result dict as readable markdown
    if isinstance(result, dict):
        lines = [f"# TIMPS {agent_name.replace('_', ' ').title()}\n"]
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (list, dict)):
                lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```\n")
            else:
                lines.append(f"**{k}:** {v}\n")
        return "\n".join(lines)
    return str(result)


def _handle_knowledge_agent(agent_name: str, args: Dict) -> str:
    """Dispatch to knowledge_swarm_agents functions."""
    from src.knowledge_swarm_agents import KNOWLEDGE_AGENTS
    fn = KNOWLEDGE_AGENTS[agent_name]
    arg_map = {
        "inbox_gatekeeper":  lambda a: fn(a.get("emails", []), a.get("context", "")),
        "meeting_condenser": lambda a: fn(a.get("transcript", ""), a.get("attendees")),
        "research_scout":    lambda a: fn(a.get("topic", ""), a.get("depth", "medium")),
        "trend_monitor":     lambda a: fn(a.get("keywords", []), a.get("sources")),
        "data_wrangler":     lambda a: fn(a.get("data", ""), None, a.get("format", "auto")),
        "competitor_tracker": lambda a: fn(a.get("competitors", []), a.get("focus_areas")),
    }
    result = arg_map[agent_name](args)
    if isinstance(result, dict):
        lines = [f"# TIMPS {agent_name.replace('_', ' ').title()}\n"]
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (list, dict)):
                lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```\n")
            else:
                lines.append(f"**{k}:** {v}\n")
        return "\n".join(lines)
    return str(result)


def _handle_connect_tools(args: Dict) -> str:
    from src.tool_connectors import connect_tool, connect_all, TOOLS as TC_TOOLS
    tool_id = args.get("tool_id", "all")
    dry_run = bool(args.get("dry_run", False))

    if tool_id and tool_id != "all":
        results = [connect_tool(tool_id, dry_run=dry_run)]
    else:
        results = connect_all(dry_run=dry_run, installed_only=True)

    lines = ["# TIMPS Tool Connector\n"]
    for r in results:
        icon = {"ok": "✅", "skipped": "⏭️", "error": "❌", "dry_run": "👀"}.get(r.get("status", ""), "?")
        lines.append(f"{icon} **{r.get('tool', r.get('id', '?'))}** — {r.get('message', '')}")
        if r.get("config_path"):
            lines.append(f"   Config: `{r['config_path']}`")

    if not results:
        lines.append("No installed tools detected. Install a tool and run again, or pass a specific `tool_id`.")

    return "\n".join(lines)


def _handle_tool_status(args: Dict) -> str:
    from src.tool_connectors import status_report
    report = status_report()
    lines = ["# TIMPS — Connected AI Coding Tools\n"]

    if report["connected"]:
        lines.append(f"## ✅ Connected ({len(report['connected'])})")
        for t in report["connected"]:
            lines.append(f"- {t['icon']} **{t['name']}**")

    if report["detected_not_configured"]:
        lines.append(f"\n## ⚠️ Detected but not configured ({len(report['detected_not_configured'])})")
        for t in report["detected_not_configured"]:
            lines.append(f"- {t['icon']} **{t['name']}** → use `timps_connect_tools` with `tool_id: {t['id']}`")

    if report["cloud_tools"]:
        lines.append(f"\n## ☁️ Cloud tools (manual setup)")
        for t in report["cloud_tools"]:
            lines.append(f"- **{t['name']}** → [{t['docs']}]({t['docs']})")

    lines.append(f"\n_Not installed: {len(report['not_installed'])} tools_")
    return "\n".join(lines)


def _handle_priority_agent(agent_name: str, args: Dict) -> str:
    """Dispatch to priority_agents functions (Phase 3 new agents)."""
    from src.priority_agents import PRIORITY_AGENTS
    fn = PRIORITY_AGENTS[agent_name]
    result = fn(args)
    if isinstance(result, dict):
        lines = [f"# TIMPS {agent_name.replace('_', ' ').title()}\n"]
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (list, dict)):
                lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```\n")
            else:
                lines.append(f"**{k}:** {v}\n")
        return "\n".join(lines)
    return str(result)


def _handle_more_agent(agent_name: str, args: Dict) -> str:
    """Dispatch to more_agents functions (Phase 5 new agents)."""
    from src.more_agents import MORE_AGENTS
    fn = MORE_AGENTS[agent_name]
    result = fn(args)
    if isinstance(result, dict):
        lines = [f"# TIMPS {agent_name.replace('_', ' ').title()}\n"]
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (list, dict)):
                try:
                    lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```\n")
                except TypeError:
                    lines.append(f"**{k}:** {str(v)[:500]}\n")
            elif isinstance(v, str) and len(v) > 500:
                lines.append(f"**{k}:**\n```\n{v[:2000]}\n```\n")
            else:
                lines.append(f"**{k}:** {v}\n")
        return "\n".join(lines)
    return str(result)


def _handle_domain_agent(package_name: str, agent_name: str, args: Dict) -> str:
    """Generic handler for all domain-package agents."""
    import importlib
    mod = importlib.import_module(f"src.{package_name}")
    agents_dict_name = f"{package_name.upper()}_AGENTS"
    agents_dict = getattr(mod, agents_dict_name, None)
    if agents_dict is None:
        raise ValueError(f"No {agents_dict_name} found in src.{package_name}")
    fn = agents_dict.get(agent_name)
    if fn is None:
        raise ValueError(f"Agent '{agent_name}' not in {agents_dict_name}")
    result = fn(args)
    if isinstance(result, dict):
        lines = [f"# TIMPS {agent_name.replace('_', ' ').title()}\n"]
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (list, dict)):
                try:
                    lines.append(f"**{k}:**\n```json\n{json.dumps(v, indent=2)}\n```\n")
                except TypeError:
                    lines.append(f"**{k}:** {str(v)[:500]}\n")
            elif isinstance(v, str) and len(v) > 500:
                lines.append(f"**{k}:**\n```\n{v[:2000]}\n```\n")
            else:
                lines.append(f"**{k}:** {v}\n")
        return "\n".join(lines)
    return str(result)


def _handle_list_providers(_args: Dict) -> str:
    from src.providers import list_providers
    providers = list_providers()
    lines = ["# TIMPS — LLM Provider Status\n"]
    for p in providers:
        icon = "✅" if p["available"] else "⬜"
        active = " **(ACTIVE)**" if p == next((x for x in providers if x["available"]), None) else ""
        lines.append(f"{icon} **{p['name']}** — `{p['model']}`{active}")
        lines.append(f"   {p['description']}")
    lines.append(
        "\nTo switch providers, set the relevant env var: "
        "`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`"
    )
    return "\n".join(lines)


# Map tool name → handler
_TOOL_HANDLERS: Dict[str, Any] = {
    "timps_list_agents":        lambda a: _handle_list_agents(a),
    "timps_dispatch":           lambda a: _handle_dispatch(a),
    "timps_full_checkup":       lambda a: _handle_full_checkup(a),
    "timps_run_task":           lambda a: _handle_run_task(a),
    "timps_system_optimizer":   lambda a: _handle_health_agent("system_optimizer",   a),
    "timps_file_organizer":     lambda a: _handle_health_agent("file_organizer",     a),
    "timps_environment_doctor": lambda a: _handle_health_agent("environment_doctor", a),
    "timps_security_guard":     lambda a: _handle_health_agent("security_guard",     a),
    "timps_network_medic":      lambda a: _handle_health_agent("network_medic",      a),
    "timps_battery_analyst":    lambda a: _handle_health_agent("battery_analyst",    a),
    "timps_update_manager":     lambda a: _handle_health_agent("update_manager",     a),
    "timps_log_interpreter":    lambda a: _handle_health_agent("log_interpreter",    a),
    "timps_privacy_cleaner":    lambda a: _handle_health_agent("privacy_cleaner",    a),
    "timps_media_librarian":    lambda a: _handle_health_agent("media_librarian",    a),
    "timps_backup_sentinel":    lambda a: _handle_health_agent("backup_sentinel",    a),
    "timps_context_switcher":   lambda a: _handle_health_agent("context_switcher",   a),
    "timps_context_briefing":   lambda a: _handle_context_briefing(a),
    "timps_delegate":            lambda a: _handle_delegate(a),
    "timps_kernel_status":       lambda a: _handle_kernel_status(a),
    # Expert agents
    "timps_dependency_rebel":         lambda a: _handle_expert_agent("dependency_rebel", a),
    "timps_merge_conflict_predictor": lambda a: _handle_expert_agent("merge_conflict_predictor", a),
    "timps_tech_debt_quantifier":     lambda a: _handle_expert_agent("tech_debt_quantifier", a),
    "timps_migration_pilot":          lambda a: _handle_expert_agent("migration_pilot", a),
    "timps_flaky_test_detective":     lambda a: _handle_expert_agent("flaky_test_detective", a),
    "timps_onboarding_mentor":        lambda a: _handle_expert_agent("onboarding_mentor", a),
    "timps_incident_responder":       lambda a: _handle_expert_agent("incident_responder", a),
    "timps_cloud_cost_auditor":       lambda a: _handle_expert_agent("cloud_cost_auditor", a),
    "timps_certificate_rotator":      lambda a: _handle_expert_agent("certificate_rotator", a),
    "timps_terraform_plan_reviewer":  lambda a: _handle_expert_agent("terraform_plan_reviewer", a),
    "timps_dotfile_doctor":           lambda a: _handle_expert_agent("dotfile_doctor", a),
    "timps_disk_space_prophet":       lambda a: _handle_expert_agent("disk_space_prophet", a),
    # Developer Swarm agents
    "timps_issue_triager":        lambda a: _handle_dev_agent("issue_triager", a),
    "timps_boilerplate_architect": lambda a: _handle_dev_agent("boilerplate_architect", a),
    "timps_pr_reviewer":          lambda a: _handle_dev_agent("pr_reviewer", a),
    "timps_dependency_sentinel":  lambda a: _handle_dev_agent("dependency_sentinel", a),
    "timps_unit_test_writer":     lambda a: _handle_dev_agent("unit_test_writer", a),
    "timps_docstring_generator":  lambda a: _handle_dev_agent("docstring_generator", a),
    "timps_log_detective":        lambda a: _handle_dev_agent("log_detective", a),
    "timps_sql_optimizer":        lambda a: _handle_dev_agent("sql_optimizer", a),
    "timps_sprint_reporter":      lambda a: _handle_dev_agent("sprint_reporter", a),
    "timps_flaky_test_hunter":    lambda a: _handle_dev_agent("flaky_test_hunter", a),
    "timps_api_contract_auditor": lambda a: _handle_dev_agent("api_contract_auditor", a),
    "timps_content_multiplier":   lambda a: _handle_dev_agent("content_multiplier", a),
    # Knowledge Worker agents
    "timps_inbox_gatekeeper":    lambda a: _handle_knowledge_agent("inbox_gatekeeper", a),
    "timps_meeting_condenser":   lambda a: _handle_knowledge_agent("meeting_condenser", a),
    "timps_research_scout":      lambda a: _handle_knowledge_agent("research_scout", a),
    "timps_trend_monitor":       lambda a: _handle_knowledge_agent("trend_monitor", a),
    "timps_data_wrangler":       lambda a: _handle_knowledge_agent("data_wrangler", a),
    "timps_competitor_tracker":  lambda a: _handle_knowledge_agent("competitor_tracker", a),
    # NEW priority agents (Phase 3)
    "timps_research_agent":      lambda a: _handle_priority_agent("research_agent", a),
    "timps_api_design_agent":    lambda a: _handle_priority_agent("api_design_agent", a),
    "timps_db_agent":            lambda a: _handle_priority_agent("db_agent", a),
    "timps_dependency_agent":    lambda a: _handle_priority_agent("dependency_agent", a),
    "timps_n8n_workflow_agent":  lambda a: _handle_priority_agent("n8n_workflow_agent", a),
    # NEW more agents (Phase 5)
    "timps_refactoring_agent":   lambda a: _handle_more_agent("refactoring_agent", a),
    "timps_test_data_agent":     lambda a: _handle_more_agent("test_data_agent", a),
    "timps_monitoring_agent":    lambda a: _handle_more_agent("monitoring_agent", a),
    "timps_ui_ux_agent":         lambda a: _handle_more_agent("ui_ux_agent", a),
    "timps_i18n_agent":          lambda a: _handle_more_agent("i18n_agent", a),
    "timps_cost_optimizer":      lambda a: _handle_more_agent("cost_optimizer", a),
    "timps_self_critic_agent":   lambda a: _handle_more_agent("self_critic_agent", a),
    # NEW domain package agents (47 agents across 7 packages)
    **{
        f"timps_{name}": (lambda pkg, ag: lambda a: _handle_domain_agent(pkg, ag, a))(pkg, name)
        for pkg, names in [
            ("intelligence", ["code_archaeology", "pattern_detector", "technical_debt",
                              "memory_agent", "learning_agent", "agent_composer"]),
            ("aiml",         ["prompt_engineer", "dataset_agent", "model_evaluator",
                              "rag_designer", "finetuning_agent", "ai_safety_agent", "vector_db_agent"]),
            ("india",        ["gst_compliance", "abdm_agent", "upi_agent",
                              "digilocker_agent", "indiehacker_agent"]),
            ("domain",       ["web_scraping", "data_pipeline", "realtime_agent", "mobile_agent",
                              "browser_automation", "graphql_agent", "cli_tool_agent", "embedded_agent"]),
            ("business",     ["analytics_agent", "ab_testing_agent", "monetization_agent",
                              "seo_agent", "postmortem_agent", "sprint_planning_agent"]),
            ("infra",        ["load_testing", "feature_flag", "disaster_recovery",
                              "finops_agent", "secrets_management", "edge_agent"]),
            ("emerging",     ["robotics_agent", "web3_agent", "federated_learning", "quantum_ready"]),
            ("nextgen",      ["threat_intel_analyst", "security_remediation", "compliance_auditor", "incident_response_coordinator",
                              "kubernetes_navigator", "pipeline_healer", "docker_compose_architect",
                              "test_intelligence", "changelog_generator",
                              "db_migration_pilot", "log_pattern_analyzer", "api_perf_profiler",
                              "accessibility_tester", "visual_regression_detective",
                              "release_manager", "tech_writer_assistant",
                              "model_perf_monitor",
                              "mcp_server_generator", "ai_workflow_orchestrator", "local_rag_builder", "git_workflow_automator",
                              "web_search"]),
            ("phase7",       ["red_team_agent", "prompt_injection_scanner", "phishing_simulator",
                              "api_security_tester", "container_image_scanner",
                              "contract_reviewer", "dpdp_act_auditor", "fssai_compliance_agent",
                              "observability_cost_optimizer", "service_mesh_configurator",
                              "iac_drift_detector", "sbom_generator", "license_compliance_scanner",
                              "deep_research_agent", "agent_marketplace_curator", "adr_writer",
                              "churn_predictor", "demand_forecaster", "agri_commodity_forecaster",
                              "calendar_optimizer", "wearable_health_coach", "game_day_facilitator",
                              "cold_email_sequence_writer", "demo_video_script_writer",
                              "podcast_show_notes_writer", "storybook_story_generator",
                              "win_loss_analyst", "voice_agent_designer", "court_case_summarizer",
                              "rag_evaluator", "computer_use_agent", "tracing_emitter"]),
        ]
        for name in names
    },
    # Provider status
    "timps_list_providers":      lambda a: _handle_list_providers(a),
    # Tool connector
    "timps_connect_tools":       lambda a: _handle_connect_tools(a),
    "timps_tool_status":         lambda a: _handle_tool_status(a),
}


# ─────────────────────────────────────────────────────────────────────────────
# MCP JSON-RPC 2.0 server (stdio transport)
# ─────────────────────────────────────────────────────────────────────────────

def _make_response(id_: Any, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id_, "result": result})


def _make_error(id_: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def _handle_request(msg: Dict) -> Optional[str]:
    """Process one JSON-RPC message and return a response string (or None for notifications)."""
    method = msg.get("method", "")
    id_ = msg.get("id")
    params = msg.get("params") or {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    if method == "initialize":
        global _CLIENT_NAME, _CLIENT_SUPPORTS_SAMPLING
        client_info = params.get("clientInfo") or {}
        _CLIENT_NAME = client_info.get("name", "unknown")
        client_caps = params.get("capabilities") or {}
        _CLIENT_SUPPORTS_SAMPLING = "sampling" in client_caps
        # Debug: dump full initialize params so we can inspect capabilities
        import pathlib, datetime
        _dbg = pathlib.Path("/tmp/timps-mcp-debug.json")
        _dbg.write_text(json.dumps({
            "ts": datetime.datetime.now().isoformat(),
            "client": _CLIENT_NAME,
            "caps": client_caps,
            "sampling_detected": _CLIENT_SUPPORTS_SAMPLING,
            "full_params": params,
        }, indent=2))
        logger.warning(
            "Client connected: %s | capabilities: %s | sampling=%s",
            _CLIENT_NAME, list(client_caps.keys()), _CLIENT_SUPPORTS_SAMPLING
        )
        # Register the sampler so LLMRouter uses it for all subsequent calls
        try:
            from src.llm_router import set_mcp_sampler
            set_mcp_sampler(_mcp_sample, supports_sampling=_CLIENT_SUPPORTS_SAMPLING)
        except Exception:
            pass
        return _make_response(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
                "sampling": {},   # server may send sampling/createMessage
            },
            "serverInfo": {
                "name": "timps-swarm",
                "version": "2.0.0",
                "description": (
                    "TIMPS Swarm: 51 AI agents — SDLC, computer health, developer "
                    "workflow, and knowledge worker tools."
                ),
            },
        })

    if method == "notifications/initialized":
        return None   # notification — no response

    if method == "ping":
        return _make_response(id_, {})

    # ── Tool discovery ─────────────────────────────────────────────────────────
    if method == "tools/list":
        return _make_response(id_, {"tools": TOOLS})

    # ── Tool execution ─────────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        # ── API key authentication ─────────────────────────────────────────
        try:
            from src.auth import check_request_auth
            if not check_request_auth(arguments):
                return _make_error(id_, -32001, (
                    "Authentication required. Add '_api_key' to your tool arguments. "
                    "Generate a key with: python3 give_work.py --keygen \"your-name\""
                ))
        except ImportError:
            pass  # auth module not available — open access

        handler = _TOOL_HANDLERS.get(tool_name)
        if not handler:
            return _make_error(id_, -32601, f"Unknown tool: {tool_name}")

        try:
            text = handler(arguments)
            return _make_response(id_, {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            })
        except Exception as exc:
            err_text = f"Tool {tool_name} failed:\n{traceback.format_exc()}"
            logger.error(err_text)
            return _make_response(id_, {
                "content": [{"type": "text", "text": err_text}],
                "isError": True,
            })

    # ── Unknown method ─────────────────────────────────────────────────────────
    if id_ is not None:
        return _make_error(id_, -32601, f"Method not found: {method}")
    return None


def run_server():
    """Main loop: read JSON-RPC from stdin, write responses to stdout."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s [timps-mcp] %(message)s",
        stream=sys.stderr,   # MCP uses stderr for logs, stdout for protocol
    )
    logger.warning("TIMPS Swarm MCP server starting (stdio transport)…")

    # Use binary mode + manual newline split for cross-platform reliability
    stdin  = sys.stdin.buffer
    stdout = sys.stdout.buffer

    # Expose the I/O handles so _mcp_sample() can use them
    global _STDIN_BUF, _STDOUT_BUF
    _STDIN_BUF  = stdin
    _STDOUT_BUF = stdout

    while True:
        try:
            line = stdin.readline()
            if not line:
                break   # EOF — client disconnected
            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                response = _make_error(None, -32700, f"Parse error: {exc}")
                stdout.write((response + "\n").encode())
                stdout.flush()
                continue

            response = _handle_request(msg)
            if response is not None:
                stdout.write((response + "\n").encode())
                stdout.flush()

        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error("Unhandled error: %s", exc, exc_info=True)


if __name__ == "__main__":
    run_server()
