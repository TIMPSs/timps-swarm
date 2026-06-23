#!/usr/bin/env node
/**
 * Codex CLI Adapter
 * =================
 * Generates ~/.codex/config.json with the TIMPS MCP server registered
 * and compatibility environment variables set so Codex CLI can discover
 * and call every TIMPS agent as a tool.
 *
 * Codex CLI (https://github.com/openai/codex) reads ~/.codex/config.json
 * for MCP server registrations under the "mcpServers" key. It also
 * supports an "env" block to forward environment variables to the server.
 *
 * This script:
 *   1. Writes/merges the TIMPS MCP server into ~/.codex/config.json
 *   2. Sets compat env vars (TIMPS_API_URL pointing to localhost:8000)
 *   3. Optionally writes a ~/.codex/agents.json with sub-agent descriptions
 *      so Codex's agent routing can discover TIMPS specialists.
 *
 * Usage:
 *   node cli/lib/codex-adapter.js                      # write config
 *   node cli/lib/codex-adapter.js --dry-run             # preview only
 *   node cli/lib/codex-adapter.js --remove              # remove TIMPS from config
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "fs";
import { homedir } from "os";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const HOME = homedir();
const CODEX_DIR = join(HOME, ".codex");
const CONFIG_PATH = join(CODEX_DIR, "config.json");

const MCP_CMD = "timps-mcp";
const API_URL = process.env.TIMPS_API_URL || "http://localhost:8000";

// ── Config template ──────────────────────────────────────────────────────────

function generateConfig() {
  return {
    mcpServers: {
      "timps-swarm": {
        command: MCP_CMD,
        type: "stdio",
        description: "TIMPS Swarm — 160+ specialist agents for SDLC, health, research, infra, and productivity",
        env: {
          TIMPS_API_URL: API_URL,
          OLLAMA_HOST: process.env.OLLAMA_HOST || "http://localhost:11434",
        },
      },
    },
    // Sub-agent descriptions for Codex's internal routing
    agents: {
      "timps-run-task": {
        description: "Full SDLC pipeline — PM, architect, code generator, reviewer, QA, security, perf, devops, docs",
        tools: ["timps_run_task"],
      },
      "timps-code-review": {
        description: "Review PR diffs, score 0-10, approve/reject verdict",
        tools: ["timps_pr_reviewer"],
      },
      "timps-tests": {
        description: "Write unit tests with happy/edge/error paths",
        tools: ["timps_unit_test_writer"],
      },
      "timps-docs": {
        description: "Generate docstrings in Google/Sphinx/NumPy/JSDoc/Doxygen format",
        tools: ["timps_docstring_generator"],
      },
      "timps-api-design": {
        description: "Design REST/GraphQL APIs with OpenAPI 3.1 specs",
        tools: ["timps_api_design_agent"],
      },
      "timps-db-design": {
        description: "Database schema design, migrations, ER diagrams, query optimisation",
        tools: ["timps_db_agent", "timps_sql_optimizer"],
      },
      "timps-dependencies": {
        description: "Scan dependencies for CVEs, license issues, and outdated packages",
        tools: ["timps_dependency_agent", "timps_dependency_sentinel"],
      },
      "timps-system-health": {
        description: "Diagnose computer health: slow system, network, battery, security, privacy",
        tools: ["timps_full_checkup", "timps_system_optimizer", "timps_network_medic"],
      },
      "timps-research": {
        description: "Deep research, trend monitoring, competitive analysis",
        tools: ["timps_research_scout", "timps_deep_research_agent"],
      },
      "timps-infra": {
        description: "Kubernetes, Docker Compose, Terraform, IaC, load testing",
        tools: ["timps_kubernetes_navigator", "timps_docker_compose_architect", "timps_terraform_plan_reviewer"],
      },
      "timps-security": {
        description: "Security audits: API, containers, secrets, compliance, prompt injection",
        tools: ["timps_api_security_tester", "timps_container_image_scanner", "timps_secrets_management"],
      },
      "timps-batch": {
        description: "Bulk operations across many files — parallel sub-task execution",
        tools: ["timps_batch"],
      },
      "timps-dispatch": {
        description: "Auto-detect best agent for any plain-English request",
        tools: ["timps_dispatch"],
      },
    },
  };
}

// ── File operations ──────────────────────────────────────────────────────────

function mergeConfig() {
  mkdirSync(CODEX_DIR, { recursive: true });
  let existing = {};
  if (existsSync(CONFIG_PATH)) {
    try {
      existing = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
    } catch { /* start fresh */ }
  }
  const newConfig = generateConfig();

  // Merge mcpServers
  existing.mcpServers = {
    ...(existing.mcpServers || {}),
    ...newConfig.mcpServers,
  };

  // Merge agents
  existing.agents = {
    ...(existing.agents || {}),
    ...newConfig.agents,
  };

  writeFileSync(CONFIG_PATH, JSON.stringify(existing, null, 2), "utf8");
  return CONFIG_PATH;
}

function removeFromConfig() {
  if (!existsSync(CONFIG_PATH)) return 0;
  let existing = {};
  try {
    existing = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
  } catch {
    return 0;
  }
  let removed = 0;

  if (existing.mcpServers && existing.mcpServers["timps-swarm"]) {
    delete existing.mcpServers["timps-swarm"];
    removed++;
  }
  if (existing.agents) {
    for (const key of Object.keys(existing.agents)) {
      if (key.startsWith("timps-")) {
        delete existing.agents[key];
        removed++;
      }
    }
  }
  writeFileSync(CONFIG_PATH, JSON.stringify(existing, null, 2), "utf8");
  return removed;
}

// ── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const remove = args.includes("--remove");

  if (remove) {
    const count = removeFromConfig();
    if (count > 0) {
      console.log(`Removed TIMPS entries from ${CONFIG_PATH}`);
    } else {
      console.log(`No TIMPS entries found in ${CONFIG_PATH}`);
    }
    return;
  }

  if (dryRun) {
    console.log(`[DRY RUN] Would merge config into: ${CONFIG_PATH}`);
    const config = generateConfig();
    console.log(`  Would add MCP server: timps-swarm (command: ${MCP_CMD})`);
    console.log(`  Would add ${Object.keys(config.agents).length} sub-agent descriptions`);
    console.log(`  Env vars: TIMPS_API_URL=${API_URL}, OLLAMA_HOST=${process.env.OLLAMA_HOST || "http://localhost:11434"}`);
    return;
  }

  const path = mergeConfig();
  console.log(`Updated Codex config: ${path}`);
  const config = JSON.parse(readFileSync(path, "utf8"));
  const agentCount = Object.keys(config.agents || {}).filter(k => k.startsWith("timps-")).length;
  console.log(`  MCP server: timps-swarm`);
  console.log(`  Sub-agents: ${agentCount}`);
}

main();
