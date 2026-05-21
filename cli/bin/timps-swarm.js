#!/usr/bin/env node
/**
 * timps-swarm CLI
 * ===============
 * npx timps-swarm <command> [options]
 *
 * Commands
 * --------
 *   fix <path>          Run the SDLC swarm on a codebase path
 *   research <topic>    Research agent — gather context before coding
 *   api-design <desc>   Generate an OpenAPI 3.1 spec from plain English
 *   db-design <desc>    Design a database schema with migrations
 *   audit <path>        Dependency vulnerability scan
 *   n8n <desc>          Generate an n8n workflow JSON
 *   health              Run computer health checkup
 *   providers           Show configured LLM providers
 *   start               Start the TIMPS Swarm API server
 *   mcp                 Start the MCP stdio server
 *   install-mcp         Auto-configure TIMPS as MCP in Claude Code / Cursor / etc.
 */

import { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import { dirname, resolve, join } from "path";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "fs";
import { spawn, execSync } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// ── Helpers ──────────────────────────────────────────────────────────────────

const API_BASE = process.env.TIMPS_API_URL || "http://localhost:8000";

async function fetchAPI(path, body) {
  const fetch = (await import("node-fetch")).default;
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`API error ${resp.status}: ${await resp.text()}`);
  return resp.json();
}

async function checkServer() {
  try {
    const fetch = (await import("node-fetch")).default;
    const resp = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    return resp.ok;
  } catch {
    return false;
  }
}

function findRepoPython() {
  // Walk up from CWD to find the timps-swarm repo root
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(dir, "mcp_server", "server.py"))) return dir;
    dir = resolve(dir, "..");
  }
  // Try common install locations
  const common = [
    resolve(__dirname, ".."),                          // npx in repo
    join(process.env.HOME, "timps-swarm"),
    join(process.env.HOME, "Desktop", "timps-swarm"),
    "/opt/timps-swarm",
  ];
  return common.find(d => existsSync(join(d, "mcp_server", "server.py"))) || null;
}

function printHeader(title) {
  console.log(chalk.bold.cyan(`\n  ◆ TIMPS Swarm — ${title}`));
  console.log(chalk.dim("  ─────────────────────────────────────────\n"));
}

function printResult(data) {
  if (typeof data === "string") {
    console.log(chalk.white(data));
  } else if (data && typeof data === "object") {
    for (const [k, v] of Object.entries(data)) {
      if (k.startsWith("_")) continue;
      const label = chalk.bold.green(`  ${k}:`);
      if (typeof v === "string" && v.length > 200) {
        console.log(`${label}\n${chalk.white(v.slice(0, 600))}${chalk.dim(v.length > 600 ? "\n  … (truncated)" : "")}`);
      } else if (Array.isArray(v)) {
        console.log(`${label} ${chalk.white(v.slice(0, 5).join(", "))}${v.length > 5 ? chalk.dim(` + ${v.length - 5} more`) : ""}`);
      } else {
        console.log(`${label} ${chalk.white(String(v))}`);
      }
    }
  }
}

// ── Program ───────────────────────────────────────────────────────────────────

const program = new Command();

program
  .name("timps-swarm")
  .description("TIMPS Swarm — 56 AI agents at your fingertips")
  .version("2.0.0");

