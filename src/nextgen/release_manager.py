"""
Release Manager — orchestrate end-to-end release coordination.

Composes the work of changelog_generator, db_migration_pilot,
security_remediation, and the SDLC pipeline into a complete release plan:
semver decision, release branch strategy, deploy plan (canary →
percentage → 100%), rollback triggers, stakeholder comms, monitoring
gates, and a pre/post-release checklist.

Input:  repo_path (str), target_version (str), deploy_strategy (str),
        environments (list), commits_text (str), risk_appetite (str)
Output: release_plan, version, canary_plan, rollback_triggers,
        comms_plan, gates, runbook, report_path
"""
from __future__ import annotations

from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def release_manager(args: Dict[str, Any]) -> Dict[str, Any]:
    repo_path       = args.get("repo_path", ".")
    target_version  = args.get("target_version", "")
    deploy_strategy = args.get("deploy_strategy", "canary")  # canary|blue_green|rolling
    environments    = args.get("environments") or ["staging", "canary", "production"]
    commits_text    = args.get("commits_text", "")
    risk_appetite   = args.get("risk_appetite", "moderate")
    has_migration   = bool(args.get("has_migration", False))

    last_tag = _run("git describe --tags --abbrev=0 2>/dev/null",
                    cwd=repo_path, timeout=5).strip()
    if not commits_text:
        rng = f"{last_tag}..HEAD" if last_tag else "HEAD"
        commits_text = _run(
            f"git log {rng} --no-merges --pretty=format:'%h %s' | head -50",
            cwd=repo_path, timeout=10)[:4000]

    # Best-effort signal: any open dependabot / vuln branches?
    branches = _run("git branch -a | head -20", cwd=repo_path, timeout=5)[:600]

    system = (
        "You are a release manager. Build a release plan that is shippable "
        "TODAY: semver, branch strategy, deploy plan with explicit gates, "
        "rollback triggers, stakeholder comms (engineering, support, sales, "
        "exec), and a checklist a junior on-call can execute. Always include "
        "feature-flag controls for risky changes. "
        "Output ONLY JSON: "
        "{recommended_version:str, version_basis:str, "
        "release_branch:str, freeze_window:str, "
        "deploy_plan:{strategy:str,steps:[{env,traffic_percent,bake_time_minutes,"
        "monitors:[str],auto_promote_criteria:str}]}, "
        "feature_flags_to_introduce:[{name,default,rollout_strategy}], "
        "gates:[{name,owner,blocking:bool,evidence_required}], "
        "rollback_triggers:[{metric,threshold,action}], "
        "comms_plan:{engineering:str,support:str,exec:str,customer:str}, "
        "preflight_checklist:[str], postflight_checklist:[str], "
        "on_call_runbook:[{step,command_or_action,timeout_minutes,if_fails}], "
        "risk_register:[{risk,likelihood,impact,mitigation,owner}], "
        "go_no_go:{recommendation:bool,reasoning,blockers:[str]}}."
    )
    prompt = (
        f"Repo: {repo_path}\nLast tag: {last_tag or '(none)'}\n"
        f"Target version override: {target_version or '(auto)'}\n"
        f"Strategy: {deploy_strategy}\nEnvironments: {environments}\n"
        f"Risk appetite: {risk_appetite}\nHas DB migration: {has_migration}\n\n"
        f"Recent commits since last tag:\n{commits_text}\n\n"
        f"Active branches sample:\n{branches}\n\n"
        "Produce a plan, not a suggestion. Be explicit about rollback."
    )

    data = _parse_json(_llm(prompt, system, "release_manager"), {
        "recommended_version": target_version or "0.0.0",
        "deploy_plan": {}, "gates": [], "rollback_triggers": [],
        "on_call_runbook": [],
    })

    ts = _ts()
    runbook = data.get("on_call_runbook", [])
    runbook_path = _save("release", f"oncall_runbook_{ts}.md",
        "# On-call Runbook\n\n" + "\n".join(
            f"## Step {i+1}: {r.get('step','?')}\n"
            f"`{r.get('command_or_action','')}`\n"
            f"_Timeout_: {r.get('timeout_minutes','?')}m  "
            f"_If fails_: {r.get('if_fails','')}\n"
            for i, r in enumerate(runbook)))

    gno = data.get("go_no_go", {})
    report = (
        f"# Release Manager — {ts}\n\n"
        f"**Version:** `{data.get('recommended_version','?')}` "
        f"({data.get('version_basis','?')})  "
        f"**Strategy:** {data.get('deploy_plan',{}).get('strategy', deploy_strategy)}  "
        f"**Branch:** `{data.get('release_branch','?')}`  "
        f"**Freeze:** {data.get('freeze_window','?')}\n\n"
        f"## Go / No-Go: **{'GO' if gno.get('recommendation') else 'NO-GO'}**\n"
        f"{gno.get('reasoning','')}\n"
        + ("\n_Blockers_:\n" + "\n".join(f"- {b}" for b in gno.get("blockers", []))
           if gno.get("blockers") else "")
        + "\n\n## Deploy plan\n"
        + "\n".join(
            f"{i+1}. **{s.get('env','?')}** — {s.get('traffic_percent','?')}% "
            f"for {s.get('bake_time_minutes','?')}m. Auto-promote: "
            f"{s.get('auto_promote_criteria','?')}"
            for i, s in enumerate(data.get("deploy_plan", {}).get("steps", []))
        )
        + "\n\n## Gates\n"
        + "\n".join(
            f"- {'**' if g.get('blocking') else ''}{g.get('name','?')}"
            f"{'**' if g.get('blocking') else ''} "
            f"(owner: {g.get('owner','?')}) — evidence: "
            f"{g.get('evidence_required','')}"
            for g in data.get("gates", [])
        )
        + "\n\n## Rollback triggers\n"
        + "\n".join(
            f"- `{t.get('metric','?')}` {t.get('threshold','?')} → "
            f"{t.get('action','?')}"
            for t in data.get("rollback_triggers", [])
        )
        + "\n\n## Risk register\n"
        + "\n".join(
            f"- [{r.get('likelihood','?')}×{r.get('impact','?')}] "
            f"{r.get('risk','?')} → {r.get('mitigation','')} "
            f"(owner: {r.get('owner','?')})"
            for r in data.get("risk_register", [])
        )
        + f"\n\n## Runbook → `{runbook_path}`"
    )
    report_path = _save("reports", f"release_manager_{ts}.md", report)

    _record("release_manager", data.get("recommended_version", "release"),
            f"strategy={deploy_strategy} gates={len(data.get('gates',[]))} "
            f"go={gno.get('recommendation')}")

    return {
        "recommended_version":         data.get("recommended_version"),
        "version_basis":               data.get("version_basis", ""),
        "release_branch":              data.get("release_branch", ""),
        "freeze_window":               data.get("freeze_window", ""),
        "deploy_plan":                 data.get("deploy_plan", {}),
        "feature_flags_to_introduce":  data.get("feature_flags_to_introduce", []),
        "gates":                       data.get("gates", []),
        "rollback_triggers":           data.get("rollback_triggers", []),
        "comms_plan":                  data.get("comms_plan", {}),
        "preflight_checklist":         data.get("preflight_checklist", []),
        "postflight_checklist":        data.get("postflight_checklist", []),
        "on_call_runbook":             runbook,
        "on_call_runbook_path":        runbook_path,
        "risk_register":               data.get("risk_register", []),
        "go_no_go":                    gno,
        "report_path":                 report_path,
        "summary": (
            f"Release plan for `{data.get('recommended_version','?')}` "
            f"({deploy_strategy}). Go={gno.get('recommendation')}. → {report_path}."
        ),
    }
