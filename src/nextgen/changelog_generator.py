"""
Changelog Generator — turn raw git history + PR titles into a clean,
audience-segmented changelog (Keep-a-Changelog format), release notes
for different audiences (engineers, customers, executives), a
breaking-changes migration guide, and a recommended semver bump.

Input:  repo_path (str), since_ref (str), until_ref (str),
        commits_text (str), pr_titles (list), audience (str),
        format (str)
Output: changelog_md, release_notes_by_audience, breaking_changes,
        recommended_version_bump, migration_guide, report_path
"""
from __future__ import annotations

from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


_VALID_BUMPS = {"major", "minor", "patch", "none"}


def changelog_generator(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path     = args.get("repo_path", ".")
    since_ref     = args.get("since_ref", "")
    until_ref     = args.get("until_ref", "HEAD")
    commits_text  = args.get("commits_text", "")
    pr_titles     = args.get("pr_titles") or []
    audience      = args.get("audience", "all")  # all|engineers|customers|executives
    fmt           = args.get("format", "keep_a_changelog")

    if not commits_text:
        if since_ref:
            rng = f"{since_ref}..{until_ref}"
        else:
            # last tag → HEAD
            last_tag = _run("git describe --tags --abbrev=0 2>/dev/null",
                            cwd=repo_path, timeout=5).strip()
            rng = f"{last_tag}..{until_ref}" if last_tag else until_ref
        commits_text = _run(
            f"git log {rng} --no-merges "
            "--pretty=format:'%h|%an|%ad|%s%n%b%n---' --date=short",
            cwd=repo_path, timeout=15)[:8000]

    pr_block = "\n".join(f"- {p}" for p in pr_titles[:80])

    system = (
        "You are a release engineer who writes changelogs that humans actually "
        "read. Categorise every commit using the Keep-a-Changelog v1.1 sections: "
        "Added, Changed, Deprecated, Removed, Fixed, Security. Detect breaking "
        "changes (BREAKING:, !:, removed exports, schema changes, env var renames) "
        "and produce a migration guide for them. Recommend a semver bump (major/"
        "minor/patch/none) with justification. Generate THREE audience variants. "
        "Output ONLY JSON: "
        "{recommended_version_bump:'major'|'minor'|'patch'|'none', "
        "version_bump_reasoning:str, "
        "changelog_md:str, "
        "release_notes_by_audience:{engineers:str,customers:str,executives:str}, "
        "categorised:{added:[str],changed:[str],deprecated:[str],removed:[str],"
        "fixed:[str],security:[str]}, "
        "breaking_changes:[{title,impact,who_is_affected,migration_steps:[str],"
        "automated_codemod_hint}], "
        "migration_guide_md:str, "
        "contributor_thanks:[str], "
        "highlights_tweet:str, "
        "next_release_themes:[str]}."
    )
    prompt = (
        f"Format: {fmt}\nAudience focus: {audience}\n"
        f"Range: {since_ref or '(last tag)'}..{until_ref}\n\n"
        f"Pull request titles:\n{pr_block or '(none provided)'}\n\n"
        f"COMMIT LOG:\n```\n{commits_text or '(no commits)'}\n```\n\n"
        "Be specific. Empty sections in the changelog should be omitted."
    )

    data = _parse_json(_llm(prompt, system, "changelog_generator"), {
        "recommended_version_bump": "patch",
        "changelog_md": "", "release_notes_by_audience": {},
        "categorised": {}, "breaking_changes": [],
    })

    bump = data.get("recommended_version_bump", "patch")
    if bump not in _VALID_BUMPS:
        bump = "patch"

    ts = _ts()
    changelog_path = _save("release", f"CHANGELOG_{ts}.md",
                           data.get("changelog_md", "") or "# Changelog\n")
    migration_path = ""
    if data.get("migration_guide_md"):
        migration_path = _save("release", f"MIGRATION_{ts}.md",
                               data["migration_guide_md"])

    audience_paths: Dict[str, str] = {}
    for k, v in (data.get("release_notes_by_audience") or {}).items():
        if v:
            audience_paths[k] = _save("release", f"release_notes_{k}_{ts}.md", v)

    cat = data.get("categorised", {})
    bcount = len(data.get("breaking_changes", []))
    summary = (
        f"# Changelog Report — {ts}\n\n"
        f"**Recommended bump:** `{bump}`\n"
        f"_Why:_ {data.get('version_bump_reasoning','')}\n\n"
        f"**Added:** {len(cat.get('added', []))}  "
        f"**Changed:** {len(cat.get('changed', []))}  "
        f"**Fixed:** {len(cat.get('fixed', []))}  "
        f"**Security:** {len(cat.get('security', []))}  "
        f"**Breaking:** {bcount}\n\n"
        f"## Tweet-sized highlight\n> {data.get('highlights_tweet','')}\n\n"
        "## Breaking changes\n"
        + "\n".join(
            f"### {b.get('title','?')}\n"
            f"Impact: {b.get('impact','')}\nWho: {b.get('who_is_affected','')}\n"
            "Migration:\n" + "\n".join(f"  - {s}" for s in b.get('migration_steps',[]))
            for b in data.get("breaking_changes", [])
        )
        + "\n## Next release themes\n"
        + "\n".join(f"- {t}" for t in data.get("next_release_themes", []))
    )
    report_path = _save("reports", f"changelog_{ts}.md", summary)

    _record("changelog_generator", since_ref or "last_tag",
            f"bump={bump} breaking={bcount}")

    return {
        "recommended_version_bump":   bump,
        "version_bump_reasoning":     data.get("version_bump_reasoning", ""),
        "changelog_md":               data.get("changelog_md", ""),
        "changelog_path":             changelog_path,
        "release_notes_by_audience":  data.get("release_notes_by_audience", {}),
        "release_notes_paths":        audience_paths,
        "categorised":                cat,
        "breaking_changes":           data.get("breaking_changes", []),
        "migration_guide_md":         data.get("migration_guide_md", ""),
        "migration_guide_path":       migration_path,
        "contributor_thanks":         data.get("contributor_thanks", []),
        "highlights_tweet":           data.get("highlights_tweet", ""),
        "next_release_themes":        data.get("next_release_themes", []),
        "report_path":                report_path,
        "summary": (
            f"Recommended `{bump}` bump. "
            f"{bcount} breaking change(s). → {changelog_path}."
        ),
    }
