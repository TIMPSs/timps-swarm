"""
src/more_agents.py
==================
7 additional specialist agents:

  refactoring_agent   — code smell detection + automated refactor suggestions
  test_data_agent     — realistic fixture / seed data generation
  monitoring_agent    — Prometheus metrics, Grafana dashboards, alerting rules
  ui_ux_agent         — UI component spec, accessibility audit, design tokens
  i18n_agent          — string extraction, translation files, RTL support
  cost_optimizer      — cloud cost estimation + architecture optimisation
  self_critic_agent   — scores any agent output and re-runs weak agents (closes the quality loop)

All follow the same contract:
  fn(args: dict) -> dict   (sync, LLM-backed, saves artefacts to generated/)
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.llm_router import LLMRouter

logger = logging.getLogger(__name__)
_router = LLMRouter()
_GEN = Path("generated")


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _llm(prompt: str, system: str, agent: str = "default") -> str:
    try:
        return _router.call(agent, prompt, system_prompt=system)
    except Exception as exc:
        logger.error("LLM call failed for %s: %s", agent, exc)
        return (
            "[No LLM provider available — raw data follows]\n\n"
            f"Agent `{agent}` could not reach any LLM. "
            "The agent has gathered data below. "
            "To enable AI analysis, connect via an MCP client that supports sampling "
            "(e.g. Claude Code), or set an API key (GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.).\n\n"
            f"{prompt[:5000]}"
        )


def _strip_fences(text: str, lang: str = "") -> str:
    """Remove ```lang ... ``` fences."""
    pattern = rf"```{lang}\s*([\s\S]*?)```"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else text.strip()


def _save(sub: str, name: str, content: str) -> str:
    path = _GEN / sub / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return str(path)


# ── 1. Refactoring Agent ──────────────────────────────────────────────────────

def refactoring_agent(args: dict) -> dict:
    """
    Analyse code for smells, then produce a refactored version with a diff summary.

    Args:
      code (str): Source code to refactor.
      language (str): 'python' | 'javascript' | 'typescript' | 'java' | 'go' | ...
      goals (list[str]): e.g. ['reduce_complexity', 'improve_readability', 'extract_functions']
    """
    code = args.get("code", "")
    language = args.get("language", "python")
    goals = args.get("goals") or ["reduce_complexity", "improve_readability", "extract_functions"]

    if not code.strip():
        return {"error": "No code provided", "refactored_code": "", "smells": []}

    system = (
        "You are a senior refactoring engineer. Analyse code, identify ALL code smells "
        "(long methods, god classes, duplicate logic, magic numbers, deep nesting, "
        "poor naming, missing abstractions), then produce a fully refactored version. "
        "Return JSON: {smells: [{name, line, description, severity}], "
        "refactored_code: string, diff_summary: string, complexity_before: int, complexity_after: int, "
        "improvements: [string]}. Output ONLY valid JSON."
    )
    prompt = (
        f"Language: {language}\nGoals: {', '.join(goals)}\n\n"
        f"Code to refactor:\n```{language}\n{code[:6000]}\n```"
    )

    raw = _llm(prompt, system, "refactoring_agent")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"refactored_code": raw, "smells": [], "diff_summary": "See refactored_code", "improvements": []}

    refactored = data.get("refactored_code", "")
    report = (
        f"# Refactoring Report — {_ts()}\n\n"
        f"**Language:** {language}  **Goals:** {', '.join(goals)}\n\n"
        f"## Code Smells Found ({len(data.get('smells', []))})\n\n"
        + "\n".join(
            f"- **{s.get('name', '?')}** (line {s.get('line', '?')}, severity: {s.get('severity', '?')}): {s.get('description', '')}"
            for s in data.get("smells", [])
        )
        + f"\n\n## Complexity: {data.get('complexity_before', '?')} → {data.get('complexity_after', '?')}\n\n"
        f"## Improvements\n" + "\n".join(f"- {i}" for i in data.get("improvements", []))
        + f"\n\n## Diff Summary\n{data.get('diff_summary', '')}\n"
    )

    report_path = _save("reports", f"refactoring_{_ts()}.md", report)
    code_path = _save("code", f"refactored_{_ts()}.{language}", refactored)

    return {
        "smells": data.get("smells", []),
        "refactored_code": refactored,
        "diff_summary": data.get("diff_summary", ""),
        "complexity_before": data.get("complexity_before"),
        "complexity_after": data.get("complexity_after"),
        "improvements": data.get("improvements", []),
        "report_path": report_path,
        "code_path": code_path,
    }


# ── 2. Test Data Agent ────────────────────────────────────────────────────────

def test_data_agent(args: dict) -> dict:
    """
    Generate realistic seed / fixture data for any schema.

    Args:
      schema (str | dict): JSON schema, SQL DDL, or plain-text description.
      count (int):  Number of records (default 20).
      format (str): 'json' | 'csv' | 'sql' | 'yaml' | 'python_dict' (default 'json').
      locale (str): 'en_US' | 'de_DE' | 'ja_JP' | ... (default 'en_US').
    """
    schema = args.get("schema", "")
    count = int(args.get("count", 20))
    fmt = args.get("format", "json")
    locale = args.get("locale", "en_US")

    system = (
        "You are a test-data generation expert. Generate realistic, diverse, edge-case-covering "
        "seed data that looks like real production data (no lorem ipsum, no placeholder@example.com). "
        "Include boundary values (empty strings, max lengths, null optionals, unicode) and at "
        "least one invalid record for negative-test coverage. "
        f"Return ONLY a raw {fmt} block — no explanation, no markdown fences."
    )
    prompt = (
        f"Schema:\n{str(schema)[:4000]}\n\n"
        f"Generate {count} records in {fmt} format for locale {locale}. "
        "Include at least 1 edge-case record and 1 invalid record (mark it with a _invalid=true field or comment)."
    )

    raw = _llm(prompt, system, "test_data_agent")
    data_str = _strip_fences(raw, fmt)

    if fmt == "json":
        try:
            records = json.loads(data_str)
            if isinstance(records, list):
                valid = []
                for r in records:
                    if isinstance(r, dict):
                        name = str(r.get("name", r.get("Name", "")))
                        age = r.get("age", r.get("Age", 0))
                        stock = r.get("stock", r.get("Stock", r.get("quantity", r.get("Quantity", 0))))
                        valid.append(r)
                data_str = json.dumps(valid, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass

    ext = {"python_dict": "py", "yaml": "yaml"}.get(fmt, fmt)
    data_path = _save("datasets", f"seed_data_{_ts()}.{ext}", data_str)

    return {
        "data": data_str,
        "count": count,
        "format": fmt,
        "locale": locale,
        "data_path": data_path,
        "summary": f"Generated {count} {locale} {fmt} records. Saved to {data_path}",
    }


# ── 3. Monitoring Agent ───────────────────────────────────────────────────────

def monitoring_agent(args: dict) -> dict:
    """
    Generate Prometheus metrics definitions, Grafana dashboard JSON, and alerting rules.

    Args:
      service_description (str): What the service does.
      language (str): Service language/runtime (python | node | java | go).
      slos (list[str]): e.g. ['p99 < 200ms', 'error_rate < 0.1%', 'availability > 99.9%'].
      alerting_platform (str): 'alertmanager' | 'pagerduty' | 'opsgenie' (default 'alertmanager').
    """
    service_desc = args.get("service_description", "a web API")
    language = args.get("language", "python")
    slos = args.get("slos") or ["p99 < 200ms", "error_rate < 0.1%", "availability > 99.9%"]
    alert_platform = args.get("alerting_platform", "alertmanager")

    system = (
        "You are an SRE expert in observability. Generate production-ready monitoring config. "
        "Return JSON with keys: "
        "{metrics: [{name, type, help, labels}], "
        "prometheus_rules: string (YAML), "
        "grafana_dashboard: object (valid Grafana dashboard JSON), "
        "instrumentation_snippet: string (code snippet showing how to instrument the service), "
        "alert_rules: [{name, expr, severity, summary, runbook_url}]}. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Service: {service_desc}\nLanguage/runtime: {language}\n"
        f"SLOs: {', '.join(slos)}\nAlerting platform: {alert_platform}\n\n"
        "Generate complete monitoring configuration for this service."
    )

    raw = _llm(prompt, system, "monitoring_agent")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"prometheus_rules": raw, "metrics": [], "alert_rules": [], "grafana_dashboard": {}}

    prom_rules = data.get("prometheus_rules", "")
    dashboard = data.get("grafana_dashboard", {})
    snippet = data.get("instrumentation_snippet", "")

    rules_path = _save("monitoring", f"prometheus_rules_{_ts()}.yml", prom_rules)
    dash_path = _save("monitoring", f"grafana_dashboard_{_ts()}.json",
                      json.dumps(dashboard, indent=2))
    snippet_path = _save("monitoring", f"instrumentation_{_ts()}.{language}", snippet)

    return {
        "metrics": data.get("metrics", []),
        "alert_rules": data.get("alert_rules", []),
        "prometheus_rules": prom_rules,
        "grafana_dashboard": dashboard,
        "instrumentation_snippet": snippet,
        "rules_path": rules_path,
        "dashboard_path": dash_path,
        "snippet_path": snippet_path,
        "summary": (
            f"Generated {len(data.get('metrics', []))} metrics, "
            f"{len(data.get('alert_rules', []))} alert rules, Grafana dashboard."
        ),
    }


# ── 4. UI/UX Agent ────────────────────────────────────────────────────────────

def ui_ux_agent(args: dict) -> dict:
    """
    Generate UI component specs, accessibility audit, design tokens, and component code.

    Args:
      description (str): What the UI is for.
      framework (str): 'react' | 'vue' | 'svelte' | 'html' (default 'react').
      design_system (str): 'tailwind' | 'material' | 'chakra' | 'custom' (default 'tailwind').
      accessibility_level (str): 'AA' | 'AAA' (WCAG, default 'AA').
    """
    description = args.get("description", "")
    framework = args.get("framework", "react")
    design_system = args.get("design_system", "tailwind")
    a11y_level = args.get("accessibility_level", "AA")

    system = (
        "You are a senior UI/UX engineer and accessibility expert. "
        "Return JSON with: "
        "{component_spec: {name, props, states, variants, interactions}, "
        "component_code: string, "
        "design_tokens: {colors, spacing, typography}, "
        "accessibility_checklist: [{criterion, passed, notes}], "
        "a11y_issues: [{severity, element, issue, fix}], "
        "storybook_story: string}. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"UI/UX task: {description}\n"
        f"Framework: {framework}, Design system: {design_system}, "
        f"Accessibility: WCAG {a11y_level}\n\n"
        "Generate the component spec, implementation, and accessibility audit."
    )

    raw = _llm(prompt, system, "ui_ux_agent")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"component_code": raw, "component_spec": {}, "a11y_issues": [], "design_tokens": {}}

    ext = {"react": "tsx", "vue": "vue", "svelte": "svelte"}.get(framework, "html")
    comp_name = data.get("component_spec", {}).get("name", "Component")

    comp_path = _save("ui", f"{comp_name}_{_ts()}.{ext}", data.get("component_code", ""))
    story_path = _save("ui", f"{comp_name}.stories.{ext}", data.get("storybook_story", ""))
    tokens_path = _save("ui", f"design_tokens_{_ts()}.json",
                        json.dumps(data.get("design_tokens", {}), indent=2))

    a11y_issues = data.get("a11y_issues", [])
    critical = [i for i in a11y_issues if i.get("severity") in ("critical", "serious")]

    return {
        "component_spec": data.get("component_spec", {}),
        "component_code": data.get("component_code", ""),
        "design_tokens": data.get("design_tokens", {}),
        "a11y_issues": a11y_issues,
        "critical_a11y_issues": len(critical),
        "storybook_story": data.get("storybook_story", ""),
        "comp_path": comp_path,
        "story_path": story_path,
        "tokens_path": tokens_path,
        "summary": (
            f"Component '{comp_name}' generated for {framework}/{design_system}. "
            f"{len(a11y_issues)} a11y issues ({len(critical)} critical)."
        ),
    }


# ── 5. i18n Agent ─────────────────────────────────────────────────────────────

def i18n_agent(args: dict) -> dict:
    """
    Extract translatable strings from source code, generate translation files,
    and flag RTL / cultural issues.

    Args:
      code (str): Source code or JSX/TSX content to scan.
      source_locale (str): e.g. 'en' (default).
      target_locales (list[str]): e.g. ['fr', 'de', 'ja', 'ar', 'he'].
      i18n_framework (str): 'react-i18next' | 'vue-i18n' | 'python-gettext' | 'fluent' | 'auto'.
    """
    code = args.get("code", "")
    source_locale = args.get("source_locale", "en")
    target_locales = args.get("target_locales") or ["fr", "de", "ja", "ar"]
    framework = args.get("i18n_framework", "auto")

    system = (
        "You are an internationalisation (i18n) expert. "
        "Extract ALL user-facing strings from the code, detect hardcoded dates/numbers/currencies, "
        "flag RTL issues (Arabic, Hebrew, Persian), and generate translation files. "
        "Return JSON: "
        "{extracted_keys: [{key, default_value, context, file_location}], "
        "translations: {locale: {key: translation}}, "
        "rtl_locales: [string], "
        "cultural_issues: [{locale, issue, recommendation}], "
        "instrumented_code: string, "
        "missing_keys: [string]}. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Source locale: {source_locale}, Target locales: {', '.join(target_locales)}\n"
        f"i18n framework: {framework}\n\nCode:\n```\n{code[:5000]}\n```\n\n"
        "Extract strings, generate translations, instrument the code."
    )

    raw = _llm(prompt, system, "i18n_agent")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"extracted_keys": [], "translations": {}, "instrumented_code": raw}

    translations = data.get("translations", {})
    saved_paths: dict[str, str] = {}
    for locale, strings in translations.items():
        content = json.dumps(strings, indent=2, ensure_ascii=False)
        saved_paths[locale] = _save("i18n", f"{locale}.json", content)

    return {
        "extracted_keys": data.get("extracted_keys", []),
        "key_count": len(data.get("extracted_keys", [])),
        "translations": translations,
        "rtl_locales": data.get("rtl_locales", []),
        "cultural_issues": data.get("cultural_issues", []),
        "instrumented_code": data.get("instrumented_code", ""),
        "missing_keys": data.get("missing_keys", []),
        "translation_paths": saved_paths,
        "summary": (
            f"Extracted {len(data.get('extracted_keys', []))} keys, "
            f"generated {len(translations)} translation files. "
            f"RTL locales: {data.get('rtl_locales', [])}."
        ),
    }


# ── 6. Cost Optimizer ─────────────────────────────────────────────────────────

def cost_optimizer(args: dict) -> dict:
    """
    Estimate cloud cost for an architecture and suggest cheaper alternatives.

    Args:
      architecture (str): Architecture description or IaC (Terraform/CDK/CloudFormation snippet).
      provider (str): 'aws' | 'gcp' | 'azure' | 'multi' (default 'aws').
      monthly_requests (int): Estimated requests/month (default 1_000_000).
      regions (list[str]): Target regions (default ['us-east-1']).
    """
    arch = args.get("architecture", "")
    provider = args.get("provider", "aws")
    monthly_reqs = int(args.get("monthly_requests", 1_000_000))
    regions = args.get("regions") or ["us-east-1"]

    system = (
        "You are a cloud FinOps expert. Estimate costs and identify savings opportunities. "
        "Return JSON: "
        "{services: [{service, tier, monthly_cost_usd, notes}], "
        "total_monthly_usd: float, "
        "total_annual_usd: float, "
        "optimisations: [{description, estimated_saving_usd, effort, risk}], "
        "recommended_architecture: string, "
        "savings_potential_usd: float, "
        "cost_breakdown_chart: [{label, value}]}. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Cloud provider: {provider}\nRegions: {', '.join(regions)}\n"
        f"Monthly requests: {monthly_reqs:,}\n\nArchitecture:\n{arch[:4000]}\n\n"
        "Estimate costs and suggest optimisations."
    )

    raw = _llm(prompt, system, "cost_optimizer")
    try:
        data = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        data = {"recommended_architecture": raw, "services": [], "optimisations": [],
                "total_monthly_usd": 0.0, "savings_potential_usd": 0.0}

    report = (
        f"# Cloud Cost Report — {provider.upper()} — {_ts()}\n\n"
        f"**Monthly requests:** {monthly_reqs:,}  **Regions:** {', '.join(regions)}\n\n"
        f"## Cost Breakdown\n\n"
        + "\n".join(
            f"| {s.get('service', '?')} | {s.get('tier', '?')} | ${s.get('monthly_cost_usd', 0):.2f}/mo |"
            for s in data.get("services", [])
        )
        + f"\n\n**Total: ${data.get('total_monthly_usd', 0):.2f}/mo "
        f"(${data.get('total_annual_usd', 0):.2f}/yr)**\n\n"
        f"## Savings Opportunities (${data.get('savings_potential_usd', 0):.2f}/mo potential)\n\n"
        + "\n".join(
            f"- **{o.get('description', '?')}** — save ~${o.get('estimated_saving_usd', 0):.2f}/mo "
            f"(effort: {o.get('effort', '?')}, risk: {o.get('risk', '?')})"
            for o in data.get("optimisations", [])
        )
        + f"\n\n## Recommended Architecture\n\n{data.get('recommended_architecture', '')}\n"
    )

    report_path = _save("reports", f"cost_report_{_ts()}.md", report)

    return {
        "services": data.get("services", []),
        "total_monthly_usd": data.get("total_monthly_usd", 0.0),
        "total_annual_usd": data.get("total_annual_usd", 0.0),
        "optimisations": data.get("optimisations", []),
        "savings_potential_usd": data.get("savings_potential_usd", 0.0),
        "recommended_architecture": data.get("recommended_architecture", ""),
        "report_path": report_path,
        "summary": (
            f"Estimated ${data.get('total_monthly_usd', 0):.2f}/mo on {provider.upper()}. "
            f"${data.get('savings_potential_usd', 0):.2f}/mo savings identified."
        ),
    }


# ── 7. Self-Critic Agent ──────────────────────────────────────────────────────

def self_critic_agent(args: dict) -> dict:
    """
    Score any agent's output on a 1-10 scale, identify weaknesses, and optionally
    re-run the originating agent until quality threshold is met. This closes the
    quality feedback loop in the swarm.

    Args:
      content (str): The output to critique.
      agent (str): Which agent produced it (for context-appropriate critique).
      task (str): The original task/requirement.
      threshold (int): Re-run if score < threshold (default 7).
      max_retries (int): Maximum re-run attempts (default 2).
    """
    content = args.get("content", "")
    agent_name = args.get("agent", "unknown")
    task = args.get("task", "")
    threshold = int(args.get("threshold", 7))
    max_retries = int(args.get("max_retries", 2))

    if not content.strip():
        return {"error": "No content to critique", "score": 0, "final_output": ""}

    if content.startswith("[No LLM provider available"):
        return {
            "error": content[:200],
            "score": 0,
            "verdict": "fail",
            "strengths": [],
            "weaknesses": ["LLM provider unavailable"],
            "critical_issues": ["Cannot score — LLM provider error"],
            "final_output": content,
            "summary": f"Cannot score {agent_name} output: LLM provider unavailable.",
        }

    # Critique rubrics per agent type
    rubrics = {
        "code_generator": "correctness, security, performance, readability, test coverage",
        "api_design_agent": "completeness, RESTful conventions, security, versioning, error schemas",
        "research_agent": "source diversity, recency, depth, actionability, bias avoidance",
        "db_agent": "normalisation, index coverage, migration safety, query efficiency",
        "n8n_workflow_agent": "node correctness, error handling, idempotency, trigger completeness",
        "refactoring_agent": "smell coverage, improvement magnitude, backward compatibility",
        "test_data_agent": "realism, diversity, edge-case coverage, boundary values",
        "monitoring_agent": "SLO coverage, alert precision, cardinality, runbook completeness",
        "ui_ux_agent": "accessibility, usability, design consistency, mobile responsiveness",
        "i18n_agent": "key completeness, translation quality, RTL handling, cultural sensitivity",
        "cost_optimizer": "accuracy, savings specificity, risk assessment, provider knowledge",
    }
    rubric = rubrics.get(agent_name, "quality, completeness, accuracy, actionability")

    system = (
        "You are a hyper-critical senior engineering reviewer. Score output quality objectively. "
        "Return JSON: "
        "{score: int (1-10), "
        "verdict: 'pass' | 'fail', "
        "strengths: [string], "
        "weaknesses: [string], "
        "critical_issues: [string], "
        "improvement_prompt: string (a better prompt to re-run the agent), "
        "revised_output: string (your own improved version if score < 7)}. "
        "Be strict: score 10 only for production-ready, 7+ for acceptable, <7 triggers re-run. "
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Agent: {agent_name}\nTask: {task}\nEvaluation rubric: {rubric}\n\n"
        f"Output to critique:\n---\n{content[:5000]}\n---\n\n"
        f"Score this output. Threshold to pass: {threshold}/10."
    )

    raw = _llm(prompt, system, "self_critic_agent")
    try:
        critique = json.loads(_strip_fences(raw, "json"))
    except json.JSONDecodeError:
        critique = {
            "score": 5, "verdict": "fail", "strengths": [], "weaknesses": ["Could not parse critique"],
            "critical_issues": [], "improvement_prompt": task, "revised_output": "",
        }

    score = int(critique.get("score", 5))
    verdict = "pass" if score >= threshold else "fail"
    critique["verdict"] = verdict
    final_output = content
    iteration = 0

    # Retry loop — re-run the originating agent with an improved prompt
    if verdict == "fail" and max_retries > 0:
        from src.priority_agents import PRIORITY_AGENTS
        from src.more_agents import MORE_AGENTS  # noqa: F811 (self-import)

        all_agents = {**PRIORITY_AGENTS, **MORE_AGENTS}
        agent_fn = all_agents.get(agent_name)

        improved_prompt = critique.get("improvement_prompt", task)

        for iteration in range(1, max_retries + 1):
            logger.info("Self-critic: re-running %s (attempt %d, score=%d)", agent_name, iteration, score)

            if agent_fn:
                # Re-run the agent with improved context
                re_args = dict(args)
                re_args["task"] = improved_prompt
                re_args["description"] = improved_prompt
                re_args["topic"] = improved_prompt
                try:
                    new_result = agent_fn(re_args)
                    new_content = str(new_result.get("summary", new_result.get("spec_yaml",
                                     new_result.get("report", json.dumps(new_result)[:2000]))))
                except Exception as exc:
                    logger.warning("Re-run failed: %s", exc)
                    break
            else:
                # Use the revised output from critique itself
                new_content = critique.get("revised_output", content)

            # Re-score
            re_prompt = (
                f"Agent: {agent_name}\nTask: {improved_prompt}\nEvaluation rubric: {rubric}\n\n"
                f"Output to critique:\n---\n{new_content[:5000]}\n---\n\n"
                f"Score this output. Threshold to pass: {threshold}/10."
            )
            re_raw = _llm(re_prompt, system, "self_critic_agent")
            try:
                re_critique = json.loads(_strip_fences(re_raw, "json"))
            except json.JSONDecodeError:
                break

            new_score = int(re_critique.get("score", score))
            logger.info("Self-critic: re-run %d score=%d", iteration, new_score)

            if new_score > score:
                score = new_score
                final_output = new_content
                critique = re_critique
                critique["verdict"] = "pass" if score >= threshold else "fail"
                if score >= threshold:
                    verdict = "pass"
                    break
            else:
                # Score didn't improve — stop trying
                break

    report_lines = [
        f"# Self-Critic Report — {agent_name} — {_ts()}\n",
        f"**Score:** {score}/10  **Verdict:** {verdict.upper()}  "
        f"**Threshold:** {threshold}  **Retries used:** {iteration}\n",
        f"**Task:** {task}\n",
        "## Strengths\n" + "\n".join(f"- {s}" for s in critique.get("strengths", [])),
        "\n## Weaknesses\n" + "\n".join(f"- {w}" for w in critique.get("weaknesses", [])),
        "\n## Critical Issues\n" + "\n".join(f"- ⚠️ {c}" for c in critique.get("critical_issues", [])),
    ]
    report_path = _save("reports", f"self_critic_{agent_name}_{_ts()}.md", "\n".join(report_lines))

    return {
        "score": score,
        "verdict": verdict,
        "threshold": threshold,
        "iterations": iteration,
        "strengths": critique.get("strengths", []),
        "weaknesses": critique.get("weaknesses", []),
        "critical_issues": critique.get("critical_issues", []),
        "improvement_prompt": critique.get("improvement_prompt", ""),
        "final_output": final_output,
        "report_path": report_path,
        "summary": (
            f"Score {score}/10 ({verdict.upper()}) for {agent_name} output. "
            f"{'Quality loop closed after ' + str(iteration) + ' retries.' if iteration > 0 else 'Passed on first attempt.'}"
        ),
    }


# ── Dispatch table ────────────────────────────────────────────────────────────

MORE_AGENTS: dict[str, Any] = {
    "refactoring_agent": refactoring_agent,
    "test_data_agent":   test_data_agent,
    "monitoring_agent":  monitoring_agent,
    "ui_ux_agent":       ui_ux_agent,
    "i18n_agent":        i18n_agent,
    "cost_optimizer":    cost_optimizer,
    "self_critic_agent": self_critic_agent,
}
