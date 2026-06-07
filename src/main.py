"""
FastAPI application — entry point for the TIMPS Swarm.

Endpoints:
  POST /swarm/run        — Start a new swarm execution
  GET  /swarm/status     — Current swarm state (polling)
  WS   /ws               — Real-time WebSocket stream for the dashboard
  GET  /health           — Health check
"""
import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Lazy import to avoid graph build at import time in tests
_graph = None

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger("timps.main")

app = FastAPI(title="TIMPS Swarm API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis-backed state store (falls back to in-memory if Redis unavailable) ─

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_redis_client = None
_runs_fallback: dict[str, dict] = {}   # used only when Redis is down


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        client = redis_lib.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        _redis_client = client
        logger.info("Redis connected: %s", _REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — using in-memory fallback", exc)
        _redis_client = None
    return _redis_client


def _runs_set(run_id: str, data: dict):
    r = _get_redis()
    if r:
        try:
            r.set(f"timps:run:{run_id}", json.dumps(data), ex=86400)  # expire after 24h
            r.zadd("timps:runs", {run_id: time.time()})
            return
        except Exception as exc:
            logger.warning("Redis write failed: %s", exc)
    _runs_fallback[run_id] = data


def _runs_get(run_id: str) -> Optional[dict]:
    r = _get_redis()
    if r:
        try:
            raw = r.get(f"timps:run:{run_id}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis read failed: %s", exc)
    return _runs_fallback.get(run_id)


def _runs_list() -> list[str]:
    r = _get_redis()
    if r:
        try:
            return list(reversed(r.zrange("timps:runs", 0, -1)))
        except Exception as exc:
            logger.warning("Redis list failed: %s", exc)
    return list(reversed(list(_runs_fallback.keys())))


_active_websockets: list[WebSocket] = []


# ── Models ─────────────────────────────────────────────────────────────────

class SwarmRequest(BaseModel):
    request: str
    language: Optional[str] = "python"
    max_iterations: Optional[int] = 10


class SwarmResponse(BaseModel):
    run_id: str
    status: str
    message: str


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_graph():
    global _graph
    if _graph is None:
        from src.graph import app as graph_app
        _graph = graph_app
    return _graph


async def _broadcast(message: dict):
    """Send state update to all connected WebSocket clients."""
    dead = []
    for ws in _active_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _active_websockets.remove(ws)


def _build_dashboard_payload(run_id: str, state: dict) -> dict:
    """Convert swarm state into dashboard-friendly format."""
    tasks = state.get("tasks", [])

    agent_names = [
        "orchestrator", "product_manager", "architect", "code_generator",
        "code_reviewer", "qa_tester", "security_auditor", "performance_optimizer",
        "documentation_writer", "devops",
    ]

    agent_colors = {
        "orchestrator": "#6366f1", "product_manager": "#8b5cf6",
        "architect": "#06b6d4", "code_generator": "#10b981",
        "code_reviewer": "#f59e0b", "qa_tester": "#ec4899",
        "security_auditor": "#ef4444", "performance_optimizer": "#f97316",
        "documentation_writer": "#84cc16", "devops": "#64748b",
    }

    agents = []
    for i, name in enumerate(agent_names):
        role_tasks = [t for t in tasks if t.get("assigned_to") == name]
        running = [t for t in role_tasks if t["status"] == "running"]
        completed = [t for t in role_tasks if t["status"] == "completed"]

        agents.append({
            "id": f"agent-{i}",
            "name": name,
            "role": name,
            "status": "running" if running else ("completed" if completed else "pending"),
            "current_task": running[0]["description"][:60] if running else None,
            "adapter_loaded": "base",
            "latency_ms": 0,
            "tokens_generated": 0,
            "last_active": datetime.now(timezone.utc).isoformat(),
            "color": agent_colors.get(name, "#94a3b8"),
        })

    completed_count = len([t for t in tasks if t["status"] == "completed"])
    failed_count = len([t for t in tasks if t["status"] == "failed"])
    running_count = len([t for t in tasks if t["status"] == "running"])
    total_tasks = len(tasks)

    # Real avg_latency: approximate from completed task timestamps
    latencies = []
    for t in tasks:
        if t.get("created_at") and t.get("completed_at"):
            try:
                created = datetime.fromisoformat(t["created_at"])
                completed = datetime.fromisoformat(t["completed_at"])
                latencies.append((completed - created).total_seconds() * 1000)
            except Exception:
                pass
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    return {
        "run_id": run_id,
        "agents": agents,
        "tasks": tasks[:50],
        "metrics": {
            "total_agents": len(agent_names),
            "active_agents": running_count,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count,
            "avg_latency": avg_latency,
            "throughput": round(completed_count / max(state.get("iteration_count", 1), 1), 2),
            "queue_depth": len([t for t in tasks if t["status"] == "pending"]),
        },
        "history": [
            {
                "time": f"{i}",
                "throughput": min(completed_count, i + 1),
                "active": running_count,
                "errors": failed_count,
            }
            for i in range(20)
        ],
        "artifacts": state.get("code_artifacts", []),
        "iteration": state.get("iteration_count", 0),
        "completed": state.get("completed", False),
    }


# ── Background swarm runner ────────────────────────────────────────────────

async def _run_swarm_async(run_id: str, request: str, language: str, max_iterations: int):
    logger.info("Starting swarm run %s", run_id)
    _runs_set(run_id, {"status": "running", "state": {}})

    initial_state = {
        "user_request": request,
        "language": language,
        "tasks": [],
        "code_artifacts": [],
        "review_comments": [],
        "errors": [],
        "iteration_count": 0,
        "max_iterations": max_iterations,
        "requirements": "",
        "architecture_plan": "",
        "test_results": "",
        "security_report": "",
        "performance_report": "",
        "documentation": "",
        "final_deliverable": "",
        "completed": False,
    }

    graph = _get_graph()

    try:
        async for event in graph.astream(initial_state):
            node_name = list(event.keys())[0] if event else "unknown"
            node_state = event.get(node_name, {})

            # Merge into accumulated state
            run_data = _runs_get(run_id) or {"status": "running", "state": {}}
            for k, v in node_state.items():
                if isinstance(v, list):
                    existing = run_data["state"].get(k, [])
                    run_data["state"][k] = existing + v
                else:
                    run_data["state"][k] = v

            run_data["state"]["last_node"] = node_name
            _runs_set(run_id, run_data)
            logger.info("Swarm %s — node: %s", run_id, node_name)

            payload = _build_dashboard_payload(run_id, run_data["state"])
            await _broadcast(payload)

        run_data = _runs_get(run_id) or {}
        run_data["status"] = "completed"
        _runs_set(run_id, run_data)
        logger.info("Swarm run %s completed ✓", run_id)

    except Exception as exc:
        logger.error("Swarm run %s failed: %s", run_id, exc, exc_info=True)
        run_data = _runs_get(run_id) or {}
        run_data["status"] = "failed"
        run_data["error"] = str(exc)
        _runs_set(run_id, run_data)
        await _broadcast({"run_id": run_id, "status": "failed", "error": str(exc)})


# ── API Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    r = _get_redis()
    return {
        "status": "ok",
        "service": "timps-swarm",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "redis": "connected" if r else "unavailable (using in-memory fallback)",
    }


@app.post("/swarm/run", response_model=SwarmResponse)
async def run_swarm(request: SwarmRequest, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(
        _run_swarm_async,
        run_id,
        request.request,
        request.language or "python",
        request.max_iterations or 10,
    )
    return SwarmResponse(
        run_id=run_id,
        status="started",
        message=f"Swarm run {run_id} started. Connect to /ws for real-time updates.",
    )


@app.get("/swarm/status")
async def swarm_status(run_id: Optional[str] = None):
    if run_id:
        data = _runs_get(run_id)
        if data:
            return _build_dashboard_payload(run_id, data.get("state", {}))

    # Return latest run or empty state
    run_ids = _runs_list()
    if run_ids:
        latest_id = run_ids[0]
        data = _runs_get(latest_id) or {}
        return _build_dashboard_payload(latest_id, data.get("state", {}))

    return _build_dashboard_payload("none", {})


@app.get("/swarm/runs")
async def list_runs():
    run_ids = _runs_list()
    results = []
    for rid in run_ids:
        data = _runs_get(rid) or {}
        tasks = data.get("state", {}).get("tasks", [])
        results.append({
            "run_id": rid,
            "status": data.get("status", "unknown"),
            "tasks_done": len([t for t in tasks if t["status"] == "completed"]),
        })
    return results


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _active_websockets.append(websocket)
    logger.info("Dashboard WebSocket connected (%d total)", len(_active_websockets))

    try:
        # Send current state immediately on connect
        run_ids = _runs_list()
        if run_ids:
            latest_id = run_ids[0]
            data = _runs_get(latest_id) or {}
            payload = _build_dashboard_payload(latest_id, data.get("state", {}))
            await websocket.send_json(payload)

        # Keep alive until client disconnects
        while True:
            await asyncio.sleep(2)
            run_ids = _runs_list()
            if run_ids:
                latest_id = run_ids[0]
                data = _runs_get(latest_id) or {}
                payload = _build_dashboard_payload(latest_id, data.get("state", {}))
                await websocket.send_json(payload)

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected")
    finally:
        if websocket in _active_websockets:
            _active_websockets.remove(websocket)


# ── Priority Agent Endpoints (used by CLI) ─────────────────────────────────

class ResearchRequest(BaseModel):
    topic: str
    depth: Optional[str] = "medium"


class APIDesignRequest(BaseModel):
    description: str
    style: Optional[str] = "rest"
    auth_scheme: Optional[str] = "jwt"


class DBDesignRequest(BaseModel):
    description: str
    db_engine: Optional[str] = "postgresql"
    migration_tool: Optional[str] = "alembic"


class DependencyAuditRequest(BaseModel):
    manifest: str
    ecosystem: Optional[str] = "auto"


class N8nWorkflowRequest(BaseModel):
    description: str
    trigger: Optional[str] = "auto"


@app.post("/agents/research")
async def agent_research(req: ResearchRequest):
    from src.priority_agents import research_agent
    return research_agent({"topic": req.topic, "depth": req.depth})


@app.post("/agents/api-design")
async def agent_api_design(req: APIDesignRequest):
    from src.priority_agents import api_design_agent
    return api_design_agent({
        "description": req.description,
        "style": req.style,
        "auth_scheme": req.auth_scheme,
    })


@app.post("/agents/db-design")
async def agent_db_design(req: DBDesignRequest):
    from src.priority_agents import db_agent
    return db_agent({
        "description": req.description,
        "db_engine": req.db_engine,
        "migration_tool": req.migration_tool,
    })


@app.post("/agents/dependency-audit")
async def agent_dependency_audit(req: DependencyAuditRequest):
    from src.priority_agents import dependency_agent
    return dependency_agent({"manifest": req.manifest, "ecosystem": req.ecosystem})


@app.post("/agents/n8n-workflow")
async def agent_n8n_workflow(req: N8nWorkflowRequest):
    from src.priority_agents import n8n_workflow_agent
    return n8n_workflow_agent({"description": req.description, "trigger": req.trigger})


# ── More Agent Endpoints (Phase 5) ─────────────────────────────────────────

class RefactoringRequest(BaseModel):
    code: str
    language: Optional[str] = "python"
    goals: Optional[list] = None


class TestDataRequest(BaseModel):
    schema_desc: str
    count: Optional[int] = 20
    format: Optional[str] = "json"
    locale: Optional[str] = "en_US"


class MonitoringRequest(BaseModel):
    service_description: str
    language: Optional[str] = "python"
    slos: Optional[list] = None
    alerting_platform: Optional[str] = "alertmanager"


class UIUXRequest(BaseModel):
    description: str
    framework: Optional[str] = "react"
    design_system: Optional[str] = "tailwind"
    accessibility_level: Optional[str] = "AA"


class I18nRequest(BaseModel):
    code: str
    source_locale: Optional[str] = "en"
    target_locales: Optional[list] = None
    i18n_framework: Optional[str] = "auto"


class CostOptimizerRequest(BaseModel):
    architecture: str
    provider: Optional[str] = "aws"
    monthly_requests: Optional[int] = 1_000_000
    regions: Optional[list] = None


class SelfCriticRequest(BaseModel):
    content: str
    agent: str
    task: str
    threshold: Optional[int] = 7
    max_retries: Optional[int] = 2


@app.post("/agents/refactor")
async def agent_refactor(req: RefactoringRequest):
    from src.more_agents import refactoring_agent
    return refactoring_agent({"code": req.code, "language": req.language, "goals": req.goals})


@app.post("/agents/test-data")
async def agent_test_data(req: TestDataRequest):
    from src.more_agents import test_data_agent
    return test_data_agent({"schema": req.schema_desc, "count": req.count,
                            "format": req.format, "locale": req.locale})


@app.post("/agents/monitoring")
async def agent_monitoring(req: MonitoringRequest):
    from src.more_agents import monitoring_agent
    return monitoring_agent({"service_description": req.service_description,
                             "language": req.language, "slos": req.slos,
                             "alerting_platform": req.alerting_platform})


@app.post("/agents/ui-ux")
async def agent_ui_ux(req: UIUXRequest):
    from src.more_agents import ui_ux_agent
    return ui_ux_agent({"description": req.description, "framework": req.framework,
                        "design_system": req.design_system,
                        "accessibility_level": req.accessibility_level})


@app.post("/agents/i18n")
async def agent_i18n(req: I18nRequest):
    from src.more_agents import i18n_agent
    return i18n_agent({"code": req.code, "source_locale": req.source_locale,
                       "target_locales": req.target_locales, "i18n_framework": req.i18n_framework})


@app.post("/agents/cost-optimizer")
async def agent_cost_optimizer(req: CostOptimizerRequest):
    from src.more_agents import cost_optimizer
    return cost_optimizer({"architecture": req.architecture, "provider": req.provider,
                           "monthly_requests": req.monthly_requests, "regions": req.regions})


@app.post("/agents/self-critic")
async def agent_self_critic(req: SelfCriticRequest):
    from src.more_agents import self_critic_agent
    return self_critic_agent({"content": req.content, "agent": req.agent, "task": req.task,
                              "threshold": req.threshold, "max_retries": req.max_retries})


@app.get("/providers")
async def list_all_providers():
    from src.providers import list_providers, registry
    providers_info = []
    for name in ["mcp", "gemini", "anthropic", "openai", "groq", "ollama", "timps"]:
        try:
            prov = registry.get(name)
            available = prov.is_available() if prov else False
            description = {
                "mcp": "MCP sampler (when inside Claude Code)",
                "gemini": "Google Gemini 2.5 Flash",
                "anthropic": "Anthropic Claude",
                "openai": "OpenAI GPT",
                "groq": "Groq fast-inference (Llama 3.3 70B)",
                "ollama": "Local Ollama (qwen2.5)",
                "timps": "TIMPS-Coder 0.5B (on-device)",
            }.get(name, "")
            model = getattr(prov, "model", getattr(prov, "_model", "—"))
            providers_info.append({
                "name": name,
                "available": available,
                "active": False,
                "model": str(model),
                "description": description,
            })
        except Exception as e:
            providers_info.append({"name": name, "available": False, "active": False, "model": "—", "description": str(e)})

    # Mark the best available one as active
    available_providers = [p for p in providers_info if p["available"]]
    if available_providers:
        available_providers[0]["active"] = True

    return {"providers": providers_info}


@app.post("/health/full")
async def full_health_checkup():
    from src.computer_agents import run_full_checkup
    try:
        result = run_full_checkup()
        return result
    except ImportError:
        return {"status": "computer_agents module not available", "summary": "N/A"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/mcp/install")
async def mcp_install(body: dict):
    """Auto-configure TIMPS as MCP server in known AI tools."""
    import json, os, pathlib
    tool_id = body.get("tool_id", "all")
    dry_run = body.get("dry_run", False)

    repo_dir = str(pathlib.Path(__file__).parent.parent.resolve())
    results = []

    configs = {
        "claude-code": {
            "path": pathlib.Path.home() / ".claude" / "mcp.json",
            "merger": lambda existing: {
                **existing,
                "mcpServers": {
                    **existing.get("mcpServers", {}),
                    "timps-swarm": {
                        "command": "python",
                        "args": ["-m", "mcp_server.server"],
                        "cwd": repo_dir,
                        "env": {},
                    },
                },
            },
        },
        "cursor": {
            "path": pathlib.Path.home() / ".cursor" / "mcp.json",
            "merger": lambda existing: {
                **existing,
                "mcpServers": {
                    **existing.get("mcpServers", {}),
                    "timps-swarm": {
                        "command": "python",
                        "args": ["-m", "mcp_server.server"],
                        "cwd": repo_dir,
                        "env": {},
                    },
                },
            },
        },
        "local-mcp": {
            "path": pathlib.Path(repo_dir) / ".claude" / "mcp.json",
            "merger": lambda _: {
                "mcpServers": {
                    "timps-swarm": {
                        "command": "python",
                        "args": ["-m", "mcp_server.server"],
                        "cwd": repo_dir,
                        "env": {},
                    },
                },
            },
        },
    }

    for cid, cfg in configs.items():
        if tool_id not in ("all", cid):
            continue
        p = cfg["path"]
        try:
            existing = json.loads(p.read_text()) if p.exists() else {}
            merged = cfg["merger"](existing)
            if dry_run:
                results.append({"tool": cid, "status": "dry_run",
                                 "message": f"Would write to {p}", "config": merged})
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(merged, indent=2))
                results.append({"tool": cid, "status": "ok",
                                 "message": f"Written to {p}"})
        except Exception as e:
            results.append({"tool": cid, "status": "error", "message": str(e)})

    return {"results": results}


# ── HTTP bridge to the MCP server ─────────────────────────────────────────
# These two endpoints let a thin Node.js stdio proxy (cli/lib/mcp-proxy.js)
# expose the full 64-tool MCP surface to Claude Code / Cursor / Codex when
# the user has `npm install -g timps-swarm` but has not cloned the Python repo.
# The proxy starts the FastAPI server (or points at a remote one) and forwards
# JSON-RPC 2.0 tool calls to these endpoints. The actual tool execution lives
# in mcp_server/server.py:_TOOL_HANDLERS — we lazy-import it here.

_MCP_HANDLERS_CACHE: Optional[Dict[str, Any]] = None
_MCP_TOOLS_CACHE: Optional[List[Dict[str, Any]]] = None


def _get_mcp_handlers() -> Dict[str, Any]:
    global _MCP_HANDLERS_CACHE
    if _MCP_HANDLERS_CACHE is None:
        from mcp_server.server import _TOOL_HANDLERS
        _MCP_HANDLERS_CACHE = _TOOL_HANDLERS
    return _MCP_HANDLERS_CACHE


def _get_mcp_tools() -> List[Dict[str, Any]]:
    global _MCP_TOOLS_CACHE
    if _MCP_TOOLS_CACHE is None:
        from mcp_server.server import TOOLS
        _MCP_TOOLS_CACHE = TOOLS
    return _MCP_TOOLS_CACHE


@app.get("/mcp/tools")
async def list_mcp_tools():
    """Return the full MCP tool catalogue (name, description, inputSchema)."""
    try:
        return {"tools": _get_mcp_tools()}
    except Exception as exc:
        logger.error("Failed to load MCP tool list: %s", exc)
        raise HTTPException(status_code=500, detail=f"Could not load MCP tools: {exc}")


class MCPCallRequest(BaseModel):
    name: str
    arguments: Optional[dict] = None


@app.post("/mcp/tools/call")
async def call_mcp_tool(req: MCPCallRequest):
    """Dispatch a single MCP tool call. Mirrors the stdio dispatch in
    mcp_server/server.py so the Node.js proxy can route any of the 160 tools
    through one HTTP endpoint."""
    handlers = _get_mcp_handlers()
    handler = handlers.get(req.name)
    if not handler:
        raise HTTPException(status_code=404, detail=f"Unknown MCP tool: {req.name}")
    try:
        text = handler(req.arguments or {})
        return {"isError": False, "content": [{"type": "text", "text": text}]}
    except Exception as exc:
        logger.exception("MCP tool %s failed", req.name)
        return {"isError": True, "content": [{"type": "text", "text": f"Tool {req.name} failed: {exc}"}]}


# ── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("DEV", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
