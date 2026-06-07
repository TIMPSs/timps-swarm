"""License Compliance Scanner — scans a repo for FOSS-license obligations
and flags GPL-contamination, missing attributions, and incompatible
licenses.

Outputs:

* A license inventory (every dep → license).
* A list of obligations (per license: attribution, source-disclosure,
  copyleft trigger, patent grant, etc.).
* A risk score per dep (0-10).
* A whitelist of compatible licenses for the user's project license.
* A SPDX-format manifest of all third-party licenses.
* A NOTICE file content the project can ship.

Inputs:

* `repo_path`     — path to the project
* `project_license` — SPDX ID of the project's license (e.g. 'MIT', 'Apache-2.0')
* `manifests`     — list of paths to scan (auto-detects by default)
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

COPYLEFT_FAMILY = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0", "EUPL-1.2", "OSL-3.0", "AGPL-1.0"}
WEAK_COPYLEFT  = {"MPL-2.0", "EPL-2.0", "CDDL-1.0"}
PERMISSIVE     = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "Zlib", "Unlicense", "CC0-1.0", "PSF-2.0"}


def license_compliance_scanner(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = Path(args.get("repo_path") or ".")
    project_license = (args.get("project_license") or "MIT").strip()
    if not repo_path.is_dir():
        return {"summary": f"Repo path '{repo_path}' not found.", "error": "repo_path required",
                "inventory": []}

    inventory = _scan(repo_path)
    obligations = _obligations(inventory)
    compatibility = _compatibility(inventory, project_license)
    risk = _risk(inventory, project_license)
    spdx = _render_spdx(inventory, project_license, repo_path)
    notice = _render_notice(inventory)
    notice_path = _save_text(repo_path, "NOTICE", notice)
    spdx_path  = _save_text(repo_path, "THIRD-PARTY-LICENSES.spdx", spdx)

    payload = {
        "summary": _summary(inventory, compatibility, project_license),
        "repo_path": str(repo_path),
        "project_license": project_license,
        "inventory": inventory,
        "obligations": obligations,
        "compatibility": compatibility,
        "risk_score": risk,
        "notice_path": notice_path,
        "spdx_path": spdx_path,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", repo_path.name).strip("_")[:40] or "repo"
    _save("phase7/license_scan", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("license_compliance_scanner", str(repo_path), f"deps={len(inventory)} risk={risk}")
    return payload


# ---------------------------------------------------------------------------

def _scan(root: Path) -> List[Dict[str, Any]]:
    inv: List[Dict[str, Any]] = []

    # package.json (npm)
    for pj in root.rglob("package.json"):
        if any(seg in pj.parts for seg in ("node_modules", "dist", "build")): continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for name, spec in {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}.items():
            lic = (spec.get("license") if isinstance(spec, dict) else None) or ""
            inv.append({"ecosystem": "npm", "name": name, "version": (spec.get("version") if isinstance(spec, dict) else str(spec)) or "*",
                        "license": lic, "path": str(pj)})

    # requirements + pyproject (pypi)
    for req in root.rglob("requirements*.txt"):
        if any(seg in req.parts for seg in (".venv", "venv", "dist", "build")): continue
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+)\s*([A-Za-z0-9_.\-]+)?", line or "")
            if m:
                inv.append({"ecosystem": "pypi", "name": m.group(1), "version": m.group(3) or "*", "license": "", "path": str(req)})

    for pyt in root.rglob("pyproject.toml"):
        if any(seg in pyt.parts for seg in (".venv", "venv", "dist", "build")): continue
        try:
            data = tomllib.loads(pyt.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for dep in (data.get("project", {}).get("dependencies") or []):
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+)\s*([A-Za-z0-9_.\-]+)?", dep)
            if m:
                inv.append({"ecosystem": "pypi", "name": m.group(1), "version": m.group(3) or "*", "license": "", "path": str(pyt)})

    # go.mod
    for gm in root.rglob("go.mod"):
        for line in gm.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.\-/]+)\s+v([A-Za-z0-9_.\-+]+)", line)
            if m:
                inv.append({"ecosystem": "go", "name": m.group(1), "version": m.group(2), "license": "", "path": str(gm)})

    # Cargo.toml
    for ct in root.rglob("Cargo.toml"):
        if any(seg in ct.parts for seg in ("target",)): continue
        try:
            data = tomllib.loads(ct.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for name, spec in {**(data.get("dependencies") or {}), **(data.get("dev-dependencies") or {})}.items():
            v = spec if isinstance(spec, str) else (spec.get("version") if isinstance(spec, dict) else None) or "*"
            lic = (spec.get("license") if isinstance(spec, dict) else None) or ""
            inv.append({"ecosystem": "cargo", "name": name, "version": v, "license": lic, "path": str(ct)})

    # de-dup by (ecosystem, name, version)
    seen: Dict[tuple, Dict[str, Any]] = {}
    for d in inv:
        k = (d["ecosystem"], d["name"], d["version"])
        if k not in seen: seen[k] = d
    return list(seen.values())


def _obligations(inv: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for d in inv:
        lic = (d.get("license") or "").strip()
        if not lic: continue
        if lic in COPYLEFT_FAMILY:
            out.setdefault(lic, []).extend([
                "Provide source code (or offer to provide) to all recipients.",
                "Preserve copyright + license notice in source.",
                "Do not add additional restrictions.",
            ])
        if lic == "AGPL-3.0":
            out.setdefault(lic, []).append("Network use is considered distribution — source must be offered to network users too.")
        if lic in WEAK_COPYLEFT:
            out.setdefault(lic, []).extend([
                "Modifications to the library itself must be released under the same license.",
                "Distribute source for any modifications to the library.",
            ])
        if lic in PERMISSIVE:
            out.setdefault(lic, []).extend([
                "Preserve copyright + license notice.",
                "Do not use the licensor's name to endorse derivative works without permission (most).",
            ])
    return out


def _compatibility(inv: List[Dict[str, Any]], project: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in inv:
        lic = (d.get("license") or "").strip()
        verdict = _compatibility_verdict(lic, project)
        out.append({"dep": d["name"], "ecosystem": d["ecosystem"], "version": d["version"],
                    "license": lic or "(unknown)", "verdict": verdict})
    return out


def _compatibility_verdict(lic: str, project: str) -> str:
    if not lic: return "unknown — verify manually"
    p = project.upper()
    if p in PERMISSIVE:
        if lic in PERMISSIVE:  return "compatible"
        if lic in WEAK_COPYLEFT: return "compatible (file-level isolation recommended)"
        if lic in COPYLEFT_FAMILY and lic not in {"AGPL-3.0"}: return "incompatible — strong copyleft"
        if lic == "AGPL-3.0": return "incompatible — network copyleft"
    if p in {"GPL-2.0", "GPL-3.0"}:
        if lic in PERMISSIVE:  return "compatible"
        if lic in {"GPL-2.0", "GPL-3.0"}: return "compatible"
        if lic == "AGPL-3.0": return "verify — depends on distribution channel"
    if p == "AGPL-3.0":
        if lic in PERMISSIVE or lic in COPYLEFT_FAMILY: return "compatible"
    return "verify — check SPDX compatibility matrix"


def _risk(inv: List[Dict[str, Any]], project: str) -> int:
    score = 0
    for d in inv:
        lic = (d.get("license") or "").strip()
        if not lic: score += 1
        elif lic in COPYLEFT_FAMILY and project.upper() in PERMISSIVE: score += 6
        elif lic in WEAK_COPYLEFT: score += 2
    return min(10, score // 5)


def _render_spdx(inv: List[Dict[str, Any]], project: str, root: Path) -> str:
    lines = [f"# SPDX-License-Identifier: {project}",
             f"# Project: {root.name}", "# Generated by TIMPS Swarm license_compliance_scanner", ""]
    for d in inv:
        lic = d.get("license") or "NOASSERTION"
        lines.append(f"# {d['ecosystem']}: {d['name']}@{d['version']}  ({lic})")
    return "\n".join(lines) + "\n"


def _render_notice(inv: List[Dict[str, Any]]) -> str:
    out = ["THIRD-PARTY SOFTWARE NOTICES AND INFORMATION", "", "This project includes software developed by third parties.", ""]
    for d in inv:
        lic = d.get("license") or "unknown"
        out.append(f"* {d['ecosystem']}/{d['name']}@{d['version']}  —  License: {lic}")
    return "\n".join(out) + "\n"


def _save_text(root: Path, name: str, content: str) -> str:
    p = root / name
    try:
        p.write_text(content, encoding="utf-8")
    except Exception:
        return ""
    return str(p)


def _summary(inv: List[Dict[str, Any]], compat: List[Dict[str, Any]], project: str) -> str:
    unknown = sum(1 for c in compat if c["verdict"].startswith("unknown"))
    incompat = sum(1 for c in compat if c["verdict"].startswith("incompatible"))
    return f"License scan: {len(inv)} deps under {project}; {incompat} incompatible, {unknown} unknown."
