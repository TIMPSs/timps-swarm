"""
LangGraph workflow — wires all agents into a conditional DAG with
parallel fan-out for independent tasks.

Flow:
  orchestrator → [research_agent →] [api_design_agent →]
               → parallel_executor (fan-out multiple ready agents)
               → [product_manager | architect | code_generator | ...]
               → [dependency_agent →] documentation_writer → END
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from langgraph.graph import StateGraph, END

from src.state import SwarmState
from src.agents import (
    orchestrator_node,
    product_manager_node,
    architect_node,
    code_generator_node,
    code_reviewer_node,
    qa_tester_node,
    security_auditor_node,
    performance_optimizer_node,
    documentation_writer_node,
    devops_node,
)

logger = logging.getLogger(__name__)

MAX_PARALLEL = 5
_PARALLEL_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_PARALLEL)

# ── New domain agent names (module-level for testability) ─────────────────────
_NEW_AGENTS = [
    # Intelligence
    "code_archaeology", "pattern_detector", "technical_debt",
    "memory_agent", "learning_agent", "agent_composer",
    # AI/ML
    "prompt_engineer", "dataset_agent", "model_evaluator",
    "rag_designer", "finetuning_agent", "ai_safety_agent", "vector_db_agent",
    # India
    "gst_compliance", "abdm_agent", "upi_agent",
    "digilocker_agent", "indiehacker_agent",
    # Domain
    "web_scraping", "data_pipeline", "realtime_agent", "mobile_agent",
    "browser_automation", "graphql_agent", "cli_tool_agent", "embedded_agent",
    # Business
    "analytics_agent", "ab_testing_agent", "monetization_agent",
    "seo_agent", "postmortem_agent", "sprint_planning_agent",
    # Infra
    "load_testing", "feature_flag", "disaster_recovery",
    "finops_agent", "secrets_management", "edge_agent",
    # Emerging
    "robotics_agent", "web3_agent", "federated_learning", "quantum_ready",
    # More agents
    "refactoring_agent", "test_data_agent", "monitoring_agent",
    "ui_ux_agent", "i18n_agent", "cost_optimizer", "self_critic_agent",
    # N8n
    "n8n_workflow_agent",
]


# ── Generic agent node factory ────────────────────────────────────────────────

def _make_node(agent_name: str, fn: Callable, state_key: str = "code_artifacts") -> Callable:
    """Wrap a plain agent function as a LangGraph-compatible node."""
    def _node(state: SwarmState) -> dict:
        pending = [t for t in state.get("tasks", [])
                   if t["assigned_to"] == agent_name and t["status"] == "pending"]
        if not pending:
            return {}
        task = pending[0]
        try:
            result = fn({
                "user_request": state.get("user_request", ""),
                "requirements": state.get("requirements", ""),
                "language":     state.get("language", "python"),
            })
        except Exception as exc:
            logger.warning("Agent %s raised: %s", agent_name, exc)
            result = {"summary": str(exc)}
        updated = dict(task)
        updated.update({
            "status":       "completed",
            "output":       result.get("summary", ""),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        artifact_keys = [k for k in result if k.endswith("_path")]
        artifacts = [result[k] for k in artifact_keys if result.get(k)]
        return {"tasks": [updated], state_key: artifacts}
    _node.__name__ = f"_{agent_name}_node"
    return _node


# ── New agent node wrappers ───────────────────────────────────────────────────
# These wrap priority_agents.py functions as LangGraph-compatible nodes.

def _research_agent_node(state: SwarmState) -> dict:
    from src.priority_agents import research_agent
    pending = [t for t in state.get("tasks", [])
               if t["assigned_to"] == "research_agent" and t["status"] == "pending"]
    if not pending:
        return {}
    task = pending[0]
    result = research_agent({"topic": state["user_request"], "depth": "medium"})
    from datetime import datetime, timezone
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("summary", ""),
                    "completed_at": datetime.now(timezone.utc).isoformat()})
    return {
        "tasks": [updated],
        "code_artifacts": [result.get("report_path", "")],
        # Inject research brief into requirements field so downstream agents see it
        "requirements": (state.get("requirements") or "") + "\n\n## Research Brief\n" + result.get("summary", ""),
    }


def _api_design_node(state: SwarmState) -> dict:
    from src.priority_agents import api_design_agent
    pending = [t for t in state.get("tasks", [])
               if t["assigned_to"] == "api_design_agent" and t["status"] == "pending"]
    if not pending:
        return {}
    task = pending[0]
    result = api_design_agent({"description": state["user_request"]})
    from datetime import datetime, timezone
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("spec_yaml", ""),
                    "artifact_path": result.get("spec_path", ""),
                    "completed_at": datetime.now(timezone.utc).isoformat()})
    return {
        "tasks": [updated],
        "code_artifacts": [result.get("spec_path", "")],
        "architecture_plan": (state.get("architecture_plan") or "") + "\n\n## API Spec\n" + result.get("spec_yaml", "")[:2000],
    }


def _dependency_agent_node(state: SwarmState) -> dict:
    from src.priority_agents import dependency_agent
    pending = [t for t in state.get("tasks", [])
               if t["assigned_to"] == "dependency_agent" and t["status"] == "pending"]
    if not pending:
        return {}
    task = pending[0]
    # Try to read requirements.txt from generated artifacts
    manifest = ""
    for path in state.get("code_artifacts", []):
        if "requirements" in str(path) or "package.json" in str(path):
            try:
                manifest = open(path, encoding="utf-8").read()
                break
            except Exception:
                pass
    result = dependency_agent({"manifest": manifest or "# No manifest found", "ecosystem": "auto"})
    from datetime import datetime, timezone
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("summary", ""),
                    "completed_at": datetime.now(timezone.utc).isoformat()})
    return {
        "tasks": [updated],
        "security_report": (state.get("security_report") or "") + "\n\n## Dependency Audit\n" + result.get("summary", ""),
        "code_artifacts": [result.get("report_path", "")],
    }


# ── Domain-agent loader (module-level so both build_graph and parallel_executor can use it) ─

def _load_agents():
    from src.intelligence import INTELLIGENCE_AGENTS
    from src.aiml       import AIML_AGENTS
    from src.india      import INDIA_AGENTS
    from src.domain     import DOMAIN_AGENTS
    from src.business   import BUSINESS_AGENTS
    from src.infra      import INFRA_AGENTS
    from src.emerging   import EMERGING_AGENTS
    from src.more_agents   import MORE_AGENTS
    from src.priority_agents import PRIORITY_AGENTS
    from src.nextgen    import NEXTGEN_AGENTS
    from src.phase7     import PHASE7_AGENTS
    combined = {}
    for d in [INTELLIGENCE_AGENTS, AIML_AGENTS, INDIA_AGENTS, DOMAIN_AGENTS,
              BUSINESS_AGENTS, INFRA_AGENTS, EMERGING_AGENTS, MORE_AGENTS,
              NEXTGEN_AGENTS, PHASE7_AGENTS]:
        combined.update(d)
    for k in ["n8n_workflow_agent"]:
        if k in PRIORITY_AGENTS:
            combined[k] = PRIORITY_AGENTS[k]
    return combined


# ── Parallel fan-out executor ──────────────────────────────────────────────────

def _deps_met(task: dict, tasks: list[dict]) -> bool:
    deps = task.get("dependencies", [])
    return all(
        any(t["id"] == d and t["status"] == "completed" for t in tasks)
        for d in deps
    )


def _resolve_node_fn(agent_name: str) -> Callable | None:
    """Get the LangGraph-compatible node function for any agent by name."""
    _CORE = {
        "orchestrator": orchestrator_node,
        "product_manager": product_manager_node,
        "architect": architect_node,
        "code_generator": code_generator_node,
        "code_reviewer": code_reviewer_node,
        "qa_tester": qa_tester_node,
        "security_auditor": security_auditor_node,
        "performance_optimizer": performance_optimizer_node,
        "documentation_writer": documentation_writer_node,
        "devops": devops_node,
        "research_agent": _research_agent_node,
        "api_design_agent": _api_design_node,
        "dependency_agent": _dependency_agent_node,
    }
    if agent_name in _CORE:
        return _CORE[agent_name]
    all_domain = _load_agents()
    if agent_name in all_domain:
        return _make_node(agent_name, all_domain[agent_name])
    return None


async def parallel_executor_node(state: SwarmState) -> dict:
    """Run all independent pending tasks concurrently via asyncio.gather()."""
    tasks = state.get("tasks", [])
    pending = [t for t in tasks if t["status"] == "pending" and _deps_met(t, tasks)]
    pending = pending[:MAX_PARALLEL]

    if not pending:
        return {}

    async def run_one(task: dict) -> dict:
        agent_name = task["assigned_to"]
        node_fn = _resolve_node_fn(agent_name)
        if node_fn is None:
            task["status"] = "failed"
            task["output"] = f"No agent function found: {agent_name}"
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            return {"tasks": [task]}
        mini_state: SwarmState = dict(state)
        mini_state["tasks"] = [task]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_PARALLEL_EXECUTOR, node_fn, mini_state)

    results = await asyncio.gather(*[run_one(t) for t in pending], return_exceptions=True)

    merged: dict[str, Any] = {}
    for result in results:
        if isinstance(result, Exception):
            logger.error("Parallel agent failed with: %s", result)
            continue
        if not isinstance(result, dict):
            continue
        for key, val in result.items():
            if isinstance(val, list):
                merged.setdefault(key, []).extend(val)
            elif val:
                merged[key] = val
    return merged


# ── Routing logic ─────────────────────────────────────────────────────────────

def route_after_orchestrator(state: SwarmState) -> str:
    """Decide which agent to invoke next based on current state."""

    if state.get("completed"):
        return "documentation_writer"

    if state.get("iteration_count", 0) > state.get("max_iterations", 10):
        return "documentation_writer"

    tasks = state.get("tasks", [])
    pending = {t["assigned_to"] for t in tasks if t["status"] == "pending"}

    # ── Parallel fan-out: if multiple independent tasks are ready, run them concurrently ────
    pending_tasks = [t for t in tasks if t["status"] == "pending" and _deps_met(t, tasks)]
    if len(pending_tasks) >= 2:
        logger.info("Parallel fan-out: %d tasks ready → parallel_executor", len(pending_tasks))
        return "parallel_executor"

    # NEW: research before everything else
    if "research_agent" in pending:
        return "research_agent"

    # NEW: API design before coding
    if "api_design_agent" in pending and not state.get("architecture_plan"):
        return "api_design_agent"

    if not state.get("requirements") and "product_manager" in pending:
        return "product_manager"

    if not state.get("architecture_plan") and "architect" in pending:
        return "architect"

    if "code_generator" in pending:
        return "code_generator"

    if "code_reviewer" in pending and state.get("code_artifacts"):
        return "code_reviewer"

    if "qa_tester" in pending and state.get("code_artifacts"):
        return "qa_tester"

    if "security_auditor" in pending and state.get("code_artifacts"):
        return "security_auditor"

    # NEW: dependency audit after security
    if "dependency_agent" in pending and state.get("code_artifacts"):
        return "dependency_agent"

    # Loop back for critical findings
    sec_report = state.get("security_report", "")
    review_comments = " ".join(state.get("review_comments", []))
    if ("CRITICAL" in sec_report or "BLOCKER" in review_comments) and state.get("iteration_count", 0) < 5:
        logger.info("Routing back to code_generator for critical fixes")
        return "code_generator"

    if "performance_optimizer" in pending and state.get("code_artifacts"):
        return "performance_optimizer"

    if "documentation_writer" in pending:
        return "documentation_writer"

    if "devops" in pending:
        return "devops"

    # ── New domain agents — any pending task for a registered agent ──────────
    # Order determines priority within a group.
    for agent in _NEW_AGENTS:
        if agent in pending:
            return agent

    return "documentation_writer"


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    workflow = StateGraph(SwarmState)

    # ── Core 10 SDLC agents ───────────────────────────────────────────────────
    workflow.add_node("orchestrator",           orchestrator_node)
    workflow.add_node("product_manager",        product_manager_node)
    workflow.add_node("architect",              architect_node)
    workflow.add_node("code_generator",         code_generator_node)
    workflow.add_node("code_reviewer",          code_reviewer_node)
    workflow.add_node("qa_tester",              qa_tester_node)
    workflow.add_node("security_auditor",       security_auditor_node)
    workflow.add_node("performance_optimizer",  performance_optimizer_node)
    workflow.add_node("documentation_writer",   documentation_writer_node)
    workflow.add_node("devops",                 devops_node)

    # ── Parallel fan-out executor ──────────────────────────────────────────────
    workflow.add_node("parallel_executor",      parallel_executor_node)

    # ── Priority agents (hand-crafted wrappers above) ─────────────────────────
    workflow.add_node("research_agent",         _research_agent_node)
    workflow.add_node("api_design_agent",       _api_design_node)
    workflow.add_node("dependency_agent",       _dependency_agent_node)

    # ── Bulk registration of domain-package agents ────────────────────────────
    all_domain_agents = _load_agents()
    for name, fn in all_domain_agents.items():
        workflow.add_node(name, _make_node(name, fn))

    # ── Entry point ───────────────────────────────────────────────────────────
    workflow.set_entry_point("orchestrator")

    # ── Conditional routing from orchestrator ─────────────────────────────────
    route_targets = {
        "parallel_executor":     "parallel_executor",
        "research_agent":        "research_agent",
        "api_design_agent":      "api_design_agent",
        "product_manager":       "product_manager",
        "architect":             "architect",
        "code_generator":        "code_generator",
        "code_reviewer":         "code_reviewer",
        "qa_tester":             "qa_tester",
        "security_auditor":      "security_auditor",
        "dependency_agent":      "dependency_agent",
        "performance_optimizer": "performance_optimizer",
        "documentation_writer":  "documentation_writer",
        "devops":                "devops",
    }
    for name in all_domain_agents:
        route_targets[name] = name

    workflow.add_conditional_edges("orchestrator", route_after_orchestrator, route_targets)

    # ── All non-terminal agents loop back to orchestrator ─────────────────────
    loop_back = [
        "parallel_executor", "research_agent", "api_design_agent",
        "product_manager", "architect", "code_generator",
        "code_reviewer", "qa_tester", "security_auditor",
        "dependency_agent", "performance_optimizer", "devops",
    ] + list(all_domain_agents.keys())

    for node in loop_back:
        workflow.add_edge(node, "orchestrator")

    # documentation_writer is the terminal node
    workflow.add_edge("documentation_writer", END)

    return workflow.compile()


# Compiled singleton
app = build_graph()
