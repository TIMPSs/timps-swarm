#!/usr/bin/env node
/**
 * Claude Code Integration
 * =======================
 * Generates Claude Code agent definitions (.md) with timps_batch routing
 * hints and merges the TIMPS MCP server into .claude/settings.json.
 *
 * Agent .md files are written to ~/.claude/agents/ so Claude Code can
 * discover them as sub-agents. Each agent file includes:
 *   - A purpose description
 *   - Which MCP tools it maps to
 *   - A routing hint: "For bulk operations, use timps_batch"
 *
 * Usage:
 *   node cli/lib/claude-code-integration.js                    # write agents + settings
 *   node cli/lib/claude-code-integration.js --dry-run           # preview only
 *   node cli/lib/claude-code-integration.js --settings-only     # only merge settings
 *   node cli/lib/claude-code-integration.js --agents-only       # only write agent files
 *   node cli/lib/claude-code-integration.js --remove            # remove our agents
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, readdirSync, unlinkSync } from "fs";
import { homedir } from "os";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const HOME = homedir();
const AGENTS_DIR = join(HOME, ".claude", "agents");
const SETTINGS_PATH = join(HOME, ".claude", "settings.json");

const REPO_ROOT = join(__dirname, "..", "..");
const MCP_CMD = "timps-mcp";

// ── Agent definitions ─────────────────────────────────────────────────────────
// Each entry generates one .md file in ~/.claude/agents/.
// The slug is used as the filename (e.g. "timps-code-reviewer.md").

const AGENTS = [
  {
    slug: "timps-sdlc-pipeline",
    name: "TIMPS SDLC Pipeline",
    purpose: "Full software development lifecycle: product management, architecture, code generation, review, QA, security, performance, devops, and documentation.",
    tools: ["timps_run_task"],
    routingHint: "For bulk code operations across many files, use `timps_batch` with agent_type='code_generator' and working_dir pointing to your project root.",
  },
  {
    slug: "timps-code-reviewer",
    name: "TIMPS Code Reviewer",
    purpose: "Review pull request diffs for blockers, suggestions, and nitpicks. Returns a structured review with a 0-10 score.",
    tools: ["timps_pr_reviewer"],
    routingHint: "For reviewing every file in a directory in one shot, use `timps_batch` with agent_type='pr_reviewer'.",
  },
  {
    slug: "timps-unit-test-writer",
    name: "TIMPS Unit Test Writer",
    purpose: "Analyse source code and generate comprehensive test suites with happy paths, edge cases, and error conditions.",
    tools: ["timps_unit_test_writer"],
    routingHint: "For adding tests to every module in a project, use `timps_batch` with agent_type='unit_test_writer' and working_dir set to your source directory.",
  },
  {
    slug: "timps-docstring-generator",
    name: "TIMPS Docstring Generator",
    purpose: "Insert production-quality docstrings in Google, Sphinx, NumPy, JSDoc, or Doxygen format without changing logic.",
    tools: ["timps_docstring_generator"],
    routingHint: "For documenting every function across a codebase, use `timps_batch` with agent_type='docstring_generator'.",
  },
  {
    slug: "timps-api-designer",
    name: "TIMPS API Designer",
    purpose: "Generate complete OpenAPI 3.1 specs from natural-language descriptions with REST/GraphQL best practices.",
    tools: ["timps_api_design_agent"],
    routingHint: null,
  },
  {
    slug: "timps-db-architect",
    name: "TIMPS DB Architect",
    purpose: "Schema design, query optimisation, migration scripts, ER diagrams, and index recommendations.",
    tools: ["timps_db_agent"],
    routingHint: null,
  },
  {
    slug: "timps-dependency-auditor",
    name: "TIMPS Dependency Auditor",
    purpose: "Scan manifests for CVEs, license compliance, version pinning strategy, and safe upgrade scripts.",
    tools: ["timps_dependency_agent", "timps_dependency_sentinel", "timps_dependency_rebel"],
    routingHint: "For scanning all manifests in a monorepo, use `timps_batch` with agent_type='dependency_agent'.",
  },
  {
    slug: "timps-system-doctor",
    name: "TIMPS System Doctor",
    purpose: "Diagnose slow computers, broken dev environments, network issues, battery drain, security vulnerabilities, and privacy risks.",
    tools: [
      "timps_system_optimizer", "timps_environment_doctor", "timps_network_medic",
      "timps_battery_analyst", "timps_security_guard", "timps_privacy_cleaner",
      "timps_log_interpreter", "timps_file_organizer",
    ],
    routingHint: "Run `timps_full_checkup` for a comprehensive 6-agent health scan.",
  },
  {
    slug: "timps-research-assistant",
    name: "TIMPS Research Assistant",
    purpose: "Deep-dive research on any topic with multi-source synthesis, trend monitoring, and competitive analysis.",
    tools: ["timps_research_scout", "timps_deep_research_agent", "timps_trend_monitor", "timps_competitor_tracker"],
    routingHint: null,
  },
  {
    slug: "timps-data-wrangler",
    name: "TIMPS Data Wrangler",
    purpose: "Clean, normalise, and transform messy data from CSV, JSON, PDF extracts, and copy-pasted tables.",
    tools: ["timps_data_wrangler"],
    routingHint: "For processing many data files at once, use `timps_batch` with agent_type='data_wrangler'.",
  },
  {
    slug: "timps-log-detective",
    name: "TIMPS Log Detective",
    purpose: "Cluster production log errors, identify root cause, and suggest fixes. Handles stack traces, JSON logs, syslog, and journald output.",
    tools: ["timps_log_detective", "timps_log_interpreter", "timps_log_pattern_analyzer"],
    routingHint: "For analysing logs from multiple services, call the agent once per service log file.",
  },
  {
    slug: "timps-security-auditor",
    name: "TIMPS Security Auditor",
    purpose: "Comprehensive security scanning: OWASP API Top 10, container CVEs, prompt injection, secrets detection, and compliance mapping.",
    tools: [
      "timps_security_guard", "timps_api_security_tester", "timps_container_image_scanner",
      "timps_prompt_injection_scanner", "timps_secrets_management", "timps_compliance_auditor",
    ],
    routingHint: null,
  },
  {
    slug: "timps-cloud-cost-analyst",
    name: "TIMPS Cloud Cost Analyst",
    purpose: "Analyse cloud costs, detect waste, generate rightsizing recommendations, and project savings.",
    tools: ["timps_cost_optimizer", "timps_cloud_cost_auditor", "timps_finops_agent", "timps_observability_cost_optimizer"],
    routingHint: null,
  },
  {
    slug: "timps-infra-engineer",
    name: "TIMPS Infra Engineer",
    purpose: "Kubernetes diagnostics, Docker Compose generation, Terraform plan review, IaC drift detection, service mesh config, and disaster recovery planning.",
    tools: [
      "timps_kubernetes_navigator", "timps_docker_compose_architect", "timps_terraform_plan_reviewer",
      "timps_iac_drift_detector", "timps_service_mesh_configurator", "timps_disaster_recovery",
    ],
    routingHint: null,
  },
  {
    slug: "timps-content-creator",
    name: "TIMPS Content Creator",
    purpose: "Transform long-form content into tweets, LinkedIn posts, changelog entries, demo scripts, and podcast show notes.",
    tools: ["timps_content_multiplier", "timps_demo_video_script_writer", "timps_podcast_show_notes_writer", "timps_cold_email_sequence_writer"],
    routingHint: null,
  },
  {
    slug: "timps-meeting-helper",
    name: "TIMPS Meeting Helper",
    purpose: "Condense meeting transcripts into action items, decisions, and open questions with owners and deadlines.",
    tools: ["timps_meeting_condenser"],
    routingHint: null,
  },
  {
    slug: "timps-email-triage",
    name: "TIMPS Email Triage",
    purpose: "Triage email batches: flag urgent, draft replies, identify newsletters to unsubscribe from.",
    tools: ["timps_inbox_gatekeeper"],
    routingHint: null,
  },
];

// ── Settings template ─────────────────────────────────────────────────────────

function mcpServerBlock() {
  return {
    command: MCP_CMD,
    env: {
      OLLAMA_HOST: "http://localhost:11434",
    },
  };
}

// ── File operations ──────────────────────────────────────────────────────────

function writeAgentFile(slug, name, purpose, tools, routingHint) {
  mkdirSync(AGENTS_DIR, { recursive: true });
  const path = join(AGENTS_DIR, `${slug}.md`);
  const lines = [
    `# ${name}`,
    "",
    purpose,
    "",
    "## MCP Tools",
    "",
  ];
  for (const t of tools) {
    lines.push(`- \`${t}\``);
  }
  if (routingHint) {
    lines.push("");
    lines.push("## Routing Hint");
    lines.push("");
    lines.push(routingHint);
  }
  lines.push("");
  lines.push("---");
  lines.push(`_Managed by timps-swarm claude-code-integration. Remove this file and re-run with --remove to unregister._`);
  lines.push("");

  writeFileSync(path, lines.join("\n"), "utf8");
  return path;
}

function removeAgentFiles() {
  if (!existsSync(AGENTS_DIR)) return 0;
  let count = 0;
  for (const f of readdirSync(AGENTS_DIR)) {
    if (f.startsWith("timps-") && f.endsWith(".md")) {
      unlinkSync(join(AGENTS_DIR, f));
      count++;
    }
  }
  return count;
}

function mergeSettings() {
  mkdirSync(dirname(SETTINGS_PATH), { recursive: true });
  let settings = {};
  if (existsSync(SETTINGS_PATH)) {
    try {
      settings = JSON.parse(readFileSync(SETTINGS_PATH, "utf8"));
    } catch { /* start fresh */ }
  }
  const mcpServers = settings.mcpServers || {};
  if (!mcpServers["timps-swarm"]) {
    mcpServers["timps-swarm"] = mcpServerBlock();
  }
  settings.mcpServers = mcpServers;
  writeFileSync(SETTINGS_PATH, JSON.stringify(settings, null, 2), "utf8");
  return SETTINGS_PATH;
}

// ── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const settingsOnly = args.includes("--settings-only");
  const agentsOnly = args.includes("--agents-only");
  const remove = args.includes("--remove");

  if (remove) {
    const count = removeAgentFiles();
    console.log(`Removed ${count} TIMPS agent .md files from ${AGENTS_DIR}`);
    // Note: settings.json removal is not done here — user must do it manually
    return;
  }

  if (!settingsOnly) {
    if (dryRun) {
      console.log(`[DRY RUN] Would write ${AGENTS.length} agent .md files to ${AGENTS_DIR}:`);
      for (const a of AGENTS) {
        console.log(`  - ${join(AGENTS_DIR, `${a.slug}.md`)}  (${a.name})`);
      }
    } else {
      let count = 0;
      for (const a of AGENTS) {
        const path = writeAgentFile(a.slug, a.name, a.purpose, a.tools, a.routingHint);
        console.log(`Wrote agent: ${path}`);
        count++;
      }
      console.log(`\nWrote ${count} agent files to ${AGENTS_DIR}`);
    }
  }

  if (!agentsOnly) {
    if (dryRun) {
      console.log(`[DRY RUN] Would merge MCP config into ${SETTINGS_PATH}`);
    } else {
      const path = mergeSettings();
      console.log(`Updated settings: ${path}`);
    }
  }

  if (dryRun) {
    console.log("\n[DRY RUN] No files were written. Remove --dry-run to apply.");
  }
}

main();
