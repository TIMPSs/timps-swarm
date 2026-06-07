"""AI Workflow Orchestrator — turns a plain-English multi-step workflow into
executable code for one of three orchestration frameworks:

* **LangGraph**  — state graph with nodes and conditional edges
* **Temporal**  — durable workflow + activities in Python
* **Claude-Flow** — Anthropic's lightweight tool-call DAG

The agent reads the description, optional file references, then asks the LLM
to design the state shape, node list, edge conditions, retry policy, and tests.
It emits a single runnable Python module under `generated/workflows/<name>/`
plus a Mermaid diagram and a tiny test harness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "nextgen"

SUPPORTED_FRAMEWORKS = ("langgraph", "temporal", "claude_flow")


def ai_workflow_orchestrator(args: Dict[str, Any]) -> Dict[str, Any]:
    description = (args.get("description") or args.get("goal") or "").strip()
    workflow_name = (args.get("name") or "workflow").strip().lower()
    workflow_name = re.sub(r"[^a-z0-9_]+", "_", workflow_name).strip("_") or "workflow"
    framework = (args.get("framework") or "langgraph").lower()
    if framework not in SUPPORTED_FRAMEWORKS:
        framework = "langgraph"
    target_dir = Path(args.get("target_dir") or f"generated/workflows/{workflow_name}")
    reference_files: List[str] = args.get("reference_files") or []

    if not description:
        return {
            "summary": "No description provided — describe the multi-step workflow you want to orchestrate.",
            "error": "description is required",
            "framework": framework,
        }

    # --------------------------------------------------------------- gather
    extra: List[str] = []
    for ref in reference_files[:3]:
        p = Path(ref)
        if p.is_file():
            try:
                extra.append(
                    f"--- REFERENCE FILE {ref} ---\n"
                    + p.read_text(encoding="utf-8", errors="ignore")[:12_000]
                )
            except Exception:
                pass

    # --------------------------------------------------------------- prompt
    system = (
        "You are a workflow-orchestration architect.  You design production-"
        "ready multi-step AI workflows and return ONLY a single JSON object — "
        "no prose, no fences.\n\n"
        "Schema:\n"
        "{\n"
        '  "state":      { "<field>": "<type|description>", ... },   // shared state\n'
        '  "nodes":      [ { "id": str_snake, "purpose": str, '
        '"inputs": [str], "outputs": [str], "llm_call": bool, "tool": str|null } ],\n'
        '  "edges":      [ { "from": str, "to": str, "condition": str|null } ],\n'
        '  "retries":    { "max_attempts": int, "backoff": "exp"|"fixed"|"linear", '
        '"base_seconds": float },\n'
        '  "human_loop": { "required": bool, "checkpoint_after": [str] },\n'
        '  "tests":      [ { "name": str, "input_state": dict, "expected_path": [str] } ],\n'
        '  "diagram":    "  Mermaid stateDiagram-v2 string (one line per node/edge) "\n'
        "}\n\n"
        "Rules:\n"
        "- Node ids MUST be unique snake_case strings.\n"
        "- Every `edges[].to` MUST reference a valid `nodes[].id`.\n"
        "- `condition` may be a Python expression evaluated against `state`.\n"
        "- `expected_path` in tests is a list of node ids in order.\n"
        "- Keep the design ≤ 20 nodes unless the description demands more."
    )

    user = (
        f"Workflow name: {workflow_name}\n"
        f"Target framework: {framework}\n\n"
        f"Plain-English description:\n{description}\n\n"
        + ("\n".join(extra))
    )

    raw = _llm(user, system, "ai_workflow_orchestrator")
    parsed = _parse_json(
        raw,
        fallback={
            "state": {"input": "dict", "output": "dict"},
            "nodes": [],
            "edges": [],
            "retries": {"max_attempts": 3, "backoff": "exp", "base_seconds": 1.0},
            "human_loop": {"required": False, "checkpoint_after": []},
            "tests": [],
            "diagram": "stateDiagram-v2\n    [*] --> Start",
        },
    )

    state_def = parsed.get("state") or {}
    nodes = parsed.get("nodes") or []
    edges = parsed.get("edges") or []
    retries = parsed.get("retries") or {}
    human_loop = parsed.get("human_loop") or {}
    tests = parsed.get("tests") or []
    diagram = parsed.get("diagram") or ""

    # --------------------------------------------------------------- emit
    target_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[str] = []

    code = _render_workflow(workflow_name, framework, state_def, nodes, edges, retries, human_loop)
    p = target_dir / "workflow.py"
    p.write_text(code, encoding="utf-8")
    out_paths.append(str(p))

    diagram_full = "```mermaid\n" + diagram.rstrip() + "\n```\n"
    p = target_dir / "diagram.md"
    p.write_text(diagram_full, encoding="utf-8")
    out_paths.append(str(p))

    p = target_dir / "tests.py"
    p.write_text(_render_tests(workflow_name, framework, tests, nodes), encoding="utf-8")
    out_paths.append(str(p))

    p = target_dir / "README.md"
    p.write_text(
        f"# {workflow_name}\n\nFramework: **{framework}**\n\n"
        f"## State\n```json\n{json.dumps(state_def, indent=2)}\n```\n\n"
        f"## Nodes ({len(nodes)})\n"
        + "\n".join(f"- `{n.get('id','')}` — {n.get('purpose','')}" for n in nodes)
        + f"\n\n## Edges ({len(edges)})\n"
        + "\n".join(
            f"- `{e.get('from','')}` → `{e.get('to','')}`"
            + (f" *if* {e.get('condition','')}" if e.get("condition") else "")
            for e in edges
        )
        + "\n",
        encoding="utf-8",
    )
    out_paths.append(str(p))

    p = target_dir / "spec.json"
    p.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    out_paths.append(str(p))

    # smoke check the generated file
    smoke = _run(
        f"cd {target_dir} && python -c \"import ast; ast.parse(open('workflow.py').read()); "
        f"ast.parse(open('tests.py').read()); print('ok')\"",
        timeout=20,
    )

    summary = (
        f"Generated {framework} workflow '{workflow_name}' with {len(nodes)} nodes, "
        f"{len(edges)} edges, {len(tests)} tests "
        f"(retries={retries.get('max_attempts', 3)}, human_loop={human_loop.get('required', False)})."
    )

    payload = {
        "summary": summary,
        "workflow_name": workflow_name,
        "framework": framework,
        "state": state_def,
        "nodes": nodes,
        "edges": edges,
        "retries": retries,
        "human_loop": human_loop,
        "tests": tests,
        "diagram": diagram,
        "files": out_paths,
        "smoke_check": smoke[:600],
        "generated_at": _ts(),
    }
    _save("workflows", f"{workflow_name}_summary.json", json.dumps(payload, indent=2))
    _record("ai_workflow_orchestrator", workflow_name, f"framework={framework} nodes={len(nodes)} edges={len(edges)}")
    return payload


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_workflow(
    name: str,
    framework: str,
    state: Dict[str, Any],
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    retries: Dict[str, Any],
    human_loop: Dict[str, Any],
) -> str:
    if framework == "langgraph":
        return _render_langgraph(name, state, nodes, edges, retries, human_loop)
    if framework == "temporal":
        return _render_temporal(name, state, nodes, edges, retries, human_loop)
    return _render_claude_flow(name, state, nodes, edges, retries, human_loop)


def _render_langgraph(name, state, nodes, edges, retries, human_loop) -> str:
    node_funcs: List[str] = []
    for n in nodes:
        nid = _snake(n.get("id") or "node")
        purpose = (n.get("purpose") or "").replace("\n", " ")
        uses_llm = bool(n.get("llm_call"))
        tool = n.get("tool")
        body_lines = [f"    state['{nid}_ran'] = True"]
        if uses_llm:
            body_lines.append(
                f"    state.setdefault('llm_calls', []).append({json.dumps(nid)})"
            )
        if tool:
            body_lines.append(
                f"    state.setdefault('tools_used', []).append({json.dumps(tool)})"
            )
        node_funcs.append(
            f"def node_{nid}(state: dict) -> dict:\n"
            f'    """{purpose}"""\n'
            + "\n".join(body_lines) + "\n    return state\n"
        )

    edge_lines: List[str] = []
    for e in edges:
        f, t, cond = e.get("from") or "START", e.get("to") or "END", e.get("condition")
        if cond:
            edge_lines.append(
                f"workflow.add_conditional_edges({json.dumps(_snake(f))}, "
                f"lambda s: bool({cond}), {{{json.dumps(_snake(t))}: {json.dumps(_snake(t))}}})"
            )
        else:
            edge_lines.append(
                f"workflow.add_edge({json.dumps(_snake(f))}, {json.dumps(_snake(t))})"
            )

    interrupt = ""
    if human_loop.get("required"):
        cps = human_loop.get("checkpoint_after") or []
        cps_ids = ", ".join(json.dumps(_snake(c)) for c in cps)
        interrupt = f"\n# human checkpoints: {cps_ids}\n"

    return (
        f'"""{name} — LangGraph workflow generated by TIMPS Swarm."""\n'
        f"from __future__ import annotations\n"
        f"from typing import TypedDict, Any\n"
        f"from langgraph.graph import StateGraph, END\n\n"
        f"class State(TypedDict, total=False):\n"
        + "\n".join(f"    {k}: Any  # {v}" for k, v in state.items())
        + "\n\n" + "\n".join(node_funcs)
        + f"\nworkflow = StateGraph(State)\n"
        + "\n".join(
            f"workflow.add_node({json.dumps(_snake(n.get('id','')))}, node_{_snake(n.get('id',''))})"
            for n in nodes
        )
        + f"\nworkflow.set_entry_point({json.dumps(_snake(nodes[0]['id']) if nodes else 'start')})\n"
        + "\n".join(edge_lines)
        + f"\nworkflow.add_edge('END' if False else {json.dumps(_snake(nodes[-1]['id']) if nodes else 'end')}, END)\n"
        f"app = workflow.compile()\n"
        f"{interrupt}"
    )


def _render_temporal(name, state, nodes, edges, retries, human_loop) -> str:
    activity_funcs = "\n\n".join(
        f"@activity.defn\nasync def act_{_snake(n.get('id',''))}(input: dict) -> dict:\n"
        f'    """{(n.get("purpose") or "").replace(chr(10), " ")}"""\n'
        f"    return {{'ok': True, 'node': {json.dumps(_snake(n.get('id','')))}, 'input': input}}\n"
        for n in nodes
    )
    wf_body_lines = ["    state: dict = args"]
    for n in nodes:
        wf_body_lines.append(
            f"    state = await workflow.execute_activity(act_{_snake(n.get('id',''))}, "
            f"state, start_to_close_timeout=timedelta(seconds=30), "
            f"retries={retries.get('max_attempts', 3)})"
        )
    return (
        f'"""{name} — Temporal workflow generated by TIMPS Swarm."""\n'
        f"from __future__ import annotations\n"
        f"from datetime import timedelta\n"
        f"from temporalio import workflow, activity\n\n"
        f"{activity_funcs}\n\n"
        f"@workflow.defn\nclass {name.title().replace('_','')}Workflow:\n"
        f"    @workflow.run\n"
        f"    async def run(self, args: dict) -> dict:\n"
        + "\n".join(wf_body_lines) + "\n        return state\n"
    )


def _render_claude_flow(name, state, nodes, edges, retries, human_loop) -> str:
    spec = {
        "name": name,
        "state_schema": state,
        "steps": [
            {
                "id": _snake(n.get("id", "")),
                "purpose": n.get("purpose", ""),
                "tool": n.get("tool"),
                "llm_call": bool(n.get("llm_call")),
            }
            for n in nodes
        ],
        "transitions": [
            {
                "from": _snake(e.get("from", "")),
                "to": _snake(e.get("to", "")),
                "condition": e.get("condition"),
            }
            for e in edges
        ],
    }
    return (
        f'"""{name} — Claude-Flow DAG generated by TIMPS Swarm."""\n'
        f"from __future__ import annotations\n"
        f"import json, asyncio\n"
        f"from claude_flow import Flow, Step  # type: ignore\n\n"
        f"SPEC = {json.dumps(spec, indent=2)}\n\n"
        f"def build_flow() -> Flow:\n"
        f"    f = Flow(name={json.dumps(name)})\n"
        f"    for s in SPEC['steps']:\n"
        f"        f.add(Step(id=s['id'], purpose=s['purpose'], "
        f"tool=s['tool'], llm_call=s['llm_call']))\n"
        f"    for t in SPEC['transitions']:\n"
        f"        f.connect(t['from'], t['to'], condition=t['condition'])\n"
        f"    return f\n\n"
        f"if __name__ == '__main__':\n"
        f"    asyncio.run(build_flow().run_async({{}}))\n"
    )


def _render_tests(name, framework, tests, nodes) -> str:
    node_ids = [n.get("id", "") for n in nodes]
    if not tests and node_ids:
        tests = [{"name": "smoke", "input_state": {}, "expected_path": node_ids}]
    body = "\n".join(
        f"def test_{i}_{_snake(t.get('name','case'))}():\n"
        f"    path = {json.dumps([_snake(x) for x in t.get('expected_path', [])])}\n"
        f"    assert path, f'empty path for test {t.get('name','')}'\n"
        f"    for step in path:\n"
        f"        assert step in NODE_IDS, f'unknown node {{step}}'\n"
        for i, t in enumerate(tests)
    )
    return (
        f'"""{name} workflow tests."""\n'
        f"NODE_IDS = {json.dumps([_snake(x) for x in node_ids])}\n\n"
        f"{body}\n"
    )


def _snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s)).strip("_").lower()
    return s or "node"
