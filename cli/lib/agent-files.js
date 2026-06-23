/**
 * agent-files.js — render native sub-agent Markdown files for all TIMPS
 * agents (currently 160), so Claude Code / Cursor / Codex pick them up as
 * parallel sub-agents (not just MCP tools).
 *
 * For each agent we write:
 *   ~/.claude/agents/timps-<name>.md      (Claude Code native sub-agent)
 *   ~/.claude/agents/timps-<name>.md      (Cursor also reads this path in Composer 1.5+)
 *   ~/.codex/agents/timps-<name>.md       (Codex-style — uses the same frontmatter)
 *
 * Each file is small: a YAML frontmatter block (name, description, tools, model)
 * and a short system-prompt body that wraps the MCP tool call.
 *
 * Re-running writeSubAgents() is idempotent — files are only written if the
 * on-disk content differs from the rendered output.
 */
import { existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync, unlinkSync } from "fs";
import { join, dirname } from "path";
import { AGENTS, agentFileBase } from "./agents-manifest.js";

/**
 * Routing hints by agent name — adds a "Routing hint" section to the agent
 * .md file suggesting `timps_batch` for bulk ops and related agents.
 */
const ROUTING_HINTS = {
  // SDLC
  timps_run_task:             "For bulk operations across many files (e.g. adding tests to all handlers), use `timps_batch` instead. Related: `timps_pr_reviewer`, `timps_unit_test_writer`, `timps_docstring_generator`.",
  timps_pr_reviewer:          "For reviewing every file in a directory in one shot, use `timps_batch` with `agent_type: 'pr_reviewer'`. Related: `timps_run_task`.",
  timps_unit_test_writer:     "For adding tests to every module in a project, use `timps_batch` with `agent_type: 'unit_test_writer'`. Related: `timps_run_task`.",
  timps_docstring_generator:  "For documenting every function across a codebase, use `timps_batch` with `agent_type: 'docstring_generator'`. Related: `timps_run_task`, `timps_tech_writer_assistant`.",
  timps_refactoring_agent:    "For bulk refactoring across many files, use `timps_batch` with `agent_type: 'refactoring_agent'`. Related: `timps_pattern_detector`, `timps_technical_debt`.",
  timps_api_contract_auditor: "For auditing multiple API specs at once, use `timps_batch`. Related: `timps_api_design_agent`, `timps_api_security_tester`.",
  timps_content_multiplier:   "Related: `timps_demo_video_script_writer`, `timps_podcast_show_notes_writer`, `timps_cold_email_sequence_writer`.",
  // Health
  timps_system_optimizer:     "Run `timps_full_checkup` for a comprehensive 6-agent health scan. Related: `timps_environment_doctor`, `timps_update_manager`.",
  timps_file_organizer:       "Related: `timps_media_librarian`, `timps_disk_space_prophet`.",
  timps_environment_doctor:   "Related: `timps_dotfile_doctor`, `timps_system_optimizer`.",
  timps_network_medic:        "Related: `timps_security_guard` (port scan), `timps_full_checkup`.",
  timps_battery_analyst:      "Related: `timps_system_optimizer`, `timps_full_checkup`.",
  timps_update_manager:       "Related: `timps_system_optimizer`, `timps_dependency_rebel`.",
  timps_log_interpreter:      "Related: `timps_log_detective`, `timps_log_pattern_analyzer`, `timps_incident_responder`.",
  timps_security_guard:       "Related: `timps_api_security_tester`, `timps_container_image_scanner`, `timps_secrets_management`.",
  timps_privacy_cleaner:      "Related: `timps_security_guard`.",
  timps_media_librarian:      "Related: `timps_file_organizer`.",
  timps_backup_sentinel:      "Related: `timps_disk_space_prophet`.",
  timps_context_switcher:     "Related: `timps_calendar_optimizer`.",
  // Developer
  timps_issue_triager:        "Related: `timps_sprint_planning_agent`, `timps_sprint_reporter`.",
  timps_boilerplate_architect:"Related: `timps_cli_tool_agent`, `timps_db_agent`, `timps_api_design_agent`.",
  timps_dependency_sentinel:  "For scanning all manifests in a monorepo, use `timps_batch` with `agent_type: 'dependency_agent'`. Related: `timps_dependency_agent`, `timps_dependency_rebel`.",
  timps_log_detective:        "Related: `timps_log_interpreter`, `timps_log_pattern_analyzer`, `timps_incident_responder`.",
  timps_sql_optimizer:        "Related: `timps_db_agent`, `timps_db_migration_pilot`.",
  timps_sprint_reporter:      "Related: `timps_sprint_planning_agent`, `timps_issue_triager`.",
  timps_flaky_test_hunter:    "Related: `timps_flaky_test_detective`, `timps_test_intelligence`.",
  // Knowledge
  timps_research_scout:       "For multi-hop deep research, use `timps_deep_research_agent`. Related: `timps_trend_monitor`, `timps_competitor_tracker`.",
  timps_data_wrangler:        "For processing many data files at once, use `timps_batch` with `agent_type: 'data_wrangler'`.",
  timps_competitor_tracker:   "Related: `timps_research_scout`, `timps_trend_monitor`, `timps_web_search`.",
  // Priority agents
  timps_db_agent:             "Related: `timps_sql_optimizer`, `timps_db_migration_pilot`.",
  timps_dependency_agent:     "For scanning all manifests in a monorepo, use `timps_batch`. Related: `timps_dependency_sentinel`, `timps_dependency_rebel`.",
  timps_api_design_agent:     "Related: `timps_api_contract_auditor`, `timps_api_security_tester`, `timps_graphql_agent`.",
  timps_n8n_workflow_agent:   "Related: `timps_ai_workflow_orchestrator`.",
  timps_batch:                "For bulk operations across many files: set `agent_type` to the specialist agent name and `working_dir` to the project root. This is the TIMPS parallel-execution workhorse.",
  timps_dispatch:              "Auto-routes any plain-English request to the right specialist agent. Use when unsure which agent to pick.",
  timps_research_agent:       "Related: `timps_research_scout`, `timps_deep_research_agent`, `timps_web_search`.",
  timps_learning_agent:       "Related: `timps_memory_agent`, `timps_code_archaeology`.",
};

