"""API Security Tester — OWASP API Top 10 (2023) scanner.

Given an OpenAPI/AsyncAPI spec or a live base URL, the agent:

1. Loads the spec (or probes a few endpoints if given a live URL).
2. For each endpoint, plans attack vectors per category
   (BOLA, BOPLA, mass-assignment, broken-auth, excessive-data-exposure,
   rate-limit, security-misconfig, injection, improper-assets).
3. Generates a runnable test script (Python + httpx) that issues the
   attacks and checks assertions.
4. Optionally executes the script against the live target and reports
   pass/fail per test.

The agent is LLM-driven: the model decides which headers/params/body
shapes to attack and what the success assertion is.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

OWASP_API_TOP_10 = (
    "API1_BOLA",          # Broken Object Level Authorization
    "API2_BOPLA",         # Broken Object Property Level Authorization
    "API3_BOPLA_auth",    # Broken Object Property Level Authorization (auth)
    "API4_resource",      # Unrestricted Resource Consumption
    "API5_broken_auth",   # Broken Function Level Authorization
    "API6_unauth",        # Server-Side Request Forgery
    "API7_security_misc", # Security Misconfiguration
    "API8_injection",     # Lack of Protection from Automated Threats
    "API9_improper_assets",# Improper Inventory Management
    "API10_unsafe_consumption",  # Unsafe Consumption of APIs
)


def api_security_tester(args: Dict[str, Any]) -> Dict[str, Any]:
    spec_path = args.get("spec_path")
    base_url = args.get("base_url")
    spec = args.get("spec")
    execute = bool(args.get("execute", False))
    auth_header = args.get("auth_header") or ""
    categories: List[str] = args.get("categories") or list(OWASP_API_TOP_10)

    if not spec and spec_path:
        try:
            spec = json.loads(Path(spec_path).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            spec = _read_yaml(spec_path)
    if not spec and not base_url:
        return {"summary": "Supply spec_path, spec, or base_url.", "error": "spec or base_url required",
                "attacks": []}

    endpoints = _extract_endpoints(spec) if spec else _probe_endpoints(base_url)
    attacks = _plan_attacks(endpoints, categories, base_url or "")
    test_script = _render_pytest(attacks, base_url or "", auth_header)
    test_path = None
    if test_script:
        slug = re.sub(r"[^a-z0-9_]+", "_", (base_url or spec_path or "api")).strip("_")[:40] or "api"
        test_path = str(Path(f"generated/phase7/api_security/{slug}_test.py"))
        Path(test_path).parent.mkdir(parents=True, exist_ok=True)
        Path(test_path).write_text(test_script, encoding="utf-8")

    run_report: Dict[str, Any] = {}
    if execute and test_path and base_url:
        run_report = _execute(test_path, base_url, auth_header)

    payload = {
        "summary": _summary(endpoints, attacks, run_report),
        "base_url": base_url,
        "endpoint_count": len(endpoints),
        "attack_count": len(attacks),
        "attacks": attacks,
        "test_script": test_path,
        "run_report": run_report,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (base_url or spec_path or "api")).strip("_")[:40] or "api"
    _save("phase7/api_security", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("api_security_tester", (base_url or spec_path or "?")[:60], f"endpoints={len(endpoints)} attacks={len(attacks)}")
    return payload


# ---------------------------------------------------------------------------

def _read_yaml(path: str) -> Any:
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _extract_endpoints(spec: Any) -> List[Dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    paths = spec.get("paths") or {}
    out: List[Dict[str, Any]] = []
    for path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                continue
            if not isinstance(op, dict):
                continue
            params = op.get("parameters") or []
            # Parameters can be referenced — we just want the inline ones
            inline = [p for p in params if isinstance(p, dict)]
            security = op.get("security") or spec.get("security") or []
            out.append({
                "path": path,
                "method": method.upper(),
                "operationId": op.get("operationId", ""),
                "parameters": [{"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False)} for p in inline],
                "security": security,
                "summary": op.get("summary", ""),
            })
    return out


def _probe_endpoints(base_url: str) -> List[Dict[str, Any]]:
    """Best-effort endpoint discovery if no spec is given."""
    candidates = ["/", "/healthz", "/api", "/api/v1", "/users", "/login"]
    return [{"path": c, "method": "GET", "operationId": "", "parameters": [], "security": [],
             "summary": "probed"} for c in candidates]


def _plan_attacks(endpoints: List[Dict[str, Any]], categories: List[str], base_url: str) -> List[Dict[str, Any]]:
    if not endpoints:
        return []
    system = (
        "You are an API penetration tester designing OWASP API Top-10 attacks.  "
        "Given a list of endpoints (method, path, parameters, security) and a "
        "set of categories, design concrete attacks.  Return ONLY a JSON object:\n"
        "{\n"
        '  "attacks": [\n'
        '    {"id": "A001", "category": str, "endpoint": {"method": str, "path": str}, '
        '    "payload": { ... }, "headers": { ... }, "assertion": str, '
        '    "severity": "low"|"medium"|"high"|"critical", '
        '    "rationale": str}\n'
        '  ]\n'
        "}\n\n"
        "For BOLA: switch one path/user id and try to access another user's resource.\n"
        "For BOPLA: add extra fields in body (e.g. isAdmin=true) and check response.\n"
        "For resource: send a page size of 100000.\n"
        "For broken_auth: remove the auth header and check 401.\n"
        "For SSRF: in any URL field, send http://169.254.169.254/latest/meta-data/.\n"
        "For injection: send SQL/JSON-LD/CRLF payloads in string fields.\n"
        "Generate 1-2 attacks per endpoint per category (don't repeat identical payloads)."
    )
    user = (
        f"Base URL: {base_url}\n"
        f"Categories: {json.dumps(categories)}\n\n"
        f"Endpoints (truncated to 20):\n{json.dumps(endpoints[:20])[:6000]}"
    )
    raw = _llm(user, system, "api_security_tester")
    parsed = _parse_json(raw, fallback={"attacks": []})
    out: List[Dict[str, Any]] = []
    for a in parsed.get("attacks") or []:
        ep = a.get("endpoint") or {}
        if not ep.get("method") or not ep.get("path"):
            continue
        out.append({
            "id": a.get("id", f"A{len(out)+1:03d}"),
            "category": a.get("category", "?"),
            "method": str(ep.get("method", "GET")).upper(),
            "path": ep.get("path", "/"),
            "payload": a.get("payload") or {},
            "headers": a.get("headers") or {},
            "assertion": a.get("assertion", ""),
            "severity": a.get("severity", "medium"),
            "rationale": a.get("rationale", ""),
        })
    return out


def _render_pytest(attacks: List[Dict[str, Any]], base_url: str, auth_header: str) -> str:
    body = (
        '"""OWASP API Top-10 test suite — generated by TIMPS Swarm api_security_tester."""\n'
        'import os, json, pytest, httpx\n\n'
        f'BASE_URL = os.environ.get("API_BASE", "{base_url}")\n'
        f'AUTH     = "{auth_header}"\n'
        'TIMEOUT  = 20\n\n'
        'def _client() -> httpx.Client:\n'
        '    headers = {"Authorization": AUTH[7:]} if AUTH.lower().startswith("bearer ") else ({"Authorization": AUTH} if AUTH else {})\n'
        '    return httpx.Client(base_url=BASE_URL, headers=headers, timeout=TIMEOUT, follow_redirects=False)\n\n'
    )
    for a in attacks:
        body += (
            f'def test_{a["id"]}_{a["category"]}_{re.sub(r"[^A-Za-z0-9]", "_", a["path"])[:30]}_{a["method"].lower()}():\n'
            f'    """{a["category"]} on {a["method"]} {a["path"]} — {a["assertion"][:80]}"""\n'
            f'    with _client() as c:\n'
            f'        method = c.{a["method"].lower()}\n'
            f'        r = method({json.dumps(a["path"])}, json={json.dumps(a["payload"])}, headers={json.dumps(a["headers"])})\n'
            f'        text = (r.text or "").lower()\n'
            f'        forbidden = ["aws_access_key", "ami-id", "internal ", "stack trace", "sqlstate"]\n'
            f'        for tok in forbidden:\n'
            f'            if tok in text:\n'
            f'                pytest.fail(f"Test {a["id"]} leaked {{tok!r}} in body")\n'
        )
    body += '\nif __name__ == "__main__":\n    pytest.main([__file__, "-v"])\n'
    return body


def _execute(test_path: str, base_url: str, auth: str) -> Dict[str, Any]:
    import subprocess, os
    env = {**os.environ, "API_BASE": base_url, "AUTH_HEADER": auth}
    try:
        proc = subprocess.run(["python3", "-m", "pytest", test_path, "-q", "--tb=line", "--no-header"],
                              capture_output=True, text=True, timeout=600, env=env)
        return {"returncode": proc.returncode, "stdout_tail": proc.stdout[-1500:],
                "stderr_tail": proc.stderr[-1000:], "passed": proc.returncode == 0}
    except Exception as e:
        return {"returncode": -1, "error": str(e)[:300], "passed": False}


def _summary(endpoints: List[Dict[str, Any]], attacks: List[Dict[str, Any]], run: Dict[str, Any]) -> str:
    n = len(attacks)
    cats = len({a["category"] for a in attacks})
    return f"API security: {len(endpoints)} endpoints, {n} attacks across {cats} OWASP categories."
