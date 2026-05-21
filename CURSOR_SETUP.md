# TIMPS Swarm — Cursor Setup

Connect TIMPS Swarm's 56 AI agents to Cursor as an MCP server.

## Quick Setup

### 1. Add to Cursor's global MCP config

Open the file `~/.cursor/mcp.json` (create it if it doesn't exist) and add:

```json
{
  "mcpServers": {
    "timps-swarm": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/timps-swarm",
      "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "GEMINI_API_KEY": "your-key-here",
        "ANTHROPIC_API_KEY": "your-key-here",
        "OPENAI_API_KEY": "your-key-here",
        "GROQ_API_KEY": "your-key-here"
      }
    }
  }
}
```

Replace `/path/to/timps-swarm` with the actual repo path.

### 2. Or use the auto-installer

```bash
# Start TIMPS server
cd /path/to/timps-swarm
python -m uvicorn src.main:app --port 8000 &

# Auto-configure Cursor
curl -sf -X POST http://localhost:8000/mcp/install \
  -H "Content-Type: application/json" \
  -d '{"tool_id": "cursor"}'
```

### 3. Restart Cursor

Cursor will pick up the new MCP server on the next launch (or use **Reload Window**).

## Available Tools in Cursor

Once connected, you can use these tools directly from Cursor's AI chat:

| Tool | Description |
|------|-------------|
| `timps_run_swarm` | Full SDLC pipeline for any task |
| `timps_research_agent` | Research best practices & context |
| `timps_api_design_agent` | Generate OpenAPI 3.1 specs |
| `timps_db_agent` | Design DB schemas with migrations |
| `timps_dependency_agent` | CVE + license audit |
| `timps_n8n_workflow_agent` | Build n8n automation workflows |
| `timps_full_checkup` | Computer health scan |
| `timps_list_providers` | Show active LLM providers |
| `timps_connect_tools` | Connect to GitHub, Jira, Slack, etc. |

## Example Usage in Cursor Chat

```
@timps-swarm timps_run_swarm Build a REST API for a todo app in Python with FastAPI
```

```
@timps-swarm timps_api_design_agent Design an API for a multi-tenant SaaS billing system with usage-based pricing
```

## Environment Variables

Set these in `~/.cursor/mcp.json` `env` block or in your shell:

```bash
export GEMINI_API_KEY=...       # Google Gemini (recommended — free tier)
export ANTHROPIC_API_KEY=...    # Claude (optional)
export OPENAI_API_KEY=...       # GPT-4 (optional)
export GROQ_API_KEY=...         # Groq fast inference (optional — very fast)
```

Priority order: MCP sampler → Gemini → Anthropic → OpenAI → Groq → Ollama (local) → TIMPS-Coder (on-device)
