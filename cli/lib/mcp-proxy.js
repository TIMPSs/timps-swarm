#!/usr/bin/env node
/**
 * Node.js MCP stdio proxy
 * ========================
 * Used as a fallback by `cli/bin/timps-swarm.js mcp` when the Python repo
 * is not available (e.g. the user ran `npm install -g timps-swarm` and
 * has no clone of https://github.com/Sandeeprdy1729/timps-swarm).
 *
 * Forwards JSON-RPC 2.0 (the Model Context Protocol transport) over stdio
 * to the FastAPI server in this repo (src/main.py), which exposes
 *   GET  /mcp/tools
 *   POST /mcp/tools/call
 * The FastAPI server holds the full dispatch table in mcp_server/server.py
 * and runs every tool in-process — so the proxy never has to know what
 * the 160 tools do, just that they exist.
 *
 * Protocol supported (a strict subset of MCP 2024-11-05):
 *   initialize                     → returns serverInfo + capabilities
 *   notifications/initialized      → ignored (no response)
 *   ping                           → {}
 *   tools/list                     → forwards GET /mcp/tools
 *   tools/call                     → forwards POST /mcp/tools/call
 *   anything else                  → JSON-RPC -32601 Method not found
 */

import { createRequire } from "module";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const require = createRequire(import.meta.url);
const fetch = require("node-fetch").default || require("node-fetch");

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

const API_BASE = process.env.TIMPS_API_URL || "http://localhost:8000";
const VERSION  = (() => {
  try {
    const pkg = JSON.parse(readFileSync(join(__dirname, "..", "package.json"), "utf8"));
    return pkg.version || "0.0.0";
  } catch { return "0.0.0"; }
})();

const SERVER_INFO = {
  name: "timps-swarm",
  version: VERSION,
  description: "TIMPS Swarm — 160 AI tools (SDLC, health, dev, expert, knowledge, priority, kernel, context, meta) via a remote FastAPI proxy.",
};
const CAPABILITIES = { tools: { listChanged: false } };

let cachedTools = null;

function log(msg) {
  process.stderr.write(`[timps-mcp] ${msg}\n`);
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function reply(id, result) {
  send({ jsonrpc: "2.0", id, result });
}

function fail(id, code, message, data) {
  send({ jsonrpc: "2.0", id, error: { code, message, ...(data !== undefined ? { data } : {}) } });
}

async function loadTools() {
  if (cachedTools) return cachedTools;
  const r = await fetch(`${API_BASE}/mcp/tools`, { signal: AbortSignal.timeout(10000) });
  if (!r.ok) throw new Error(`GET /mcp/tools → ${r.status} ${r.statusText}`);
  const data = await r.json();
  cachedTools = Array.isArray(data.tools) ? data.tools : [];
  return cachedTools;
}

async function callToolHttp(name, args) {
  const r = await fetch(`${API_BASE}/mcp/tools/call`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, arguments: args || {} }),
    signal: AbortSignal.timeout(120000),
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    return {
      isError: true,
      content: [{ type: "text", text: `Upstream HTTP ${r.status}: ${body.slice(0, 600)}` }],
    };
  }
  return r.json();
}

async function handle(msg) {
  const { id, method, params } = msg;
  try {
    switch (method) {
      case "initialize":
        return reply(id, {
          protocolVersion: "2024-11-05",
          capabilities: CAPABILITIES,
          serverInfo: SERVER_INFO,
        });

      case "notifications/initialized":
        return;  // no response per spec

      case "ping":
        return reply(id, {});

      case "tools/list": {
        const tools = await loadTools();
        return reply(id, { tools });
      }

      case "tools/call": {
        const name = params?.name || "";
        const args = params?.arguments || {};
        if (!name) return fail(id, -32602, "Missing params.name");
        const result = await callToolHttp(name, args);
        return reply(id, result);
      }

      default:
        if (id !== undefined && id !== null) {
          return fail(id, -32601, `Method not found: ${method}`);
        }
        return;  // unknown notification — ignore
    }
  } catch (err) {
    log(`${method} failed: ${err.message}`);
    if (id !== undefined && id !== null) {
      return fail(id, -32603, err.message || String(err));
    }
  }
}

// ── stdio JSON-RPC 2.0 line reader ──────────────────────────────────────────
let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let idx;
  while ((idx = buffer.indexOf("\n")) !== -1) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); }
    catch (e) {
      log(`Invalid JSON on stdin: ${e.message}`);
      fail(null, -32700, "Parse error");
      continue;
    }
    handle(msg);
  }
});

process.stdin.on("end", () => {
  log("stdin closed — exiting");
  process.exit(0);
});

// Pre-warm the tool list in the background so the first tools/call is fast.
loadTools().then(
  (n) => log(`loaded ${n} tools from ${API_BASE}/mcp/tools`),
  (e) => log(`could not pre-warm tool list: ${e.message} (will retry on first tools/list)`),
);

log(`Node.js MCP proxy starting → ${API_BASE}`);
