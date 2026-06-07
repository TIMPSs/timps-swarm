"""
TIMPS Swarm — Next-Generation Agents (Phase 6)
================================================

21 new specialist agents derived from the June 2026 Deep Research Report.
Each agent addresses a specific gap identified in the AI agent market
analysis (security ops, K8s, accessibility, release engineering, MLOps,
emerging tech) that the existing 110-agent fleet does not yet cover.

All agents follow the standard TIMPS contract:
    fn(args: Dict[str, Any]) -> Dict[str, Any]

…and reuse `src._helpers` for LLM routing, JSON parsing, file persistence,
shell execution, and memory recording so they integrate seamlessly with
the SDLC DAG, MCP server, dashboard, and Self-Critic loop.
"""
from __future__ import annotations

# ── Security Operations (4) ──────────────────────────────────────────────────
from src.nextgen.threat_intel_analyst         import threat_intel_analyst
from src.nextgen.security_remediation         import security_remediation
from src.nextgen.compliance_auditor           import compliance_auditor
from src.nextgen.incident_response_coordinator import incident_response_coordinator

# ── DevOps & Infrastructure (3) ──────────────────────────────────────────────
from src.nextgen.kubernetes_navigator         import kubernetes_navigator
from src.nextgen.pipeline_healer              import pipeline_healer
from src.nextgen.docker_compose_architect     import docker_compose_architect

# ── Code Quality (2) ─────────────────────────────────────────────────────────
from src.nextgen.test_intelligence            import test_intelligence
from src.nextgen.changelog_generator          import changelog_generator

# ── Data & Analytics (3) ─────────────────────────────────────────────────────
from src.nextgen.db_migration_pilot           import db_migration_pilot
from src.nextgen.log_pattern_analyzer         import log_pattern_analyzer
from src.nextgen.api_perf_profiler            import api_perf_profiler

# ── User Experience (2) ──────────────────────────────────────────────────────
from src.nextgen.accessibility_tester         import accessibility_tester
from src.nextgen.visual_regression_detective  import visual_regression_detective

# ── Business & Productivity (2) ──────────────────────────────────────────────
from src.nextgen.release_manager              import release_manager
from src.nextgen.tech_writer_assistant        import tech_writer_assistant

# ── MLOps (1) ────────────────────────────────────────────────────────────────
from src.nextgen.model_perf_monitor           import model_perf_monitor

# ── Emerging Technology (4) ──────────────────────────────────────────────────
from src.nextgen.mcp_server_generator         import mcp_server_generator
from src.nextgen.ai_workflow_orchestrator     import ai_workflow_orchestrator
from src.nextgen.local_rag_builder            import local_rag_builder
from src.nextgen.git_workflow_automator       import git_workflow_automator

# ── New emerging tool: web search (added 2026-06) ────────────────────────────
from src.nextgen.web_search                   import web_search


NEXTGEN_AGENTS = {
    # Security
    "threat_intel_analyst":          threat_intel_analyst,
    "security_remediation":          security_remediation,
    "compliance_auditor":            compliance_auditor,
    "incident_response_coordinator": incident_response_coordinator,
    # DevOps
    "kubernetes_navigator":          kubernetes_navigator,
    "pipeline_healer":               pipeline_healer,
    "docker_compose_architect":      docker_compose_architect,
    # Code quality
    "test_intelligence":             test_intelligence,
    "changelog_generator":           changelog_generator,
    # Data
    "db_migration_pilot":            db_migration_pilot,
    "log_pattern_analyzer":          log_pattern_analyzer,
    "api_perf_profiler":             api_perf_profiler,
    # UX
    "accessibility_tester":          accessibility_tester,
    "visual_regression_detective":   visual_regression_detective,
    # Business
    "release_manager":               release_manager,
    "tech_writer_assistant":         tech_writer_assistant,
    # MLOps
    "model_perf_monitor":            model_perf_monitor,
    # Emerging
    "mcp_server_generator":          mcp_server_generator,
    "ai_workflow_orchestrator":      ai_workflow_orchestrator,
    "local_rag_builder":             local_rag_builder,
    "git_workflow_automator":        git_workflow_automator,
    # Emerging → New tools (web search)
    "web_search":                    web_search,
}

NEXTGEN_AGENT_CATEGORIES = {
    "security":     ["threat_intel_analyst", "security_remediation",
                     "compliance_auditor", "incident_response_coordinator"],
    "devops":       ["kubernetes_navigator", "pipeline_healer", "docker_compose_architect"],
    "code_quality": ["test_intelligence", "changelog_generator"],
    "data":         ["db_migration_pilot", "log_pattern_analyzer", "api_perf_profiler"],
    "ux":           ["accessibility_tester", "visual_regression_detective"],
    "business":     ["release_manager", "tech_writer_assistant"],
    "mlops":        ["model_perf_monitor"],
    "emerging":     ["mcp_server_generator", "ai_workflow_orchestrator",
                     "local_rag_builder", "git_workflow_automator", "web_search"],
}

__all__ = list(NEXTGEN_AGENTS.keys()) + ["NEXTGEN_AGENTS", "NEXTGEN_AGENT_CATEGORIES"]
