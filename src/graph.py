"""
LangGraph workflow — wires all agents into a conditional DAG.

Flow:
  orchestrator → [research_agent →] [api_design_agent →]
               → [product_manager | architect | code_generator | ...]
               → [dependency_agent →] documentation_writer → END
"""
import logging

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
    from datetime import datetime
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("summary", ""),
                    "completed_at": datetime.utcnow().isoformat()})
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
    from datetime import datetime
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("spec_yaml", ""),
                    "artifact_path": result.get("spec_path", ""),
                    "completed_at": datetime.utcnow().isoformat()})
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
                import os
                manifest = open(path).read()
                break
            except Exception:
                pass
    result = dependency_agent({"manifest": manifest or "# No manifest found", "ecosystem": "auto"})
    from datetime import datetime
    updated = dict(task)
    updated.update({"status": "completed", "output": result.get("summary", ""),
                    "completed_at": datetime.utcnow().isoformat()})
    return {
        "tasks": [updated],
        "security_report": (state.get("security_report") or "") + "\n\n## Dependency Audit\n" + result.get("summary", ""),
        "code_artifacts": [result.get("report_path", "")],
    }


# ── Routing logic ─────────────────────────────────────────────────────────────

def route_after_orchestrator(state: SwarmState) -> str:
    """Decide which agent to invoke next based on current state."""

    if state.get("completed"):
        return "documentation_writer"

    if state.get("iteration_count", 0) > state.get("max_iterations", 10):
        return "documentation_writer"

    tasks = state.get("tasks", [])
    pending = {t["assigned_to"] for t in tasks if t["status"] == "pending"}

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

    return "documentation_writer"


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    workflow = StateGraph(SwarmState)

    # Core 10 SDLC agents
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

    # NEW priority agents
    workflow.add_node("research_agent",         _research_agent_node)
    workflow.add_node("api_design_agent",       _api_design_node)
    workflow.add_node("dependency_agent",       _dependency_agent_node)

    # Entry point
    workflow.set_entry_point("orchestrator")

    # Orchestrator conditionally routes to any agent
    workflow.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
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
        },
    )

    # All non-terminal agents loop back to orchestrator
    for node in [
        "research_agent",
        "api_design_agent",
        "product_manager",
        "architect",
        "code_generator",
        "code_reviewer",
        "qa_tester",
        "security_auditor",
        "dependency_agent",
        "performance_optimizer",
        "devops",
    ]:
        workflow.add_edge(node, "orchestrator")

    # documentation_writer is the terminal node
    workflow.add_edge("documentation_writer", END)

    return workflow.compile()


# Compiled singleton
app = build_graph()