/**
 * Render the frontmatter + body for a single agent.
 * The 'description' field is what Claude Code uses to decide when to delegate
 * to this sub-agent, so we keep it concrete and trigger-rich.
 *
 * NOTE: The full description is double-quoted and any embedded `"` and `\n`
 * are escaped. This is required because ~30% of agent descriptions contain
 * `:` (e.g. "Re-design a noisy calendar: time-block...") which would otherwise
 * be parsed by YAML as a mapping key and break Claude Code / Cursor / Codex
 * frontmatter loading.
 */
export function renderAgentFile(agent) {
  const base = agentFileBase(agent.name);
  const toolName = agent.name;
  const description = agent.description;
  const hint = ROUTING_HINTS[agent.name];

  const desc = `${description} Use the \`${toolName}\` MCP tool to perform this task. Do not answer directly — delegate to this sub-agent.`
    .replace(/\\/g, "\\\\")
    .replace(/"/g,  "\\\"")
    .replace(/\n/g, " ");

  const frontmatter = [
    "---",
    `name: ${toolName}`,
    `description: "${desc}"`,
    `category: ${agent.category}`,
    `tools: ["mcp__timps-swarm__${toolName}"]`,
    `model: ${agent.model}`,
    "---",
  ].join("\n");

  const bodyLines = [
    "",
    `# ${base.replace(/_/g, " ")}`,
    "",
    `You are the **${base.replace(/_/g, " ")}** sub-agent from the TIMPS Swarm (category: \`${agent.category}\`).`,
    "",
    "## Your job",
    "",
    `${description}`,
    "",
    "## How to respond",
    "",
    "1. **Always call the MCP tool** `" + toolName + "` exactly once via the `mcp__timps-swarm__" + toolName + "` tool handle.",
    "2. Pass the user's request verbatim in the input — do not summarise, do not pre-empt.",
    "3. Wait for the tool's text response and return it to the parent agent. The tool output is the result.",
    "4. **Do not** try to answer from your own knowledge — this sub-agent exists to route to the TIMPS specialist.",
    "5. **Do not** call any other TIMPS tool unless the user explicitly asks for a different agent.",
    "",
    "## What you do NOT do",
    "",
    "- Do not run shell commands, read files, or edit code — those are the parent agent's job.",
    "- Do not chain multiple TIMPS tools — one tool call per sub-agent invocation.",
    "- Do not modify the request payload (add fields, change casing, etc.) — forward as-is.",
    "",
    "## Input contract",
    "",
    "The MCP tool `" + toolName + "` accepts a JSON object. Pass through whatever the parent agent provided. Common shapes:",
    "```json",
    "{ \"request\": \"<plain-English task>\" }",
    "```",
    "or for the structured agents:",
    "```json",
    "{ \"code\": \"...\", \"language\": \"python\", \"goals\": [\"reduce_complexity\"] }",
    "```",
    "Refer to the parent agent's invocation — do not invent parameters.",
    "",
    "## Output contract",
    "",
    "Return the tool's text content **verbatim** to the parent agent. Do not wrap it in extra markdown headings, do not add commentary. The parent will integrate it into the user's final answer.",
    "",
  ];

  if (hint) {
    bodyLines.splice(bodyLines.length - 1, 0,
      "",
      "## Routing hint",
      "",
      hint,
    );
  }

  return frontmatter + bodyLines.join("\n");
}

