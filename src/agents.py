"""
All 10 Agent Nodes for the TIMPS Swarm.

Each function is a LangGraph node that:
  1. Reads from SwarmState
  2. Uses AgentComputer (real browser, terminal, search, files) for grounding
  3. Calls the appropriate LLM via the router
  4. Returns a partial state update (dict)
"""
import os
import json
import logging
import subprocess
from datetime import datetime
from typing import Optional

from src.state import SwarmState, Task
from src.llm_router import get_router
from src.adapter_router import get_adapter_router
from src.computer_use import get_agent_computer

logger = logging.getLogger(__name__)

GENERATED_DIR = os.getenv("GENERATED_DIR", "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────

def _save(filename: str, content: str) -> str:
    """Write content to generated/ and return the path."""
    path = os.path.join(GENERATED_DIR, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.debug("Saved artifact: %s", path)
    return path


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _get_pending_tasks(state: SwarmState, role: str) -> list[Task]:
    return [t for t in state.get("tasks", []) if t["assigned_to"] == role and t["status"] == "pending"]


def _mark_task(task: Task, status: str, output: str = "") -> Task:
    t = dict(task)
    t["status"] = status
    t["output"] = output
    t["completed_at"] = datetime.utcnow().isoformat()
    return t


def _parse_json_safe(text: str) -> Optional[list]:
    """Try to extract a JSON array from text."""
    try:
        # Find first [ ... ]
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — ORCHESTRATOR
# Role: Supervisor. Decomposes requests into a DAG of tasks.
# ─────────────────────────────────────────────────────────────────────────────

def orchestrator_node(state: SwarmState) -> dict:
    logger.info("[Orchestrator] Evaluating state — iteration %d", state.get("iteration_count", 0))

    # Avoid infinite loops
    count = state.get("iteration_count", 0) + 1
    if count > state.get("max_iterations", 10):
        logger.warning("[Orchestrator] Max iterations reached — finalising")
        return {"iteration_count": count, "completed": True}

    # If no tasks exist yet, create the initial DAG
    existing_tasks = state.get("tasks", [])
    if not existing_tasks:
        system = (
            "You are the Orchestrator of a software engineering AI swarm. "
            "Break the user's request into a JSON array of tasks. "
            "Each task: {id, description, assigned_to, dependencies, status}. "
            "assigned_to must be one of: research_agent, api_design_agent, "
            "product_manager, architect, code_generator, "
            "code_reviewer, qa_tester, security_auditor, performance_optimizer, "
            "dependency_agent, documentation_writer, devops. "
            "ALWAYS start with research_agent (id t0, no deps). "
            "If building an API, add api_design_agent (id t0b, depends on t0) before product_manager. "
            "Add dependency_agent after code_generator (depends on code_generator task). "
            "status must be 'pending'. Output ONLY valid JSON — no prose."
        )
        prompt = f"User request: {state['user_request']}\nGenerate the task plan."
        raw = get_router().call("orchestrator", prompt, system)
        tasks = _parse_json_safe(raw)

        if not tasks:
            # Fallback default pipeline
            tasks = _default_task_dag(state["user_request"])

        # Normalise tasks
        normalised = []
        for t in tasks:
            normalised.append(Task(
                id=t.get("id", f"task-{len(normalised)}"),
                description=t.get("description", ""),
                assigned_to=t.get("assigned_to", "code_generator"),
                status="pending",
                dependencies=t.get("dependencies", []),
                output=None,
                artifact_path=None,
                created_at=datetime.utcnow().isoformat(),
                completed_at=None,
                retry_count=0,
            ))
        return {"tasks": normalised, "iteration_count": count}

    return {"iteration_count": count}


def _default_task_dag(request: str) -> list:
    return [
        {"id": "t0",  "description": f"Research best practices for: {request}", "assigned_to": "research_agent", "dependencies": [], "status": "pending"},
        {"id": "t1",  "description": f"Write requirements for: {request}", "assigned_to": "product_manager", "dependencies": ["t0"], "status": "pending"},
        {"id": "t2",  "description": "Design system architecture", "assigned_to": "architect", "dependencies": ["t1"], "status": "pending"},
        {"id": "t2b", "description": f"Design API spec for: {request}", "assigned_to": "api_design_agent", "dependencies": ["t2"], "status": "pending"},
        {"id": "t3",  "description": f"Implement code for: {request}", "assigned_to": "code_generator", "dependencies": ["t2b"], "status": "pending"},
        {"id": "t4",  "description": "Review generated code", "assigned_to": "code_reviewer", "dependencies": ["t3"], "status": "pending"},
        {"id": "t5",  "description": "Write and run tests", "assigned_to": "qa_tester", "dependencies": ["t3"], "status": "pending"},
        {"id": "t6",  "description": "Security audit of code", "assigned_to": "security_auditor", "dependencies": ["t3"], "status": "pending"},
        {"id": "t6b", "description": "Dependency vulnerability scan", "assigned_to": "dependency_agent", "dependencies": ["t3"], "status": "pending"},
        {"id": "t7",  "description": "Profile and optimise performance", "assigned_to": "performance_optimizer", "dependencies": ["t4"], "status": "pending"},
        {"id": "t8",  "description": "Write README and API docs", "assigned_to": "documentation_writer", "dependencies": ["t4", "t5"], "status": "pending"},
        {"id": "t9",  "description": "Generate Dockerfile and CI/CD", "assigned_to": "devops", "dependencies": ["t5", "t6"], "status": "pending"},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — PRODUCT MANAGER
# Role: Planner. Converts user request → PRD with user stories.
# ─────────────────────────────────────────────────────────────────────────────

def product_manager_node(state: SwarmState) -> dict:
    logger.info("[ProductManager] Writing requirements")
    pending = _get_pending_tasks(state, "product_manager")
    if not pending:
        return {}

    task = pending[0]

    # ── Real computer use: search industry standards for the request ──
    computer = get_agent_computer("product_manager")
    research = computer.research_sync(
        f"{state['user_request']} product requirements user stories best practices", follow_links=1
    )
    logger.info("[ProductManager] Web research complete (%d chars)", len(research))

    system = (
        "You are a senior Product Manager. Write a concise Product Requirements Document (PRD) "
        "with: Overview, Goals, User Stories, Acceptance Criteria, and Out-of-Scope items. "
        "Be specific and developer-friendly. Ground your requirements in the research context provided."
    )
    prompt = (
        f"User request: {state['user_request']}\n\n"
        f"Research context (from live web search):\n{research[:3000]}\n\n"
        f"Task: {task['description']}"
    )
    requirements = get_router().call("product_manager", prompt, system)

    path = _save("requirements.md", requirements)
    updated_task = _mark_task(task, "completed", requirements)

    return {
        "requirements": requirements,
        "tasks": [updated_task],
        "code_artifacts": [path],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — ARCHITECT
# Role: Planner. Designs system structure, APIs, data models.
# ─────────────────────────────────────────────────────────────────────────────

def architect_node(state: SwarmState) -> dict:
    logger.info("[Architect] Designing architecture")
    pending = _get_pending_tasks(state, "architect")
    if not pending:
        return {}

    task = pending[0]

    # ── Real computer use: look up current best-practice tech stacks ──
    computer = get_agent_computer("architect")
    research = computer.research_sync(
        f"{state['user_request']} system architecture design patterns tech stack 2024", follow_links=1
    )
    logger.info("[Architect] Web research complete (%d chars)", len(research))

    system = (
        "You are a Software Architect. Output a technical design covering: "
        "Tech Stack selection, Component diagram (text), API contracts (OpenAPI-style), "
        "Data models, Security considerations, and Scalability notes. "
        "Use the research context to choose modern, proven technologies."
    )
    prompt = (
        f"Requirements:\n{state.get('requirements', state['user_request'])}\n\n"
        f"Research context (from live web search):\n{research[:3000]}\n\n"
        f"Task: {task['description']}"
    )
    plan = get_router().call("architect", prompt, system)

    path = _save("architecture.md", plan)
    updated_task = _mark_task(task, "completed", plan)

    return {
        "architecture_plan": plan,
        "tasks": [updated_task],
        "code_artifacts": [path],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 — CODE GENERATOR (TIMPS-Coder + Qwen)
# Role: Doer. Writes implementation code per spec.
# ─────────────────────────────────────────────────────────────────────────────

def code_generator_node(state: SwarmState) -> dict:
    logger.info("[CodeGenerator] Generating code")
    pending = _get_pending_tasks(state, "code_generator")
    if not pending:
        return {}

    task = pending[0]
    prompt = task["description"]
    is_bug_fix = any(
        kw in prompt.lower()
        for kw in ["fix", "bug", "error", "exception", "crash", "null", "undefined", "injection", "xss"]
    )

    # ── Real computer use: search for code patterns before generating ──
    computer = get_agent_computer("code_generator")
    search_query = f"{prompt} Python code example best practice"
    research = computer.research_sync(search_query)
    logger.info("[CodeGenerator] Web research complete (%d chars)", len(research))

    if is_bug_fix:
        system = (
            f"Architecture context:\n{state.get('architecture_plan', '')}\n\n"
            f"Relevant code patterns from web search:\n{research[:2000]}\n\n"
            "Explain the root cause of the bug, then provide the complete corrected code."
        )
        code = get_adapter_router().generate(prompt, system, max_tokens=2048)
    else:
        system = (
            "You are an expert software engineer. Implement clean, production-ready code. "
            "Include docstrings and inline comments. Follow best practices for the language used.\n\n"
            f"Architecture:\n{state.get('architecture_plan', '')}\n\n"
            f"Relevant patterns from web search:\n{research[:2000]}"
        )
        code = get_router().call("code_generator", prompt, system)

    # Determine file extension
    lang = state.get("language", "python")
    ext_map = {"java": "java", "javascript": "js", "typescript": "ts",
               "go": "go", "rust": "rs", "cpp": "cpp", "python": "py"}
    ext = ext_map.get(lang.lower() if lang else "python", "py")

    filename = f"code/{task['id']}.{ext}"
    path = _save(filename, code)

    # ── Real computer use: actually run the generated code to verify it executes ──
    run_result = None
    if ext == "py":
        run_result = computer.code.run_file(path)
        if run_result.success:
            logger.info("[CodeGenerator] Code executed successfully")
        else:
            logger.warning("[CodeGenerator] Code execution failed: %s", run_result.error)

    updated_task = _mark_task(task, "completed", code)
    updated_task["artifact_path"] = path

    state_update = {
        "code_artifacts": [path],
        "tasks": [updated_task],
    }
    if run_result:
        state_update["test_results"] = f"[Initial run]\n{run_result.output[:500]}"

    return state_update


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 5 — CODE REVIEWER
# Role: Critic. Reviews PRs for bugs, style, pattern violations.
# ─────────────────────────────────────────────────────────────────────────────

def code_reviewer_node(state: SwarmState) -> dict:
    logger.info("[CodeReviewer] Reviewing code artifacts")
    pending = _get_pending_tasks(state, "code_reviewer")
    artifacts = state.get("code_artifacts", [])
    if not artifacts and not pending:
        return {}

    system = (
        "You are a Senior Code Reviewer. Review the code for: "
        "1) Logic errors and bugs, 2) Anti-patterns, 3) Style violations, "
        "4) Missing error handling, 5) Inconsistency with the architecture spec. "
        "Rate each finding: BLOCKER / MAJOR / MINOR. Be concise and actionable."
    )

    reviews = []
    for artifact in artifacts[-5:]:  # Review up to last 5 artifacts
        code = _read(artifact)
        if not code:
            continue
        prompt = (
            f"Architecture spec:\n{state.get('architecture_plan', 'N/A')}\n\n"
            f"Code to review ({artifact}):\n```\n{code[:4000]}\n```"
        )
        review = get_router().call("code_reviewer", prompt, system)
        reviews.append(f"### Review of `{artifact}`\n{review}")

    path = _save("review_comments.md", "\n\n".join(reviews))

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", "\n".join(reviews)))

    return {
        "review_comments": reviews,
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 6 — QA / TESTER
# Role: Critic. Writes and runs tests, reports coverage.
# ─────────────────────────────────────────────────────────────────────────────

def qa_tester_node(state: SwarmState) -> dict:
    logger.info("[QATester] Writing tests")
    pending = _get_pending_tasks(state, "qa_tester")
    artifacts = state.get("code_artifacts", [])

    if not artifacts and not pending:
        return {}

    system = (
        "You are a QA Engineer. Write comprehensive pytest unit tests and integration tests. "
        "Aim for 100% coverage of critical paths. Include: happy paths, edge cases, "
        "error conditions, and boundary values. Add docstrings to each test."
    )

    code_contents = "\n\n".join([_read(a) for a in artifacts[:3] if _read(a)])
    prompt = f"Write tests for this code:\n```\n{code_contents[:5000]}\n```"
    tests = get_router().call("qa_tester", prompt, system)

    path = _save("tests/test_generated.py", tests)

    # ── Real computer use: actually run the tests and capture results ──
    computer = get_agent_computer("qa_tester")
    run_result = computer.code.run_pytest(path)
    test_result = run_result.output if run_result.output else run_result.error
    logger.info("[QATester] Tests %s", "passed" if run_result.success else "failed")

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", test_result))

    return {
        "test_results": test_result,
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }


def _run_tests_safe(test_path: str) -> str:
    """Kept for backward compatibility — delegates to TerminalTool."""
    computer = get_agent_computer("qa_tester")
    result = computer.code.run_pytest(test_path)
    return result.output or result.error


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 7 — SECURITY AUDITOR
# Role: Critic. Scans for vulnerabilities.
# ─────────────────────────────────────────────────────────────────────────────

def security_auditor_node(state: SwarmState) -> dict:
    logger.info("[SecurityAuditor] Running security audit")
    pending = _get_pending_tasks(state, "security_auditor")
    artifacts = state.get("code_artifacts", [])

    if not artifacts and not pending:
        return {}

    system = (
        "You are a Security Auditor (OWASP expert). Scan the code for: "
        "SQL Injection, XSS, CSRF, hardcoded secrets, insecure deserialization, "
        "path traversal, broken authentication, sensitive data exposure. "
        "Rate each finding: CRITICAL / HIGH / MEDIUM / LOW / INFO. "
        "Provide fix recommendations for each finding."
    )

    # ── Real computer use: search OWASP and CVE databases for context ──
    computer = get_agent_computer("security_auditor")
    lang = state.get("language", "python")
    research = computer.research_sync(f"OWASP {lang} security vulnerabilities 2024 checklist")
    logger.info("[SecurityAuditor] Security research complete (%d chars)", len(research))

    code_contents = "\n\n".join([_read(a) for a in artifacts[:3] if _read(a)])
    prompt = (
        f"OWASP security checklist context:\n{research[:2000]}\n\n"
        f"Security audit:\n```\n{code_contents[:5000]}\n```"
    )
    report = get_router().call("security_auditor", prompt, system)

    # ── Real computer use: run bandit static analysis ──
    py_files = [a for a in artifacts if a.endswith(".py")]
    bandit_output = ""
    if py_files:
        bandit_result = computer.code.run_bandit(py_files[0])
        bandit_output = bandit_result.output or bandit_result.error
        logger.info("[SecurityAuditor] Bandit scan complete: %s", "passed" if bandit_result.success else "issues found")

    full_report = f"{report}\n\n---\n### Bandit Static Analysis\n{bandit_output or 'No Python files scanned.'}"

    path = _save("security_report.md", full_report)

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", full_report))

    return {
        "security_report": full_report,
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }


def _run_bandit_safe(artifacts: list) -> str:
    """Kept for backward compatibility — delegates to computer tool."""
    computer = get_agent_computer("security_auditor")
    py_files = [a for a in artifacts if a.endswith(".py")]
    if not py_files:
        return "No Python files to scan."
    result = computer.code.run_bandit(py_files[0])
    return result.output or result.error


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 8 — PERFORMANCE OPTIMIZER
# Role: Doer. Profiles code and suggests improvements.
# ─────────────────────────────────────────────────────────────────────────────

def performance_optimizer_node(state: SwarmState) -> dict:
    logger.info("[PerformanceOptimizer] Analysing performance")
    pending = _get_pending_tasks(state, "performance_optimizer")
    artifacts = state.get("code_artifacts", [])

    # Skip if critical security issues
    sec_report = state.get("security_report", "")
    if "CRITICAL" in sec_report:
        logger.warning("[PerformanceOptimizer] Skipping — CRITICAL security issues must be fixed first")
        updated_tasks = [_mark_task(t, "failed", "Skipped: CRITICAL security issues") for t in pending]
        return {"tasks": updated_tasks}

    if not artifacts and not pending:
        return {}

    system = (
        "You are a Performance Engineer. Analyse code for: "
        "1) Big-O complexity improvements, 2) Database query optimisation (N+1, indexes), "
        "3) Caching opportunities, 4) Async/concurrent execution patterns, "
        "5) Memory efficiency. Provide concrete code examples for each suggestion."
    )

    code_contents = "\n\n".join([_read(a) for a in artifacts[:3] if _read(a)])
    prompt = f"Optimise performance:\n```\n{code_contents[:5000]}\n```"
    report = get_router().call("performance_optimizer", prompt, system)

    path = _save("performance_report.md", report)

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", report))

    return {
        "performance_report": report,
        "review_comments": [report],
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 9 — DOCUMENTATION WRITER
# Role: Presenter. Writes README, API docs, inline comments.
# ─────────────────────────────────────────────────────────────────────────────

def documentation_writer_node(state: SwarmState) -> dict:
    logger.info("[DocumentationWriter] Writing documentation")
    pending = _get_pending_tasks(state, "documentation_writer")

    # ── Real computer use: fetch official docs for the libraries used ──
    computer = get_agent_computer("documentation_writer")
    research = computer.research_sync(
        f"{state['user_request']} documentation README guide installation examples"
    )
    logger.info("[DocumentationWriter] Docs research complete (%d chars)", len(research))

    system = (
        "You are a Technical Writer. Write comprehensive documentation in Markdown: "
        "1) README.md with project overview, installation, usage, examples, "
        "2) API reference (if applicable), 3) Deployment guide, "
        "4) Contributing guide. Be clear, concise, and developer-friendly."
    )

    prompt = (
        f"Project: {state['user_request']}\n\n"
        f"Architecture:\n{state.get('architecture_plan', 'N/A')[:2000]}\n\n"
        f"Code artifacts: {state.get('code_artifacts', [])}\n\n"
        f"Test results summary: {state.get('test_results', 'N/A')[:500]}\n\n"
        f"Research context:\n{research[:2000]}\n\n"
        "Generate complete documentation."
    )
    docs = get_router().call("documentation_writer", prompt, system)

    path = _save("README.md", docs)

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", docs))

    return {
        "documentation": docs,
        "final_deliverable": docs,
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 10 — DEVOPS / INTEGRATION
# Role: Tool Operator. Manages Docker, CI/CD, deployments.
# ─────────────────────────────────────────────────────────────────────────────

def devops_node(state: SwarmState) -> dict:
    logger.info("[DevOps] Generating DevOps configuration")
    pending = _get_pending_tasks(state, "devops")

    system = (
        "You are a DevOps Engineer. Generate production-ready configuration files: "
        "1) Dockerfile (multi-stage, optimised), 2) docker-compose.yml, "
        "3) GitHub Actions CI/CD pipeline (.github/workflows/ci.yml), "
        "4) Health check endpoints, 5) Environment variable documentation. "
        "Output each file clearly labelled."
    )

    prompt = (
        f"Project: {state['user_request']}\n\n"
        f"Architecture:\n{state.get('architecture_plan', 'N/A')[:1500]}\n\n"
        f"Code artifacts: {state.get('code_artifacts', [])}\n\n"
        f"Security report summary:\n{state.get('security_report', 'N/A')[:500]}\n\n"
        "Generate complete DevOps configuration."
    )
    config = get_router().call("devops", prompt, system)

    path = _save("devops_config.md", config)

    updated_tasks = []
    for task in pending:
        updated_tasks.append(_mark_task(task, "completed", config))

    return {
        "tasks": updated_tasks,
        "code_artifacts": [path],
    }
