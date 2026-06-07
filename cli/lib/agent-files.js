/**
 * agent-files.js — render native sub-agent Markdown files for the 64 TIMPS
 * tools, so Claude Code / Cursor / Codex pick them up as parallel sub-agents
 * (not just MCP tools).
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
 * Render the frontmatter + body for a single agent.
 * The 'description' field is what Claude Code uses to decide when to delegate
 * to this sub-agent, so we keep it concrete and trigger-rich.
 */
export function renderAgentFile(agent) {
  const base = agentFileBase(agent.name);
  const toolName = agent.name;
  const description = agent.description;

  const frontmatter = [
    "---",
    `name: ${toolName}`,
    `description: ${description} Use the \`${toolName}\` MCP tool to perform this task. Do not answer directly — delegate to this sub-agent.`,
    `category: ${agent.category}`,
    `tools: ["mcp__timps-swarm__${toolName}"]`,
    `model: ${agent.model}`,
    "---",
  ].join("\n");

  const body = [
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
  ].join("\n");

  return frontmatter + body;
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
 * Idempotently write all 64 sub-agent files to the requested IDE targets.
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
