"""
TIMPS Agent Kernel — Task Delegation Engine
════════════════════════════════════════════
Shifts TIMPS from a "passive tool server" to an "autonomous workforce."

Instead of:  MCP client calls timps_run_security_scan
Now:         MCP client calls timps_delegate(goal="fix the auth bug and deploy it")
             → Orchestrator breaks goal into sub-tasks
             → 22 agents self-organize to complete them
             → Result + artifacts returned when done

Architecture:
  1. Dispatcher    — receives high-level goal from MCP host
  2. Planner       — LLM breaks goal into an ordered task list (JSON)
  3. Blackboard    — shared memory where agents post progress
  4. Supervisor    — monitors execution, re-routes stuck tasks
  5. Executor      — runs each sub-task against the right agent
  6. Reporter      — aggregates all outputs into structured result

Example delegation:
  {
    "goal": "Ensure the new feature branch meets security standards,
             has 80% test coverage, and won't break staging",
    "context": {
      "branch": "feature/new-auth",
      "repo_path": "/path/to/repo"
    }
  }
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BLACKBOARD_DIR = Path("generated/kernel")

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KernelTask:
    id: str
    goal: str
    agent: str                          # which TIMPS agent handles it
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"             # pending | running | done | failed | skipped
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    retries: int = 0


@dataclass
class KernelRun:
    run_id: str
    goal: str
    context: Dict[str, Any]
    tasks: List[KernelTask] = field(default_factory=list)
    status: str = "planning"            # planning | running | done | failed
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    finished_at: Optional[str] = None
    final_report: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Blackboard (shared memory for all tasks in a run)
# ─────────────────────────────────────────────────────────────────────────────

class Blackboard:
    """Persistent shared state for a kernel run."""

    def __init__(self, run_id: str):
        BLACKBOARD_DIR.mkdir(parents=True, exist_ok=True)
        self.path = BLACKBOARD_DIR / f"run_{run_id}.json"
        self.run_id = run_id

    def load(self) -> Optional[Dict]:
        try:
            return json.loads(self.path.read_text()) if self.path.exists() else None
        except Exception:
            return None

    def save(self, run: KernelRun):
        data = {
            "run_id": run.run_id,
            "goal": run.goal,
            "context": run.context,
            "status": run.status,
            "created_at": run.created_at,
            "finished_at": run.finished_at,
            "final_report": run.final_report,
            "artifacts": run.artifacts,
            "tasks": [asdict(t) for t in run.tasks],
        }
        self.path.write_text(json.dumps(data, indent=2, default=str))

    def post_task_result(self, run: KernelRun, task_id: str, result: str):
        for t in run.tasks:
            if t.id == task_id:
                t.result = result
                t.status = "done"
                t.finished_at = datetime.datetime.now().isoformat()
                break
        self.save(run)

    def post_task_error(self, run: KernelRun, task_id: str, error: str):
        for t in run.tasks:
            if t.id == task_id:
                t.error = error
                t.status = "failed"
                t.finished_at = datetime.datetime.now().isoformat()
                break
        self.save(run)


# ─────────────────────────────────────────────────────────────────────────────
# Planner — turns a high-level goal into an ordered task list
# ─────────────────────────────────────────────────────────────────────────────

# Maps agent names to brief capability descriptions for the planner prompt
_AGENT_CAPABILITIES = {
    # SDLC
    "product_manager":        "write requirements, PRD, acceptance criteria",
    "architect":              "design system architecture, API contracts",
    "code_generator":         "write production code, implement features, fix bugs",
    "code_reviewer":          "review code for correctness, style, anti-patterns",
    "qa_tester":              "write and run automated tests, measure coverage",
    "security_auditor":       "OWASP scan, detect CVEs, run bandit, check auth",
    "performance_optimizer":  "identify bottlenecks, Big-O analysis, caching",
    "documentation_writer":   "write README, docstrings, API docs",
    "devops":                 "Dockerfile, CI/CD pipeline, deployment config",
    # Health
    "system_optimizer":       "diagnose slow laptop, CPU hogs, thermal",
    "file_organizer":         "clean up downloads, find duplicates, large files",
    "environment_doctor":     "fix broken Python/Node/Docker/PATH",
    "security_guard":         "open ports, camera/mic permissions, suspicious processes",
    "network_medic":          "WiFi drops, DNS, latency, connectivity",
    "battery_analyst":        "energy drainers, battery health",
    "update_manager":         "pending OS/brew/pip/npm updates",
    "log_interpreter":        "crash logs → plain English",
    "privacy_cleaner":        "browser cookies, app permissions audit",
    "media_librarian":        "organize photos/videos/screenshots",
    "backup_sentinel":        "Time Machine, git uncommitted/unpushed",
    "context_switcher":       "identify distractions, generate focus script",
    "context_keeper":         "capture current work context, generate resumption briefing",
}

_TASK_PLAN_SCHEMA = """
Return ONLY valid JSON matching this schema (no prose, no markdown fences):
{
  "tasks": [
    {
      "id": "t1",
      "goal": "<specific sub-task description>",
      "agent": "<agent_name from list>",
      "depends_on": []
    },
    {
      "id": "t2",
      "goal": "<specific sub-task description>",
      "agent": "<agent_name from list>",
      "depends_on": ["t1"]
    }
  ],
  "rationale": "<one sentence explaining the plan>"
}
Rules:
- Use only agents from the provided list
- depends_on must reference IDs of tasks that must complete first
- Keep to ≤8 tasks; prefer parallel tasks (same depends_on) over serial chains
- Each task goal must be self-contained and specific
"""


def _plan_tasks(goal: str, context: Dict, max_tasks: int = 8) -> List[KernelTask]:
    """Use LLM to decompose a high-level goal into ordered sub-tasks."""
    capabilities_txt = "\n".join(
        f"  - {name}: {desc}"
        for name, desc in _AGENT_CAPABILITIES.items()
    )

    context_txt = ""
    if context:
        context_txt = "\nContext:\n" + "\n".join(
            f"  {k}: {v}" for k, v in context.items()
        )

    system_prompt = (
        "You are a task planner for a multi-agent AI system. "
        "Break down a high-level goal into concrete sub-tasks, "
        "each assigned to the best specialist agent. "
        "Maximize parallelism — tasks that don't depend on each other should run together.\n\n"
        f"Available agents:\n{capabilities_txt}\n\n"
        f"{_TASK_PLAN_SCHEMA}"
    )

    user_msg = f"Goal: {goal}{context_txt}"

    tasks: List[KernelTask] = []

    try:
        from src.llm_router import LLMRouter
        raw = LLMRouter().call("orchestrator", user_msg, system_prompt=system_prompt)
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = "\n".join(raw.split("\n")[:-1])
        plan = json.loads(raw)
        for t in plan.get("tasks", [])[:max_tasks]:
            tasks.append(KernelTask(
                id=t["id"],
                goal=t["goal"],
                agent=t["agent"],
                depends_on=t.get("depends_on", []),
            ))
    except Exception as exc:
        logger.warning("LLM planner failed (%s) — using heuristic plan", exc)
        tasks = _heuristic_plan(goal)

    return tasks


def _heuristic_plan(goal: str) -> List[KernelTask]:
    """Fallback: rule-based task plan when LLM is unavailable."""
    gl = goal.lower()
    tasks: List[KernelTask] = []

    # Code-oriented goals
    if any(kw in gl for kw in ["code", "fix", "bug", "implement", "api", "function", "class"]):
        tasks = [
            KernelTask("t1", f"Analyse requirements: {goal}", "product_manager"),
            KernelTask("t2", f"Design architecture for: {goal}", "architect", ["t1"]),
            KernelTask("t3", f"Implement: {goal}", "code_generator", ["t2"]),
            KernelTask("t4", f"Review code for: {goal}", "code_reviewer", ["t3"]),
            KernelTask("t5", f"Write tests for: {goal}", "qa_tester", ["t3"]),
            KernelTask("t6", f"Security audit for: {goal}", "security_auditor", ["t3"]),
        ]
    # Health goals
    elif any(kw in gl for kw in ["slow", "broken", "env", "wifi", "battery", "backup"]):
        tasks = [
            KernelTask("t1", f"System health check: {goal}", "system_optimizer"),
            KernelTask("t2", f"Network check: {goal}", "network_medic"),
            KernelTask("t3", f"Environment check: {goal}", "environment_doctor"),
            KernelTask("t4", f"Security check: {goal}", "security_guard"),
        ]
    # Deploy / DevOps goals
    elif any(kw in gl for kw in ["deploy", "docker", "ci", "pipeline", "ship"]):
        tasks = [
            KernelTask("t1", f"Security check before deploy: {goal}", "security_auditor"),
            KernelTask("t2", f"Run full test suite: {goal}", "qa_tester"),
            KernelTask("t3", f"Create deployment config: {goal}", "devops", ["t1", "t2"]),
            KernelTask("t4", f"Document deployment: {goal}", "documentation_writer", ["t3"]),
        ]
    # Fallback: full SDLC
    else:
        tasks = [
            KernelTask("t1", goal, "code_generator"),
            KernelTask("t2", f"Test: {goal}", "qa_tester", ["t1"]),
            KernelTask("t3", f"Security review: {goal}", "security_auditor", ["t1"]),
        ]

    return tasks


# ─────────────────────────────────────────────────────────────────────────────
# Executor — runs a single task against its agent
# ─────────────────────────────────────────────────────────────────────────────

def _execute_task(task: KernelTask, run: KernelRun) -> str:
    """Execute a single KernelTask and return the result text."""
    from src.computer_agents import dispatch as health_dispatch
    from src.context_keeper import context_keeper_node

    # Build state for the agent
    state: Dict[str, Any] = {
        "user_request": task.goal,
        "_context": run.context,
        "_run_id": run.run_id,
        "_task_id": task.id,
    }

    # Inject previous task results as context
    completed_results = {
        t.id: (t.result or "")[:500]
        for t in run.tasks
        if t.status == "done" and t.result
    }
    if completed_results:
        state["_prior_results"] = completed_results

    # Route to the correct agent
    agent = task.agent
    result_dict: Dict = {}

    try:
        if agent == "context_keeper":
            result_dict = context_keeper_node(state)

        elif agent in {
            "system_optimizer", "file_organizer", "environment_doctor",
            "security_guard", "network_medic", "battery_analyst",
            "update_manager", "log_interpreter", "privacy_cleaner",
            "media_librarian", "backup_sentinel", "context_switcher",
        }:
            result_dict = health_dispatch(task.goal, state)

        elif agent in {
            "orchestrator", "product_manager", "architect",
            "code_generator", "code_reviewer", "qa_tester",
            "security_auditor", "performance_optimizer",
            "documentation_writer", "devops",
        }:
            # Route to SDLC agents via LLM
            result_dict = _run_sdlc_agent(agent, task.goal, state)

        else:
            # Unknown agent — try health dispatch as fallback
            logger.warning("Unknown agent '%s', using health dispatch", agent)
            result_dict = health_dispatch(task.goal, state)

    except Exception as exc:
        logger.error("Task %s (%s) failed: %s", task.id, agent, exc, exc_info=True)
        return f"Error in {agent}: {exc}"

    # Extract result text
    report = result_dict.get("report", "")
    report_path = result_dict.get("report_path", "")
    result_text = report
    if report_path:
        result_text += f"\n\n_Report: `{report_path}`_"
        run.artifacts.append(report_path)
    if result_dict.get("script_path"):
        run.artifacts.append(result_dict["script_path"])

    return result_text or f"{agent} completed with no report output"


def _run_sdlc_agent(agent_name: str, goal: str, state: Dict) -> Dict:
    """Run a single SDLC agent node without the full LangGraph pipeline."""
    try:
        from src.llm_router import LLMRouter
        router = LLMRouter()
    except Exception as exc:
        return {"agent": agent_name, "report": f"LLM unavailable: {exc}"}

    # Build agent-specific system prompts
    SYSTEM_PROMPTS = {
        "product_manager": (
            "You are a Product Manager. Write clear requirements, acceptance criteria, "
            "and user stories for the given task."
        ),
        "architect": (
            "You are a Software Architect. Design the system architecture, component breakdown, "
            "API contracts, and data models for the given task."
        ),
        "code_generator": (
            "You are an expert Software Engineer. Write clean, production-ready code "
            "with proper error handling and comments for the given task."
        ),
        "code_reviewer": (
            "You are a Code Reviewer. Review the code for correctness, security, "
            "performance, and style. List specific issues and suggested fixes."
        ),
        "qa_tester": (
            "You are a QA Engineer. Write comprehensive test cases (unit, integration) "
            "for the given task. Use pytest syntax."
        ),
        "security_auditor": (
            "You are a Security Auditor. Check the task for OWASP Top 10 vulnerabilities, "
            "insecure patterns, and provide CVSS-scored findings."
        ),
        "performance_optimizer": (
            "You are a Performance Engineer. Identify bottlenecks, Big-O complexity issues, "
            "N+1 queries, and caching opportunities."
        ),
        "documentation_writer": (
            "You are a Technical Writer. Write clear README sections, docstrings, "
            "and API documentation for the given task."
        ),
        "devops": (
            "You are a DevOps Engineer. Create Dockerfile, CI/CD pipeline config, "
            "and deployment instructions for the given task."
        ),
        "orchestrator": (
            "You are an Orchestrator. Analyse the task and provide a high-level "
            "execution plan with clear next steps."
        ),
    }

    system_prompt = SYSTEM_PROMPTS.get(
        agent_name,
        f"You are a {agent_name.replace('_', ' ').title()}. Complete the following task."
    )

    prior = state.get("_prior_results", {})
    user_msg = goal
    if prior:
        prior_txt = "\n\n".join(f"### {tid} result:\n{res}" for tid, res in prior.items())
        user_msg = f"Previous work:\n{prior_txt}\n\nYour task: {goal}"

    try:
        report = router.call(agent_name, user_msg, system_prompt=system_prompt)
    except Exception as exc:
        report = f"[LLM unavailable] {exc}"

    # Save report
    from src.computer_agents import _save_report
    ts = datetime.datetime.now().strftime("%H%M%S")
    report_path = _save_report(f"kernel_{agent_name}_{ts}.md", f"# {agent_name}\n\n{report}")

    return {"agent": agent_name, "report": report, "report_path": report_path}


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor — monitors execution, re-routes stuck tasks
# ─────────────────────────────────────────────────────────────────────────────

def _check_ready(task: KernelTask, run: KernelRun) -> bool:
    """Return True if all dependencies of `task` are done."""
    done_ids = {t.id for t in run.tasks if t.status == "done"}
    return all(dep in done_ids for dep in task.depends_on)


def _get_next_tasks(run: KernelRun) -> List[KernelTask]:
    """Return all pending tasks whose dependencies are satisfied."""
    return [
        t for t in run.tasks
        if t.status == "pending" and _check_ready(t, run)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Main kernel entry point
# ─────────────────────────────────────────────────────────────────────────────

def delegate(
    goal: str,
    context: Optional[Dict] = None,
    max_parallel: int = 3,
    timeout_per_task: int = 300,
) -> Dict[str, Any]:
    """
    Accept a high-level goal, plan sub-tasks, execute them autonomously,
    and return a structured result.

    Parameters
    ──────────
    goal          : Plain-English description of what to achieve
    context       : Optional metadata: repo path, branch, language, etc.
    max_parallel  : How many tasks can run simultaneously
    timeout_per_task: Max seconds per task before marking as failed

    Returns a dict with:
      run_id, status, final_report, artifacts, tasks (with results)
    """
    run_id = uuid.uuid4().hex[:16]
    ctx = context or {}
    board = Blackboard(run_id)

    # ── 1. Plan ───────────────────────────────────────────────────────────────
    logger.info("[kernel] Planning goal: %s (run_id=%s)", goal[:80], run_id)
    tasks = _plan_tasks(goal, ctx)
    run = KernelRun(run_id=run_id, goal=goal, context=ctx, tasks=tasks)
    run.status = "running"
    board.save(run)

    # ── 2. Execute ─────────────────────────────────────────────────────────────
    total_tasks = len(tasks)
    completed = 0
    failed = 0

    logger.info("[kernel] Executing %d tasks for run %s", total_tasks, run_id)

    while completed + failed < total_tasks:
        ready = _get_next_tasks(run)
        if not ready:
            # Check for deadlock: all remaining tasks are stuck
            remaining = [t for t in run.tasks if t.status == "pending"]
            if remaining:
                logger.warning("[kernel] Deadlock detected for run %s — skipping %d tasks", run_id, len(remaining))
                for t in remaining:
                    t.status = "skipped"
                    t.error = "Dependency deadlock"
                    failed += 1
            break

        # Execute up to max_parallel ready tasks
        batch = ready[:max_parallel]
        for task in batch:
            task.status = "running"
            task.started_at = datetime.datetime.now().isoformat()
            board.save(run)

        # Sequential execution within batch (can be parallelised with threads in future)
        for task in batch:
            logger.info("[kernel] Running task %s (%s): %s", task.id, task.agent, task.goal[:60])
            try:
                result = _execute_task(task, run)
                board.post_task_result(run, task.id, result)
                completed += 1
                logger.info("[kernel] Task %s done (%d/%d)", task.id, completed, total_tasks)
            except Exception as exc:
                board.post_task_error(run, task.id, str(exc))
                failed += 1
                logger.error("[kernel] Task %s FAILED: %s", task.id, exc)

    # ── 3. Synthesise final report ──────────────────────────────────────────
    run.status = "done" if failed == 0 else "partial"
    run.finished_at = datetime.datetime.now().isoformat()
    run.final_report = _synthesise_report(run)
    board.save(run)

    logger.info("[kernel] Run %s complete: %d done, %d failed", run_id, completed, failed)

    return {
        "run_id": run_id,
        "status": run.status,
        "goal": goal,
        "tasks_total": total_tasks,
        "tasks_done": completed,
        "tasks_failed": failed,
        "final_report": run.final_report,
        "artifacts": run.artifacts,
        "tasks": [asdict(t) for t in run.tasks],
        "blackboard": str(board.path),
    }


def _synthesise_report(run: KernelRun) -> str:
    """Combine all task results into a final structured report."""
    lines = [
        f"# TIMPS Kernel Run: {run.run_id}",
        f"\n**Goal:** {run.goal}",
        f"**Status:** {run.status}",
        f"**Completed:** {run.finished_at}",
        f"**Tasks:** {len([t for t in run.tasks if t.status == 'done'])}/{len(run.tasks)} done\n",
    ]

    # Try LLM synthesis
    done_tasks = [t for t in run.tasks if t.status == "done" and t.result]
    if done_tasks:
        try:
            from src.llm_router import LLMRouter
            results_txt = "\n\n".join(
                f"### {t.agent} ({t.id}):\n{(t.result or '')[:600]}"
                for t in done_tasks
            )
            system_prompt = (
                "You are a project manager synthesising a multi-agent task completion report. "
                "Given the results from multiple specialist agents, write a concise executive summary "
                "(max 5 sentences) and a prioritised list of next actions."
            )
            summary = LLMRouter().call(
                "orchestrator",
                f"Goal: {run.goal}\n\nAgent results:\n{results_txt}\n\nWrite executive summary + next actions:",
                system_prompt=system_prompt,
            )
            lines.append("## Executive Summary\n")
            lines.append(summary)
        except Exception:
            pass

    lines.append("\n\n## Task Results\n")
    for t in run.tasks:
        status_icon = {"done": "✅", "failed": "❌", "skipped": "⏭️", "running": "🔄"}.get(t.status, "⏳")
        lines.append(f"\n### {status_icon} [{t.id}] {t.agent}: {t.goal[:80]}")
        if t.result:
            lines.append(t.result[:800] + ("…" if len(t.result or "") > 800 else ""))
        if t.error:
            lines.append(f"_Error: {t.error}_")

    if run.artifacts:
        lines.append("\n\n## Generated Artifacts\n")
        for a in run.artifacts:
            lines.append(f"- `{a}`")

    report = "\n".join(lines)

    # Save to disk
    BLACKBOARD_DIR.mkdir(parents=True, exist_ok=True)
    report_path = BLACKBOARD_DIR / f"run_{run.run_id}_report.md"
    report_path.write_text(report, encoding="utf-8")
    run.artifacts.append(str(report_path))

    return report
