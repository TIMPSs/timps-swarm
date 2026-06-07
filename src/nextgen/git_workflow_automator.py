"""Git Workflow Automator — generates a complete, opinionated git workflow
configuration for a project based on its release style and team size.

Outputs (under `generated/git_workflow/<name>/`):

* `pre-commit-config.yaml`    — black/ruff/mypy/bandit/secrets scanning
* `commitlint.config.js`      — Conventional Commits enforcement
* `commit-msg` hook           — invokes commitlint
* `lefthook.yml`              — faster alt to husky, written in Go
* `.releaserc.json`           OR `release-please-config.json`  (semantic-release)
* `PULL_REQUEST_TEMPLATE.md`  — standard PR body
* `CONTRIBUTING.md`           — branch model + commit message rules
* `branch_protection.md`      — GitHub branch-protection policy checklist
* `CODEOWNERS`                — minimal fallback file
* `Makefile`                  — `make tag` / `make changelog` shortcuts
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _run, _save, _ts

DOMAIN = "nextgen"

RELEASE_STYLES = ("semver", "calver", "library", "service")
BRANCH_MODELS = ("trunk", "github_flow", "gitflow")


def git_workflow_automator(args: Dict[str, Any]) -> Dict[str, Any]:
    project_name = (args.get("name") or "project").strip().lower()
    project_name = re.sub(r"[^a-z0-9_]+", "_", project_name).strip("_") or "project"
    release_style = (args.get("release_style") or "semver").lower()
    if release_style not in RELEASE_STYLES:
        release_style = "semver"
    branch_model = (args.get("branch_model") or "github_flow").lower()
    if branch_model not in BRANCH_MODELS:
        branch_model = "github_flow"
    team_size = int(args.get("team_size") or 5)
    primary_branch = args.get("primary_branch") or "main"
    languages: List[str] = args.get("languages") or ["python"]
    target_dir = Path(args.get("target_dir") or f"generated/git_workflow/{project_name}")

    # --------------------------------------------------------------- prompt
    system = (
        "You are a DevEx engineer designing an opinionated git workflow.  You "
        "return ONLY a single JSON object — no prose, no fences.\n\n"
        "Schema:\n"
        "{\n"
        '  "precommit_hooks":  [ { "repo": str, "hooks": [ { "id": str, "args": [str] } ] } ],\n'
        '  "commit_types":      [str],     // e.g. feat, fix, chore, docs, perf, refactor, test\n'
        '  "branch_model":      "trunk"|"github_flow"|"gitflow",\n'
        '  "release_strategy":  { "tool": "semantic-release"|"release-please"|"cz-cli", '
        '"branches": [str], "plugins": [str] },\n'
        '  "codeowners":        [ { "path": str, "owners": [str] } ],\n'
        '  "branch_protection": { "required_reviews": int, "dismiss_stale": bool, '
        '"require_linear_history": bool, "require_signed_commits": bool, '
        '"enforce_admins": bool },\n'
        '  "pr_template_sections": [str],\n'
        '  "contrib_rules":     [str]      // 5-10 bullet rules for CONTRIBUTING.md\n'
        "}\n\n"
        "Rules:\n"
        "- branch_model must match the requested style unless the user demanded otherwise.\n"
        "- codeowners must include at least one default catch-all rule (@org/team-lead).\n"
        "- precommit_hooks must be installable with `pip install pre-commit`."
    )

    user = (
        f"Project: {project_name}\nRelease style: {release_style}\n"
        f"Branch model: {branch_model}\nTeam size: {team_size}\n"
        f"Primary branch: {primary_branch}\nLanguages: {', '.join(languages)}\n"
    )

    raw = _llm(user, system, "git_workflow_automator")
    parsed = _parse_json(
        raw,
        fallback={
            "precommit_hooks": [
                {
                    "repo": "https://github.com/pre-commit/pre-commit-hooks",
                    "hooks": [
                        {"id": "check-yaml", "args": []},
                        {"id": "end-of-file-fixer", "args": []},
                        {"id": "trailing-whitespace", "args": []},
                    ],
                }
            ],
            "commit_types": ["feat", "fix", "chore", "docs", "perf", "refactor", "test", "build", "ci"],
            "branch_model": branch_model,
            "release_strategy": {
                "tool": "release-please" if release_style == "calver" else "semantic-release",
                "branches": [primary_branch],
                "plugins": ["@semantic-release/commit-analyzer", "@semantic-release/release-notes-generator"],
            },
            "codeowners": [{"path": "*", "owners": ["@org/team-lead"]}],
            "branch_protection": {
                "required_reviews": 1 if team_size <= 3 else 2,
                "dismiss_stale": True,
                "require_linear_history": branch_model == "trunk",
                "require_signed_commits": False,
                "enforce_admins": True,
            },
            "pr_template_sections": [
                "Summary", "Linked Issues", "Type of change", "How to test",
                "Checklist", "Screenshots",
            ],
            "contrib_rules": [
                "Branch off `main` with a descriptive prefix (feat/, fix/, chore/).",
                "Use Conventional Commits: type(scope): subject.",
                "Keep PRs < 400 lines where possible.",
                "All tests must pass and coverage must not drop.",
                "Squash-merge to keep history linear.",
            ],
        },
    )

    hooks = parsed.get("precommit_hooks") or []
    types_ = parsed.get("commit_types") or []
    codeowners = parsed.get("codeowners") or []
    bp = parsed.get("branch_protection") or {}
    pr_sections = parsed.get("pr_template_sections") or []
    contrib = parsed.get("contrib_rules") or []
    rel = parsed.get("release_strategy") or {}

    # --------------------------------------------------------------- emit
    target_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[str] = []

    files: Dict[str, str] = {
        ".pre-commit-config.yaml": _render_precommit(hooks, languages),
        "commitlint.config.js":    _render_commitlint(types_),
        ".git/hooks/commit-msg":   _render_commit_msg_hook(),
        "lefthook.yml":            _render_lefthook(hooks, languages),
        _release_config_filename(rel.get("tool")): _render_release_config(rel, release_style),
        "PULL_REQUEST_TEMPLATE.md": _render_pr_template(pr_sections),
        "CONTRIBUTING.md":         _render_contributing(primary_branch, branch_model, contrib),
        "branch_protection.md":    _render_branch_protection(primary_branch, bp, team_size),
        "CODEOWNERS":              _render_codeowners(codeowners),
        "Makefile":                _render_makefile(rel.get("tool"), primary_branch),
        "README.md":               _render_readme(project_name, branch_model, release_style, rel, types_, bp),
    }
    for fname, content in files.items():
        full = target_dir / fname
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        out_paths.append(str(full))

    summary = (
        f"Generated git workflow '{project_name}': branch_model={branch_model}, "
        f"release={rel.get('tool','semantic-release')}, "
        f"hooks={sum(len(h.get('hooks', [])) for h in hooks)}, "
        f"commit_types={len(types_)}, branch_protection.reviews={bp.get('required_reviews', 1)}."
    )

    payload = {
        "summary": summary,
        "project_name": project_name,
        "branch_model": branch_model,
        "release_style": release_style,
        "release_strategy": rel,
        "branch_protection": bp,
        "commit_types": types_,
        "files": out_paths,
        "generated_at": _ts(),
    }
    _save("git_workflow", f"{project_name}_summary.json", json.dumps(payload, indent=2))
    _record("git_workflow_automator", project_name, f"branch={branch_model} release={rel.get('tool')} hooks={len(hooks)}")
    return payload


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _render_precommit(hooks, languages) -> str:
    lines = ["repos:"]
    seen: set = set()
    for entry in hooks:
        repo = entry.get("repo", "")
        if not repo or repo in seen:
            continue
        seen.add(repo)
        rev = "v4.6.0" if "pre-commit-hooks" in repo else "v1.0.0"
        lines.append(f"  - repo: {repo}")
        lines.append(f"    rev: {rev}")
        lines.append("    hooks:")
        for h in entry.get("hooks", []):
            args = h.get("args") or []
            lines.append(f"      - id: {h.get('id','hook')}")
            if args:
                lines.append("        args: [" + ", ".join(json.dumps(a) for a in args) + "]")
    if "python" in [l.lower() for l in languages]:
        lines += [
            "  - repo: https://github.com/astral-sh/ruff-pre-commit",
            "    rev: v0.5.0",
            "    hooks:",
            "      - id: ruff",
            "        args: [--fix]",
            "      - id: ruff-format",
        ]
    return "\n".join(lines) + "\n"


def _render_commitlint(types_) -> str:
    return (
        "module.exports = {\n"
        "  extends: ['@commitlint/config-conventional'],\n"
        f"  rules: {{ 'type-enum': [2, 'always', {json.dumps(types_)}] }},\n"
        "};\n"
    )


def _render_commit_msg_hook() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "# Installed by TIMPS Swarm git_workflow_automator.\n"
        "set -e\n"
        "npx --no-install commitlint --edit \"$1\" || {\n"
        "  echo 'commitlint failed; run: npx commitlint --edit $1' >&2\n"
        "  exit 1\n"
        "}\n"
    )


def _render_lefthook(hooks, languages) -> str:
    cmds: List[str] = ["pre-commit:", "  parallel: true", "  commands:"]
    seen_ids: set = set()
    for entry in hooks:
        for h in entry.get("hooks", []):
            hid = h.get("id", "hook")
            if hid in seen_ids:
                continue
            seen_ids.add(hid)
            cmds.append(f"    {hid}:\n      run: pre-commit run {hid} --all-files")
    if "python" in [l.lower() for l in languages]:
        cmds += [
            "    ruff:",
            "      run: ruff check .",
            "    ruff-format:",
            "      run: ruff format --check .",
        ]
    cmds += [
        "commit-msg:",
        "  commands:",
        "    commitlint:",
        '      run: npx --no-install commitlint --edit {staged_files}',
    ]
    return "\n".join(cmds) + "\n"


def _release_config_filename(tool: str) -> str:
    return {
        "semantic-release": ".releaserc.json",
        "release-please": "release-please-config.json",
        "cz-cli": ".czrc",
    }.get(tool or "semantic-release", ".releaserc.json")


def _render_release_config(rel, style) -> str:
    tool = rel.get("tool") or "semantic-release"
    branches = rel.get("branches") or ["main"]
    if tool == "release-please":
        return json.dumps(
            {
                "release-type": "python" if style != "calver" else "calendar",
                "branches": branches,
                "changelog-path": "CHANGELOG.md",
            },
            indent=2,
        ) + "\n"
    if tool == "cz-cli":
        return json.dumps({"path": "./cz-config.js"}, indent=2) + "\n"
    return json.dumps(
        {
            "branches": [{"name": b, "channel": "latest" if b == branches[0] else "next"} for b in branches],
            "plugins": rel.get("plugins") or [
                "@semantic-release/commit-analyzer",
                "@semantic-release/release-notes-generator",
                "@semantic-release/changelog",
            ],
        },
        indent=2,
    ) + "\n"


def _render_pr_template(sections) -> str:
    body = ["<!-- Generated by TIMPS Swarm git_workflow_automator -->", ""]
    for s in sections or ["Summary", "Linked Issues", "Type of change", "How to test", "Checklist"]:
        body += [f"## {s}", "", "<!-- describe -->", ""]
    return "\n".join(body)


def _render_contributing(branch, model, rules) -> str:
    body = [
        f"# Contributing to this project\n",
        f"## Branch model: **{model}** — primary branch: `{branch}`\n",
        "## Rules\n",
    ]
    body += [f"- {r}" for r in (rules or [])]
    body += [
        "",
        "## Releasing",
        "Releases are managed by the configured release tool — humans should not "
        "manually edit version numbers or `CHANGELOG.md`.",
    ]
    return "\n".join(body) + "\n"


def _render_branch_protection(branch, bp, team_size) -> str:
    return (
        f"# Branch protection policy for `{branch}`\n\n"
        f"## Required status checks\n"
        f"- [ ] CI / lint\n- [ ] CI / unit tests\n- [ ] CI / coverage ≥ {70 if team_size < 10 else 80}%\n\n"
        f"## Pull-request reviews\n"
        f"- [ ] Require **{bp.get('required_reviews', 1)}** approving review(s).\n"
        f"- [ ] Dismiss stale reviews on new push: **{bp.get('dismiss_stale', True)}**.\n"
        f"- [ ] Enforce for admins: **{bp.get('enforce_admins', True)}**.\n\n"
        f"## Additional\n"
        f"- [ ] Require linear history: **{bp.get('require_linear_history', False)}**.\n"
        f"- [ ] Require signed commits: **{bp.get('require_signed_commits', False)}**.\n"
        f"- [ ] Block force pushes.\n"
        f"- [ ] Block branch deletion.\n"
    )


def _render_codeowners(rows) -> str:
    lines = ["# CODEOWNERS — generated by TIMPS Swarm git_workflow_automator"]
    for r in rows or []:
        path = r.get("path", "*")
        owners = r.get("owners") or ["@org/team-lead"]
        lines.append(f"{path}  {' '.join(owners)}")
    return "\n".join(lines) + "\n"


def _render_makefile(tool, branch) -> str:
    cmd = {
        "semantic-release": "npx semantic-release",
        "release-please": "npx release-please make-release",
        "cz-cli": "npx cz",
    }.get(tool or "semantic-release", "npx semantic-release")
    return (
        f".PHONY: install hooks tag changelog release\n"
        f"install:\\n"
        f"\\tnpm install --save-dev @commitlint/{{cli,config-conventional}} husky\\n\\n"
        f"hooks:\\n"
        f"\\tpre-commit install\\n"
        f"\\tgit config core.hooksPath .githooks\\n\\n"
        f"tag:\\n"
        f"\\tgit fetch --tags && git tag --sort=-creatordate | head -1\\n\\n"
        f"changelog:\\n"
        f"\\tnpx conventional-changelog -p angular -i CHANGELOG.md -s\\n\\n"
        f"release:\\n"
        f"\\t{cmd}\\n"
    ).replace("\\n", "\n")


def _render_readme(name, model, style, rel, types_, bp) -> str:
    return (
        f"# {name} — Git Workflow Bundle\n\n"
        f"Generated by **TIMPS Swarm** `git_workflow_automator`.\n\n"
        f"- Branch model: **{model}**\n"
        f"- Release style: **{style}**\n"
        f"- Release tool: **{rel.get('tool','semantic-release')}**\n"
        f"- Commit types: {', '.join(types_)}\n"
        f"- Required PR reviews: **{bp.get('required_reviews', 1)}**\n\n"
        f"## Files\n"
        f"- `.pre-commit-config.yaml` — pre-commit hooks\n"
        f"- `commitlint.config.js` — Conventional Commits enforcement\n"
        f"- `lefthook.yml` — fast Git-hook manager (Go)\n"
        f"- `CONTRIBUTING.md`, `PULL_REQUEST_TEMPLATE.md`, `CODEOWNERS`\n"
        f"- `branch_protection.md` — GitHub policy checklist\n\n"
        f"## Install\n"
        f"```bash\nmake install\nmake hooks\n```\n"
    )
