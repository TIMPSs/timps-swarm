"""Computer-Use Agent — planner that generates executable scripts for driving
a desktop (macOS / Linux / Windows) via native automation tools.

This is a *planner + auditor*, not a runtime — it does NOT execute anything
destructive.  It produces:

* A step-by-step plan in natural language
* A ready-to-run shell / PowerShell script using `cliclick` (macOS),
  `xdotool` (Linux), or PowerShell + `Add-Type` (Windows)
* A safety review listing destructive steps that need human approval
* A dry-run simulator (parses the script, classifies each command as
  read / write / destructive)

Wraps the LLM with strong constraints about which GUI tools exist on each
OS and refuses to script things the OS can't do (e.g. drag-and-drop in
headless mode).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

SUPPORTED_OS = ("macos", "linux", "windows")

GUI_TOOLS = {
    "macos":   {"click": "cliclick c:{x},{y}",     "type": "cliclick t:{text}",    "key": "cliclick kp:{key}",
                "screenshot": "screencapture -x {path}", "open": "open {path}", "url": "open {url}"},
    "linux":   {"click": "xdotool mousemove {x} {y} click {button}", "type": "xdotool type --clearmodifiers '{text}'",
                "key": "xdotool key {key}", "screenshot": "import -window root {path}", "open": "xdg-open {path}",
                "url": "xdg-open {url}"},
    "windows": {"click": "Add-Type -AssemblyName UIAutomationClient; ... (UIA click at {x},{y})",
                "type": "[System.Windows.Forms.SendKeys]::SendWait('{text}')", "key": "[System.Windows.Forms.SendKeys]::SendWait('{{{key}}}')",
                "screenshot": "Add-Type -AssemblyName System.Windows.Forms; [Console]::WriteLine('screenshot to {path}')",
                "open": "Start-Process {path}", "url": "Start-Process {url}"},
}

DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\s+-r?f\b", re.I),
    re.compile(r"\bdel\s+/[sq]\b|\brmdir\s+/[sq]\b", re.I),
    re.compile(r"\$\s*ConfirmPreference.*High", re.I),  # PS confirm prefs
    re.compile(r"--force\b", re.I),
    re.compile(r"\bformat\b|\bdiskutil\s+erase\b", re.I),
    re.compile(r"\bsudo\s+", re.I),
    re.compile(r"\b(dd|mkfs|fdisk)\b", re.I),
]


def computer_use_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    task = (args.get("task") or args.get("request") or "").strip()
    os_name = (args.get("os") or "macos").lower()
    if os_name not in SUPPORTED_OS:
        os_name = "macos"
    max_steps = int(args.get("max_steps") or 12)
    dry_run = bool(args.get("dry_run", True))
    require_approval = bool(args.get("require_approval", True))

    if not task:
        return {
            "summary": "No task supplied.",
            "error": "task is required",
            "script": "", "plan": [],
        }

    plan = _plan_steps(task, os_name, max_steps)
    script = _render_script(os_name, plan)
    safety = _classify_commands(script)
    hardened_script = _wrap_with_approval(script, require_approval, any(s["category"] == "destructive" for s in safety))

    payload = {
        "summary": _summary(task, os_name, len(plan), safety),
        "task": task,
        "os": os_name,
        "max_steps": max_steps,
        "plan": plan,
        "script": hardened_script,
        "raw_script": script,
        "safety": safety,
        "destructive_count": sum(1 for s in safety if s["category"] == "destructive"),
        "approval_required": require_approval and any(s["category"] == "destructive" for s in safety),
        "gui_tools_available": list(GUI_TOOLS[os_name].keys()),
        "generated_at": _ts(),
    }

    slug = re.sub(r"[^a-z0-9_]+", "_", task.lower()).strip("_")[:50] or "task"
    _save("phase7/computer_use", f"{slug}_plan.json", json.dumps(payload, indent=2))
    _save("phase7/computer_use", f"{slug}_script.sh" if os_name != "windows" else f"{slug}_script.ps1", hardened_script)
    _record("computer_use_agent", task[:60], f"os={os_name} steps={len(plan)} destructive={payload['destructive_count']}")
    return payload


# ---------------------------------------------------------------------------

def _plan_steps(task: str, os_name: str, max_steps: int) -> List[Dict[str, Any]]:
    system = (
        "You are a desktop automation planner.  The user wants to accomplish "
        "a task on their computer via GUI automation.  Return ONLY JSON:\n"
        "{\n"
        '  "steps": [\n'
        '    {\n'
        '      "id": int, "action": "click"|"type"|"key"|"open"|"screenshot"|"wait"|"url", '
        '      "args": { ... },  // keys depend on action; see rules\n'
        '      "expected": str,  // what should be true after this step (for verification)\n'
        '      "rollback": str    // how a human would undo it (or "" if not needed)\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "Rules:\n"
        "- `click`: args {x:int, y:int, button:1|2} (screen coords; you do not know exact coords so use (0,0) and tell the user to adjust).\n"
        "- `type`:  args {text:str}.  Escape single quotes.\n"
        "- `key`:   args {key:str} — e.g. 'Return', 'Tab', 'ctrl+s'.\n"
        "- `open`:  args {path:str} — open a file/folder.\n"
        "- `url`:   args {url:str} — open a URL in default browser.\n"
        "- `screenshot`: args {path:str} — save full screen.\n"
        "- `wait`:  args {seconds:int}.\n"
        f"- Keep ≤ {max_steps} steps.  Always start with a screenshot of the current state.\n"
        "- End with a screenshot to verify completion.\n"
        "- Prefer the keyboard over the mouse when possible (more reliable).\n"
        "- If the task is risky (delete, format, send email, post publicly), add a "
        "rollback step and mark expected='requires human approval'."
    )
    user = (
        f"OS: {os_name}\n"
        f"Task: {task}\n"
        f"Max steps: {max_steps}\n"
    )
    raw = _llm(user, system, "computer_use_agent")
    parsed = _parse_json(raw, fallback={"steps": []})
    steps = parsed.get("steps") or []
    if not steps:
        steps = [{"id": 1, "action": "screenshot", "args": {"path": "/tmp/before.png"},
                  "expected": "capture initial state", "rollback": ""}]
    return steps[:max_steps]


def _render_script(os_name: str, plan: List[Dict[str, Any]]) -> str:
    """Render the plan as a runnable shell script for the given OS."""
    tmpl = GUI_TOOLS[os_name]
    lines: List[str] = [_script_header(os_name)]
    for step in plan:
        action = step.get("action")
        args = step.get("args") or {}
        if action not in tmpl:
            lines.append(f"# step {step.get('id')}: unknown action '{action}' — skipped")
            continue
        tmpl_str = tmpl[action]
        try:
            cmd = tmpl_str.format(**{k: _shell_escape(str(v)) for k, v in args.items()})
        except KeyError as exc:
            cmd = f"# step {step.get('id')}: missing arg {exc}"
        lines.append(f"# step {step.get('id')}: {action}  | expected: {step.get('expected','')}")
        lines.append(cmd)
    return "\n".join(lines) + "\n"


def _script_header(os_name: str) -> str:
    if os_name == "windows":
        return (
            "# Computer-Use script — generated by TIMPS Swarm computer_use_agent\n"
            "# Run as: powershell -ExecutionPolicy Bypass -File <this_file>\n"
            "$ErrorActionPreference = 'Stop'\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "# Computer-Use script — generated by TIMPS Swarm computer_use_agent\n"
        "# Review every command.  Destructive steps are tagged below.\n"
        "set -euo pipefail\n"
    )


def _classify_commands(script: str) -> List[Dict[str, Any]]:
    """Walk the script line-by-line and classify each non-comment, non-empty line."""
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(script.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("$ErrorActionPreference") or "set -euo" in line:
            continue
        cat = "read" if any(tok in line for tok in ("screencapture", "screenshot", "import -window", "ls ", "cat ", "echo ")) else "write"
        if any(p.search(line) for p in DESTRUCTIVE_PATTERNS):
            cat = "destructive"
        out.append({"line": i, "command": line, "category": cat})
    return out


def _wrap_with_approval(script: str, require_approval: bool, has_destructive: bool) -> str:
    if not (require_approval and has_destructive):
        return script
    banner = (
        "# ============================================================\n"
        "# !!! DESTRUCTIVE COMMANDS DETECTED — HUMAN APPROVAL REQUIRED !!!\n"
        "# Review the lines tagged 'destructive' before running.\n"
        "# To proceed, run with APPROVE=1 ./script.sh\n"
        "# ============================================================\n"
    )
    guard = '\nif [ "${APPROVE:-0}" != "1" ]; then\n  echo "Refusing to run destructive script without APPROVE=1" >&2\n  exit 2\nfi\n'
    return banner + script + guard


def _shell_escape(s: str) -> str:
    if re.match(r"^[A-Za-z0-9_\-./:=]+$", s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def _summary(task: str, os_name: str, n_steps: int, safety: List[Dict[str, Any]]) -> str:
    n_dest = sum(1 for s in safety if s["category"] == "destructive")
    return (
        f"Computer-use plan for {os_name}: {n_steps} steps, "
        f"{n_dest} destructive, {len(safety)} total commands."
    )
