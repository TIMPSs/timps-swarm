"""
Technical Writer Assistant — continuously generates and maintains
documentation that stays in sync with code.

Scans a repo for stale README sections, missing API references, missing
or outdated ADRs (Architecture Decision Records), unclear setup steps,
and missing contribution guides. Produces a refresh PR-style bundle:
updated README, generated API reference, an ADR template filled from
recent significant commits, and a contributor guide.

Input:  repo_path (str), focus (str), readme_text (str), code_sample (str),
        audience (str), include_adr (bool)
Output: refreshed_readme, api_reference_md, adr_drafts, contributing_md,
        doc_freshness_score, stale_sections, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _collect_repo_signal(repo_path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    root = Path(repo_path or ".")
    for fname in ("README.md", "README.rst", "README.txt",
                  "CONTRIBUTING.md", "docs/index.md",
                  "pyproject.toml", "package.json", "Cargo.toml", "go.mod"):
        p = root / fname
        if p.is_file():
            out[fname] = p.read_text(encoding="utf-8", errors="ignore")[:2500]
    # Recent ADRs
    adr_dirs = [root / "docs" / "adr", root / "doc" / "adr", root / "adr"]
    for d in adr_dirs:
        if d.is_dir():
            files = sorted(d.rglob("*.md"))[-5:]
            out["recent_adrs"] = "\n\n".join(
                f"### {f.name}\n" + f.read_text(encoding="utf-8", errors="ignore")[:800]
                for f in files)
            break
    # Recent significant commits (features/breaking)
    out["significant_commits"] = _run(
        "git log --pretty=format:'%h|%s' -n 40 | "
        "grep -iE 'feat|break|major|refactor' | head -25",
        cwd=str(root), timeout=8)[:2500]
    return out


def tech_writer_assistant(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path     = args.get("repo_path", ".")
    focus         = args.get("focus", "all")  # all|readme|api|adr|contributing
    readme_text   = args.get("readme_text", "")
    code_sample   = args.get("code_sample", "")
    audience      = args.get("audience", "developers")
    include_adr   = bool(args.get("include_adr", True))

    signal = _collect_repo_signal(repo_path)
    if not readme_text:
        readme_text = signal.get("README.md") or signal.get("README.rst", "")

    manifest_blob = "\n\n".join(
        f"### {k}\n{v}" for k, v in signal.items()
        if k in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod"))

    system = (
        "You are a senior technical writer who ships docs PRs. Produce the "
        "REFRESHED versions of the docs below — never just suggest. Maintain "
        "the existing tone of the repo, fix factual drift, and add what's "
        "missing. For ADRs, draft one ADR per significant commit theme. "
        "Output ONLY JSON: "
        "{doc_freshness_score:int (0-100), audience:str, "
        "stale_sections:[{section,why_stale,replacement_md}], "
        "refreshed_readme_md:str, "
        "api_reference_md:str, "
        "adr_drafts:[{number,title,context,decision,consequences,status_md}], "
        "contributing_md:str, "
        "quickstart_commands:[{shell,description}], "
        "diagrams_to_add:[{title,mermaid_code}], "
        "doc_lint_warnings:[{file,issue,fix}], "
        "next_writing_actions:[str]}."
    )
    prompt = (
        f"Focus: {focus}\nAudience: {audience}\nInclude ADRs: {include_adr}\n\n"
        f"Manifest signal:\n{manifest_blob}\n\n"
        f"Existing README:\n```md\n{readme_text[:4000]}\n```\n\n"
        f"Recent significant commits:\n{signal.get('significant_commits','(none)')}\n\n"
        f"Existing ADRs sample:\n{signal.get('recent_adrs','(none)')}\n\n"
        f"Code sample (for API ref):\n```\n{code_sample[:3000]}\n```\n\n"
        "Refreshed README must be a drop-in replacement."
    )

    data = _parse_json(_llm(prompt, system, "tech_writer_assistant"), {
        "doc_freshness_score": 0, "stale_sections": [],
        "refreshed_readme_md": "", "adr_drafts": [],
        "api_reference_md": "", "contributing_md": "",
    })

    ts = _ts()
    paths: Dict[str, str] = {}
    if data.get("refreshed_readme_md"):
        paths["readme"] = _save("docs", f"README_refreshed_{ts}.md",
                                data["refreshed_readme_md"])
    if data.get("api_reference_md"):
        paths["api_reference"] = _save("docs", f"API_REFERENCE_{ts}.md",
                                       data["api_reference_md"])
    if data.get("contributing_md"):
        paths["contributing"] = _save("docs", f"CONTRIBUTING_{ts}.md",
                                      data["contributing_md"])

    adr_paths: List[str] = []
    if include_adr:
        for adr in data.get("adr_drafts", []):
            num = str(adr.get("number") or len(adr_paths) + 1).zfill(4)
            fname = f"{num}-{(adr.get('title','adr') or 'adr').lower().replace(' ', '-')}_{ts}.md"
            body = (
                f"# {num} — {adr.get('title','?')}\n\n"
                f"**Status:** {adr.get('status_md','Proposed')}\n\n"
                f"## Context\n{adr.get('context','')}\n\n"
                f"## Decision\n{adr.get('decision','')}\n\n"
                f"## Consequences\n{adr.get('consequences','')}\n"
            )
            adr_paths.append(_save("docs/adr", fname, body))

    diagram_paths: List[str] = []
    for d in data.get("diagrams_to_add", []):
        fname = f"{(d.get('title','diagram') or 'diagram').lower().replace(' ', '_')}_{ts}.mmd"
        diagram_paths.append(_save("docs/diagrams", fname,
                                    d.get("mermaid_code", "") or "graph TD\n  A-->B"))

    report = (
        f"# Tech Writer Assistant — {ts}\n\n"
        f"**Freshness score:** {data.get('doc_freshness_score','?')}/100  "
        f"**Audience:** {audience}\n\n"
        f"**Stale sections:** {len(data.get('stale_sections', []))}  "
        f"**ADRs drafted:** {len(adr_paths)}  "
        f"**Diagrams:** {len(diagram_paths)}\n\n"
        "## Stale sections\n"
        + "\n".join(
            f"- **{s.get('section','?')}** — {s.get('why_stale','')}"
            for s in data.get("stale_sections", [])
        )
        + "\n\n## Quickstart\n"
        + "\n".join(
            f"```{q.get('shell','bash')}\n{q.get('description','')}\n```"
            for q in data.get("quickstart_commands", [])
        )
        + "\n\n## Next writing actions\n"
        + "\n".join(f"- {a}" for a in data.get("next_writing_actions", []))
    )
    report_path = _save("reports", f"tech_writer_{ts}.md", report)

    _record("tech_writer_assistant", focus,
            f"freshness={data.get('doc_freshness_score')} "
            f"stale={len(data.get('stale_sections',[]))} adrs={len(adr_paths)}")

    return {
        "doc_freshness_score":   data.get("doc_freshness_score"),
        "audience":              audience,
        "stale_sections":        data.get("stale_sections", []),
        "refreshed_readme_path": paths.get("readme", ""),
        "api_reference_path":    paths.get("api_reference", ""),
        "contributing_path":     paths.get("contributing", ""),
        "adr_paths":             adr_paths,
        "diagram_paths":         diagram_paths,
        "quickstart_commands":   data.get("quickstart_commands", []),
        "doc_lint_warnings":     data.get("doc_lint_warnings", []),
        "next_writing_actions":  data.get("next_writing_actions", []),
        "report_path":           report_path,
        "summary": (
            f"Doc freshness {data.get('doc_freshness_score','?')}/100. "
            f"{len(data.get('stale_sections',[]))} stale, {len(adr_paths)} ADRs. "
            f"→ {report_path}."
        ),
    }
