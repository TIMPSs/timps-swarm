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
  "      if isinstance(elt, ast.Dict):",
  "        d = {}",
  "        for k, v in zip(elt.keys, elt.values):",
  "          if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):",
  "            if k.value in ('name', 'description'): d[k.value] = v.value",
  "        if d.get('name', '').startswith('timps_'): tools.append(d)",
  "      elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.ListComp):",
  "        lc = elt.value",
  "        gen = lc.generators[0]",
  "        iter_node = gen.iter",
  "        if not isinstance(iter_node, ast.List): continue",
  "        targets = gen.target.elts if isinstance(gen.target, ast.Tuple) else [gen.target]",
  "        target_names = [t.id for t in targets]",
  "        for tup in iter_node.elts:",
  "          if not isinstance(tup, ast.Tuple): continue",
  "          d = {}",
  "          for tname, teval in zip(target_names, tup.elts):",
  "            if isinstance(teval, ast.Constant):",
  "              d[tname] = teval.value",
  "          tool = {'name': 'timps_' + d.get(target_names[0], ''), 'description': d.get(target_names[1], '')}",
  "          if tool['name'].startswith('timps_') and tool['name'] != 'timps_': tools.append(tool)",
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
  // ── priority (high-impact generalists — sonnet)
  timps_research_agent: "priority", timps_api_design_agent: "priority",
  timps_db_agent: "priority", timps_dependency_agent: "priority",
  timps_n8n_workflow_agent: "priority", timps_refactoring_agent: "priority",
  timps_test_data_agent: "priority", timps_monitoring_agent: "priority",
  timps_ui_ux_agent: "priority", timps_i18n_agent: "priority",
  timps_cost_optimizer: "priority", timps_self_critic_agent: "priority",
  timps_ab_testing_agent: "priority", timps_abdm_agent: "priority",
  timps_agent_composer: "priority", timps_agent_marketplace_curator: "priority",
  timps_analytics_agent: "priority", timps_browser_automation: "priority",
  timps_calendar_optimizer: "priority", timps_churn_predictor: "priority",
  timps_cli_tool_agent: "priority", timps_cold_email_sequence_writer: "priority",
  timps_deep_research_agent: "priority", timps_demo_video_script_writer: "priority",
  timps_demand_forecaster: "priority", timps_digilocker_agent: "priority",
  timps_dpdp_act_auditor: "priority", timps_feature_flag: "priority",
  timps_federated_learning: "priority", timps_finetuning_agent: "priority",
  timps_finops_agent: "priority", timps_fssai_compliance_agent: "priority",
  timps_gst_compliance: "priority", timps_indiehacker_agent: "priority",
  timps_learning_agent: "priority", timps_memory_agent: "priority",
  timps_mobile_agent: "priority", timps_model_evaluator: "priority",
  timps_model_perf_monitor: "priority", timps_monetization_agent: "priority",
  timps_observability_cost_optimizer: "priority",
  timps_podcast_show_notes_writer: "priority",
  timps_prompt_engineer: "priority", timps_prompt_injection_scanner: "priority",
  timps_quantum_ready: "priority", timps_rag_designer: "priority",
  timps_rag_evaluator: "priority", timps_realtime_agent: "priority",
  timps_red_team_agent: "priority", timps_release_manager: "priority",
  timps_robotics_agent: "priority", timps_sbom_generator: "priority",
  timps_secrets_management: "priority", timps_security_remediation: "priority",
  timps_seo_agent: "priority", timps_service_mesh_configurator: "priority",
  timps_sprint_planning_agent: "priority",
  timps_storybook_story_generator: "priority",
  timps_tech_writer_assistant: "priority", timps_technical_debt: "priority",
  timps_threat_intel_analyst: "priority", timps_tracing_emitter: "priority",
  timps_upi_agent: "priority", timps_vector_db_agent: "priority",
  timps_voice_agent_designer: "priority", timps_wearable_health_coach: "priority",
  timps_web3_agent: "priority", timps_win_loss_analyst: "priority",
  // ── expert (deep specialty — sonnet)
  timps_accessibility_tester: "expert", timps_adr_writer: "expert",
  timps_ai_safety_agent: "expert", timps_ai_workflow_orchestrator: "expert",
  timps_api_perf_profiler: "expert", timps_api_security_tester: "expert",
  timps_changelog_generator: "expert", timps_code_archaeology: "expert",
  timps_compliance_auditor: "expert", timps_computer_use_agent: "expert",
  timps_container_image_scanner: "expert", timps_contract_reviewer: "expert",
  timps_court_case_summarizer: "expert", timps_data_pipeline: "expert",
  timps_dataset_agent: "expert", timps_db_migration_pilot: "expert",
  timps_disaster_recovery: "expert", timps_docker_compose_architect: "expert",
  timps_edge_agent: "expert", timps_embedded_agent: "expert",
  timps_game_day_facilitator: "expert", timps_git_workflow_automator: "expert",
  timps_graphql_agent: "expert", timps_iac_drift_detector: "expert",
  timps_incident_response_coordinator: "expert",
  timps_kubernetes_navigator: "expert",
  timps_license_compliance_scanner: "expert", timps_load_testing: "expert",
  timps_local_rag_builder: "expert", timps_log_pattern_analyzer: "expert",
  timps_mcp_server_generator: "expert", timps_pattern_detector: "expert",
  timps_phishing_simulator: "expert", timps_pipeline_healer: "expert",
  timps_postmortem_agent: "expert", timps_test_intelligence: "expert",
  timps_visual_regression_detective: "expert", timps_web_scraping: "expert",
  timps_web_search: "expert",
  // ── knowledge (India / domain knowledge)
  timps_agri_commodity_forecaster: "knowledge",
  // ── meta
  timps_list_agents: "meta", timps_dispatch: "meta", timps_full_checkup: "meta",
  timps_list_providers: "meta", timps_connect_tools: "meta", timps_tool_status: "meta",
  timps_batch: "meta",
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
