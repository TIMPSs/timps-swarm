#!/usr/bin/env node
/**
 * timps-swarm CLI
 * ===============
 * npx timps-swarm <command> [options]
 *
 * Commands
 * --------
 *   audit <path>        Security audit — secrets + CVEs + SAST (no backend needed)
 *   fix <path>          Run the SDLC swarm on a codebase path
 *   research <topic>    Research agent — gather context before coding
 *   api-design <desc>   Generate an OpenAPI 3.1 spec from plain English
 *   db-design <desc>    Design a database schema with migrations
 *   n8n <desc>          Generate an n8n workflow JSON
 *   health              Run computer health checkup
 *   providers           Show configured LLM providers
 *   start               Start the TIMPS Swarm API server
 *   mcp                 Start the MCP stdio server
 *   install-mcp         Auto-configure TIMPS as MCP + register 64 native sub-agents
 *   uninstall-mcp       Remove the TIMPS MCP config and 64 sub-agent .md files
 */

import { Command } from "commander";
import chalk from "chalk";
import ora from "ora";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import { dirname, resolve, join } from "path";
import { existsSync, readFileSync, writeFileSync, mkdirSync, statSync } from "fs";
import { spawn, execSync } from "child_process";
import { auditDirectory } from "../lib/local-audit.js";
import { writeSubAgents, removeSubAgents, subAgentTargets } from "../lib/agent-files.js";
import { AGENTS } from "../lib/agents-manifest.js";

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
  // 1. Explicit override (set TIMPS_REPO=/path/to/timps-swarm to skip auto-detection)
  if (process.env.TIMPS_REPO && existsSync(join(process.env.TIMPS_REPO, "mcp_server", "server.py"))) {
    return process.env.TIMPS_REPO;
  }
  // 2. Walk up from CWD
  let dir = process.cwd();
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(dir, "mcp_server", "server.py"))) return dir;
    dir = resolve(dir, "..");
  }
  // 3. Common install locations
  const common = [
    join(process.env.HOME || "", "timps-swarm"),
    join(process.env.HOME || "", "Desktop", "timps-swarm"),
    "/opt/timps-swarm",
  ];
  const found = common.find(d => d && existsSync(join(d, "mcp_server", "server.py")));
  if (found) return found;
  // 4. npm global prefix (for `npm install -g` users who bundled Python files)
  try {
    const npmPrefix = execSync("npm config get prefix", { encoding: "utf8" }).trim();
    if (npmPrefix) {
      const npmLib = join(npmPrefix, "lib", "node_modules", "timps-swarm");
      if (existsSync(join(npmLib, "mcp_server", "server.py"))) return npmLib;
    }
  } catch {}
  return null;
}

function pythonBin() {
  // Prefer python3 — macOS 12+ and most Linux distros don't ship `python` anymore.
  try { execSync("python3 --version", { stdio: "ignore" }); return "python3"; } catch {}
  try { execSync("python --version", { stdio: "ignore" }); return "python"; } catch {}
  return "python3";
}

function serverDownError(err) {
  const msg = String((err && err.message) || err || "");
  const isDown = msg.includes("ECONNREFUSED") || msg.includes("fetch failed") ||
                 msg.includes("ENOTFOUND") || msg.includes("ECONNRESET") ||
                 msg.includes("aborted") || msg.includes("timeout") ||
                 // node-fetch v2 produces "request to <url> failed, reason: " with empty
                 // reason when the connection is refused (no DNS or port binding).
                 (msg.includes("request to ") && msg.includes("failed"));
  if (isDown) {
    console.log(chalk.red(`\n  ✗ TIMPS Swarm server not running at ${API_BASE}\n`));
    console.log(chalk.dim("  Start it in another terminal:"));
    console.log(chalk.cyan("    npx timps-swarm start"));
    console.log(chalk.cyan("    npx timps-swarm start --repo <path>   # explicit Python repo path"));
    console.log(chalk.cyan("    cd ~/timps-swarm && npx timps-swarm start --repo ."));
    console.log(chalk.dim("  Or:  TIMPS_API_URL=https://your-server npx timps-swarm <command>"));
  } else {
    console.log(chalk.red(`  ✗ ${msg}`));
  }
}

