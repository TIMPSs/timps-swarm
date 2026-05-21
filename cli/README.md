# timps-swarm CLI

> 56 AI agents for code generation, API design, database design,
> dependency scanning, and n8n workflow generation — in one command.

## Install

```bash
npm install -g timps-swarm
# or run without installing:
npx timps-swarm <command>
```

**Requires:** Node 18+ and a running TIMPS Swarm server (see below).

## Start the server

```bash
# Clone and start
git clone https://github.com/Sandeeprdy1729/timps-swarm
cd timps-swarm
pip install -e .
python -m uvicorn src.main:app --port 8000 --reload

# Or use the CLI itself (auto-starts if needed)
npx timps-swarm start
```

Set `TIMPS_API_URL` to point to a remote instance (default: `http://localhost:8000`).

## Commands

### `fix` — Run the full SDLC swarm

```bash
npx timps-swarm fix "build a REST API for a todo app"
npx timps-swarm fix ./src --language typescript
```

### `research` — Research Agent

```bash
npx timps-swarm research "best practices for distributed tracing in 2025"
npx timps-swarm research "OpenTelemetry vs Jaeger" --depth deep
```

### `api-design` — OpenAPI 3.1 spec generator

```bash
npx timps-swarm api-design "multi-tenant SaaS billing API with metered usage"
npx timps-swarm api-design "e-commerce cart API" --auth jwt --style rest
```

### `db-design` — Database schema designer

```bash
npx timps-swarm db-design "multi-tenant user and subscription system"
npx timps-swarm db-design "IoT sensor time-series store" --engine postgresql --migration-tool alembic
```

### `audit` — Dependency vulnerability scanner

```bash
npx timps-swarm audit requirements.txt
npx timps-swarm audit package.json --ecosystem node
npx timps-swarm audit                              # auto-detects from CWD
```

### `n8n` — n8n workflow generator

```bash
npx timps-swarm n8n "when GitHub issue is labeled bug, post to Slack #alerts and create Jira ticket"
npx timps-swarm n8n "daily Postgres → BigQuery sync at 2am UTC" --trigger cron --output workflow.json
```

### `health` — Computer health checkup

```bash
npx timps-swarm health
```

### `providers` — Show LLM providers

```bash
npx timps-swarm providers
```

### `mcp` — Start the MCP stdio server

```bash
npx timps-swarm mcp
```

For use in `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "timps-swarm": {
      "command": "npx",
      "args": ["timps-swarm", "mcp"]
    }
  }
}
```

### `install-mcp` — Auto-configure MCP in AI tools

```bash
npx timps-swarm install-mcp              # configure Claude Code + Cursor
npx timps-swarm install-mcp --tool cursor
npx timps-swarm install-mcp --dry-run    # preview only
```

## Environment Variables

| Variable | Description |
| :--- | :--- |
| `TIMPS_API_URL` | TIMPS server URL (default: `http://localhost:8000`) |
| `GEMINI_API_KEY` | Google Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GROQ_API_KEY` | Groq API key (fast Llama 3.3 70B) |

## License

MIT
