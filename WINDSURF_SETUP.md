# TIMPS Swarm — Windsurf Setup

Connect TIMPS Swarm's 56 AI agents to Windsurf (Codeium) as an MCP server.

## Quick Setup

### 1. Open Windsurf MCP Settings

In Windsurf: **Settings → AI → MCP Servers → Add Server**

Or manually edit `~/.windsurf/mcp.json`:

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

### 2. Or use the auto-installer

```bash
cd /path/to/timps-swarm
python -m uvicorn src.main:app --port 8000 &
npx timps-swarm install-mcp
```

### 3. Restart Windsurf

Use **Reload Window** or restart the application.

## Available Agents

The same 56-agent suite is available in Windsurf. Ask Cascade:

```
Use timps_run_swarm to build a microservice for user authentication with JWT, refresh tokens, and rate limiting
```

## Environment Variables

```bash
export GEMINI_API_KEY=...
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GROQ_API_KEY=...
```

## Troubleshooting

1. **MCP not detected** — ensure `cwd` is the absolute path to the repo and Python can import `mcp_server.server`
2. **Ollama errors** — run `ollama pull qwen2.5-coder:7b` before starting
3. **No API keys** — the system falls back to local Ollama automatically; set GEMINI_API_KEY for best results