function printHeader(title) {
  console.log(chalk.bold.cyan(`\n  ◆ TIMPS Swarm — ${title}`));
  console.log(chalk.dim("  ─────────────────────────────────────────\n"));
}

function printStarCTA() {
  console.log();
  console.log(chalk.dim("  ★  Found this useful? A star keeps the project going:"));
  console.log(chalk.cyan("     https://github.com/Sandeeprdy1729/timps-swarm"));
  console.log();
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
  .version("2.1.0");

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
      const proc = spawn(pythonBin(), ["-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"], {
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
      printStarCTA();
    } catch (err) {
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
      process.exit(1);
    }
  });

// ── audit ─────────────────────────────────────────────────────────────────────
program
  .command("audit [path]")
  .description("Security audit — hardcoded secrets, CVEs, and SAST findings (no backend needed)")
  .option("-o, --output <file>", "Save JSON report to file")
  .option("--no-cve", "Skip CVE scan (faster, offline-only)")
  .option("-e, --ecosystem <eco>", "python | node | rust | go | auto (for manifest-only mode)", "auto")
  .action(async (path, opts) => {
    printHeader("Security Audit");

    const targetPath = resolve(path || ".");

    // Determine if target is a directory
    let isActualDir = false;
    try { isActualDir = statSync(targetPath).isDirectory(); } catch {}

    if (isActualDir || !existsSync(targetPath)) {
      // Local security audit — works with zero backend
      const spinner = ora("  Scanning for secrets, CVEs, and SAST issues…").start();
      let results;
      try {
        results = await auditDirectory(targetPath);
      } catch (err) {
        spinner.fail(chalk.red(`  ${err.message}`));
        process.exit(1);
      }

      const sevColor = { CRITICAL: "red", HIGH: "redBright", MEDIUM: "yellow", LOW: "dim", UNKNOWN: "dim" };
      const sevIcon  = { CRITICAL: "●", HIGH: "●", MEDIUM: "◐", LOW: "○", UNKNOWN: "○" };

      spinner.succeed(chalk.green("  Scan complete!"));
      console.log();
      console.log(chalk.bold(`  Target: ${results.target}`));
      console.log(chalk.dim(`  Found:  ${results.manifests.length} manifest${results.manifests.length !== 1 ? "s" : ""} · ${results.packageCount} packages · ${results.fileCount} source files\n`));

      // CVEs
      if (results.cves.length > 0) {
        console.log(chalk.bold("  ── CVE Findings ──────────────────────────────────"));
        for (const c of results.cves) {
          const col = sevColor[c.severity] || "white";
          const cveId = c.cves.length > 0 ? c.cves[0] : c.id;
          console.log(`  ${chalk[col](`${sevIcon[c.severity]} ${c.severity.padEnd(8)}`)}  ${chalk.bold(cveId)}`);
          console.log(`             ${chalk.white(c.package + "@" + c.version)} — ${chalk.dim(c.summary)}`);
          if (c.fixed) console.log(`             ${chalk.green("Fix: upgrade to " + c.fixed)}`);
          console.log();
        }
      } else if (results.packageCount > 0) {
        console.log(chalk.green("  ✓  No CVEs found in " + results.packageCount + " packages"));
        console.log();
      }

      // Secrets
      if (results.secrets.length > 0) {
        console.log(chalk.bold("  ── Hardcoded Secrets ─────────────────────────────"));
        for (const s of results.secrets) {
          console.log(`  ${chalk.red("⚠  " + s.type)}`);
          console.log(`     ${chalk.dim(s.file + ":" + s.line)}`);
          console.log(`     ${chalk.dim(s.snippet.replace(/./g, (c, i) => i > 20 && i < s.snippet.length - 4 ? "·" : c))}`);
          console.log();
        }
      } else {
        console.log(chalk.green("  ✓  No hardcoded secrets found"));
        console.log();
      }

      // SAST
      if (results.sast.length > 0) {
        console.log(chalk.bold("  ── SAST Findings ─────────────────────────────────"));
        for (const s of results.sast) {
          const col = sevColor[s.severity] || "white";
          console.log(`  ${chalk[col](`${sevIcon[s.severity]} ${s.severity.padEnd(8)}`)}  ${chalk.bold(s.rule)}  ${s.name}`);
          console.log(`             ${chalk.dim(s.file + ":" + s.line)}`);
          console.log(`             ${chalk.dim(s.description)}`);
          console.log();
        }
      } else {
        console.log(chalk.green("  ✓  No SAST findings"));
        console.log();
      }

      // Summary bar
      const totalIssues = results.cves.length + results.secrets.length + results.sast.length;
      const score = results.score;
      const barLen = 20;
      const filled = Math.round((score / 100) * barLen);
      const bar = chalk.green("■".repeat(filled)) + chalk.dim("□".repeat(barLen - filled));
      const scoreColor = score >= 80 ? "green" : score >= 60 ? "yellow" : "red";
      console.log(chalk.bold("  ── Summary ───────────────────────────────────────"));
      console.log(`  Security score: ${chalk[scoreColor].bold(score + "/100")}  ${bar}`);
      if (totalIssues === 0) {
        console.log(chalk.green("  No issues found. Clean!"));
      } else {
        const crit = results.cves.filter(c => c.severity === "CRITICAL").length;
        const high = results.cves.filter(c => c.severity === "HIGH").length + results.sast.filter(s => s.severity === "HIGH").length;
        const parts = [];
        if (crit) parts.push(chalk.red(`${crit} CRITICAL`));
        if (high) parts.push(chalk.redBright(`${high} HIGH`));
        if (results.secrets.length) parts.push(chalk.red(`${results.secrets.length} secret${results.secrets.length !== 1 ? "s" : ""}`));
        const low = totalIssues - crit - high - results.secrets.length;
        if (low > 0) parts.push(chalk.yellow(`${low} lower`));
        console.log("  " + parts.join("  ·  "));
      }
      console.log();

      if (opts.output) {
        writeFileSync(opts.output, JSON.stringify(results, null, 2));
        console.log(chalk.cyan(`  Report saved → ${opts.output}`));
        console.log();
      }

      printStarCTA();
      process.exit(totalIssues > 0 && results.cves.some(c => c.severity === "CRITICAL") ? 1 : 0);
      return;
    }

    // Manifest file path: fall back to backend dependency audit
    let manifest = "";
    if (existsSync(targetPath)) {
      manifest = readFileSync(targetPath, "utf8");
    } else {
      manifest = targetPath;
    }
    const spinner = ora("  Scanning dependencies…").start();
    try {
      const result = await fetchAPI("/agents/dependency-audit", {
        manifest,
        ecosystem: opts.ecosystem,
      });
      spinner.succeed(chalk.green("  Audit complete!"));
      printResult(result);
      printStarCTA();
    } catch (err) {
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      printStarCTA();
    } catch (err) {
      spinner.stop();
      serverDownError(err);
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
      console.error();
      serverDownError(err);
      process.exit(1);
    }
  });

