"""Container Image Scanner — Trivy/Grype wrapper + manifest-only fallback.

Scans a list of container image references (or a Dockerfile that builds
one) and returns a severity-ranked vulnerability list with concrete
remediation suggestions (base-image bumps, multi-stage rebuilds, distroless
alternatives, package pin hints).

If neither `trivy` nor `grype` is on PATH, the agent falls back to a
manifest-only analysis: parses the Dockerfile and emits best-practice
hints (e.g. "use :slim or :alpine", "pin to a digest", "add a non-root USER").
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

SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0, "NEGLIGIBLE": 0}


def container_image_scanner(args: Dict[str, Any]) -> Dict[str, Any]:
    images: List[str] = list(args.get("images") or [])
    dockerfile = args.get("dockerfile")
    if dockerfile and not images:
        images = _extract_from_dockerfile(dockerfile)
    use_trivy = bool(args.get("use_trivy", True))
    use_grype = bool(args.get("use_grype", True))
    severity_floor = (args.get("severity_floor") or "LOW").upper()

    if not images and not dockerfile:
        return {"summary": "No images or dockerfile supplied.", "error": "supply images[] or dockerfile path",
                "findings": []}

    all_findings: List[Dict[str, Any]] = []
    image_meta: List[Dict[str, Any]] = []

    for img in images:
        meta = {"image": img, "scanner": None, "findings": 0, "by_severity": {}}
        try:
            if use_trivy and shutil.which("trivy"):
                findings = _trivy(img)
                meta["scanner"] = "trivy"
            elif use_grype and shutil.which("grype"):
                findings = _grype(img)
                meta["scanner"] = "grype"
            else:
                findings = _fallback_static(img)
                meta["scanner"] = "manifest-only"
        except Exception as e:
            findings = []
            meta["error"] = str(e)[:200]
        meta["findings"] = len(findings)
        meta["by_severity"] = _severity_breakdown(findings)
        image_meta.append(meta)
        all_findings.extend({"image": img, **f} for f in findings)

    ranked = sorted(all_findings, key=lambda f: -SEVERITY_RANK.get(f.get("severity", "UNKNOWN"), 0))
    filtered = [f for f in ranked if SEVERITY_RANK.get(f.get("severity", "UNKNOWN"), 0) >= SEVERITY_RANK.get(severity_floor, 0)]

    remediation = _llm_remediation(filtered, images)

    payload = {
        "summary": _summary(image_meta, filtered, severity_floor),
        "images": image_meta,
        "findings": filtered,
        "total_findings": len(filtered),
        "severity_floor": severity_floor,
        "remediation": remediation,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (images[0] if images else "dockerfile")).strip("_")[:40] or "scan"
    _save("phase7/image_scan", f"{slug}_{_ts()}_scan.json", json.dumps(payload, indent=2))
    _record("container_image_scanner", (images or [dockerfile])[0], f"findings={len(filtered)}")
    return payload


# ---------------------------------------------------------------------------

def _extract_from_dockerfile(path: str) -> List[str]:
    p = Path(path)
    if not p.is_file():
        return []
    images: List[str] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^FROM\s+([^\s]+)", line.strip(), re.I)
        if m and m.group(1).lower() not in {"scratch"}:
            images.append(m.group(1))
    return images


def _trivy(image: str) -> List[Dict[str, Any]]:
    proc = subprocess.run(
        ["trivy", "image", "--quiet", "--format", "json", "--scanners", "vuln",
         "--severity", "CRITICAL,HIGH,MEDIUM,LOW", image],
        capture_output=True, text=True, timeout=600,
    )
    out: List[Dict[str, Any]] = []
    if proc.returncode != 0 or not proc.stdout.strip():
        return out
    data = json.loads(proc.stdout)
    for r in data.get("Results") or []:
        for v in r.get("Vulnerabilities") or []:
            out.append({
                "package": v.get("PkgName", "?"),
                "version": v.get("InstalledVersion", "?"),
                "fix": v.get("FixedVersion", ""),
                "id": v.get("VulnerabilityID", ""),
                "severity": v.get("Severity", "UNKNOWN"),
                "title": (v.get("Title") or "")[:160],
                "target": r.get("Target", ""),
            })
    return out


def _grype(image: str) -> List[Dict[str, Any]]:
    proc = subprocess.run(
        ["grype", "-o", "json", image],
        capture_output=True, text=True, timeout=600,
    )
    out: List[Dict[str, Any]] = []
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        return out
    data = json.loads(proc.stdout)
    for m in data.get("matches") or []:
        v = m.get("vulnerability") or {}
        out.append({
            "package": (m.get("artifact") or {}).get("name", "?"),
            "version": (m.get("artifact") or {}).get("version", "?"),
            "fix": (v.get("fix") or {}).get("versions", [""])[0] if isinstance(v.get("fix"), dict) else "",
            "id": v.get("id", ""),
            "severity": (v.get("severity") or "UNKNOWN").upper(),
            "title": (v.get("description") or "")[:160],
        })
    return out


def _fallback_static(image: str) -> List[Dict[str, Any]]:
    """Heuristic Dockerfile/image hints when no scanner is available."""
    out: List[Dict[str, Any]] = []
    if image.endswith(":latest") or ":" not in image.split("/")[-1]:
        out.append({"package": "base-image", "version": "latest", "fix": "pin to a specific tag or digest",
                    "id": "PIN-LATEST", "severity": "MEDIUM",
                    "title": "Image uses :latest or untagged base — no reproducible builds.",
                    "target": "FROM"})
    if image.startswith(("ubuntu:", "debian:", "node:", "python:")):
        out.append({"package": "base-image", "version": image, "fix": "distroless or -slim variant",
                    "id": "DISTROLESS", "severity": "LOW",
                    "title": "Consider distroless or slim variant to reduce attack surface.",
                    "target": "FROM"})
    if "library/" not in image and "/" not in image:
        out.append({"package": "image-source", "version": image, "fix": "use a trusted registry",
                    "id": "UNVERIFIED", "severity": "MEDIUM",
                    "title": "Image is not from a verified publisher — verify provenance.",
                    "target": "FROM"})
    return out


def _severity_breakdown(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for f in findings:
        s = f.get("severity", "UNKNOWN")
        out[s] = out.get(s, 0) + 1
    return out


def _llm_remediation(findings: List[Dict[str, Any]], images: List[str]) -> List[Dict[str, Any]]:
    if not findings:
        return []
    system = (
        "You are a container security engineer.  Given a deduplicated set of "
        "vulnerabilities and the images they affect, propose concrete "
        "remediation actions in priority order.  Return ONLY a JSON object: "
        "{\"actions\": [{\"title\": str, \"images\": [str], \"commands\": [str], "
        "\"impact\": \"low\"|\"medium\"|\"high\"}]}  No prose, no fences."
    )
    user = (
        f"Images: {json.dumps(images)}\n\n"
        f"Top findings (max 20): {json.dumps(findings[:20])}"
    )
    raw = _llm(user, system, "container_image_scanner")
    parsed = _parse_json(raw, fallback={"actions": []})
    return parsed.get("actions") or []


def _summary(meta: List[Dict[str, Any]], findings: List[Dict[str, Any]], floor: str) -> str:
    n = len(findings)
    n_crit = sum(1 for f in findings if f.get("severity") == "CRITICAL")
    n_high = sum(1 for f in findings if f.get("severity") == "HIGH")
    return (f"Image scan: {len(meta)} images, {n} findings ≥{floor} "
            f"({n_crit} critical, {n_high} high).")
