"""IaC Drift Detector — diffs Terraform state against real infrastructure
or against the live plan, and produces a remediation playbook.

Inputs:

* `repo_path`     — path to the Terraform repo
* `state_path`    — path to a `terraform.tfstate` (defaults to `<repo>/terraform.tfstate`)
* `workspace`     — Terraform workspace name
* `execute_plan`  — if True, runs `terraform plan -detailed-exitcode -out=plan.bin`
                    and parses the result for drift.

If `terraform` is not on PATH, falls back to a static plan-vs-config diff
using `python-hcl2` to parse HCL files.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def iac_drift_detector(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = Path(args.get("repo_path") or ".")
    state_path = args.get("state_path")
    workspace = args.get("workspace") or "default"
    execute = bool(args.get("execute_plan", False))

    if not repo_path.is_dir():
        return {"summary": f"Repo path '{repo_path}' not found.", "error": "repo_path required",
                "drifts": []}

    if not state_path:
        for cand in ("terraform.tfstate", "terraform.tfstate.d/terraform.tfstate"):
            p = repo_path / cand
            if p.is_file():
                state_path = str(p)
                break

    if execute and shutil.which("terraform"):
        plan_summary, plan_changes = _run_terraform_plan(repo_path, workspace)
    else:
        plan_summary = "(no live plan — static analysis only)"
        plan_changes = []

    # Static config files
    config_resources = _scan_hcl(repo_path)
    state_resources = _scan_state(state_path) if state_path else []

    drifts = _compute_drift(config_resources, state_resources, plan_changes)
    remediation = _llm_remediation(drifts, plan_summary)

    payload = {
        "summary": _summary(drifts, len(config_resources), len(state_resources), plan_summary),
        "repo_path": str(repo_path),
        "state_path": state_path,
        "workspace": workspace,
        "config_resource_count": len(config_resources),
        "state_resource_count": len(state_resources),
        "plan_summary": plan_summary,
        "drifts": drifts,
        "remediation": remediation,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", repo_path.name).strip("_")[:40] or "tf"
    _save("phase7/iac_drift", f"{slug}_{_ts()}_drift.json", json.dumps(payload, indent=2))
    _record("iac_drift_detector", str(repo_path), f"drifts={len(drifts)}")
    return payload


# ---------------------------------------------------------------------------

def _run_terraform_plan(repo: Path, workspace: str) -> tuple:
    if workspace != "default":
        subprocess.run(["terraform", "workspace", "select", workspace], cwd=repo,
                       capture_output=True, text=True)
    proc = subprocess.run(
        ["terraform", "plan", "-detailed-exitcode", "-no-color"],
        cwd=repo, capture_output=True, text=True, timeout=600,
    )
    out = proc.stdout + "\n" + proc.stderr
    # Extract the "Plan:" summary line
    m = re.search(r"Plan:.*", out)
    summary = m.group(0) if m else out.strip()[:400]
    # Extract resource change lines
    changes: List[Dict[str, Any]] = []
    for line in out.splitlines():
        m = re.match(r"\s*([+#~-])\s+(\S+)\s+will be (\S+)", line)
        if m:
            changes.append({"symbol": m.group(1), "address": m.group(2), "action": m.group(3)})
    return summary.strip(), changes


def _scan_hcl(repo: Path) -> List[Dict[str, Any]]:
    """Light-weight HCL resource extraction without external deps."""
    out: List[Dict[str, Any]] = []
    for tf in list(repo.rglob("*.tf")):
        try:
            text = tf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text):
            out.append({"type": m.group(1), "name": m.group(2), "source": str(tf)})
    return out


def _scan_state(state_path: str) -> List[Dict[str, Any]]:
    if not state_path or not Path(state_path).is_file():
        return []
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in data.get("resources") or []:
        for inst in r.get("instances") or []:
            out.append({
                "type":   r.get("type", "?"),
                "name":   r.get("name", "?"),
                "module": r.get("module", ""),
                "provider": r.get("provider", ""),
                "attributes": list((inst.get("attributes") or {}).keys()),
            })
    return out


def _compute_drift(config: List[Dict[str, Any]], state: List[Dict[str, Any]], plan_changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cfg_keys = {(c["type"], c["name"]) for c in config}
    state_keys = {(s["type"], s["name"]) for s in state}

    drifts: List[Dict[str, Any]] = []
    for k in state_keys - cfg_keys:
        drifts.append({"resource_type": k[0], "resource_name": k[1],
                       "kind": "unmanaged",   # in state, not in code
                       "severity": "high",
                       "explanation": "Resource exists in state but is not declared in any .tf file — likely manual change or imported resource."})
    for k in cfg_keys - state_keys:
        drifts.append({"resource_type": k[0], "resource_name": k[1],
                       "kind": "missing",     # in code, not in state
                       "severity": "medium",
                       "explanation": "Resource declared in code but missing from state — never applied or recently destroyed."})
    for change in plan_changes:
        drifts.append({
            "resource_type": change["address"].split(".")[0] if "." in change["address"] else "?",
            "resource_name": change["address"],
            "kind": "plan_change",
            "action": change["action"],
            "symbol": change["symbol"],
            "severity": "high" if change["symbol"] in {"#", "~"} else "low",
            "explanation": f"`terraform plan` will {change['action']} this resource.",
        })
    return drifts


def _llm_remediation(drifts: List[Dict[str, Any]], plan_summary: str) -> List[Dict[str, Any]]:
    if not drifts:
        return []
    system = (
        "You are a Platform engineer producing a remediation playbook for "
        "Terraform drift.  Return ONLY a JSON object: {\"actions\": [{\"title\": str, "
        "\"steps\": [str], \"risk\": \"low\"|\"medium\"|\"high\", "
        "\"rollback\": str}]}.  No prose, no fences."
    )
    user = (
        f"Plan summary: {plan_summary}\n\n"
        f"Drifts: {json.dumps(drifts[:20])}"
    )
    raw = _llm(user, system, "iac_drift_detector")
    parsed = _parse_json(raw, fallback={"actions": []})
    return parsed.get("actions") or []


def _summary(drifts: List[Dict[str, Any]], cfg: int, st: int, plan: str) -> str:
    n = len(drifts)
    high = sum(1 for d in drifts if d.get("severity") == "high")
    return f"IaC drift: {n} drifts ({high} high) — {cfg} in code, {st} in state. Plan: {plan[:100]}"
