"""
LangGraph workflow — wires all 10 agents into a conditional DAG.

Flow:
  orchestrator → [product_manager | architect | code_generator | ...]
               ↑_______________________________________________|

  documentation_writer → END
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


# ── Routing logic ─────────────────────────────────────────────────────────────

def route_after_orchestrator(state: SwarmState) -> str:
    """Decide which agent to invoke next based on current state."""

    if state.get("completed"):
        return "documentation_writer"

    if state.get("iteration_count", 0) > state.get("max_iterations", 10):
        return "documentation_writer"

    tasks = state.get("tasks", [])
    pending = {t["assigned_to"] for t in tasks if t["status"] == "pending"}
    failed  = {t["assigned_to"] for t in tasks if t["status"] == "failed"}

    # Follow dependency order
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

    # All done
    return "documentation_writer"


# ── Build the graph ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    workflow = StateGraph(SwarmState)

    # Register all 10 agent nodes
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

    # Entry point
    workflow.set_entry_point("orchestrator")

    # Orchestrator conditionally routes to any agent
    workflow.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "product_manager":       "product_manager",
            "architect":             "architect",
            "code_generator":        "code_generator",
            "code_reviewer":         "code_reviewer",
            "qa_tester":             "qa_tester",
            "security_auditor":      "security_auditor",
            "performance_optimizer": "performance_optimizer",
            "documentation_writer":  "documentation_writer",
            "devops":                "devops",
        },
    )

    # All non-terminal agents loop back to orchestrator
    for node in [
        "product_manager",
        "architect",
        "code_generator",
        "code_reviewer",
        "qa_tester",
        "security_auditor",
        "performance_optimizer",
        "devops",
    ]:
        workflow.add_edge(node, "orchestrator")

    # documentation_writer is the terminal node
    workflow.add_edge("documentation_writer", END)

    return workflow.compile()


# Compiled singleton
app = build_graph()
