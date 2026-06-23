# AGENTS.md

Guidance for OpenCode sessions working in the TIMPS Swarm monorepo. Only signals you would miss from a quick read of the README are listed here.

## Layout

- `src/main.py` — FastAPI server (port 8000). Lazy-imports the LangGraph `_graph` to keep tests/imports cheap. Also exposes `GET /mcp/tools` and `POST /mcp/tools/call` so the Node.js MCP proxy can reach every tool over HTTP.
- `src/agents.py`, `src/more_agents.py`, `src/expert_agents.py`, `src/developer_swarm_agents.py`, `src/intelligence_agents.py`, `src/aiml_agents.py`, `src/knowledge_swarm_agents.py`, `src/computer_agents.py`, `src/priority_agents.py` — flat agent modules.
- `src/aiml/`, `src/business/`, `src/domain/`, `src/emerging/`, `src/india/`, `src/infra/`, `src/intelligence/`, `src/nextgen/`, `src/phase7/` — subpackages of specialist agents. Each is a sibling flat namespace; import as `from src.nextgen.foo import foo`.
- `src/layer1_computer_manager.py`, `src/layer2_swarm_bridge.py`, `src/layer3_swarm_cli.py` — the 3-layer runtime (per-agent compute isolation, swarm bridge/orchestration, CLI shim).
- `src/observer.py` — TaskObserver: sliding-window call buffer, args fingerprinting, repetitive-pattern detection; fires `spawn_callbacks` when a tool is invoked ≥3 times with similar args.
- `src/auto_spawner.py` — AutoSpawner: wired to observer callbacks, maps MCP tool names → AgentRole, spawns sub-agent batches via `layer2_swarm_bridge`.
- `src/context_sharing.py` — ContextSharer: captures git status, recent diff, file tree, framework detection, test examples, style config, and open editor files for injection into sub-agent contexts.
- `src/llm_router.py` is a thin façade — provider logic lives in `src/providers/*.py` (gemini, anthropic, openai, groq, ollama, mcp_sampler, timps, null). All providers use `requests.Session` with connection pooling (`HTTPAdapter pool_maxsize=50`) and retry-on-status (429, 5xx).
- `mcp_server/server.py` — MCP stdio server (JSON-RPC 2.0). Uses a `ThreadPoolExecutor(max_workers=10)` to run tool handlers in background threads, sending `notifications/progress` messages to the client. Registers an MCP-sampling callback that the LLM router prefers over cloud providers when the host supports it. Defines `TOOLS` (the 160-tool catalogue) and `_TOOL_HANDLERS` (name → lambda). The FastAPI server lazy-imports both for `/mcp/tools` and `/mcp/tools/call`.
- `cli/` — the published npm package (`@timps-swarm/cli`-style). Layout: `bin/timps-swarm.js`, `lib/local-audit.js`, `lib/agents-manifest.js` (64 agent metadata), `lib/agent-files.js` (sub-agent `.md` writer/remover), `lib/mcp-proxy.js` (Node.js JSON-RPC 2.0 stdio proxy for `mcp` when Python repo missing), `tools/generate-manifest.js` (Python-AST re-sync). Has its own `package.json`, `node_modules/`, `package-lock.json`. `postinstall` runs `bin/timps-swarm.js install-mcp` which writes 1) the `timps-swarm` MCP server entry into 9 IDE config files (with `env:` block forwarding `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `TIMPS_API_URL`, `OLLAMA_HOST`, `REDIS_URL`) and 2) one sub-agent `.md` file per TIMPS tool into `~/.claude/agents/`, `./.claude/agents/`, and `~/.codex/agents/`. `timps-swarm uninstall-mcp` reverses both. Add `--no-sub-agents` to install-mcp to skip the `.md` files.
- `dashboard/` — React UI (react-scripts). Talks to the API via `proxy: http://localhost:8000` and a WebSocket at `ws://localhost:8000/ws`.
- Top-level Python entry points: `give_work.py` (SDLC/health dispatch), `timps_cli.py` (unified `timps` CLI), `timps_daemon.py` (context-keeper daemon), `timps_doctor.py` (env diagnostics).
- `generated/` — runtime artefacts (created on first run; mounted as `/app/generated` in Docker).
- `dist/` — built wheel/sdist from `pyproject.toml` (do not edit by hand).

## Build / run

- Dev API: `make up-local` (alias for `DEV=true PORT=8000 python3 -m src.main`) or just `python3 -m src.main`.
- Full stack: `make up` (Ollama + Redis + sandbox + swarm-api + dashboard via `docker-compose.yml`). First-run pulls models via `scripts/pull-models.sh` (20–60 min).
- MCP stdio (full Python server, supports MCP sampling): `python3 -m mcp_server.server` (the `timps-mcp` console script) or `timps-swarm mcp --repo <path>`.
- MCP stdio (Node.js fallback, when the Python repo is unreachable): `timps-swarm mcp` falls back to `cli/lib/mcp-proxy.js`, a JSON-RPC 2.0 stdio server that proxies `tools/list` and `tools/call` to `${TIMPS_API_URL:-http://localhost:8000}/mcp/tools` and `/mcp/tools/call`. Point at a remote API with `TIMPS_API_URL=https://your-server timps-swarm mcp`.
- Dashboard only: `make ui` (runs `npm install` then `npm start` in `dashboard/`). WebSocket URL is hard-coded via `REACT_APP_WS_URL=ws://localhost:8000/ws` in the npm `start` script.
- Health: `curl http://localhost:8000/health` (and `/health/full` for provider status). Interactive docs at `/docs`.
- Smoke-test the MCP server end-to-end: `python3 mcp_server/test_server.py` (spawns the server as a subprocess and exchanges JSON-RPC).
- Smoke-test computer allocation: `python3 test_computer_allocation.py` (top-level standalone script, not pytest).

## Tests, lint, typecheck

- **`make test` is currently a no-op** — `pyproject.toml` sets `testpaths = ["tests"]` and the Makefile runs `pytest tests/`, but **the `tests/` directory does not exist**. Add it before relying on `make test`. Existing runnable test scripts are top-level (`test_all_adapters.py`, `test_computer_allocation.py`, `mcp_server/test_server.py`).
- No CI runs tests. `.github/workflows/timps-swarm.yml` only spins up the API and POSTs `/swarm/run`. `pages.yml` deploys `index.html` to GitHub Pages on pushes to `main` only when that file or `CNAME` change.
- Lint: `ruff` is configured in `pyproject.toml` (line-length 100, target py310) but there is no `make lint` target — invoke `ruff check .` directly. `black` is in the dev extras; no formatter is enforced in CI.
- Typecheck: none configured.

## Environment

Required for full functionality; first one set wins in `src/llm_router.py`:
- `GEMINI_API_KEY` (recommended — free tier), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY` (priority order).
- `OLLAMA_HOST` (default `http://localhost:11434`) and `TIMPS_MODEL_PATH` (default `sandeeprdy1729/TIMPS-Coder-0.5B`).
- `TIMPS_MAX_AGENT_WORKERS` (default `10`) — thread pool size in `mcp_server/server.py` for concurrent tool execution.
- `REDIS_URL` (default `redis://localhost:6379/0`) — falls back to an in-memory dict silently when Redis is down (`src/main.py:_runs_fallback`).
- `GENERATED_DIR` (default `generated`) — where agents write artefacts.
- `TIMPS_AUTH=1` enables API key auth; keys are SHA-256 hashed in `~/.timps/.secrets` (chmod 600).
- `LOG_LEVEL` (default `INFO`).

## Conventions

- Agent function signature: `def agent(args: dict) -> dict`. Helpers in `src/_helpers.py` (`_ts`, `_llm`, `_strip_fences`, `_save`, `_run`) are imported with a leading underscore but are the de-facto shared API.
- New agent modules export a function matching the file name and are registered in the package `__init__.py`'s `AGENTS`/`*_AGENTS` dict; the MCP server auto-discovers tools from those dicts.
- **Adding a new sub-agent file** after editing `mcp_server/server.py:TOOLS`: run `node cli/tools/generate-manifest.js` to regenerate `cli/lib/agents-manifest.js` (the parser fails loudly on unmapped tools so you must also add a category in the manifest switch). The `npm install` postinstall will then write the new `.md` for existing installs.
- CLI helpers in `cli/bin/timps-swarm.js`: `findRepoPython()` (priority: `$TIMPS_REPO` env → walk up CWD → `~/timps-swarm` → `~/Desktop/timps-swarm` → `/opt/timps-swarm` → `npm config get prefix`/lib/node_modules/timps-swarm), `pythonBin()` (probes `python3` first, falls back to `python`), `serverDownError(err)` (detects `ECONNREFUSED` / `fetch failed` / `request to … failed` and prints start-server instructions).
- The 10-agent SDLC graph is wired in `src/graph.py`; includes a `parallel_executor_node` that uses `ThreadPoolExecutor` + `asyncio.gather()` to run independent agent tasks concurrently. `src/agent_kernel.py` is the higher-level "delegate a goal" planner (planner → blackboard → supervisor → executor → reporter). The blackboard lives at `generated/kernel/`.
- `give_work.py` routes between the SDLC pipeline and the computer-health pipeline by keyword match — adding a new health domain requires extending the `_DOMAINS` list in `give_work.py`.
- Python ≥ 3.10 (`pyproject.toml`); CI pins 3.11.
- The base model for adapter fine-tuning is `Qwen/Qwen2.5-Coder-0.5B-Instruct` (see `Makefile` `BASE_MODEL`). 20 LoRA adapters live under `adapters/`. MLX (Apple Silicon) is the documented path; CUDA torch or plain torch also supported.

## Packaging

- `pyproject.toml` defines three console scripts: `timps-mcp` → `mcp_server.server:run_server`, `timps` → `timps_cli:main`, `timps-swarm` → `give_work:main`.
- `[tool.setuptools.packages.find]` includes only `src*` and `mcp_server*`. The top-level `give_work.py`, `timps_cli.py`, `timps_daemon.py`, `timps_doctor.py` are picked up via the `project.scripts` entries only — they are not packaged as a module.
- The npm package lives in `cli/`, not the repo root. `package.json` in `cli/` declares `"type": "module"`.

## Git / repo quirks

- `.gitignore` covers `__pycache__/`, `*-node_modules/`, `.DS_Store`, `.env`, and runtime artefacts; the tracked `cli/node_modules/` was removed in `267e3c11`.
- `dashboard/node_modules/`, `cli/node_modules/`, and `dist/` are tracked or untracked depending on history. Don't `git clean -dfx` blindly.
- Branch-protection / PR / release expectations are not codified anywhere in the repo (no `CONTRIBUTING.md`, no PR template). If asked, default to conventional commits, PRs against `main`.

## Existing instruction sources worth knowing about

- `README.md` — user-facing quick start, CLI command list, agent catalogue, REST examples.
- `cli/README.md` — npm CLI command reference and `TIMPS_API_URL` semantics.
- `CURSOR_SETUP.md`, `WINDSURF_SETUP.md` — per-IDE MCP config snippets (the npm `install-mcp` command supersedes these).
- `install.sh` — universal one-shot installer; auto-registers MCP for every detected IDE.
- `.claude/mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json` are checked-in local MCP configs that point at this repo — keep them in sync if you rename or relocate the project.
