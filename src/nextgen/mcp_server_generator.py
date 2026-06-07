"""MCP Server Generator — scaffolds a complete Model Context Protocol (MCP)
server from a plain-English description of the tools / resources / prompts to
expose.  Produces an importable `server.py` (FastMCP / mcp SDK), a `pyproject`
entry-point, an installable CLI, a smoke-test client, and a README.

The agent is LLM-driven: the local scan reads the description, any sibling
files referenced (e.g. the existing `mcp_server/server.py` of the parent
project when `mode="extend"`), and asks the LLM to design the tool surface,
input schemas, error contracts, and security boundaries.  The output is saved
under `generated/mcp_servers/<name>/` and is ready to `pip install -e .`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "nextgen"


def mcp_server_generator(args: Dict[str, Any]) -> Dict[str, Any]:
    description = (args.get("description") or args.get("spec") or "").strip()
    server_name = (args.get("name") or "timps_mcp_server").strip().lower()
    server_name = re.sub(r"[^a-z0-9_]+", "_", server_name).strip("_") or "timps_mcp_server"
    mode = args.get("mode", "create")  # 'create' or 'extend'
    transport = args.get("transport", "stdio")  # 'stdio' | 'sse' | 'streamable-http'
    target_dir = Path(args.get("target_dir") or f"generated/mcp_servers/{server_name}")

    if not description:
        return {
            "summary": "No description provided — supply a plain-English spec of the tools, resources, and prompts the server should expose.",
            "tools": [], "resources": [], "prompts": [],
            "error": "description is required",
        }

    # --------------------------------------------------------------- gather
    extra: List[str] = []
    if mode == "extend":
        parent = Path("mcp_server/server.py")
        if parent.exists():
            try:
                extra.append(
                    "--- EXISTING PARENT mcp_server/server.py (first 400 lines) ---\n"
                    + parent.read_text(encoding="utf-8", errors="ignore")[:24_000]
                )
            except Exception:
                pass

    # --------------------------------------------------------------- prompt
    system = (
        "You are a senior protocol engineer designing a Model Context Protocol "
        "(MCP) server.  You return ONLY a single JSON object — no prose, no "
        "markdown fences.\n\n"
        "Schema:\n"
        "{\n"
        '  "tools":     [ { "name": str_snake, "description": str, '
        '"input_schema": { "type":"object", "properties": {..}, "required":[..] } } ],\n'
        '  "resources": [ { "uri_template": str, "name": str, "description": str, '
        '"mime_type": str } ],\n'
        '  "prompts":   [ { "name": str, "description": str, "arguments": [str] } ],\n'
        '  "security_notes":   [str],  // rate-limiting, auth, dangerous inputs\n'
        '  "implementation":   { "sdk": "mcp" | "fastmcp", "transport": "stdio"|"sse"|"streamable-http", '
        '"python_min": "3.10", "deps": [str] },\n'
        '  "cli_entrypoint":   "console_scripts entry, e.g. my_server=server:run",\n'
        '  "test_outline":     [str]   // smoke test cases for a test client\n'
        "}\n\n"
        "Rules:\n"
        "- Tool names MUST be snake_case and unique.\n"
        "- input_schema is JSON-Schema (Draft 7) with at least `type: object`.\n"
        "- All string fields accept natural-language input; do not invent fields.\n"
        "- Do not expose any tool that deletes files outside the project root or "
        "makes network calls without an explicit opt-in flag.\n"
        "- If the description references a real-world domain (e.g. GitHub, "
        "Postgres, S3) the implementation must wrap the SDK rather than shelling out."
    )

    user = (
        f"Server name: {server_name}\n"
        f"Mode: {mode}\n"
        f"Transport: {transport}\n\n"
        f"User description:\n{description}\n\n"
        + ("\n".join(extra))
    )

    raw = _llm(user, system, "mcp_server_generator")
    parsed = _parse_json(
        raw,
        fallback={
            "tools": [],
            "resources": [],
            "prompts": [],
            "security_notes": [],
            "implementation": {"sdk": "mcp", "transport": transport, "deps": []},
            "cli_entrypoint": "",
            "test_outline": [],
        },
    )

    tools = parsed.get("tools") or []
    resources = parsed.get("resources") or []
    prompts = parsed.get("prompts") or []
    impl = parsed.get("implementation") or {}
    sdk = (impl.get("sdk") or "mcp").lower()
    impl_transport = (impl.get("transport") or transport).lower()
    deps = impl.get("deps") or []
    cli_ep = parsed.get("cli_entrypoint") or f"{server_name}=server:run"

    # --------------------------------------------------------------- emit
    target_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[str] = []

    server_py = _render_server_py(
        server_name, sdk, impl_transport, tools, resources, prompts
    )
    p = target_dir / "server.py"
    p.write_text(server_py, encoding="utf-8")
    out_paths.append(str(p))

    pyproject = _render_pyproject(server_name, deps, cli_ep, sdk)
    p = target_dir / "pyproject.toml"
    p.write_text(pyproject, encoding="utf-8")
    out_paths.append(str(p))

    readme = _render_readme(server_name, tools, resources, prompts, deps, sdk, impl_transport)
    p = target_dir / "README.md"
    p.write_text(readme, encoding="utf-8")
    out_paths.append(str(p))

    test_py = _render_test_client(server_name, tools, resources, prompts)
    p = target_dir / "test_client.py"
    p.write_text(test_py, encoding="utf-8")
    out_paths.append(str(p))

    # --- also stash the raw JSON spec for auditability
    p = target_dir / "spec.json"
    p.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    out_paths.append(str(p))

    # --------------------------------------------------------------- sanity
    smoke = _run(
        f"cd {target_dir} && python -c \"import ast; ast.parse(open('server.py').read()); "
        f"ast.parse(open('test_client.py').read()); print('ok')\"",
        timeout=20,
    )

    summary = (
        f"Scaffolded MCP server '{server_name}' with {len(tools)} tools, "
        f"{len(resources)} resources, and {len(prompts)} prompts "
        f"(transport={impl_transport}, sdk={sdk})."
    )

    payload = {
        "summary": summary,
        "server_name": server_name,
        "mode": mode,
        "transport": impl_transport,
        "sdk": sdk,
        "tools": tools,
        "resources": resources,
        "prompts": prompts,
        "security_notes": parsed.get("security_notes", []),
        "deps": deps,
        "cli_entrypoint": cli_ep,
        "test_outline": parsed.get("test_outline", []),
        "files": out_paths,
        "smoke_check": smoke[:600],
        "generated_at": _ts(),
    }
    _save("mcp_servers", f"{server_name}_summary.json", json.dumps(payload, indent=2))
    _record("mcp_server_generator", server_name, f"tools={len(tools)} resources={len(resources)} prompts={len(prompts)}")
    return payload


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_server_py(
    name: str,
    sdk: str,
    transport: str,
    tools: List[Dict[str, Any]],
    resources: List[Dict[str, Any]],
    prompts: List[Dict[str, Any]],
) -> str:
    """Build a self-contained server.py that the user can `pip install -e .`."""
    tool_funcs: List[str] = []
    for t in tools:
        fn = _snake(t.get("name") or "tool")
        desc = (t.get("description") or "").replace("\n", " ")
        tool_funcs.append(
            f"@mcp.tool(name={json.dumps(fn)}, description={json.dumps(desc)})\n"
            f"def {fn}(**kwargs) -> dict:\n"
            f"    \"\"\"{desc}\"\"\"\n"
            f"    return {{'ok': True, 'tool': {json.dumps(fn)}, 'args': kwargs}}\n"
        )

    res_funcs: List[str] = []
    for r in resources:
        uri = r.get("uri_template") or "resource://example"
        rn = _snake(r.get("name") or "resource")
        mime = r.get("mime_type") or "text/plain"
        res_funcs.append(
            f"@mcp.resource(uri={json.dumps(uri)}, name={json.dumps(rn)}, "
            f"mime_type={json.dumps(mime)})\n"
            f"def {rn}() -> str:\n"
            f"    return ''  # replace with real fetch\n"
        )

    prompt_funcs: List[str] = []
    for p in prompts:
        pn = _snake(p.get("name") or "prompt")
        desc = (p.get("description") or "").replace("\n", " ")
        args = p.get("arguments") or []
        sig = ", ".join(f"{_snake(a)}: str" for a in args)
        prompt_funcs.append(
            f"@mcp.prompt(name={json.dumps(pn)}, description={json.dumps(desc)})\n"
            f"def {pn}({sig}) -> str:\n"
            f"    return {json.dumps(desc)}\n"
        )

    sdk_import = (
        "from mcp.server.fastmcp import FastMCP\n"
        if sdk == "fastmcp"
        else "from mcp.server import Server\n"
        "from mcp.server.stdio import stdio_server\n"
        "from mcp.types import Tool, TextContent\n"
    )
    run_block = (
        "if __name__ == '__main__':\n"
        "    mcp.run(transport=" + json.dumps(transport) + ")\n"
        if sdk == "fastmcp"
        else
        "async def run():\n"
        "    async with stdio_server() as (r, w):\n"
        "        await mcp.run(r, w, mcp.create_initialization_options())\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    import asyncio\n"
        "    asyncio.run(run())\n"
    )

    return (
        f'"""{name} — generated by TIMPS Swarm mcp_server_generator."""\n'
        f"from __future__ import annotations\n\n"
        f"{sdk_import}\n"
        f"mcp = FastMCP({json.dumps(name)}) if '{sdk}' == 'fastmcp' else Server({json.dumps(name)})\n\n"
        + "\n".join(tool_funcs + res_funcs + prompt_funcs)
        + "\n\n"
        + run_block
    )


def _render_pyproject(name: str, deps: List[str], cli_ep: str, sdk: str) -> str:
    pkg_dep = "mcp[cli]>=1.0" if sdk == "fastmcp" else "mcp>=1.0"
    extras = "\n    ".join(f'"{d}",' for d in deps)
    extras_block = f"    {extras}" if deps else ""
    if extras:
        runtime_deps = f"    {pkg_dep}\n    {extras}"
    else:
        runtime_deps = f"    {pkg_dep}"
    if "=" in cli_ep:
        ep_module, ep_callable = cli_ep.split("=", 1)
    else:
        ep_module, ep_callable = name, "run"
    return (
        "[build-system]\nrequires = [\"setuptools>=68\", \"wheel\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        f"[project]\nname = \"{name}\"\nversion = \"0.1.0\"\ndescription = \"MCP server generated by TIMPS Swarm\"\n"
        "requires-python = \">=3.10\"\n"
        f"dependencies = [\n{runtime_deps}\n]\n\n"
        "[project.scripts]\n"
        f"{ep_module} = \"server:{ep_callable}\"\n\n"
        "[tool.setuptools]\npy-modules = [\"server\"]\n"
    )


def _render_readme(
    name: str,
    tools: List[Dict[str, Any]],
    resources: List[Dict[str, Any]],
    prompts: List[Dict[str, Any]],
    deps: List[str],
    sdk: str,
    transport: str,
) -> str:
    tool_rows = "\n".join(
        f"- `{t.get('name','')}` — {(t.get('description') or '').strip()[:120]}"
        for t in tools
    ) or "- (none)"
    res_rows = "\n".join(
        f"- `{r.get('uri_template','')}` — {(r.get('name') or '').strip()}"
        for r in resources
    ) or "- (none)"
    prompt_rows = "\n".join(
        f"- `{p.get('name','')}` — {(p.get('description') or '').strip()[:120]}"
        for p in prompts
    ) or "- (none)"
    return (
        f"# {name}\n\n"
        f"Model Context Protocol (MCP) server generated by **TIMPS Swarm**.\n\n"
        f"- SDK: `{sdk}`\n"
        f"- Transport: `{transport}`\n"
        f"- Runtime: Python ≥ 3.10\n\n"
        f"## Tools\n{tool_rows}\n\n"
        f"## Resources\n{res_rows}\n\n"
        f"## Prompts\n{prompt_rows}\n\n"
        f"## Install\n"
        f"```bash\npython -m venv .venv && source .venv/bin/activate\n"
        f"pip install -e .\n```\n\n"
        f"## Run (stdio — for Claude Desktop, etc.)\n"
        f"```bash\n{name}\n```\n\n"
        f"## Smoke test\n"
        f"```bash\npython test_client.py\n```\n"
    )


def _render_test_client(name: str, tools: List[Dict[str, Any]], resources: List[Dict[str, Any]], prompts: List[Dict[str, Any]]) -> str:
    tool_calls = ",\n    ".join(
        f'    ("call_tool", {json.dumps(t.get("name",""))}, {{}})' for t in tools
    ) or '    ("list_tools", "", {})'
    return (
        f"\"\"\"Smoke test for {name}.  Spins up the server in-process and lists tools.\"\"\"\n"
        f"import asyncio, json, sys\nfrom mcp.client.stdio import stdio_client, StdioServerParameters\n"
        f"from mcp.client.session import ClientSession\n\n"
        f"PARAMS = StdioServerParameters(command=sys.executable, args=['server.py'])\n\n"
        f"async def main():\n"
        f"    async with stdio_client(PARAMS) as (r, w):\n"
        f"        async with ClientSession(r, w) as s:\n"
        f"            await s.initialize()\n"
        f"            tools = await s.list_tools()\n"
        f"            print('tools:', [t.name for t in tools.tools])\n"
        + (
            "\n".join(
                f"            res = await s.call_tool({json.dumps(t.get('name',''))}, {{}})\n"
                f"            print({json.dumps(t.get('name',''))}, '->', res)\n"
                for t in tools
            )
            or "            pass"
        )
        + "\n\nif __name__ == '__main__':\n    asyncio.run(main())\n"
    )


def _snake(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "item"
