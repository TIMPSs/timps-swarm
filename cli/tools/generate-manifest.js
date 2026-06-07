#!/usr/bin/env node
/**
 * generate-manifest.js — re-sync cli/lib/agents-manifest.js from the Python
 * server's TOOLS list. Run after editing mcp_server/server.py.
 *
 * Usage: node cli/tools/generate-manifest.js
 */
import { writeFileSync, mkdirSync, mkdtempSync, rmSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, resolve, join } from "path";
import { tmpdir } from "os";
import { execFileSync } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..", "..");
const SRC = resolve(REPO_ROOT, "mcp_server/server.py");
const OUT = resolve(__dirname, "..", "lib/agents-manifest.js");

const PY = [
  "import json, ast, sys",
  `with open(${JSON.stringify(SRC)}) as f: tree = ast.parse(f.read())`,
  "for node in ast.walk(tree):",
  "  if isinstance(node, ast.AnnAssign) and getattr(node.target, 'id', '') == 'TOOLS':",
  "    if not isinstance(node.value, ast.List): break",
  "    tools = []",
  "    for elt in node.value.elts:",
  "      if not isinstance(elt, ast.Dict): continue",
  "      d = {}",
  "      for k, v in zip(elt.keys, elt.values):",
  "        if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):",
  "          if k.value in ('name', 'description'): d[k.value] = v.value",
  "      if d.get('name', '').startswith('timps_'): tools.append(d)",
  "    print(json.dumps(tools))",
  "    break",
  "",
].join("\n");

const tmp = mkdtempSync(join(tmpdir(), "timps-manifest-"));
const pyFile = join(tmp, "extract.py");
writeFileSync(pyFile, PY);
let json_out;
try {
  json_out = execFileSync("python3", [pyFile], { encoding: "utf8" }).trim();
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
const tools = JSON.parse(json_out);
if (tools.length === 0) {
  console.error("No timps_ tools parsed from mcp_server/server.py — aborting");
  process.exit(1);
}

const CATEGORIES = {
  timps_run_task: "sdlc",
  timps_system_optimizer: "health", timps_file_organizer: "health", timps_environment_doctor: "health",
  timps_security_guard: "health", timps_network_medic: "health", timps_battery_analyst: "health",
  timps_update_manager: "health", timps_log_interpreter: "health", timps_privacy_cleaner: "health",
  timps_media_librarian: "health", timps_backup_sentinel: "health", timps_context_switcher: "health",
  timps_context_briefing: "context", timps_delegate: "kernel", timps_kernel_status: "kernel",
  timps_dependency_rebel: "expert", timps_merge_conflict_predictor: "expert",
  timps_tech_debt_quantifier: "expert", timps_migration_pilot: "expert",
  timps_flaky_test_detective: "expert", timps_onboarding_mentor: "expert",
  timps_incident_responder: "expert", timps_cloud_cost_auditor: "expert",
  timps_certificate_rotator: "expert", timps_terraform_plan_reviewer: "expert",
  timps_dotfile_doctor: "expert", timps_disk_space_prophet: "expert",
  timps_issue_triager: "developer", timps_boilerplate_architect: "developer",
  timps_pr_reviewer: "developer", timps_dependency_sentinel: "developer",
  timps_unit_test_writer: "developer", timps_docstring_generator: "developer",
  timps_log_detective: "developer", timps_sql_optimizer: "developer",
  timps_sprint_reporter: "developer", timps_flaky_test_hunter: "developer",
  timps_api_contract_auditor: "developer", timps_content_multiplier: "developer",
  timps_inbox_gatekeeper: "knowledge", timps_meeting_condenser: "knowledge",
  timps_research_scout: "knowledge", timps_trend_monitor: "knowledge",
  timps_data_wrangler: "knowledge", timps_competitor_tracker: "knowledge",
  timps_research_agent: "priority", timps_api_design_agent: "priority",
  timps_db_agent: "priority", timps_dependency_agent: "priority",
  timps_n8n_workflow_agent: "priority", timps_refactoring_agent: "priority",
  timps_test_data_agent: "priority", timps_monitoring_agent: "priority",
  timps_ui_ux_agent: "priority", timps_i18n_agent: "priority",
  timps_cost_optimizer: "priority", timps_self_critic_agent: "priority",
  timps_list_agents: "meta", timps_dispatch: "meta", timps_full_checkup: "meta",
  timps_list_providers: "meta", timps_connect_tools: "meta", timps_tool_status: "meta",
};
const MODEL = {
  sdlc: "sonnet", priority: "sonnet", expert: "sonnet", kernel: "sonnet",
  health: "haiku", developer: "haiku", knowledge: "haiku", meta: "haiku", context: "haiku",
};

const unmapped = tools.filter(t => !CATEGORIES[t.name]);
if (unmapped.length) {
  console.error("Unmapped:", unmapped.map(t => t.name).join(", "));
  process.exit(1);
}

const escape = s => s
  .replace(/\\/g, "\\\\")
  .replace(/'/g, "\\'")
  .replace(/\n/g, " ")
  .replace(/\r/g, " ");

const lines = [];
lines.push("// AUTO-GENERATED from mcp_server/server.py:TOOLS by cli/tools/generate-manifest.js");
lines.push("// Keep names & descriptions in sync with mcp_server/server.py.");
lines.push(`// Total: ${tools.length} agents.`);
lines.push("");
lines.push("/** @typedef {{name: string, description: string, category: string, model: string}} Agent */");
lines.push("");
lines.push("/** @type {Agent[]}");
lines.push(" *  Source of truth: mcp_server/server.py TOOLS[]. Mirror it here; keep names/descriptions in sync.");
lines.push(" */");
lines.push("export const AGENTS = [");
for (const t of tools) {
  const cat = CATEGORIES[t.name];
  const model = MODEL[cat] || "sonnet";
  lines.push(`  { name: '${t.name}', description: '${escape(t.description)}', category: '${cat}', model: '${model}' },`);
}
lines.push("];");
lines.push("");
lines.push("export const CATEGORIES_ORDER = ['sdlc','health','developer','expert','priority','knowledge','kernel','context','meta'];");
lines.push("export const CATEGORY_LABELS = {");
lines.push("  sdlc: 'SDLC Pipeline', health: 'Computer Health', developer: 'Developer Swarm',");
lines.push("  expert: 'Expert Diagnostics', priority: 'Priority Agents', knowledge: 'Knowledge Worker',");
lines.push("  kernel: 'Agent Kernel', context: 'Context', meta: 'Meta',");
lines.push("};");
lines.push("");
lines.push("/** 'timps_security_auditor' -> 'security-auditor' */");
lines.push("export function agentFileBase(name) { return name.replace(/^timps_/, ''); }");
lines.push("");

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, lines.join("\n"));
console.log(`Wrote ${tools.length} agents to ${OUT}`);