// ── start ─────────────────────────────────────────────────────────────────────
program
  .command("start")
  .description("Start the TIMPS Swarm API + dashboard server")
  .option("-p, --port <port>", "API port", "8000")
  .option("--repo <path>", "Path to timps-swarm Python repo (auto-detected if omitted)")
  .action((opts) => {
    printHeader("Starting Server");
    const repoDir = opts.repo || findRepoPython();
    if (!repoDir) {
      console.error(chalk.red("  Could not find timps-swarm repo."));
      console.error(chalk.dim("  Clone it:  git clone https://github.com/Sandeeprdy1729/timps-swarm ~/timps-swarm"));
      console.error(chalk.dim("  Or pass:   npx timps-swarm start --repo <path>"));
      console.error(chalk.dim("  Or set:    TIMPS_REPO=/path/to/timps-swarm"));
      process.exit(1);
    }
    console.log(chalk.cyan(`  Repo:   ${repoDir}`));
    console.log(chalk.cyan(`  API:    http://localhost:${opts.port}`));
    console.log(chalk.cyan("  Docs:   http://localhost:8000/docs\n"));
    const proc = spawn(
      pythonBin(), ["-m", "uvicorn", "src.main:app",
                 "--host", "0.0.0.0", "--port", opts.port, "--reload"],
      { cwd: repoDir, stdio: "inherit" }
    );
    proc.on("exit", code => process.exit(code || 0));
  });

