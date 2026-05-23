<div align="center">

<br/>

<img src="https://img.shields.io/badge/TIMPS%20SWARM-v2.0-FF6B35?style=for-the-badge&labelColor=1a1a1a" alt="TIMPS Swarm v2.0" />

<br/><br/>

**A local swarm of 64 specialist AI agents — one MCP server, every tool you already use.**

<br/>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![npm](https://img.shields.io/badge/npm-timps--swarm-CB3837?style=flat-square&logo=npm&logoColor=white)](https://www.npmjs.com/package/timps-swarm)
[![MCP Protocol](https://img.shields.io/badge/Protocol-MCP-7C3AED?style=flat-square)](https://modelcontextprotocol.io)
[![LangGraph](https://img.shields.io/badge/Powered_by-LangGraph-1C7EBF?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Ollama](https://img.shields.io/badge/Local_AI-Ollama-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.ai)
[![Discord](https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/MmsTNm8WF6)

<br/>

[Quick Start](#quick-start) · [Integrations](#integrations) · [Agents](#the-64-agents) · [CLI](#cli) · [Architecture](#architecture) · [API](#rest-api)

<br/>

</div>

---

I got tired of explaining the same codebase context to six different AI tools every day. TIMPS Swarm is the single layer that sits underneath all of them. One MCP server, 64 specialist agents, running locally on your machine. Claude Code calls it for a security audit. Cursor pulls it in for test generation. Aider uses it for code review. They all share the same swarm — nothing leaves your machine unless you explicitly configure a cloud LLM.

It started as a computer health tool to fix my perpetually broken laptop. Then it grew into a full SDLC pipeline. Then developer workflow agents. Then knowledge-worker agents for the non-coding half of the day. Then seven more. This is where it landed.

---

## Quick Start

```bash
# Clone and install
git clone https://github.com/Sandeeprdy1729/timps-swarm
cd timps-swarm
pip install -e .

# Wire it into every AI tool on your machine (no server needed)
npx timps-swarm install-mcp

# Restart your tool — TIMPS Swarm appears as an MCP server with 64 tools
```

Or use Docker if you don't want to touch your Python environment:

```bash
make all
open http://localhost:3000   # dashboard
```

Pull local models once (~16 GB):

```bash
ollama pull qwen2.5:14b && ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b && ollama pull qwen2.5:3b
```

---

## Integrations

TIMPS Swarm speaks [MCP](https://modelcontextprotocol.io) — one config block and all 64 agents appear in your tool automatically.

```bash
npx timps-swarm install-mcp          # auto-configure Claude Code, Cursor, Windsurf
npx timps-swarm install-mcp --tool cursor      # single tool only
npx timps-swarm install-mcp --dry-run          # preview without writing files
```

### CLI Agents

| Tool | Integration |
|------|-------------|
| [![Claude Code](https://img.shields.io/badge/Claude_Code-CC785C?style=flat-square&logo=anthropic&logoColor=white)](https://claude.ai/code) | MCP stdio → `~/.claude/mcp.json` |
| [![Codex CLI](https://img.shields.io/badge/Codex_CLI-412991?style=flat-square&logo=openai&logoColor=white)](https://github.com/openai/codex) | MCP stdio → `~/.codex/config.json` |
| [![Gemini CLI](https://img.shields.io/badge/Gemini_CLI-4285F4?style=flat-square&logo=google&logoColor=white)](https://github.com/google-gemini/gemini-cli) | MCP → `~/.gemini/settings.json` |
| [![Aider](https://img.shields.io/badge/Aider-FF4B4B?style=flat-square&logo=git&logoColor=white)](https://aider.chat) | YAML → `~/.aider.conf.yml` |
| [![Goose](https://img.shields.io/badge/Goose-1a1a1a?style=flat-square&logo=block&logoColor=white)](https://block.github.io/goose/) | Extension → `~/.config/goose/config.yaml` |
| [![Amp](https://img.shields.io/badge/Amp-FF6D00?style=flat-square&logo=sourcegraph&logoColor=white)](https://sourcegraph.com/amp) | MCP stdio → `~/.amp/mcp.json` |
| [![Warp](https://img.shields.io/badge/Warp-01A4FF?style=flat-square&logo=warp&logoColor=white)](https://warp.dev) | MCP → `~/.warp/mcp_servers.json` |

### IDE Extensions & Copilots

| Tool | Integration |
|------|-------------|
| [![GitHub Copilot](https://img.shields.io/badge/GitHub_Copilot-000000?style=flat-square&logo=github&logoColor=white)](https://github.com/features/copilot) | `.vscode/mcp.json` |
| [![Cline](https://img.shields.io/badge/Cline-007ACC?style=flat-square&logo=visualstudiocode&logoColor=white)](https://github.com/cline/cline) | `.vscode/mcp.json` |
| [![Continue](https://img.shields.io/badge/Continue-6B4FBB?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyQzYuNDggMiAyIDYuNDggMiAxMnM0LjQ4IDEwIDEwIDEwIDEwLTQuNDggMTAtMTBTMTcuNTIgMiAxMiAyem0tMSAxNXYtNEg3bDUtOXY0aDRsLTUgOXoiLz48L3N2Zz4=&logoColor=white)](https://continue.dev) | `~/.continue/config.json` |
| [![Kilo Code](https://img.shields.io/badge/Kilo_Code-2196F3?style=flat-square&logo=visualstudiocode&logoColor=white)](https://kilocode.ai) | `.vscode/mcp.json` |
| [![Roo Code](https://img.shields.io/badge/Roo_Code-00C853?style=flat-square&logo=visualstudiocode&logoColor=white)](https://roocode.com) | `.vscode/mcp.json` |
| [![Augment Code](https://img.shields.io/badge/Augment_Code-FF3D00?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xOSAzSDVjLTEuMSAwLTIgLjktMiAydjE0YzAgMS4xLjkgMiAyIDJoMTRjMS4xIDAgMi0uOSAyLTJWNWMwLTEuMS0uOS0yLTItMnptLTcgM2MxLjY2IDAgMyAxLjM0IDMgM3MtMS4zNCAzLTMgMy0zLTEuMzQtMy0zIDEuMzQtMyAzLTN6bTYgMTJINlYxN2MwLTIgNC0zLjEgNi0zLjEgMiAwIDYgMS4xIDYgMy4xdjF6Ii8+PC9zdmc+&logoColor=white)](https://augmentcode.com) | `.vscode/mcp.json` |

### IDEs

| Tool | Integration |
|------|-------------|
| [![Cursor](https://img.shields.io/badge/Cursor-000000?style=flat-square&logo=cursor&logoColor=white)](https://cursor.com) | MCP → `~/.cursor/mcp.json` |
| [![Windsurf](https://img.shields.io/badge/Windsurf-0090FF?style=flat-square&logo=codeium&logoColor=white)](https://codeium.com/windsurf) | MCP → `~/.windsurf/mcp.json` |
| [![Zed](https://img.shields.io/badge/Zed-F97316?style=flat-square&logo=zed&logoColor=white)](https://zed.dev) | `settings.json` lsp/mcp block |
| [![VS Code](https://img.shields.io/badge/VS_Code-007ACC?style=flat-square&logo=visualstudiocode&logoColor=white)](https://code.visualstudio.com) | `.vscode/mcp.json` |

### Cloud & SaaS

| Tool | Integration |
|------|-------------|
| [![Devin](https://img.shields.io/badge/Devin-6366F1?style=flat-square&logo=cognition&logoColor=white)](https://devin.ai) | Team MCP endpoint (cloud-hosted) |
| [![Replit](https://img.shields.io/badge/Replit-F26207?style=flat-square&logo=replit&logoColor=white)](https://replit.com) | `.replit` mcp_servers block |
| [![v0](https://img.shields.io/badge/v0-000000?style=flat-square&logo=vercel&logoColor=white)](https://v0.dev) | Next.js API route wrapper |
| [![n8n](https://img.shields.io/badge/n8n-EA4B71?style=flat-square&logo=n8n&logoColor=white)](https://n8n.io) | HTTP Request node → REST API |
| [![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white)](https://github.com/features/actions) | Reusable workflow |

### Manual config snippets

<details>
<summary>Show config for every tool</summary>

**Claude Code** — `~/.claude/mcp.json`
```json
{
  "mcpServers": {
    "timps-swarm": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/timps-swarm"
    }
  }
}
```

**Cursor / Windsurf** — `~/.cursor/mcp.json` or `~/.windsurf/mcp.json`
```json
{
  "mcpServers": {
    "timps-swarm": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/timps-swarm"
    }
  }
}
```

**GitHub Copilot / Cline / Roo Code** — `.vscode/mcp.json`
```json
{
  "mcp": {
    "servers": {
      "timps-swarm": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "mcp_server.server"],
        "cwd": "/path/to/timps-swarm"
      }
    }
  }
}
```

**Aider** — `~/.aider.conf.yml`
```yaml
mcp-servers:
  timps-swarm:
    command: python
    args: ["-m", "mcp_server.server"]
    cwd: /path/to/timps-swarm
    type: stdio
```

**Goose** — `~/.config/goose/config.yaml`
```yaml
extensions:
  - name: timps-swarm
    type: stdio
    cmd: python -m mcp_server.server
    enabled: true
```

**Continue** — `~/.continue/config.json`
```json
{
  "mcpServers": [{
    "name": "timps-swarm",
    "command": "python",
    "args": ["-m", "mcp_server.server"],
    "cwd": "/path/to/timps-swarm"
  }]
}
```

**Zed** — `~/.config/zed/settings.json`
```json
{
  "assistant": {
    "mcp_servers": {
      "timps-swarm": {
        "command": "python",
        "args": ["-m", "mcp_server.server"]
      }
    }
  }
}
```

**GitHub Actions** — reusable workflow
```yaml
jobs:
  generate:
    uses: Sandeeprdy1729/timps-swarm/.github/workflows/timps-swarm.yml@main
    with:
      task: "Build a microservice for JWT authentication"
      language: python
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

</details>

---

## LLM Providers

TIMPS Swarm tries providers in priority order and uses the first one available. Mix and match — local and cloud coexist.

| Priority | Provider | Set env var | Notes |
|----------|----------|-------------|-------|
| 1 | MCP Sampler | *(auto)* | Uses the host tool's model |
| 2 | Gemini 2.5 Flash | `GEMINI_API_KEY` | Fast, generous free tier |
| 3 | Anthropic Claude | `ANTHROPIC_API_KEY` | Best for complex reasoning |
| 4 | OpenAI GPT-4o | `OPENAI_API_KEY` | |
| 5 | Groq (Llama 3.3 70B) | `GROQ_API_KEY` | Fastest API inference |
| 6 | Ollama (local) | *(auto-detected)* | Fully private, no API key |
| 7 | TIMPS-Coder 0.5B | *(built-in)* | On-device, always available |

```bash
export GEMINI_API_KEY=...      # recommended starting point
export ANTHROPIC_API_KEY=...   # optional
export OPENAI_API_KEY=...      # optional
export GROQ_API_KEY=...        # optional — free tier available
```

---

## The 64 Agents

### SDLC Pipeline — 10 agents

The full software development lifecycle as a LangGraph DAG. Give it a task and all ten agents sequence through it automatically — or call any agent individually.

| # | Agent | What it does |
|---|-------|--------------|
| 1 | Orchestrator | Decomposes requests into a task DAG, routes work, handles retries |
| 2 | Product Manager | Writes PRDs and acceptance criteria from vague requirements |
| 3 | Architect | System design, API contracts, data models, ADRs |
| 4 | Code Generator | Implementation using TIMPS-Coder + 20 LoRA bug-class adapters |
| 5 | Code Reviewer | Bugs, anti-patterns, architecture drift, 0-10 score |
| 6 | QA Tester | pytest / Jest / JUnit test suites run in a sandbox |
| 7 | Security Auditor | OWASP scan, bandit SAST, secret detection |
| 8 | Performance Optimizer | Big-O analysis, N+1 detection, caching recommendations |
| 9 | Docs Writer | README, API reference, deployment guide |
| 10 | DevOps | Multi-stage Dockerfile, docker-compose, GitHub Actions CI |

```bash
python3 give_work.py "Build a rate-limited REST API for user authentication"
# Product Manager → Architect → Code Generator → Reviewer → QA → Security → Perf → Docs → DevOps
```

### Computer Health — 12 agents

Twelve agents that diagnose real problems on your machine and hand back the exact commands to fix them. Not generic advice — they pull real data from `psutil`, `tccutil`, `netstat`, and your actual file system.

| # | Agent | What it diagnoses |
|---|-------|-------------------|
| 11 | System Optimizer | CPU hogs, thermal throttling, memory pressure |
| 12 | File Organizer | Downloads chaos, duplicates, junk files |
| 13 | Environment Doctor | Broken Python/Node/Docker/PATH — exact fix commands |
| 14 | Security Guard | Open ports, camera/mic permissions, suspicious processes |
| 15 | Network Medic | WiFi drops, DNS failures, high latency |
| 16 | Battery Analyst | Energy vampires, battery health, cycle count |
| 17 | Update Manager | Pending OS/brew/pip/npm updates — safe ordered script |
| 18 | Log Interpreter | Crash logs → plain-English explanation |
| 19 | Privacy Cleaner | Browser cookies, macOS app permission review |
| 20 | Media Librarian | Photo/screenshot rename plan, ffmpeg compression |
| 21 | Backup Sentinel | Time Machine gaps, uncommitted git changes |
| 22 | Context Switcher | Tab overload triage, focus-mode script |

```bash
python3 give_work.py "My laptop fan is always running"
python3 give_work.py --health   # full six-agent scan
```

### Developer Swarm — 12 agents

Narrow, fast, production-quality. Each agent does one thing really well.

| # | Agent | Input → Output |
|---|-------|----------------|
| 23 | Issue Triager | Bug report → severity + duplicate check + suggested owner |
| 24 | Boilerplate Architect | Project description → folder tree + stub files + setup commands |
| 25 | PR Reviewer | Git diff → blockers, suggestions, nitpicks, score |
| 26 | Dependency Sentinel | requirements.txt / package.json → CVEs + outdated packages |
| 27 | Unit Test Writer | Function source → full test file (pytest / Jest / JUnit / Go) |
| 28 | Docstring Generator | Raw code → documented code (Google / Sphinx / JSDoc / Doxygen) |
| 29 | Log Detective | Log dump → error clusters + root cause + fix |
| 30 | SQL Optimizer | Slow query + EXPLAIN → rewrite + CREATE INDEX |
| 31 | Sprint Reporter | Task list → formatted daily standup |
| 32 | Flaky Test Hunter | CI history → ranked flaky tests + root causes |
| 33 | API Contract Auditor | Old + new OpenAPI spec → breaking changes + migration guide |
| 34 | Content Multiplier | Blog post → tweet thread + LinkedIn + changelog + HN title |

### Knowledge Worker — 10 agents

For the non-coding half of the day.

| # | Agent | Input → Output |
|---|-------|----------------|
| 35 | Inbox Gatekeeper | Email batch → urgent flags + drafted replies + unsubscribe list |
| 36 | Meeting Condenser | Transcript → action items + decisions + open questions |
| 37 | Calendar Tetris | Availability windows → ranked meeting slot recommendations |
| 38 | Research Scout | Topic → structured brief with key findings and sources |
| 39 | Trend Monitor | Keywords → trend direction + sentiment + community digest |
| 40 | Data Wrangler | Messy CSV/JSON/PDF → clean normalised records |
| 41 | Expense Auditor | Receipts + card statement → matched pairs + anomaly flags |
| 42 | Reference Checker | Document → verified/flagged facts + accuracy score |
| 43 | Client Liaison | Customer question + KB → accurate answer or escalation |
| 44 | Competitor Tracker | Competitor list → pricing changes + feature updates + hiring signals |

### Expert Diagnostic — 12 agents

Deep-specialist agents for high-friction devops and codebase pain points.

`dependency_rebel` · `merge_conflict_predictor` · `tech_debt_quantifier` · `migration_pilot` · `flaky_test_detective` · `onboarding_mentor` · `incident_responder` · `cloud_cost_auditor` · `certificate_rotator` · `terraform_plan_reviewer` · `dotfile_doctor` · `disk_space_prophet`

### Priority Agents — 5 agents

| # | Agent | What it does |
|---|-------|--------------|
| 57 | Research Agent | Web + GitHub + Stack Overflow research before coding starts |
| 58 | API Design Agent | Complete OpenAPI 3.1 YAML from plain English |
| 59 | DB Agent | Schema DDL + Mermaid ER diagrams + migration scripts |
| 60 | Dependency Agent | CVE scan + license compliance + upgrade scripts |
| 61 | n8n Workflow Agent | Complete importable n8n workflow JSON (35+ node types) |

```bash
npx timps-swarm api-design "SaaS billing API with metered usage and Stripe webhooks"
npx timps-swarm n8n "when GitHub issue is labelled bug, post to Slack and create Jira ticket"
npx timps-swarm audit requirements.txt
```

### New Specialist Agents — 7 agents

| # | Agent | What it does |
|---|-------|--------------|
| 62 | Refactoring Agent | Detect code smells + produce refactored version + diff summary |
| 63 | Test Data Agent | Realistic seed/fixture data for any schema (JSON, CSV, SQL, YAML) |
| 64 | Monitoring Agent | Prometheus metrics + Grafana dashboard JSON + alerting rules |
| 65 | UI/UX Agent | Component spec + code + Storybook story + WCAG accessibility audit |
| 66 | i18n Agent | Extract strings + translation files for multiple locales + RTL flags |
| 67 | Cost Optimizer | Cloud cost estimate + prioritised savings recommendations |
| 68 | Self-Critic Agent | Score any output 1–10, re-run the originating agent until threshold is met |

The Self-Critic Agent is the most valuable one — it closes the quality loop across the entire swarm.

```bash
npx timps-swarm refactor src/auth.py --goals reduce_complexity,extract_functions
npx timps-swarm monitor "FastAPI user service" --slos "p99 < 200ms"
npx timps-swarm critique "$(cat generated/code/api.py)" --agent code_generator --threshold 8
```

---

## CLI

Install globally or use `npx`:

```bash
npm install -g timps-swarm
# or use without installing
npx timps-swarm <command>
```

```
COMMANDS
  fix <path>          Run the full 10-agent SDLC pipeline on a codebase
  research <topic>    Research a topic before writing code
  api-design <desc>   Generate an OpenAPI 3.1 spec from plain English
  db-design <desc>    Design a database schema with DDL + ER diagram
  audit <path>        Dependency CVE scan + license check
  n8n <desc>          Generate a complete n8n workflow JSON
  refactor [path]     Detect code smells + produce refactored version
  test-data <schema>  Generate realistic seed / fixture data
  monitor <service>   Prometheus + Grafana + alerting config
  ui <desc>           UI component spec + code + accessibility audit
  i18n [path]         Extract strings + generate translation files
  cost <arch>         Cloud cost estimate + savings recommendations
  critique <content>  Score output quality, auto-improve until threshold
  health              Run computer health checkup
  providers           Show configured LLM providers and their status
  install-mcp         Auto-configure TIMPS as MCP in Claude Code / Cursor / Windsurf
  start               Start the TIMPS Swarm API server (port 8000)
  mcp                 Start the MCP stdio server directly
```

```bash
# Common examples
npx timps-swarm fix ./my-api --language python
npx timps-swarm research "distributed tracing best practices 2025"
npx timps-swarm refactor src/main.py --goals "reduce_complexity,add_types"
npx timps-swarm test-data '{"id": "uuid", "name": "string", "age": "int"}' --count 50
npx timps-swarm monitor "Node.js payments service" --slos "p99 < 100ms,error_rate < 0.01%"
npx timps-swarm cost "3-tier web app on AWS with RDS and ElastiCache" --provider aws
npx timps-swarm providers   # see which LLMs are currently available
npx timps-swarm health      # diagnose your machine
```

---

## Architecture

```
User / AI coding tool (MCP call or HTTP)
               │
               ▼
    ┌──────────────────────┐
    │  mcp_server/server   │  ← 64 tools over MCP stdio (JSON-RPC 2.0)
    │  src/main.py         │  ← FastAPI REST + WebSocket (port 8000)
    └──────────┬───────────┘
               │
    ┌──────────┴──────────────────────────────┐
    │            Swarm Bridge                  │
    │  (agent lifecycle, task routing, retries)│
    └──┬──────────┬────────────────┬──────────┘
       ▼          ▼                ▼
  SDLC DAG   Health Graph    Specialist Agents
  (10 nodes)  (12 nodes)      (42 direct calls)
       │          │                │
       └──────────┴────────────────┘
                  │
             LLM Router
    ┌─────────────┼───────────────────────────┐
    ▼             ▼         ▼         ▼        ▼
 Gemini      Anthropic   OpenAI    Groq     Ollama
 2.5 Flash    Claude     GPT-4o  Llama 3.3  (local)
                                            + TIMPS-Coder 0.5B
```

**Layer 1 — Computer Manager** (`src/layer1_computer_manager.py`)
Each agent gets an isolated working directory with a CPU cap, memory limit, and disk quota.

**Layer 2 — Swarm Bridge** (`src/layer2_swarm_bridge.py`)
Handles agent lifecycle: spawning, team formation, running the LangGraph DAG, and collecting results.

**Layer 3 — CLI** (`src/layer3_swarm_cli.py`)
Exposes everything through `give_work.py` and the npm CLI.

---

## REST API

```bash
# Health
curl http://localhost:8000/health
curl http://localhost:8000/health/full   # deep check with provider status

# Run the full SDLC pipeline
curl -X POST http://localhost:8000/swarm/run \
  -H "Content-Type: application/json" \
  -d '{"request": "Fix SQL injection in my FastAPI endpoint", "language": "python"}'

# Specialist agents
curl -X POST http://localhost:8000/agents/refactor \
  -H "Content-Type: application/json" \
  -d '{"code": "...", "language": "python", "goals": ["reduce_complexity"]}'

curl -X POST http://localhost:8000/agents/monitoring \
  -H "Content-Type: application/json" \
  -d '{"service_description": "FastAPI auth service", "slos": ["p99 < 200ms"]}'

curl -X POST http://localhost:8000/agents/self-critic \
  -H "Content-Type: application/json" \
  -d '{"content": "...", "agent": "code_generator", "task": "...", "threshold": 8}'

# List available LLM providers
curl http://localhost:8000/providers

# Real-time stream
wscat -c ws://localhost:8000/ws
```

---

## Training Custom Adapters

The Code Generator uses TIMPS-Coder — a 0.5B model with 20 LoRA adapters, one per bug class. Add examples and push — GitHub Actions trains new adapters automatically.

```bash
cp my_bugs.jsonl datasets/custom/
git add datasets/custom/my_bugs.jsonl
git commit -m "feat: 40 new Python async bug examples"
git push origin main
```

The pipeline merges your data, trains 20 adapters in parallel on Apple Silicon (MLX), runs benchmarks, and publishes to HuggingFace. Set `HF_TOKEN` and `HF_REPO_ID` in your repo secrets.

**The 20 bug-class adapters:** `java_npe` · `java_ioob` · `java_concurrent` · `python_keyerror` · `python_typeerror` · `python_recursion` · `python_async` · `python_logic` · `javascript_null` · `javascript_scope` · `javascript_async` · `cpp_memory` · `cpp_bounds` · `go_routine` · `rust_borrow` · `sql_injection` · `xss_vuln` · `auth_bypass` · `performance_slow` · `api_design`

---

## Hardware

| Setup | RAM | Notes |
|-------|-----|-------|
| Minimum | 8 GB | One Ollama model at a time |
| Recommended | 16 GB | All models loaded simultaneously |
| Fine-tuning | 8 GB Apple Silicon | MLX on M1/M2/M3/M4 |
| Scale | 64 GB server | Multiple Ollama instances + load balancer |

To scale to 300+ parallel agents, set `MAX_PARALLEL_AGENTS` in `.env` and use the sharding pattern in `src/layer2_swarm_bridge.py`.

---

## Agent Memory

Every agent run appends to `~/.timps/memory/runs.jsonl`. Before each LLM call, the agent retrieves past runs with overlapping keywords and prepends that context to the prompt — so if System Optimizer fixed your `WindowServer` problem two months ago, it carries that context into the next diagnosis.

```bash
python3 give_work.py --memory   # browse what the agents have learned
```

---

## Security

API key auth is off by default. Turn it on when sharing the server across a team:

```bash
TIMPS_AUTH=1 make up-local

python3 give_work.py --keygen "sandeep-laptop"   # generate a key (shown once)
python3 give_work.py --keys                       # list active keys
python3 give_work.py --revoke timps-sk-xxxx       # revoke a key
```

Keys are stored as SHA-256 hashes in `~/.timps/.secrets` (chmod 600). Pass the key in any MCP tool call:

```json
{ "_api_key": "timps-sk-...", "request": "..." }
```

---

<div align="center">

Built on [TIMPS-Coder](https://github.com/Sandeeprdy1729/timps-coder) — a 0.5B model fine-tuned with 20 LoRA adapters for specific bug patterns.

MIT License

</div>


**44 specialist AI agents. One swarm. Plugs into every tool you already use.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Built on Ollama](https://img.shields.io/badge/Powered_by-Ollama-black?logo=ollama)](https://ollama.ai)
[![MCP Protocol](https://img.shields.io/badge/Protocol-MCP-purple)](https://modelcontextprotocol.io)

</div>

---

I built this because I got tired of context-switching between ten different AI tools, each knowing only a slice of my codebase. TIMPS Swarm is the layer underneath — a local swarm of specialist agents that any coding tool can call into. Claude Code runs it for complex refactors. Cursor grabs it when it needs a security audit. Aider pulls in the test writer. They all share the same 44 agents running on your machine, and nothing leaves your box unless you tell it to.

It started as a computer health tool (12 agents for diagnosing slow laptops, broken Python envs, WiFi issues). Then I added the full 10-agent SDLC pipeline. Then developer workflow agents. Then knowledge-worker agents for the non-coding half of the day. It grew. This is where it landed.

---

## Connect your tools in 30 seconds

```bash
git clone https://github.com/Sandeeprdy1729/timps-swarm
cd timps-swarm
pip install -e .
timps connect all    # auto-configures every tool it finds
timps status         # see what connected
```

That's it. The MCP server starts automatically and shows up in whichever tools are installed.

---

## The tools it plugs into

TIMPS Swarm connects to 22+ AI coding tools. Most integrate via [MCP](https://modelcontextprotocol.io) — one config line and all 44 agents appear automatically.

### CLI Agents

| Tool | Vendor | Integration |
|------|--------|-------------|
| ![Claude Code](https://img.shields.io/badge/Claude_Code-CC785C?style=flat-square&logo=anthropic&logoColor=white) **Claude Code** | Anthropic | MCP stdio — `~/.claude/mcp.json` |
| ![Codex CLI](https://img.shields.io/badge/Codex_CLI-412991?style=flat-square&logo=openai&logoColor=white) **Codex CLI** | OpenAI | MCP stdio — `~/.codex/config.json` |
| ![Gemini CLI](https://img.shields.io/badge/Gemini_CLI-4285F4?style=flat-square&logo=google&logoColor=white) **Gemini CLI** | Google | MCP — `~/.gemini/settings.json` |
| ![OpenCode](https://img.shields.io/badge/OpenCode-2D2D2D?style=flat-square&logo=gnubash&logoColor=white) **OpenCode** | OpenCode | MCP stdio — `~/.config/opencode/` |
| ![Aider](https://img.shields.io/badge/Aider-FF4B4B?style=flat-square&logo=git&logoColor=white) **Aider** | Paul Gauthier | YAML config — `~/.aider.conf.yml` |
| ![Goose](https://img.shields.io/badge/Goose-000000?style=flat-square&logo=block&logoColor=white) **Goose** | Block | Extension — `~/.config/goose/config.yaml` |
| ![Amp](https://img.shields.io/badge/Amp-FF6D00?style=flat-square&logo=sourcegraph&logoColor=white) **Amp** | Sourcegraph | MCP stdio — `~/.amp/mcp.json` |
| ![Warp](https://img.shields.io/badge/Warp-01A4FF?style=flat-square&logo=warp&logoColor=white) **Warp** | Warp | MCP — `~/.warp/mcp_servers.json` |

### IDE Extensions

| Tool | Vendor | Integration |
|------|--------|-------------|
| ![GitHub Copilot](https://img.shields.io/badge/GitHub_Copilot-000000?style=flat-square&logo=github&logoColor=white) **GitHub Copilot** | Microsoft/GitHub | `.vscode/mcp.json` |
| ![Cline](https://img.shields.io/badge/Cline-007ACC?style=flat-square&logo=visualstudiocode&logoColor=white) **Cline** | Cline | `.vscode/mcp.json` |
| ![Continue](https://img.shields.io/badge/Continue-6B4FBB?style=flat-square&logo=continue&logoColor=white) **Continue** | Continue.dev | `~/.continue/config.json` |
| ![Kilo Code](https://img.shields.io/badge/Kilo_Code-2196F3?style=flat-square&logo=code&logoColor=white) **Kilo Code** | Kilo Code | `.vscode/mcp.json` |
| ![Roo Code](https://img.shields.io/badge/Roo_Code-00C853?style=flat-square&logo=visualstudiocode&logoColor=white) **Roo Code** | Roo Code | `.vscode/mcp.json` |
| ![Augment Code](https://img.shields.io/badge/Augment_Code-FF3D00?style=flat-square&logo=augment&logoColor=white) **Augment Code** | Augment | `.vscode/mcp.json` |
| ![Kimi Code](https://img.shields.io/badge/Kimi_Code-7B2FBE?style=flat-square&logo=moonshot&logoColor=white) **Kimi Code** | Moonshot AI | `.vscode/mcp.json` |

### IDE Applications

| Tool | Vendor | Integration |
|------|--------|-------------|
| ![Cursor](https://img.shields.io/badge/Cursor-000000?style=flat-square&logo=cursor&logoColor=white) **Cursor** | Anysphere | MCP — `~/.cursor/mcp.json` |
| ![Windsurf](https://img.shields.io/badge/Windsurf-0090FF?style=flat-square&logo=wind&logoColor=white) **Windsurf** | Cognition | MCP — `~/.codeium/windsurf/mcp_config.json` |
| ![Antigravity](https://img.shields.io/badge/Antigravity-34A853?style=flat-square&logo=google&logoColor=white) **Antigravity** | Google | MCP — `~/.antigravity/mcp.json` |
| ![Zed](https://img.shields.io/badge/Zed-F97316?style=flat-square&logo=zed&logoColor=white) **Zed** | Zed Industries | settings.json lsp/mcp block |

### Cloud / SaaS

| Tool | Vendor | Integration |
|------|--------|-------------|
| ![Devin](https://img.shields.io/badge/Devin-6366F1?style=flat-square&logo=cognition&logoColor=white) **Devin** | Cognition | Team MCP endpoint (cloud-hosted) |
| ![Factory](https://img.shields.io/badge/Factory-374151?style=flat-square&logo=factory&logoColor=white) **Factory** | Factory AI | `droids.yml` MCP tool stanza |
| ![Replit](https://img.shields.io/badge/Replit-F26207?style=flat-square&logo=replit&logoColor=white) **Replit Agent** | Replit | `.replit` mcp_servers block |
| ![Jules](https://img.shields.io/badge/Jules-4285F4?style=flat-square&logo=googlelabs&logoColor=white) **Jules** | Google Labs | GitHub App webhook integration |
| ![v0](https://img.shields.io/badge/v0-000000?style=flat-square&logo=vercel&logoColor=white) **v0** | Vercel | Next.js API route wrapper |

Run `timps connect all` and the connector auto-detects what's installed and writes the right config for each tool. For cloud tools that can't be auto-configured, it prints the manual steps.

---

## Quick start

**Docker (recommended)**

```bash
git clone https://github.com/Sandeeprdy1729/timps-swarm
cd timps-swarm
make all
open http://localhost:3000
```

**Local**

```bash
make install

# Pull the models once (~16 GB total)
ollama serve &
ollama pull qwen2.5:14b && ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b && ollama pull qwen2.5:3b

make up-local
make ui   # open the dashboard in a second terminal
```

---

## What it does

There are four swarms running in parallel, each with a distinct purpose.

### The SDLC pipeline

Give it a task and ten agents sequence through the whole thing. Product Manager writes the requirements. Architect designs the system. Code Generator implements using TIMPS-Coder (our 0.5B fine-tuned model with 20 LoRA adapters). Reviewer checks it. QA writes the test suite. Security Auditor scans for OWASP issues. Performance Optimizer profiles it. Docs Writer generates the README. DevOps produces the Dockerfile and CI/CD config. The whole pipeline runs as a LangGraph DAG with dependency tracking and automatic retries.

```bash
python3 give_work.py "Build a rate-limited REST API for user authentication"
# → Requirements → Architecture → Code → Review → Tests → Security → Perf → Docs → Docker
```

### The computer health swarm

Twelve agents that diagnose real problems on your machine and give you the exact commands to fix them. Not generic advice — they pull real data. System Optimizer runs `psutil`. Environment Doctor checks your actual `$PATH` and virtual environments. Network Medic pings Cloudflare and traces your DNS. Security Guard reads macOS TCC permissions from `tccutil`.

```bash
python3 give_work.py "My laptop fan is always running"
python3 give_work.py "My Python virtualenv is broken"
python3 give_work.py "Why is my WiFi dropping every 20 minutes?"
python3 give_work.py --health   # full six-agent scan
```

### The developer swarm

Twelve atomic developer tasks — each one narrow, fast, and production-quality.

| Agent | What it does |
|-------|-------------|
| Issue Triager | Reads a bug report, assigns severity, flags duplicates, suggests owner |
| Boilerplate Architect | Scaffolds a new project: folder tree + stub files + setup commands |
| PR Reviewer | Reviews a diff: blockers, suggestions, nitpicks, 0-10 score |
| Dependency Sentinel | CVE scan + outdated package detection on any manifest file |
| Unit Test Writer | Generates edge-case test suites (pytest, Jest, JUnit, Go testing) |
| Docstring Generator | Inserts Google/Sphinx/NumPy/JSDoc/Doxygen docs without changing logic |
| Log Detective | Clusters error patterns, finds root cause, suggests the fix |
| SQL Optimizer | Rewrites slow queries + generates CREATE INDEX SQL |
| Sprint Reporter | Turns task lists into a formatted daily standup in seconds |
| Flaky Test Hunter | Finds non-deterministic tests from CI history |
| API Contract Auditor | Diffs OpenAPI specs, flags breaking changes, writes migration guide |
| Content Multiplier | One blog post → tweet thread + LinkedIn post + changelog + HN title |

### The knowledge worker swarm

Ten agents for the non-coding half of the day. Email, meetings, research, data, competitors.

| Agent | What it does |
|-------|-------------|
| Inbox Gatekeeper | Triages a batch of emails: urgent flag, auto-draft replies, unsubscribe targets |
| Meeting Condenser | Transcript → action items with owners, decisions, open questions |
| Calendar Tetris | Finds the best slot for 3+ people without the email back-and-forth |
| Research Scout | Deep dives a topic and returns a structured brief with sources |
| Trend Monitor | Watches HN/Reddit/GitHub for keyword spikes and sentiment shifts |
| Data Wrangler | Cleans messy CSV/PDF/JSON data into normalised records |
| Expense Auditor | Matches receipts to card transactions, flags policy violations |
| Reference Checker | Verifies factual claims in a document against web sources |
| Client Liaison | Answers customer FAQs using your knowledge base, escalates when unsure |
| Competitor Tracker | Monitors competitor pricing, features, and job postings |

---

## Architecture

Three layers sit between the user and the agents doing the work.

```
User / AI coding tool (MCP call)
           │
           ▼
    mcp_server/server.py  ← 44 tools exposed over MCP stdio
           │
    ┌──────┴──────┐
    │ swarm_bridge │  ← agent lifecycle, task routing, retries
    └──────┬──────┘
           │
    ┌──────┼────────────────────────────────┐
    ▼      ▼                                ▼
SDLC DAG  Computer Health Graph      Developer & Knowledge Agents
(10 nodes) (12 nodes, keyword-routed)  (22 functions, direct calls)
    │           │                           │
    └───────────┴───────────────────────────┘
                    LLM Router
           (qwen2.5:14b / 7b / 3b / TIMPS-Coder)
```

**Layer 1 — Computer Manager** (`src/layer1_computer_manager.py`) gives every agent its own isolated working directory with a CPU cap, memory limit, and disk quota.

**Layer 2 — Swarm Bridge** (`src/layer2_swarm_bridge.py`) handles agent lifecycle: spawning, team formation, running the LangGraph DAG.

**Layer 3 — CLI** (`src/layer3_swarm_cli.py`) exposes everything through `give_work.py` and the `timps` shell shim.

**TIMPS Swarm v2.0 now includes 56 agents** — the original 44 plus 5 new priority agents and an expanded LLM provider layer with Groq, Gemini, Anthropic, and OpenAI support alongside the local Ollama stack.

### New in v2.0: Priority Agents (5 agents)

| # | Agent | What it does |
|---|-------|--------------|
| 45 | Research Agent | Web + GitHub + Stack Overflow research — synthesises into a structured brief before coding starts |
| 46 | API Design Agent | Generates complete OpenAPI 3.1 YAML specs from plain-English descriptions |
| 47 | DB Agent | Designs schemas with DDL, Mermaid ER diagrams, migration scripts, and query templates |
| 48 | Dependency Agent | CVE scanning, license compliance, upgrade scripts — runs `pip-audit`, `npm audit`, `cargo audit` |
| 49 | n8n Workflow Agent | Generates complete importable n8n workflow JSON (35+ node types, webhook/cron/email triggers) |

### New in v2.0: LLM Provider Layer

Priority chain: **MCP Sampler → Gemini 2.5 Flash → Anthropic Claude → OpenAI GPT → Groq (Llama 3.3 70B) → Ollama (local) → TIMPS-Coder 0.5B**

Set any combination of these env vars — the system uses the first available:

```bash
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GROQ_API_KEY=...
# No key needed for Ollama or TIMPS-Coder (on-device)
```

### New in v2.0: CLI + GitHub Actions

```bash
# Install the npm CLI
npm install -g timps-swarm
# or
npx timps-swarm fix "build a rate-limited auth API in Python"
npx timps-swarm research "best practices for distributed tracing"
npx timps-swarm api-design "SaaS billing API with metered usage"
npx timps-swarm n8n "when GitHub issue is labelled bug, post to Slack and create Jira ticket"
npx timps-swarm audit requirements.txt
npx timps-swarm install-mcp   # auto-configure Claude Code, Cursor, Windsurf
```

Use in GitHub Actions (reusable workflow):

```yaml
jobs:
  generate:
    uses: Sandeeprdy1729/timps-swarm/.github/workflows/timps-swarm.yml@main
    with:
      task: "Build a microservice for JWT authentication"
      language: python
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

---

## MCP setup (manual)

If you don't want to use `timps connect all`, here's the config for each tool.

**Claude Code** — `~/.claude/mcp.json`
```json
{ "mcpServers": { "timps-swarm": { "command": "timps-mcp" } } }
```

**GitHub Copilot in VS Code** — `.vscode/mcp.json` (already in this repo)
```json
{ "mcp": { "servers": { "timps-swarm": { "type": "stdio", "command": "timps-mcp" } } } }
```

**Cursor / Windsurf** — `~/.cursor/mcp.json` or `~/.codeium/windsurf/mcp_config.json`
```json
{ "mcpServers": { "timps-swarm": { "type": "stdio", "command": "timps-mcp" } } }
```

**Aider** — `~/.aider.conf.yml`
```yaml
mcp-servers:
  timps-swarm:
    command: timps-mcp
    type: stdio
```

**Goose** — `~/.config/goose/config.yaml`
```yaml
extensions:
  - name: timps-swarm
    type: stdio
    cmd: timps-mcp
    enabled: true
```

**Continue** — `~/.continue/config.json`
```json
{ "mcpServers": [{ "name": "timps-swarm", "command": "timps-mcp" }] }
```

**Zed** — `~/.config/zed/settings.json`
```json
{ "assistant": { "mcp_servers": { "timps-swarm": { "command": "timps-mcp" } } } }
```

Once configured, the tools show up automatically. A few things you can ask from within any of them:

```
"Triage this bug report" → Issue Triager assigns severity and suggests an owner
"Why is my laptop slow?" → System Optimizer gives you the exact processes to kill
"Write tests for this function" → Unit Test Writer generates full edge-case coverage
"Summarise this meeting" → Meeting Condenser extracts actions, decisions, and blockers
"Scan this requirements.txt for CVEs" → Dependency Sentinel runs a full security audit
```

---

## The agents in full

### SDLC pipeline (10 agents)

| # | Agent | Model | What it does |
|---|-------|-------|--------------|
| 1 | Orchestrator | qwen2.5:14b | Decomposes requests into a task DAG, routes work, handles retries |
| 2 | Product Manager | qwen2.5:7b | Writes PRDs and acceptance criteria |
| 3 | Architect | qwen2.5:14b | System design, API contracts, data models |
| 4 | Code Generator | TIMPS-Coder + qwen2.5-coder:7b | Implementation and bug fixes using 20 LoRA adapters |
| 5 | Code Reviewer | qwen2.5:7b | Bugs, anti-patterns, architecture drift |
| 6 | QA Tester | qwen2.5-coder:7b | pytest and integration tests, run in sandbox |
| 7 | Security Auditor | qwen2.5:7b | OWASP scan, bandit SAST, secrets detection |
| 8 | Performance Optimizer | qwen2.5:7b | Big-O analysis, N+1 detection, caching recommendations |
| 9 | Docs Writer | qwen2.5:3b | README, API reference, deployment guide |
| 10 | DevOps | qwen2.5:7b | Multi-stage Dockerfile, docker-compose, GitHub Actions |

### Computer health agents (12 agents)

| # | Agent | What it diagnoses and fixes |
|---|-------|-----------------------------|
| 11 | System Optimizer | CPU hogs, startup bloat, thermal throttling, memory pressure |
| 12 | File Organizer | Downloads folder chaos, duplicates, large junk files |
| 13 | Environment Doctor | Broken Python/Node/Docker/PATH — generates exact fix commands |
| 14 | Security Guard | Open ports, camera and mic permissions, suspicious background processes |
| 15 | Network Medic | WiFi drops, DNS failures, high latency |
| 16 | Battery Analyst | Energy vampire processes, battery health, cycle count |
| 17 | Update Manager | Pending OS/brew/pip/npm updates — safe ordered update script |
| 18 | Log Interpreter | Reads crash logs, explains them in plain English |
| 19 | Privacy Cleaner | Browser cookie audit, macOS app permission review |
| 20 | Media Librarian | Photo and screenshot rename plan, ffmpeg compression suggestions |
| 21 | Backup Sentinel | Time Machine gaps, uncommitted git changes, at-risk files |
| 22 | Context Switcher | Tab overload triage, focus-mode script |

### Developer swarm agents (12 agents)

| # | Agent | Input → Output |
|---|-------|----------------|
| 23 | Issue Triager | Bug report text → severity label, duplicate check, suggested owner |
| 24 | Boilerplate Architect | Project description → folder tree + stub files + setup commands |
| 25 | PR Reviewer | Git diff → blockers, suggestions, nitpicks, 0-10 score |
| 26 | Dependency Sentinel | requirements.txt / package.json / go.mod → CVEs + outdated packages |
| 27 | Unit Test Writer | Function source → full test file (pytest / Jest / JUnit / Go) |
| 28 | Docstring Generator | Raw code → documented code (Google / Sphinx / JSDoc / Doxygen) |
| 29 | Log Detective | Log dump → error clusters + root cause + fix suggestion |
| 30 | SQL Optimizer | Slow query + EXPLAIN → rewrite + CREATE INDEX SQL |
| 31 | Sprint Reporter | Task lists → formatted daily standup markdown |
| 32 | Flaky Test Hunter | CI history → ranked flaky tests + causes + fixes |
| 33 | API Contract Auditor | Old + new OpenAPI spec → breaking changes + migration guide |
| 34 | Content Multiplier | Long-form post → tweet thread + LinkedIn + changelog + HN title |

### Knowledge worker agents (10 agents)

| # | Agent | Input → Output |
|---|-------|----------------|
| 35 | Inbox Gatekeeper | Email batch → urgent flags + drafted replies + unsubscribe list |
| 36 | Meeting Condenser | Meeting transcript → action items + decisions + open questions |
| 37 | Calendar Tetris | Availability windows → ranked meeting slot recommendations |
| 38 | Research Scout | Topic + depth → structured brief with key findings and sources |
| 39 | Trend Monitor | Keywords → trend direction + sentiment + community digest |
| 40 | Data Wrangler | Messy CSV/JSON/PDF → clean normalised records + quality score |
| 41 | Expense Auditor | Receipts + card statement → matched pairs + anomaly flags |
| 42 | Reference Checker | Document with claims → verified/flagged facts + accuracy score |
| 43 | Client Liaison | Customer question + KB → accurate answer or escalation |
| 44 | Competitor Tracker | Competitor list → pricing changes + feature updates + hiring signals |

### Expert diagnostic agents (12 agents)

These are the deep-specialist agents for high-friction devops and codebase pain points. Call them through `timps_delegate` or directly from any MCP client.

`dependency_rebel` · `merge_conflict_predictor` · `tech_debt_quantifier` · `migration_pilot` · `flaky_test_detective` · `onboarding_mentor` · `incident_responder` · `cloud_cost_auditor` · `certificate_rotator` · `terraform_plan_reviewer` · `dotfile_doctor` · `disk_space_prophet`

---

## CLI reference

```bash
# SDLC pipeline — runs all 10 agents in sequence
python3 give_work.py "Write a REST API for user authentication"
python3 give_work.py "Create a background job queue" -l python

# Spawn specific agents only
python3 give_work.py --spawn code_generator qa_tester "Write code and test it"

# Computer health
python3 give_work.py "My laptop fan is always running"
python3 give_work.py --health   # full six-agent scan

# Developer swarm (called via give_work or MCP)
python3 give_work.py --triage "NullPointerException in AuthService.java line 87"
python3 give_work.py --tests src/auth.py
python3 give_work.py --review path/to/diff.patch

# Tool connector
timps connect all               # configure every detected tool
timps connect cursor            # configure a specific tool
timps connect all --dry-run     # preview only
timps status                    # see what's connected

# Memory and auth
python3 give_work.py --memory
python3 give_work.py --keygen "team-key"
python3 give_work.py --keys
python3 give_work.py --revoke timps-sk-xxxx
```

---

## Agent memory

Every agent run appends to `~/.timps/memory/runs.jsonl`. Before each LLM call, the agent queries that log for past runs with overlapping keywords and prepends them to the prompt. If System Optimizer fixed your `WindowServer` problem last month, it remembers that context going into the next run.

```bash
python3 give_work.py --memory   # browse what the agents have learned
```

---

## API key auth

Optional. Off by default. Turn it on when sharing the server with a team.

```bash
TIMPS_AUTH=1 make up-local

# Generate a key
python3 give_work.py --keygen "sandeep-laptop"
# → timps-sk-a9073c90b94...  (shown once, never stored raw)

python3 give_work.py --keys
python3 give_work.py --revoke timps-sk-a907

# Pass the key in MCP tool calls
{ "_api_key": "timps-sk-...", "request": "..." }
```

Keys are stored as SHA-256 hashes in `~/.timps/.secrets` (chmod 600).

---

## REST API

```bash
# Health check
curl http://localhost:8000/health

# Run a task
curl -X POST http://localhost:8000/swarm/run \
  -H "Content-Type: application/json" \
  -d '{"request": "Fix SQL injection in my FastAPI endpoint", "language": "python"}'

# Poll status
curl http://localhost:8000/swarm/status?run_id=abc12345

# Real-time stream
wscat -c ws://localhost:8000/ws
```

---

## Training your own adapters

The Code Generator uses TIMPS-Coder — a 0.5B model fine-tuned with 20 LoRA adapters, one per bug class. Add examples and push — GitHub Actions trains new adapters automatically.

```bash
# Add examples
cp my_bugs.jsonl datasets/custom/
git add datasets/custom/my_bugs.jsonl
git commit -m "feat: 40 new Python async bug examples"
git push origin main
```

The pipeline merges your data, trains 20 adapters in parallel on Apple Silicon (MLX), runs benchmarks, and publishes to HuggingFace and GitHub Releases. Set `HF_TOKEN` and `HF_REPO_ID` in your repo secrets to enable the publish step.

**The 20 adapters:** `java_npe` · `java_ioob` · `java_concurrent` · `python_keyerror` · `python_typeerror` · `python_recursion` · `python_async` · `python_logic` · `javascript_null` · `javascript_scope` · `javascript_async` · `cpp_memory` · `cpp_bounds` · `go_routine` · `rust_borrow` · `sql_injection` · `xss_vuln` · `auth_bypass` · `performance_slow` · `api_design`

---

## Hardware requirements

| Setup | RAM | Notes |
|-------|-----|-------|
| Minimum | 8 GB | One Ollama model at a time |
| Recommended | 16 GB | All models loaded simultaneously |
| Training | 8 GB Apple Silicon | MLX fine-tuning on M1/M2/M3 |
| Scale | 64 GB server | Multiple Ollama instances behind a load balancer |

To scale to 300+ parallel agents: edit `MAX_PARALLEL_AGENTS` in `.env` and use the sharding pattern in `src/layer2_swarm_bridge.py`.

---

Built on [TIMPS-Coder](https://github.com/Sandeeprdy1729/timps-coder) — a 0.5B model fine-tuned with 20 LoRA adapters for specific bug patterns.

MIT. 