/**
 * Render the per-IDE list of (directory, filename) pairs.
 * Each entry is `{ dir, file }` where `dir` is the agent directory and `file`
 * is the rendered filename. The same filename pattern works for all three IDEs.
 */
export function subAgentTargets(home, cwd) {
  return [
    { id: "claude-code", label: "Claude Code",  dir: join(home, ".claude", "agents") },
    { id: "cursor",      label: "Cursor",       dir: join(cwd,  ".claude", "agents") },  // Cursor also reads this
    { id: "codex",       label: "Codex CLI",    dir: join(home, ".codex",  "agents") },
  ];
}

export function subAgentFilename(agent) {
  return `timps-${agentFileBase(agent.name)}.md`;
}

/**
 * Idempotently write all sub-agent files to the requested IDE targets.
 * The number written equals AGENTS.length (160 at v2.2.0).
 *
 * @param {{home?: string, cwd?: string, targetIds?: string[], dryRun?: boolean}} opts
 * @returns {{written: string[], skipped: string[], errors: string[]}}
 */
export function writeSubAgents(opts = {}) {
  const home = opts.home || process.env.HOME || process.env.USERPROFILE || "~";
  const cwd  = opts.cwd  || process.cwd();
  const requested = opts.targetIds || ["claude-code", "cursor", "codex"];
  const targets = subAgentTargets(home, cwd).filter(t => requested.includes(t.id));

  const written = [];
  const skipped = [];
  const errors  = [];

  for (const target of targets) {
    try {
      mkdirSync(target.dir, { recursive: true });
    } catch (err) {
      errors.push(`${target.id}: mkdir ${target.dir} — ${err.message}`);
      continue;
    }

    for (const agent of AGENTS) {
      const file = join(target.dir, subAgentFilename(agent));
      const content = renderAgentFile(agent);

      if (existsSync(file) && readFileSync(file, "utf8") === content) {
        skipped.push(file);
        continue;
      }
      if (opts.dryRun) {
        written.push(file);
        continue;
      }
      try {
        writeFileSync(file, content);
        written.push(file);
      } catch (err) {
        errors.push(`${file}: ${err.message}`);
      }
    }
  }

  return { written, skipped, errors, targets };
}

/**
 * Remove TIMPS sub-agent files from a target directory. Only files that start
 * with `timps-` and end with `.md` are removed — never touch user files.
 */
export function removeSubAgents(opts = {}) {
  const home = opts.home || process.env.HOME || process.env.USERPROFILE || "~";
  const cwd  = opts.cwd  || process.cwd();
  const requested = opts.targetIds || ["claude-code", "cursor", "codex"];
  const targets = subAgentTargets(home, cwd).filter(t => requested.includes(t.id));

  const removed = [];
  const notPresent = [];
  const errors = [];

  for (const target of targets) {
    if (!existsSync(target.dir)) {
      notPresent.push(target.dir);
      continue;
    }
    let entries;
    try {
      entries = readdirSync(target.dir);
    } catch (err) {
      errors.push(`${target.id}: readdir ${target.dir} — ${err.message}`);
      continue;
    }
    for (const name of entries) {
      if (!name.startsWith("timps-") || !name.endsWith(".md")) continue;
      const file = join(target.dir, name);
      if (opts.dryRun) { removed.push(file); continue; }
      try {
        unlinkSync(file);
        removed.push(file);
      } catch (err) {
        errors.push(`${file}: ${err.message}`);
      }
    }
  }

  return { removed, notPresent, errors, targets };
}
