"""
TIMPS Swarm — Phase 7 Specialist Agents (32)
=============================================
32 new specialist agents shipped in the 2026-06 expansion. They cover gaps
in security & offensive testing, compliance & legal, DevOps & reliability,
data & forecasting, ML/AI ops, research & intel, content & creative,
voice/sales, and personal productivity.

All agents follow the standard TIMPS contract::

    fn(args: Dict[str, Any]) -> Dict[str, Any]

and reuse ``src._helpers`` for LLM routing, JSON parsing, file persistence,
shell execution, and memory recording — so they integrate with the SDLC
DAG, MCP server, dashboard, and Self-Critic loop without any extra glue.
"""
from __future__ import annotations

# ── Security & Offensive Testing (5) ──────────────────────────────────────────
from src.phase7.red_team_agent           import red_team_agent
from src.phase7.prompt_injection_scanner import prompt_injection_scanner
from src.phase7.phishing_simulator       import phishing_simulator
from src.phase7.api_security_tester      import api_security_tester
from src.phase7.container_image_scanner  import container_image_scanner

# ── Compliance & Legal (3) ────────────────────────────────────────────────────
from src.phase7.contract_reviewer        import contract_reviewer
from src.phase7.dpdp_act_auditor         import dpdp_act_auditor
from src.phase7.fssai_compliance_agent   import fssai_compliance_agent

# ── DevOps & Reliability (5) ──────────────────────────────────────────────────
from src.phase7.observability_cost_optimizer import observability_cost_optimizer
from src.phase7.service_mesh_configurator    import service_mesh_configurator
from src.phase7.iac_drift_detector           import iac_drift_detector
from src.phase7.sbom_generator               import sbom_generator
from src.phase7.license_compliance_scanner   import license_compliance_scanner

# ── Research & Intel (3) ──────────────────────────────────────────────────────
from src.phase7.deep_research_agent          import deep_research_agent
from src.phase7.agent_marketplace_curator    import agent_marketplace_curator
from src.phase7.adr_writer                   import adr_writer

# ── Data & Forecasting (3) ────────────────────────────────────────────────────
from src.phase7.churn_predictor              import churn_predictor
from src.phase7.demand_forecaster            import demand_forecaster
from src.phase7.agri_commodity_forecaster    import agri_commodity_forecaster

# ── Productivity & Wellness (3) ───────────────────────────────────────────────
from src.phase7.calendar_optimizer           import calendar_optimizer
from src.phase7.wearable_health_coach        import wearable_health_coach
from src.phase7.game_day_facilitator         import game_day_facilitator

# ── Content & Creative (4) ────────────────────────────────────────────────────
from src.phase7.cold_email_sequence_writer   import cold_email_sequence_writer
from src.phase7.demo_video_script_writer     import demo_video_script_writer
from src.phase7.podcast_show_notes_writer    import podcast_show_notes_writer
from src.phase7.storybook_story_generator    import storybook_story_generator

# ── Sales, Voice & Legal-adjacent (3) ─────────────────────────────────────────
from src.phase7.win_loss_analyst             import win_loss_analyst
from src.phase7.voice_agent_designer         import voice_agent_designer
from src.phase7.court_case_summarizer        import court_case_summarizer

# ── ML / AI Ops (3) ───────────────────────────────────────────────────────────
from src.phase7.rag_evaluator                import rag_evaluator
from src.phase7.computer_use_agent           import computer_use_agent
from src.phase7.tracing_emitter              import tracing_emitter


PHASE7_AGENTS = {
    # Security & Offensive Testing
    "red_team_agent":             red_team_agent,
    "prompt_injection_scanner":   prompt_injection_scanner,
    "phishing_simulator":         phishing_simulator,
    "api_security_tester":        api_security_tester,
    "container_image_scanner":    container_image_scanner,
    # Compliance & Legal
    "contract_reviewer":          contract_reviewer,
    "dpdp_act_auditor":           dpdp_act_auditor,
    "fssai_compliance_agent":     fssai_compliance_agent,
    # DevOps & Reliability
    "observability_cost_optimizer": observability_cost_optimizer,
    "service_mesh_configurator":    service_mesh_configurator,
    "iac_drift_detector":           iac_drift_detector,
    "sbom_generator":               sbom_generator,
    "license_compliance_scanner":   license_compliance_scanner,
    # Research & Intel
    "deep_research_agent":         deep_research_agent,
    "agent_marketplace_curator":   agent_marketplace_curator,
    "adr_writer":                  adr_writer,
    # Data & Forecasting
    "churn_predictor":             churn_predictor,
    "demand_forecaster":           demand_forecaster,
    "agri_commodity_forecaster":   agri_commodity_forecaster,
    # Productivity & Wellness
    "calendar_optimizer":          calendar_optimizer,
    "wearable_health_coach":       wearable_health_coach,
    "game_day_facilitator":        game_day_facilitator,
    # Content & Creative
    "cold_email_sequence_writer":  cold_email_sequence_writer,
    "demo_video_script_writer":    demo_video_script_writer,
    "podcast_show_notes_writer":   podcast_show_notes_writer,
    "storybook_story_generator":   storybook_story_generator,
    # Sales, Voice & Legal-adjacent
    "win_loss_analyst":            win_loss_analyst,
    "voice_agent_designer":        voice_agent_designer,
    "court_case_summarizer":       court_case_summarizer,
    # ML / AI Ops
    "rag_evaluator":               rag_evaluator,
    "computer_use_agent":          computer_use_agent,
    "tracing_emitter":             tracing_emitter,
}

PHASE7_AGENT_CATEGORIES = {
    "security_offensive": [
        "red_team_agent", "prompt_injection_scanner", "phishing_simulator",
        "api_security_tester", "container_image_scanner",
    ],
    "compliance_legal": [
        "contract_reviewer", "dpdp_act_auditor", "fssai_compliance_agent",
    ],
    "devops_reliability": [
        "observability_cost_optimizer", "service_mesh_configurator",
        "iac_drift_detector", "sbom_generator", "license_compliance_scanner",
    ],
    "research_intel": [
        "deep_research_agent", "agent_marketplace_curator", "adr_writer",
    ],
    "data_forecasting": [
        "churn_predictor", "demand_forecaster", "agri_commodity_forecaster",
    ],
    "productivity_wellness": [
        "calendar_optimizer", "wearable_health_coach", "game_day_facilitator",
    ],
    "content_creative": [
        "cold_email_sequence_writer", "demo_video_script_writer",
        "podcast_show_notes_writer", "storybook_story_generator",
    ],
    "sales_voice_legal": [
        "win_loss_analyst", "voice_agent_designer", "court_case_summarizer",
    ],
    "ml_ai_ops": [
        "rag_evaluator", "computer_use_agent", "tracing_emitter",
    ],
}

__all__ = list(PHASE7_AGENTS.keys()) + ["PHASE7_AGENTS", "PHASE7_AGENT_CATEGORIES"]
