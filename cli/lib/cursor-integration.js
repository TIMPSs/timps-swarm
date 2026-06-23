#!/usr/bin/env node
/**
 * Cursor Integration
 * ==================
 * Generates .cursorrules and .cursor/rules/*.mdc files that teach Cursor
 * about the TIMPS Swarm tool suite — making every TIMPS agent discoverable
 * as a rule-referenced capability inside Cursor's composer and chat.
 *
 * The generated files tell Cursor:
 *   1. The full list of available timps_* tools (by category)
 *   2. When to use `timps_batch` for bulk operations
 *   3. How to delegate to TIMPS for computer health, code review, research, etc.
 *
 * Usage:
 *   node cli/lib/cursor-integration.js                          # write rules
 *   node cli/lib/cursor-integration.js --dry-run                 # preview only
 *   node cli/lib/cursor-integration.js --project-dir <path>     # write into a specific project
 *   node cli/lib/cursor-integration.js --remove                  # remove our rules
 *   node cli/lib/cursor-integration.js --user-only               # only write ~/.cursorrules
 *   node cli/lib/cursor-integration.js --project-only            # only write .cursor/rules/*.mdc
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, unlinkSync } from "fs";
import { homedir } from "os";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const HOME = homedir();

// ── Paths ────────────────────────────────────────────────────────────────────

const USER_RULES_PATH = join(HOME, ".cursorrules");
const CURSOR_DIR = join(HOME, ".cursor");
const CURSOR_RULES_DIR = join(CURSOR_DIR, "rules");

// ── .cursorrules content ─────────────────────────────────────────────────────

function generateUserRules() {
  return `# TIMPS Swarm — AI Agent Toolkit
# Managed by timps-swarm/cursor-integration.js
#
# TIMPS exposes 160+ specialist agents as MCP tools. Cursor can call them
# directly via \`tools.call("timps_*", {...})\` or via the composer/chat.
#
# ── Categories ────────────────────────────────────────────────────────────────

## SDLC Pipeline
- \`timps_run_task\` — Full 10-agent SDLC pipeline (PM → architect → coder → reviewer → QA → security → perf → devops → docs)
- \`timps_pr_reviewer\` — Structured PR review with 0-10 score
- \`timps_unit_test_writer\` — Generate test suites with happy/edge/error paths
- \`timps_docstring_generator\` — Insert docstrings (Google/Sphinx/NumPy/JSDoc/Doxygen)
- \`timps_refactoring_agent\` — Detect code smells and produce refactored code

## API & Database Design
- \`timps_api_design_agent\` — Generate OpenAPI 3.1 specs from natural language
- \`timps_db_agent\` — Schema design, migrations, ER diagrams, index recommendations
- \`timps_sql_optimizer\` — Analyse slow queries, suggest indexes and rewrites
- \`timps_api_contract_auditor\` — Diff two API specs for breaking changes
- \`timps_graphql_agent\` — Write GraphQL SDL, resolvers, DataLoader, subscriptions

## Code Quality & Security
- \`timps_dependency_agent\` — CVE scan, license check, version pinning, upgrade script
- \`timps_dependency_sentinel\` — Ranked CVE report from any manifest
- \`timps_security_guard\` — Open ports, camera/mic permissions, suspicious processes
- \`timps_api_security_tester\` — OWASP API Top-10 audit against spec or endpoint
- \`timps_dependency_rebel\` — Dependency conflict/vulnerability detection
- \`timps_code_archaeology\` — Git history → AST import graph + risk map
- \`timps_pattern_detector\` — Duplicate code, god classes, magic numbers
- \`timps_technical_debt\` — Radon complexity + git churn + TODO density → debt roadmap

## Computer Health (diagnose and fix)
- \`timps_system_optimizer\` — Diagnose slow laptop: CPU hogs, startup bloat, thermal
- \`timps_environment_doctor\` — Fix broken Python/Node/Docker/PATH environments
- \`timps_network_medic\` — Diagnose WiFi drops, DNS failures, high latency
- \`timps_battery_analyst\` — Identify energy vampire processes
- \`timps_security_guard\` — Open ports, permissions scan
- \`timps_file_organizer\` — Organise Downloads/Desktop clutter
- \`timps_full_checkup\` — Run all health agents for a comprehensive scan

## Research & Knowledge
- \`timps_research_scout\` — Deep-dive on any topic with sourced brief
- \`timps_deep_research_agent\` — Multi-hop, multi-source research planner
- \`timps_trend_monitor\` — Track keywords across HN/Reddit/GitHub/Dev.to
- \`timps_competitor_tracker\` — Monitor competitors for pricing/features/hiring
- \`timps_data_wrangler\` — Clean and normalise messy data (CSV/JSON/PDF)

## Infrastructure & DevOps
- \`timps_kubernetes_navigator\` — Diagnose K8s workloads, output fix YAML
- \`timps_docker_compose_architect\` — Production-grade compose files
- \`timps_terraform_plan_reviewer\` — Review terraform plan for destructive changes
- \`timps_load_testing\` — k6/Artillery/Locust scripts with ramp-up plans
- \`timps_disaster_recovery\` — RTO/RPO-aware DR plans and failover runbooks
- \`timps_cost_optimizer\` — Estimate cloud costs and generate savings plan
- \`timps_certificate_rotator\` — Check TLS expiry for all hosts in config

## Content & Communication
- \`timps_content_multiplier\` — Long-form → tweet thread, LinkedIn, changelog, docs
- \`timps_inbox_gatekeeper\` — Triage email: urgent flags, draft replies
- \`timps_meeting_condenser\` — Transcript → action items, decisions, open questions
- \`timps_cold_email_sequence_writer\` — 5-7 step outreach sequences
- \`timps_demo_video_script_writer\` — 60-90s product demo script with storyboard

## Log Analysis & Incident Response
- \`timps_log_detective\` — Cluster errors from logs, identify root cause
- \`timps_log_interpreter\` — Crash logs → plain English explanation
- \`timps_incident_responder\` — Multi-source log correlation for incidents
- \`timps_incident_response_coordinator\` — Play-by-play incident response

## Bulk Operations
When you need to apply the same operation across many files:
- \`timps_batch\` — Decompose a bulk task into parallel sub-tasks, execute concurrently, return aggregated result
  - Example: \`timps_batch({ instruction: "add tests for all handlers", agent_type: "unit_test_writer", working_dir: "/project" })\`
  - Example: \`timps_batch({ instruction: "add docstrings to all Python files", agent_type: "docstring_generator", working_dir: "/project/src" })\`
  - Example: \`timps_batch({ instruction: "review all API endpoints", agent_type: "pr_reviewer", working_dir: "/project/api" })\`

## Meta
- \`timps_dispatch\` — Auto-detect the best agent for any plain-English request
- \`timps_list_agents\` — List all available agents with descriptions
- \`timps_tool_status\` — Show which tools are connected to TIMPS
- \`timps_connect_tools\` — Auto-configure TIMPS as MCP in all installed coding tools
`;
}

// ── .mdc rule content ────────────────────────────────────────────────────────
// These go in .cursor/rules/ and are scoped by glob pattern.

const MDC_TEMPLATES = {
  "timps-sdlc.mdc": {
    globs: "**/*.{py,js,ts,jsx,tsx,go,java,rs}",
    content: `---
description: TIMPS SDLC Pipeline — full software development lifecycle
globs: **/*.{py,js,ts,jsx,tsx,go,java,rs}
---
When writing code, use these TIMPS tools:

- \`timps_run_task\` — Full SDLC pipeline (PM → architect → coder → reviewer → QA → security → perf → devops → docs)
- \`timps_unit_test_writer\` — Generate test suites
- \`timps_docstring_generator\` — Add docstrings
- \`timps_pr_reviewer\` — Review code changes
- \`timps_refactoring_agent\` — Refactor code

For bulk operations across many files, use \`timps_batch\` with the appropriate \`agent_type\`.
`,
  },

  "timps-security.mdc": {
    globs: "**/*",
    content: `---
description: TIMPS Security Agents — vulnerability scanning and auditing
globs: **/*
---
Security checks available via TIMPS:

- \`timps_dependency_agent\` — CVE scan manifests
- \`timps_api_security_tester\` — OWASP API Top-10 audit
- \`timps_security_guard\` — Local security scan
- \`timps_secrets_management\` — Detect hardcoded secrets
- \`timps_compliance_auditor\` — SOC 2 / ISO 27001 / HIPAA / PCI-DSS / GDPR
- \`timps_container_image_scanner\` — Dockerfile CVEs and misconfigs
`,
  },

  "timps-infra.mdc": {
    globs: "**/*.{yml,yaml,tf,tfvars,dockerfile,json,toml}",
    content: `---
description: TIMPS Infrastructure & DevOps Agents
globs: **/*.{yml,yaml,tf,tfvars,dockerfile,json,toml}
---
Infrastructure tasks via TIMPS:

- \`timps_kubernetes_navigator\` — Diagnose K8s workloads
- \`timps_docker_compose_architect\` — Create compose files
- \`timps_terraform_plan_reviewer\` — Review terraform plans
- \`timps_iac_drift_detector\` — Detect IaC drift
- \`timps_load_testing\` — Generate load test scripts
- \`timps_disaster_recovery\` — Design DR plans
`,
  },

  "timps-database.mdc": {
    globs: "**/*.{sql,py,js,ts}",
    content: `---
description: TIMPS Database & Query Agents
globs: **/*.{sql,py,js,ts}
---
Database tasks via TIMPS:

- \`timps_db_agent\` — Schema design, migrations, ER diagrams
- \`timps_sql_optimizer\` — Analyse slow queries
- \`timps_db_migration_pilot\` — Zero-downtime migration planning
`,
  },
};