// ── mcp ───────────────────────────────────────────────────────────────────────
program
  .command("mcp")
  .description("Start the MCP stdio server (for Claude Code, Cursor, etc.)")
  .option("--repo <path>", "Path to timps-swarm Python repo (auto-detected if omitted)")
  .action(async (opts) => {
    const repoDir = opts.repo || findRepoPython();
    if (repoDir) {
      // Path 1: full Python MCP server (in-process, supports MCP sampling)
      const proc = spawn(pythonBin(), ["-m", "mcp_server.server"], {
        cwd: repoDir,
        stdio: "inherit",
        env: { ...process.env },
      });
      proc.on("exit", code => process.exit(code || 0));
      return;
    }
    // Path 2: Node.js JSON-RPC 2.0 proxy → a running FastAPI server.
    // Lets `npm install -g timps-swarm` users run the MCP server without
    // cloning the Python backend, as long as the API server is reachable
    // (locally via `npx timps-swarm start` or remotely via TIMPS_API_URL).
    const url = await import("node:url");
    const proxyPath = url.fileURLToPath(new URL("../lib/mcp-proxy.js", import.meta.url));
    const proc = spawn(process.execPath, [proxyPath], {
      stdio: "inherit",
      env: { ...process.env },
    });
    proc.on("exit", code => process.exit(code || 0));
  });

