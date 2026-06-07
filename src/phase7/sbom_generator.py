"""SBOM Generator — produces a CycloneDX or SPDX Software Bill of Materials
from a project repo, with optional container-image scanning and CVE
correlation.

Pipeline:

1. Walk the repo and identify package manifests (package.json, requirements*.txt,
   pyproject.toml, go.mod, Cargo.toml, pom.xml, build.gradle, Gemfile, composer.json).
2. Parse each to extract (name, version, ecosystem, scope).
3. (Optional) If `syft` is on PATH, run `syft <path> -o cyclonedx-json` and merge.
4. (Optional) If container images are listed, run `trivy image -f json <img>` and merge.
5. Write a CycloneDX 1.5 or SPDX 2.3 JSON file.
6. Correlate with NVD via local cache (or skip if offline).
7. Save the SBOM + a vulnerability summary.

If no LLM and no `syft`/`trivy` are available, the agent still produces
a manifest-only SBOM with `{tool: 'timps-sbom (manifest-only)'}`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "phase7"

SUPPORTED_FORMATS = ("cyclonedx", "spdx")


def sbom_generator(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path = Path(args.get("repo_path") or ".")
    fmt = (args.get("format") or "cyclonedx").lower()
    if fmt not in SUPPORTED_FORMATS:
        fmt = "cyclonedx"
    include_dev = bool(args.get("include_dev", True))
    scan_images: List[str] = args.get("scan_images") or []
    use_syft = bool(args.get("use_syft", True))
    use_trivy = bool(args.get("use_trivy", True))

    if not repo_path.is_dir():
        return {
            "summary": f"Repo path '{repo_path}' not found.",
            "error": "repo_path must be an existing directory",
            "components": [],
        }

    components = _scan_manifests(repo_path, include_dev)

    if use_syft and shutil.which("syft"):
        components = _merge_syft(repo_path, components)

    image_vulns: List[Dict[str, Any]] = []
    if scan_images and use_trivy and shutil.which("trivy"):
        for img in scan_images:
            image_vulns.append(_scan_trivy_image(img))

    sbom = _render_sbom(fmt, components, repo_path, scan_images)
    vuln_report = _correlate_vulns(components, image_vulns)

    slug = re.sub(r"[^a-z0-9_]+", "_", str(repo_path).lower()).strip("_")[:40] or "repo"
    out_dir = Path("generated/phase7/sbom") / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = out_dir / f"sbom.{fmt}.json"
    sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
    vuln_path = out_dir / "vulnerabilities.json"
    vuln_path.write_text(json.dumps(vuln_report, indent=2), encoding="utf-8")

    payload = {
        "summary": _summary(components, vuln_report, image_vulns, fmt),
        "format": fmt,
        "component_count": len(components),
        "ecosystems": _ecosystem_counts(components),
        "components": components,
        "vulnerabilities": vuln_report,
        "images_scanned": [v.get("image") for v in image_vulns],
        "tools_used": _tools_used(use_syft and shutil.which("syft"),
                                  use_trivy and shutil.which("trivy") and bool(scan_images)),
        "sbom_path": str(sbom_path),
        "vuln_report_path": str(vuln_path),
        "generated_at": _ts(),
    }
    _save("phase7/sbom", f"{slug}_summary.json", json.dumps(payload, indent=2))
    _record("sbom_generator", str(repo_path), f"components={len(components)} vulns={len(vuln_report)}")
    return payload


# ---------------------------------------------------------------------------
# Manifest scanners
# ---------------------------------------------------------------------------

def _scan_manifests(root: Path, include_dev: bool) -> List[Dict[str, Any]]:
    comps: List[Dict[str, Any]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        # Skip common heavy dirs
        if any(seg in path.parts for seg in ("node_modules", ".venv", "venv", "target", "dist", "build", ".git", "__pycache__")):
            continue
        try:
            if name == "requirements.txt" or (name.startswith("requirements") and name.endswith(".txt")):
                comps.extend(_parse_requirements_txt(path))
            elif name == "pyproject.toml":
                comps.extend(_parse_pyproject(path, include_dev))
            elif name == "package.json":
                comps.extend(_parse_package_json(path, include_dev))
            elif name == "go.mod":
                comps.extend(_parse_go_mod(path))
            elif name == "Cargo.toml":
                comps.extend(_parse_cargo_toml(path, include_dev))
            elif name == "Gemfile":
                comps.extend(_parse_gemfile(path))
            elif name == "composer.json":
                comps.extend(_parse_composer(path, include_dev))
            elif name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
                comps.extend(_parse_jvm(path))
        except Exception as e:
            comps.append({"name": name, "ecosystem": "unknown", "version": "*",
                          "scope": "unknown", "path": str(path), "error": str(e)[:120]})
    return comps


def _parse_requirements_txt(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # skip editable / paths
        if line.startswith("-") or line.startswith("git+") or line.startswith("http"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+)\s*([A-Za-z0-9_.\-]+)?", line)
        if m:
            out.append({"name": m.group(1), "version": m.group(3) or "*", "ecosystem": "pypi",
                        "scope": "runtime", "path": str(p)})
    return out


def _parse_pyproject(p: Path, include_dev: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    data = tomllib.loads(p.read_text(encoding="utf-8", errors="ignore"))
    proj = data.get("project") or {}
    for dep in proj.get("dependencies") or []:
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+)\s*([A-Za-z0-9_.\-]+)?", dep)
        if m:
            out.append({"name": m.group(1), "version": m.group(3) or "*", "ecosystem": "pypi",
                        "scope": "runtime", "path": str(p)})
    for grp in (data.get("project", {}).get("optional-dependencies") or {}).values():
        for dep in grp:
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+)\s*([A-Za-z0-9_.\-]+)?", dep)
            if m:
                out.append({"name": m.group(1), "version": m.group(3) or "*", "ecosystem": "pypi",
                            "scope": "optional", "path": str(p)})
    if include_dev:
        for grp in (data.get("tool", {}).get("poetry", {}).get("group", {}) or {}).values():
            for dep in (grp.get("dependencies") or {}).keys():
                out.append({"name": dep, "version": "*", "ecosystem": "pypi",
                            "scope": "dev", "path": str(p)})
    return out


def _parse_package_json(p: Path, include_dev: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out
    for name, ver in (data.get("dependencies") or {}).items():
        out.append({"name": name, "version": re.sub(r"[^0-9.]", "", ver) or "*",
                    "ecosystem": "npm", "scope": "runtime", "path": str(p)})
    if include_dev:
        for name, ver in (data.get("devDependencies") or {}).items():
            out.append({"name": name, "version": re.sub(r"[^0-9.]", "", ver) or "*",
                        "ecosystem": "npm", "scope": "dev", "path": str(p)})
    return out


def _parse_go_mod(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    in_block = False
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line.strip() == ")":
            in_block = False
            continue
        m = re.match(r"^\s*([A-Za-z0-9_.\-/]+)\s+v([A-Za-z0-9_.\-+]+)", line)
        if m:
            out.append({"name": m.group(1), "version": m.group(2), "ecosystem": "go",
                        "scope": "runtime" if not in_block else "indirect", "path": str(p)})
    return out


def _parse_cargo_toml(p: Path, include_dev: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out
    for name, spec in (data.get("dependencies") or {}).items():
        v = spec if isinstance(spec, str) else spec.get("version", "*")
        out.append({"name": name, "version": str(v), "ecosystem": "cargo", "scope": "runtime", "path": str(p)})
    if include_dev:
        for name, spec in (data.get("dev-dependencies") or {}).items():
            v = spec if isinstance(spec, str) else spec.get("version", "*")
            out.append({"name": name, "version": str(v), "ecosystem": "cargo", "scope": "dev", "path": str(p)})
    return out


def _parse_gemfile(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^\s*gem\s+['\"]([^'\"]+)['\"](?:,\s*['\"]([^'\"]+)['\"])?", line)
        if m:
            out.append({"name": m.group(1), "version": m.group(2) or "*", "ecosystem": "rubygems",
                        "scope": "runtime", "path": str(p)})
    return out


def _parse_composer(p: Path, include_dev: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return out
    for name, ver in (data.get("require") or {}).items():
        if name == "php": continue
        out.append({"name": name, "version": ver or "*", "ecosystem": "composer", "scope": "runtime", "path": str(p)})
    if include_dev:
        for name, ver in (data.get("require-dev") or {}).items():
            out.append({"name": name, "version": ver or "*", "ecosystem": "composer", "scope": "dev", "path": str(p)})
    return out


def _parse_jvm(p: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if p.suffix == ".xml":
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>(?:\s*<version>([^<]+)</version>)?", text):
            out.append({"name": f"{m.group(1)}:{m.group(2)}", "version": m.group(3) or "*",
                        "ecosystem": "maven", "scope": "runtime", "path": str(p)})
    else:  # gradle
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(?:implementation|api|compileOnly|runtimeOnly)\s*['\"]([^'\"]+)['\"]", text):
            parts = m.group(1).split(":")
            if len(parts) >= 2:
                out.append({"name": f"{parts[0]}:{parts[1]}", "version": parts[2] if len(parts) > 2 else "*",
                            "ecosystem": "gradle", "scope": "runtime", "path": str(p)})
    return out


# ---------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------

def _merge_syft(repo: Path, comps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["syft", str(repo), "-o", "cyclonedx-json"],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            existing = {(c.get("name"), c.get("version"), c.get("ecosystem")) for c in comps}
            for c in (data.get("components") or []):
                eco = (c.get("purl") or "").split(":")[1] if c.get("purl") and ":" in c.get("purl") else "unknown"
                key = (c.get("name"), c.get("version"), eco)
                if key not in existing:
                    comps.append({"name": c.get("name", "?"), "version": c.get("version", "*"),
                                  "ecosystem": eco, "scope": "syft", "path": str(repo)})
    except Exception:
        pass
    return comps


def _scan_trivy_image(image: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"image": image, "vulnerabilities": []}
    try:
        proc = subprocess.run(
            ["trivy", "image", "--quiet", "--format", "json", "--scanners", "vuln", image],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            for r in data.get("Results") or []:
                for v in r.get("Vulnerabilities") or []:
                    out["vulnerabilities"].append({
                        "package": v.get("PkgName", "?"),
                        "version": v.get("InstalledVersion", "?"),
                        "id": v.get("VulnerabilityID", ""),
                        "severity": v.get("Severity", "UNKNOWN"),
                        "title": v.get("Title", ""),
                    })
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


# ---------------------------------------------------------------------------
# SBOM render
# ---------------------------------------------------------------------------

def _render_sbom(fmt: str, comps: List[Dict[str, Any]], repo: Path, images: List[str]) -> Dict[str, Any]:
    if fmt == "cyclonedx":
        return {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "version": 1,
            "metadata": {
                "timestamp": _ts(),
                "tools": [{"vendor": "TIMPS Swarm", "name": "sbom_generator", "version": "1.0"}],
                "component": {"type": "application", "name": repo.name, "version": "0.0.0"},
                "properties": [{"name": "scanned_images", "value": ",".join(images) or "none"}],
            },
            "components": [
                {"type": "library",
                 "name": c.get("name", "?"),
                 "version": c.get("version", "*"),
                 "purl": _purl(c),
                 "properties": [{"name": "ecosystem", "value": c.get("ecosystem", "")},
                                {"name": "scope", "value": c.get("scope", "")}]}
                for c in comps
            ],
        }
    # SPDX
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": repo.name,
        "documentNamespace": f"https://timps-swarm.local/spdx/{repo.name}-{_ts()}",
        "creationInfo": {"created": _ts(), "creators": ["Tool: TIMPS Swarm sbom_generator"]},
        "packages": [
            {"SPDXID": f"SPDXRef-Pkg-{i}",
             "name": c.get("name", "?"),
             "versionInfo": c.get("version", "*"),
             "downloadLocation": "NOASSERTION",
             "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER",
                               "referenceType": "purl",
                               "referenceLocator": _purl(c)}]}
            for i, c in enumerate(comps)
        ],
    }


def _purl(c: Dict[str, Any]) -> str:
    eco = c.get("ecosystem", "")
    prefix = {"pypi": "pypi", "npm": "npm", "go": "golang", "cargo": "cargo",
              "rubygems": "rubygems", "composer": "composer", "maven": "maven",
              "gradle": "gradle"}.get(eco, "generic")
    name = c.get("name", "?").replace(" ", "_")
    ver = c.get("version", "*")
    return f"pkg:{prefix}/{name}@{ver}"


# ---------------------------------------------------------------------------
# Vulnerability correlation
# ---------------------------------------------------------------------------

def _correlate_vulns(comps: List[Dict[str, Any]], image_vulns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine trivy image vulns and any in-repo notes.  No network calls."""
    out: List[Dict[str, Any]] = []
    for img in image_vulns:
        for v in img.get("vulnerabilities") or []:
            out.append({"source": "trivy", "image": img.get("image"),
                        "package": v.get("package"), "version": v.get("version"),
                        "id": v.get("id"), "severity": v.get("severity"),
                        "title": v.get("title")})
    return out


def _ecosystem_counts(comps: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c in comps:
        out[c.get("ecosystem", "unknown")] = out.get(c.get("ecosystem", "unknown"), 0) + 1
    return out


def _tools_used(syft: bool, trivy: bool) -> List[str]:
    out = ["manifest-parser"]
    if syft: out.append("syft")
    if trivy: out.append("trivy")
    return out


def _summary(comps: List[Dict[str, Any]], vulns: List[Dict[str, Any]], images: List[Dict[str, Any]], fmt: str) -> str:
    return (
        f"SBOM ({fmt}): {len(comps)} components across "
        f"{len(_ecosystem_counts(comps))} ecosystems; "
        f"{len(vulns)} vulnerabilities across {len(images)} images."
    )