// ── File operations ──────────────────────────────────────────────────────────

function writeUserRules(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content, "utf8");
  return path;
}

function writeMdcFile(dir, filename, mdc) {
  mkdirSync(dir, { recursive: true });
  const path = join(dir, filename);
  const content = `${mdc.content}`;
  writeFileSync(path, content, "utf8");
  return path;
}

function removeGeneratedFiles() {
  let count = 0;

  // Remove .cursorrules if it mentions TIMPS
  if (existsSync(USER_RULES_PATH)) {
    const content = readFileSync(USER_RULES_PATH, "utf8");
    if (content.includes("TIMPS Swarm")) {
      writeFileSync(USER_RULES_PATH, "", "utf8");
      count++;
      console.log(`Cleared: ${USER_RULES_PATH}`);
    }
  }

  // Remove .mdc files
  if (existsSync(CURSOR_RULES_DIR)) {
    for (const f of readdirSync(CURSOR_RULES_DIR)) {
      if (f.startsWith("timps-") && f.endsWith(".mdc")) {
        unlinkSync(join(CURSOR_RULES_DIR, f));
        count++;
      }
    }
  }

  return count;
}

// ── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const remove = args.includes("--remove");
  const userOnly = args.includes("--user-only");
  const projectOnly = args.includes("--project-only");
  const projectDir = args.includes("--project-dir")
    ? resolve(args[args.indexOf("--project-dir") + 1])
    : null;

  if (remove) {
    const count = removeGeneratedFiles();
    console.log(`Removed ${count} TIMPS-generated Cursor files`);
    return;
  }

  if (!userOnly || projectOnly) {
    // Write .cursorrules (global, user-level)
    if (dryRun) {
      console.log(`[DRY RUN] Would write: ${USER_RULES_PATH}`);
    } else {
      const path = writeUserRules(USER_RULES_PATH, generateUserRules());
      console.log(`Wrote user rules: ${path}`);
    }
  }

  if (!projectOnly || userOnly) {
    // Write .mdc files
    const rulesDir = projectDir ? join(projectDir, ".cursor", "rules") : CURSOR_RULES_DIR;

    if (dryRun) {
      console.log(`[DRY RUN] Would write ${Object.keys(MDC_TEMPLATES).length} .mdc files to ${rulesDir}:`);
      for (const name of Object.keys(MDC_TEMPLATES)) {
        console.log(`  - ${join(rulesDir, name)}`);
      }
    } else {
      let count = 0;
      for (const [filename, mdc] of Object.entries(MDC_TEMPLATES)) {
        const path = writeMdcFile(rulesDir, filename, mdc);
        console.log(`Wrote rule: ${path}`);
        count++;
      }
      if (count > 0) {
        console.log(`\nWrote ${count} .mdc rule files to ${rulesDir}`);
      }
    }
  }

  if (dryRun) {
    console.log("\n[DRY RUN] No files were written.");
  }
}

main();