// ── install-mcp ───────────────────────────────────────────────────────────────
program
  .command("install-mcp")
  .description("Auto-configure TIMPS Swarm as MCP server in Claude Code, Cursor, Windsurf, Continue, Aider, Zed, VS Code, and more")
  .option("--tool <id>", "Specific tool to configure (see list below)")
  .option("--dry-run", "Preview only — don't write any files")
  .option("--silent", "Suppress output (used during postinstall)")
  .option("--repo <path>", "Path to timps-swarm repo (auto-detected if omitted)")
  .option("--no-sub-agents", "Skip writing 64 sub-agent .md files (MCP config only)")
  .action(async (opts) => {
    // In postinstall context with CI / non-TTY, skip silently
    if (opts.silent && (process.env.CI || process.env.CONTINUOUS_INTEGRATION || !process.stdout.isTTY)) {
      process.exit(0);
    }

    if (!opts.silent) printHeader("MCP Installer");

    const home = process.env.HOME || process.env.USERPROFILE || "~";
    const cwd  = process.cwd();
    const repoDir = opts.repo || findRepoPython() || resolve(__dirname, "../..");

    // MCP entry — use `npx timps-swarm mcp` so it works globally or locally
    const envVars = {};
    for (const k of ["ANTHROPIC_API_KEY","OPENAI_API_KEY","GEMINI_API_KEY","GROQ_API_KEY","TIMPS_API_URL","OLLAMA_HOST","REDIS_URL"]) {
      if (process.env[k]) envVars[k] = process.env[k];
    }
    const mcpCmd  = { command: "npx", args: ["timps-swarm", "mcp"], env: envVars };
    // Alternative: direct Python server (used when repo is found)
    const pyCmd   = repoDir
      ? { command: "python", args: ["-m", "mcp_server.server"], cwd: repoDir, env: envVars }
      : mcpCmd;

    // ── Tool registry ────────────────────────────────────────────────────────
    // format: "claude-mcp"    → { mcpServers: { "timps-swarm": entry } }
    //         "vscode-mcp"    → { mcp: { servers: { "timps-swarm": { type:"stdio", ...entry } } } }
    //         "continue-mcp"  → { mcpServers: [ { name, ...entry } ] }
    //         "zed-mcp"       → { assistant: { mcp_servers: { "timps-swarm": entry } } }
    //         "warp-mcp"      → { "timps-swarm": entry }
    //         "aider-yaml"    → YAML append
    //         "goose-yaml"    → YAML append
    const tools = [
      { id: "claude-code",  label: "Claude Code",    fmt: "claude-mcp",   path: join(home, ".claude", "mcp.json"),             detectionDir: join(home, ".claude") },
      { id: "cursor",       label: "Cursor",         fmt: "claude-mcp",   path: join(home, ".cursor", "mcp.json"),             detectionDir: join(home, ".cursor"),     detectionApp: "/Applications/Cursor.app" },
      { id: "windsurf",     label: "Windsurf",       fmt: "claude-mcp",   path: join(home, ".windsurf", "mcp.json"),           detectionDir: join(home, ".windsurf"),   detectionApp: "/Applications/Windsurf.app" },
      { id: "continue",     label: "Continue",       fmt: "continue-mcp", path: join(home, ".continue", "config.json"),        detectionDir: join(home, ".continue") },
      { id: "zed",          label: "Zed",            fmt: "zed-mcp",      path: join(home, ".config", "zed", "settings.json"), detectionDir: join(home, ".config", "zed"), detectionApp: "/Applications/Zed.app" },
      { id: "aider",        label: "Aider",          fmt: "aider-yaml",   path: join(home, ".aider.conf.yml"),                 detectionBin: "aider" },
      { id: "goose",        label: "Goose",          fmt: "goose-yaml",   path: join(home, ".config", "goose", "config.yaml"), detectionDir: join(home, ".config", "goose"), detectionBin: "goose" },
      { id: "gemini-cli",   label: "Gemini CLI",     fmt: "claude-mcp",   path: join(home, ".gemini", "settings.json"),        detectionDir: join(home, ".gemini"),     detectionBin: "gemini" },
      { id: "codex-cli",    label: "Codex CLI",      fmt: "claude-mcp",   path: join(home, ".codex", "config.json"),           detectionDir: join(home, ".codex"),      detectionBin: "codex" },
      { id: "amp",          label: "Amp",            fmt: "claude-mcp",   path: join(home, ".amp", "mcp.json"),                detectionDir: join(home, ".amp") },
      { id: "warp",         label: "Warp",           fmt: "warp-mcp",     path: join(home, ".warp", "mcp_servers.json"),       detectionDir: join(home, ".warp"),       detectionApp: "/Applications/Warp.app" },
      { id: "vscode",       label: "VS Code / Cline",fmt: "vscode-mcp",   path: join(cwd, ".vscode", "mcp.json"),              detectionBin: "code",                    detectionApp: "/Applications/Visual Studio Code.app" },
    ];

    function isDetected(tool) {
      if (tool.detectionDir && existsSync(tool.detectionDir)) return true;
      if (tool.detectionApp && existsSync(tool.detectionApp)) return true;
      if (tool.detectionBin) {
        try { execSync(`which ${tool.detectionBin}`, { stdio: "ignore" }); return true; } catch {}
      }
      return false;
    }

    function mergeJSON(existing, entry, fmt) {
      switch (fmt) {
        case "claude-mcp":
          return { ...existing, mcpServers: { ...(existing.mcpServers || {}), "timps-swarm": entry } };
        case "continue-mcp": {
          const servers = (existing.mcpServers || []).filter(s => s.name !== "timps-swarm");
          return { ...existing, mcpServers: [...servers, { name: "timps-swarm", ...entry }] };
        }
        case "zed-mcp":
          return {
            ...existing,
            assistant: {
              ...(existing.assistant || {}),
              mcp_servers: { ...((existing.assistant || {}).mcp_servers || {}), "timps-swarm": entry },
            },
          };
        case "vscode-mcp":
          return {
            ...existing,
            mcp: {
              ...(existing.mcp || {}),
              servers: {
                ...((existing.mcp || {}).servers || {}),
                "timps-swarm": { type: "stdio", ...entry },
              },
            },
          };
        case "warp-mcp":
          return { ...existing, "timps-swarm": entry };
        default:
          return null;
      }
    }

    function appendYAML(filePath, fmt, entry) {
      const cmd = entry.command;
      const args = entry.args || [];
      let block = "";

      if (fmt === "aider-yaml") {
        block = `\nmcp-servers:\n  timps-swarm:\n    command: ${cmd}\n    args: [${args.join(", ")}]\n    type: stdio\n`;
      } else if (fmt === "goose-yaml") {
        block = `\nextensions:\n  - name: timps-swarm\n    type: stdio\n    cmd: ${cmd} ${args.join(" ")}\n    enabled: true\n`;
      }

      if (existsSync(filePath)) {
        const current = readFileSync(filePath, "utf8");
        if (current.includes("timps-swarm")) return "already configured";
        writeFileSync(filePath, current.trimEnd() + "\n" + block);
      } else {
        mkdirSync(dirname(filePath), { recursive: true });
        writeFileSync(filePath, block.trimStart());
      }
      return "ok";
    }

    const wanted = opts.tool ? [tools.find(t => t.id === opts.tool)].filter(Boolean) : tools;

    if (opts.tool && wanted.length === 0) {
      console.error(chalk.red(`  Unknown tool: ${opts.tool}`));
      console.log(chalk.dim("  Available: " + tools.map(t => t.id).join(", ")));
      process.exit(1);
    }

    const results = [];
    for (const tool of wanted) {
      // Skip undetected tools unless explicitly requested
      const detected = isDetected(tool);
      if (!opts.tool && !detected) {
        results.push({ tool, status: "not_installed" });
        continue;
      }

      const entry = mcpCmd; // always use npx for portability
      const isYAML = tool.fmt === "aider-yaml" || tool.fmt === "goose-yaml";

      if (opts.dryRun) {
        results.push({ tool, status: "dry_run", msg: `Would write to ${tool.path}` });
        continue;
      }

      try {
        if (isYAML) {
          const yamlResult = appendYAML(tool.path, tool.fmt, entry);
          results.push({ tool, status: yamlResult === "already configured" ? "skipped" : "ok", msg: tool.path });
        } else {
          let existing = {};
          if (existsSync(tool.path)) {
            try { existing = JSON.parse(readFileSync(tool.path, "utf8")); } catch {}
          }
          const merged = mergeJSON(existing, entry, tool.fmt);
          if (!merged) throw new Error("Unknown format");
          mkdirSync(dirname(tool.path), { recursive: true });
          writeFileSync(tool.path, JSON.stringify(merged, null, 2));
          results.push({ tool, status: "ok", msg: tool.path });
        }
      } catch (err) {
        results.push({ tool, status: "error", msg: err.message });
      }
    }

    // ── Sub-agent file registration ───────────────────────────────────────
    // Each of the 64 MCP tools is also registered as a native sub-agent so
    // Claude Code / Cursor / Codex can dispatch them in parallel via their
    // Task/Composer systems. Default-on, idempotent, reversible via uninstall-mcp.
    if (opts.subAgents !== false) {
      const subTargetIds = (() => {
        if (opts.tool) {
          // --tool narrows the MCP config to one IDE; mirror that for sub-agents
          if (opts.tool === "vscode") return ["claude-code"];  // VS Code uses .vscode/mcp.json, not agents dir
          if (["claude-code", "cursor", "codex-cli", "gemini-cli"].includes(opts.tool)) {
            return opts.tool === "codex-cli" ? ["codex"] : [opts.tool === "claude-code" ? "claude-code" : "cursor"];
          }
          return [];
        }
        return ["claude-code", "cursor", "codex"];
      })();

      if (subTargetIds.length > 0) {
        try {
          const { written, skipped, errors } = writeSubAgents({
            home,
            cwd,
            targetIds: subTargetIds,
            dryRun: !!opts.dryRun,
          });
          const all = [...written, ...skipped];
          if (!opts.dryRun) {
            for (const e of errors) console.log(`  ${chalk.red("✗")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim(e)}`);
          }
          if (all.length > 0 && !opts.silent) {
            const byTarget = {};
            for (const p of all) {
              for (const t of subAgentTargets(home, cwd)) {
                if (p.startsWith(t.dir)) { (byTarget[t.id] = byTarget[t.id] || []).push(p); break; }
              }
            }
            for (const [id, files] of Object.entries(byTarget)) {
              const label = ({ "claude-code": "Claude Code agents", cursor: "Cursor agents", codex: "Codex agents" })[id] || id;
              const verb = opts.dryRun ? "would write" : (skipped.length > 0 && files.every(f => skipped.includes(f)) ? "already up to date" : `wrote ${files.length}`);
              const totalTargets = subTargetIds.length;
              const expected = AGENTS.length;
              const note = totalTargets > 1
                ? ` (${expected} per target × ${totalTargets} targets = ${expected * totalTargets} total)`
                : ` (${expected} files)`;
              console.log(`  ${chalk.green("✓")}  ${chalk.bold(label.padEnd(20))}  ${chalk.dim(verb + note)}`);
            }
          }
        } catch (err) {
          console.log(`  ${chalk.red("✗")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim(err.message)}`);
        }
      }
    }

    if (opts.silent) process.exit(0);

    const icons = { ok: chalk.green("✓"), dry_run: chalk.cyan("?"), error: chalk.red("✗"), skipped: chalk.dim("–"), not_installed: null };
    const configured = results.filter(r => r.status === "ok");
    const failed     = results.filter(r => r.status === "error");
    const skipped    = results.filter(r => r.status === "skipped");

    console.log();
    for (const r of results) {
      if (r.status === "not_installed") continue; // don't clutter output
      const icon = icons[r.status] || "?";
      console.log(`  ${icon}  ${chalk.bold(r.tool.label.padEnd(16))}  ${chalk.dim(r.msg || "")}`);
    }
    console.log();

    if (configured.length > 0) {
      console.log(chalk.green(`  ✓ Configured ${configured.length} tool${configured.length !== 1 ? "s" : ""}. Restart your AI tool to see the swarm.`));
    } else if (opts.dryRun) {
      console.log(chalk.yellow("  Dry-run complete — no files written."));
      console.log(chalk.dim("  Run without --dry-run to apply."));
    } else if (failed.length > 0) {
      console.log(chalk.red(`  ${failed.length} tool${failed.length !== 1 ? "s" : ""} failed — see errors above.`));
      process.exit(1);
    } else {
      console.log(chalk.dim("  No supported AI tools detected on this machine."));
      console.log(chalk.dim("  Use --tool <id> to force-configure a specific tool."));
      console.log(chalk.dim("  Supported: " + tools.map(t => t.id).join(", ")));
    }

    if (skipped.length > 0) {
      console.log(chalk.dim(`  ${skipped.length} already configured (skipped).`));
    }
    console.log();
  });