// ── fix ───────────────────────────────────────────────────────────────────────
program
  .command("fix [path]")
  .description("Run the full SDLC swarm on a task or codebase path")
  .option("-l, --language <lang>", "Programming language", "python")
  .option("--max-iter <n>", "Max pipeline iterations", "10")
  .action(async (path, opts) => {
    printHeader("SDLC Swarm");
    const task = path || process.argv.slice(3).join(" ");
    if (!task) {
      console.error(chalk.red("  Error: provide a task or path, e.g. npx timps-swarm fix ./src"));
      process.exit(1);
    }

    const serverUp = await checkServer();
    if (!serverUp) {
      console.log(chalk.yellow("  TIMPS server not running — starting it now…\n"));
      const repoDir = findRepoPython();
      if (!repoDir) {
        console.error(chalk.red("  Could not find timps-swarm repo. Set TIMPS_API_URL or clone the repo."));
        process.exit(1);
      }
      const proc = spawn("python", ["-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"], {
        cwd: repoDir, detached: true, stdio: "ignore",
      });
      proc.unref();
      await new Promise(r => setTimeout(r, 3000));
    }

    const spinner = ora("  Running SDLC swarm…").start();
    try {
      const result = await fetchAPI("/swarm/run", {
        request: task,
        language: opts.language,
        max_iterations: parseInt(opts.maxIter),
      });
      spinner.succeed(chalk.green("  Swarm complete!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── research ──────────────────────────────────────────────────────────────────
program
  .command("research <topic>")
  .description("Research Agent — gather context before coding")
  .option("-d, --depth <level>", "quick | medium | deep", "medium")
  .action(async (topic, opts) => {
    printHeader("Research Agent");
    const spinner = ora(`  Researching: ${topic}…`).start();
    try {
      const result = await fetchAPI("/agents/research", { topic, depth: opts.depth });
      spinner.succeed(chalk.green("  Research complete!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── api-design ────────────────────────────────────────────────────────────────
program
  .command("api-design <description>")
  .description("Generate an OpenAPI 3.1 spec from plain English")
  .option("-s, --style <style>", "rest | graphql | grpc", "rest")
  .option("-a, --auth <scheme>", "jwt | oauth2 | api_key | none", "jwt")
  .action(async (description, opts) => {
    printHeader("API Design Agent");
    const spinner = ora("  Generating OpenAPI spec…").start();
    try {
      const result = await fetchAPI("/agents/api-design", {
        description,
        style: opts.style,
        auth_scheme: opts.auth,
      });
      spinner.succeed(chalk.green("  Spec generated!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── db-design ─────────────────────────────────────────────────────────────────
program
  .command("db-design <description>")
  .description("Design a database schema with DDL, ER diagram, and migrations")
  .option("-e, --engine <engine>", "postgresql | mysql | sqlite | mongodb", "postgresql")
  .option("-m, --migration-tool <tool>", "alembic | flyway | raw_sql", "alembic")
  .action(async (description, opts) => {
    printHeader("DB Agent");
    const spinner = ora("  Designing database schema…").start();
    try {
      const result = await fetchAPI("/agents/db-design", {
        description,
        db_engine: opts.engine,
        migration_tool: opts.migrationTool,
      });
      spinner.succeed(chalk.green("  Schema designed!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── audit ─────────────────────────────────────────────────────────────────────
program
  .command("audit [path]")
  .description("Dependency vulnerability scan (CVEs, license compliance)")
  .option("-e, --ecosystem <eco>", "python | node | rust | go | auto", "auto")
  .action(async (path, opts) => {
    printHeader("Dependency Agent");
    const manifestPath = path || "./requirements.txt";
    let manifest = "";
    if (existsSync(manifestPath)) {
      manifest = readFileSync(manifestPath, "utf8");
    } else {
      manifest = manifestPath;  // treat as raw manifest content
    }
    const spinner = ora("  Scanning dependencies…").start();
    try {
      const result = await fetchAPI("/agents/dependency-audit", {
        manifest,
        ecosystem: opts.ecosystem,
      });
      spinner.succeed(chalk.green("  Audit complete!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── n8n ───────────────────────────────────────────────────────────────────────
program
  .command("n8n <description>")
  .description("Generate a complete n8n workflow JSON from plain English")
  .option("-t, --trigger <type>", "webhook | cron | email | github | manual | auto", "auto")
  .option("-o, --output <file>", "Output file path (default: print to stdout)")
  .action(async (description, opts) => {
    printHeader("n8n Workflow Agent");
    const spinner = ora("  Building n8n workflow…").start();
    try {
      const result = await fetchAPI("/agents/n8n-workflow", {
        description,
        trigger: opts.trigger,
      });
      spinner.succeed(chalk.green("  Workflow generated!"));
      if (opts.output) {
        const { writeFileSync } = await import("fs");
        writeFileSync(opts.output, result.workflow_json || "{}");
        console.log(chalk.cyan(`  Saved to: ${opts.output}`));
      } else {
        printResult(result);
      }
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── health ────────────────────────────────────────────────────────────────────
program
  .command("health")
  .description("Run a full computer health checkup (6 agents)")
  .action(async () => {
    printHeader("Computer Health Checkup");
    const spinner = ora("  Running health scan…").start();
    try {
      const result = await fetchAPI("/health/full", {});
      spinner.succeed(chalk.green("  Health scan complete!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── providers ─────────────────────────────────────────────────────────────────
program
  .command("providers")
  .description("Show configured LLM providers and which is active")
  .action(async () => {
    printHeader("LLM Providers");
    try {
      const result = await fetchAPI("/providers", {});
      for (const p of (result.providers || [])) {
        const icon = p.available ? chalk.green("✓") : chalk.dim("○");
        const active = p.active ? chalk.bold.cyan(" (ACTIVE)") : "";
        console.log(`  ${icon}  ${chalk.bold(p.name.padEnd(12))} ${chalk.dim(p.model)}${active}`);
        console.log(`       ${chalk.dim(p.description)}`);
      }
    } catch (err) {
      console.error(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── start ─────────────────────────────────────────────────────────────────────
program
  .command("start")
  .description("Start the TIMPS Swarm API + dashboard server")
  .option("-p, --port <port>", "API port", "8000")
  .action((opts) => {
    printHeader("Starting Server");
    const repoDir = findRepoPython();
    if (!repoDir) {
      console.error(chalk.red("  Could not find timps-swarm repo. Clone it first."));
      process.exit(1);
    }
    console.log(chalk.cyan(`  Repo:   ${repoDir}`));
    console.log(chalk.cyan(`  API:    http://localhost:${opts.port}`));
    console.log(chalk.cyan("  Docs:   http://localhost:8000/docs\n"));
    const proc = spawn(
      "python", ["-m", "uvicorn", "src.main:app",
                 "--host", "0.0.0.0", "--port", opts.port, "--reload"],
      { cwd: repoDir, stdio: "inherit" }
    );
    proc.on("exit", code => process.exit(code || 0));
  });

// ── mcp ───────────────────────────────────────────────────────────────────────
program
  .command("mcp")
  .description("Start the MCP stdio server (for Claude Code, Cursor, etc.)")
  .action(() => {
    const repoDir = findRepoPython();
    if (!repoDir) {
      process.stderr.write("Could not find timps-swarm repo.\n");
      process.exit(1);
    }
    const proc = spawn("python", ["-m", "mcp_server.server"], {
      cwd: repoDir,
      stdio: "inherit",
      env: { ...process.env },
    });
    proc.on("exit", code => process.exit(code || 0));
  });

// ── install-mcp ───────────────────────────────────────────────────────────────
program
  .command("install-mcp")
  .description("Auto-configure TIMPS Swarm as MCP server in Claude Code, Cursor, Windsurf, etc.")
  .option("--tool <id>", "Specific tool to configure: claude-code|cursor|windsurf|local-mcp (default: all)")
  .option("--dry-run", "Preview only — don't write any files")
  .option("--repo <path>", "Path to timps-swarm repo (auto-detected if omitted)")
  .action(async (opts) => {
    printHeader("MCP Installer");

    // Resolve the repo root — prefer explicit --repo, then walk up from this file
    const repoDir = opts.repo || findRepoPython() || resolve(__dirname, "../..");
    const home = process.env.HOME || process.env.USERPROFILE || "~";

    const mcpEntry = {
      command: "python",
      args: ["-m", "mcp_server.server"],
      cwd: repoDir,
      env: {},
    };

    const targets = {
      "claude-code":  join(home, ".claude", "mcp.json"),
      "cursor":       join(home, ".cursor", "mcp.json"),
      "windsurf":     join(home, ".windsurf", "mcp.json"),
      "local-mcp":    join(repoDir, ".claude", "mcp.json"),
    };

    const wanted = opts.tool ? [opts.tool] : Object.keys(targets);
    const results = [];

    for (const id of wanted) {
      const filePath = targets[id];
      if (!filePath) {
        results.push({ id, status: "error", message: "Unknown tool id" });
        continue;
      }
      try {
        let existing = {};
        if (existsSync(filePath)) {
          try { existing = JSON.parse(readFileSync(filePath, "utf8")); } catch {}
        }
        const merged = {
          ...existing,
          mcpServers: { ...(existing.mcpServers || {}), "timps-swarm": mcpEntry },
        };
        if (opts.dryRun) {
          results.push({ id, status: "dry_run", message: `Would write to ${filePath}` });
        } else {
          mkdirSync(dirname(filePath), { recursive: true });
          writeFileSync(filePath, JSON.stringify(merged, null, 2));
          results.push({ id, status: "ok", message: `Written → ${filePath}` });
        }
      } catch (err) {
        results.push({ id, status: "error", message: err.message });
      }
    }

    const icons = { ok: "✅", dry_run: "👀", error: "❌" };
    const anyOk = results.some(r => r.status === "ok");
    console.log();
    for (const r of results) {
      console.log(`  ${icons[r.status] || "?"} ${chalk.bold(r.id.padEnd(14))} ${r.message}`);
    }
    console.log();
    if (anyOk) {
      console.log(chalk.green("  MCP configuration complete!"));
      console.log(chalk.dim(`  Repo path : ${repoDir}`));
      console.log(chalk.dim("  Restart your AI tool and TIMPS Swarm will appear as an MCP server."));
    } else if (opts.dryRun) {
      console.log(chalk.yellow("  Dry-run complete — no files written."));
    } else {
      console.log(chalk.red("  Some targets failed — see errors above."));
      process.exit(1);
    }
  });

// ── refactor ──────────────────────────────────────────────────────────────────
program
  .command("refactor [path]")
  .description("Detect code smells and produce a refactored version")
  .option("-l, --language <lang>", "Language", "python")
  .option("-g, --goals <goals>", "Comma-separated goals", "reduce_complexity,extract_functions")
  .action(async (path, opts) => {
    printHeader("Refactoring Agent");
    let code = "";
    if (path && existsSync(path)) {
      code = readFileSync(path, "utf8");
    } else if (path) {
      code = path;
    } else {
      console.error(chalk.red("  Provide a file path or inline code snippet."));
      process.exit(1);
    }
    const spinner = ora("  Analysing and refactoring…").start();
    try {
      const result = await fetchAPI("/agents/refactor", {
        code, language: opts.language,
        goals: opts.goals.split(",").map(s => s.trim()),
      });
      spinner.succeed(chalk.green("  Done!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── test-data ─────────────────────────────────────────────────────────────────
program
  .command("test-data <schema>")
  .description("Generate realistic seed / fixture data for any schema")
  .option("-n, --count <n>", "Number of records", "20")
  .option("-f, --format <fmt>", "json | csv | sql | yaml | python_dict", "json")
  .option("--locale <locale>", "Locale e.g. en_US, de_DE, ja_JP", "en_US")
  .action(async (schema, opts) => {
    printHeader("Test Data Agent");
    const spinner = ora(`  Generating ${opts.count} ${opts.format} records…`).start();
    try {
      const result = await fetchAPI("/agents/test-data", {
        schema, count: parseInt(opts.count), format: opts.format, locale: opts.locale,
      });
      spinner.succeed(chalk.green("  Done!"));
      console.log(chalk.cyan(`  Saved to: ${result.data_path || "(inline)"}`));
      if (result.data_path) {
        console.log(chalk.dim(`  ${result.summary}`));
      } else {
        console.log(chalk.white(String(result.data || "").slice(0, 800)));
      }
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── monitor ───────────────────────────────────────────────────────────────────
program
  .command("monitor <service>")
  .description("Generate Prometheus rules, Grafana dashboard, and alerting config")
  .option("-l, --language <lang>", "Service language/runtime", "python")
  .option("--slos <slos>", "Comma-separated SLOs", "p99 < 200ms,error_rate < 0.1%")
  .option("--platform <p>", "alertmanager | pagerduty | opsgenie", "alertmanager")
  .action(async (service, opts) => {
    printHeader("Monitoring Agent");
    const spinner = ora("  Generating monitoring config…").start();
    try {
      const result = await fetchAPI("/agents/monitoring", {
        service_description: service,
        language: opts.language,
        slos: opts.slos.split(",").map(s => s.trim()),
        alerting_platform: opts.platform,
      });
      spinner.succeed(chalk.green("  Done!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── ui ────────────────────────────────────────────────────────────────────────
program
  .command("ui <description>")
  .description("Generate a UI component spec, code, Storybook story, and accessibility audit")
  .option("-f, --framework <fw>", "react | vue | svelte | html", "react")
  .option("-d, --design-system <ds>", "tailwind | material | chakra | custom", "tailwind")
  .option("--a11y <level>", "WCAG level: AA | AAA", "AA")
  .action(async (description, opts) => {
    printHeader("UI/UX Agent");
    const spinner = ora("  Designing component…").start();
    try {
      const result = await fetchAPI("/agents/ui-ux", {
        description, framework: opts.framework,
        design_system: opts.designSystem, accessibility_level: opts.a11y,
      });
      spinner.succeed(chalk.green("  Done!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── i18n ──────────────────────────────────────────────────────────────────────
program
  .command("i18n [path]")
  .description("Extract translatable strings and generate translation files")
  .option("--locales <ls>", "Comma-separated target locales", "fr,de,ja,ar")
  .option("--source <locale>", "Source locale", "en")
  .option("--framework <fw>", "i18n framework", "auto")
  .action(async (path, opts) => {
    printHeader("i18n Agent");
    let code = "";
    if (path && existsSync(path)) code = readFileSync(path, "utf8");
    else if (path) code = path;
    const spinner = ora("  Extracting strings…").start();
    try {
      const result = await fetchAPI("/agents/i18n", {
        code, source_locale: opts.source,
        target_locales: opts.locales.split(",").map(s => s.trim()),
        i18n_framework: opts.framework,
      });
      spinner.succeed(chalk.green("  Done!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── cost ──────────────────────────────────────────────────────────────────────
program
  .command("cost <architecture>")
  .description("Estimate cloud cost and surface savings optimisations")
  .option("-p, --provider <p>", "aws | gcp | azure | multi", "aws")
  .option("-r, --requests <n>", "Monthly requests", "1000000")
  .option("--regions <r>", "Comma-separated regions", "us-east-1")
  .action(async (architecture, opts) => {
    printHeader("Cost Optimizer");
    const spinner = ora("  Calculating cloud costs…").start();
    try {
      const result = await fetchAPI("/agents/cost-optimizer", {
        architecture, provider: opts.provider,
        monthly_requests: parseInt(opts.requests),
        regions: opts.regions.split(",").map(s => s.trim()),
      });
      spinner.succeed(chalk.green("  Done!"));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

// ── critique ──────────────────────────────────────────────────────────────────
program
  .command("critique <content>")
  .description("Self-Critic Agent — score output quality and auto-improve until threshold is met")
  .option("-a, --agent <name>", "Which agent produced the content")
  .option("-t, --task <task>", "The original task")
  .option("--threshold <n>", "Score threshold to pass (1-10)", "7")
  .option("--retries <n>", "Max re-run attempts", "2")
  .action(async (content, opts) => {
    printHeader("Self-Critic Agent");
    const spinner = ora("  Critiquing output…").start();
    try {
      const result = await fetchAPI("/agents/self-critic", {
        content, agent: opts.agent || "unknown",
        task: opts.task || content.slice(0, 80),
        threshold: parseInt(opts.threshold),
        max_retries: parseInt(opts.retries),
      });
      spinner.succeed(chalk.green(
        result.verdict === "pass"
          ? `  PASS — Score ${result.score}/10`
          : `  FAIL — Score ${result.score}/10 (threshold: ${result.threshold})`
      ));
      printResult(result);
    } catch (err) {
      spinner.fail(chalk.red(`  Failed: ${err.message}`));
      process.exit(1);
    }
  });

program.parse();
