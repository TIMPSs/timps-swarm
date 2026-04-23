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
import uuid
from datetime import datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
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

# ── In-memory state store ──────────────────────────────────────────────────
_runs: dict[str, dict] = {}          # run_id → swarm state snapshot
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
            "last_active": datetime.utcnow().isoformat(),
            "color": agent_colors.get(name, "#94a3b8"),
        })

    completed_count = len([t for t in tasks if t["status"] == "completed"])
    failed_count = len([t for t in tasks if t["status"] == "failed"])
    running_count = len([t for t in tasks if t["status"] == "running"])

    return {
        "run_id": run_id,
        "agents": agents,
        "tasks": tasks[:50],
        "metrics": {
            "total_agents": len(agent_names),
            "active_agents": running_count,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count,
            "avg_latency": 450,
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
    _runs[run_id] = {"status": "running", "state": {}}

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
            for k, v in node_state.items():
                if isinstance(v, list):
                    existing = _runs[run_id]["state"].get(k, [])
                    _runs[run_id]["state"][k] = existing + v
                else:
                    _runs[run_id]["state"][k] = v

            _runs[run_id]["state"]["last_node"] = node_name
            logger.info("Swarm %s — node: %s", run_id, node_name)

            payload = _build_dashboard_payload(run_id, _runs[run_id]["state"])
            await _broadcast(payload)

        _runs[run_id]["status"] = "completed"
        logger.info("Swarm run %s completed ✓", run_id)

    except Exception as exc:
        logger.error("Swarm run %s failed: %s", run_id, exc, exc_info=True)
        _runs[run_id]["status"] = "failed"
        _runs[run_id]["error"] = str(exc)
        await _broadcast({"run_id": run_id, "status": "failed", "error": str(exc)})


# ── API Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "timps-swarm", "timestamp": datetime.utcnow().isoformat()}


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
    if run_id and run_id in _runs:
        state = _runs[run_id]["state"]
        return _build_dashboard_payload(run_id, state)

    # Return latest run or empty state
    if _runs:
        latest_id = list(_runs.keys())[-1]
        return _build_dashboard_payload(latest_id, _runs[latest_id]["state"])

    return _build_dashboard_payload("none", {})


@app.get("/swarm/runs")
async def list_runs():
    return [
        {
            "run_id": rid,
            "status": data["status"],
            "tasks_done": len([t for t in data["state"].get("tasks", []) if t["status"] == "completed"]),
        }
        for rid, data in _runs.items()
    ]


# ── WebSocket ──────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _active_websockets.append(websocket)
    logger.info("Dashboard WebSocket connected (%d total)", len(_active_websockets))

    try:
        # Send current state immediately on connect
        if _runs:
            latest_id = list(_runs.keys())[-1]
            payload = _build_dashboard_payload(latest_id, _runs[latest_id]["state"])
            await websocket.send_json(payload)

        # Keep alive until client disconnects
        while True:
            await asyncio.sleep(2)
            if _runs:
                latest_id = list(_runs.keys())[-1]
                payload = _build_dashboard_payload(latest_id, _runs[latest_id]["state"])
                await websocket.send_json(payload)

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected")
    finally:
        if websocket in _active_websockets:
            _active_websockets.remove(websocket)


# ── Entrypoint ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("DEV", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