// ── uninstall-mcp ────────────────────────────────────────────────────────────
program
  .command("uninstall-mcp")
  .description("Remove the TIMPS MCP server entry and 64 sub-agent files from every configured IDE")
  .option("--tool <id>", "Specific tool to remove (default: all detected)")
  .option("--dry-run", "Preview only — don't delete any files")
  .option("--keep-config", "Only remove sub-agent .md files; keep the MCP server config")
  .option("--keep-agents", "Only remove the MCP server config; keep the 64 sub-agent .md files")
  .action(async (opts) => {
    printHeader("MCP Uninstaller");
    const home = process.env.HOME || process.env.USERPROFILE || "~";
    const cwd  = process.cwd();

    // 1. Remove sub-agent .md files (default behaviour)
    if (!opts.keepAgents) {
      try {
        const { removed, notPresent, errors } = removeSubAgents({
          home, cwd, targetIds: ["claude-code", "cursor", "codex"], dryRun: !!opts.dryRun,
        });
        if (notPresent.length > 0) {
          for (const d of notPresent) console.log(`  ${chalk.dim("–")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim(d + " (not present)")}`);
        }
        for (const e of errors) console.log(`  ${chalk.red("✗")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim(e)}`);
        const total = removed.length;
        if (total > 0) {
          console.log(`  ${chalk.green("✓")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim((opts.dryRun ? "would remove " : "removed ") + total + " timps-*.md files from ~/.claude/agents, ./.claude/agents, ~/.codex/agents")}`);
        } else if (notPresent.length === 0) {
          console.log(`  ${chalk.dim("–")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim("no timps-*.md files found")}`);
        }
      } catch (err) {
        console.log(`  ${chalk.red("✗")}  ${chalk.bold("sub-agents".padEnd(16))}  ${chalk.dim(err.message)}`);
      }
    }

    // 2. Remove MCP server entries from the 12 IDE config files
    if (!opts.keepConfig) {
      const targets = [
        { id: "claude-code", label: "Claude Code", path: join(home, ".claude", "mcp.json") },
        { id: "cursor",      label: "Cursor",      path: join(home, ".cursor", "mcp.json") },
        { id: "windsurf",    label: "Windsurf",    path: join(home, ".windsurf", "mcp.json") },
        { id: "codex",       label: "Codex CLI",   path: join(home, ".codex", "config.json") },
        { id: "vscode",      label: "VS Code",     path: join(cwd, ".vscode", "mcp.json") },
      ];
      for (const t of targets) {
        if (opts.tool && opts.tool !== t.id) continue;
        if (!existsSync(t.path)) {
          console.log(`  ${chalk.dim("–")}  ${chalk.bold(t.label.padEnd(16))}  ${chalk.dim(t.path + " (not present)")}`);
          continue;
        }
        try {
          const j = JSON.parse(readFileSync(t.path, "utf8"));
          const before = JSON.stringify(j);
          const drop = (obj) => { if (obj && obj.mcpServers) delete obj.mcpServers["timps-swarm"]; if (obj && obj.mcp && obj.mcp.servers) delete obj.mcp.servers["timps-swarm"]; if (obj && obj.assistant && obj.assistant.mcp_servers) delete obj.assistant.mcp_servers["timps-swarm"]; };
          drop(j);
          // For continue: mcpServers is an array
          if (Array.isArray(j.mcpServers)) j.mcpServers = j.mcpServers.filter(s => s.name !== "timps-swarm");
          // For warp: top-level
          if (j["timps-swarm"] && typeof j["timps-swarm"] === "object") delete j["timps-swarm"];
          if (JSON.stringify(j) === before) {
            console.log(`  ${chalk.dim("–")}  ${chalk.bold(t.label.padEnd(16))}  ${chalk.dim(t.path + " (no timps-swarm entry)")}`);
            continue;
          }
          if (!opts.dryRun) writeFileSync(t.path, JSON.stringify(j, null, 2));
          console.log(`  ${chalk.green("✓")}  ${chalk.bold(t.label.padEnd(16))}  ${chalk.dim((opts.dryRun ? "would remove from " : "removed from ") + t.path)}`);
        } catch (err) {
          console.log(`  ${chalk.red("✗")}  ${chalk.bold(t.label.padEnd(16))}  ${chalk.dim(err.message)}`);
        }
      }
    }

    console.log();
    console.log(chalk.dim("  Restart your AI tool to apply changes."));
    console.log();
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
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
      spinner.stop();
      serverDownError(err);
      process.exit(1);
    }
  });

program.parse();
