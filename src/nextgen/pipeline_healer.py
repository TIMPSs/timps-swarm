"""
Pipeline Healer — diagnose and auto-fix CI/CD pipeline failures.

Reads a failed build log (or recent CI history), classifies the failure
mode (flaky test, dep conflict, OOM, network blip, missing secret,
linter regression, container build cache miss, schema drift), correlates
with recent commits, and emits a fix patch + a config tweak + a retry
strategy. Designed to slot into the existing flaky_test_hunter and
incident_responder agents.

Input:  ci_log (str), ci_provider (str), recent_commits (str),
        pipeline_config (str), repo_path (str)
Output: classification, root_cause, fix_patch, ci_config_patch,
        retry_strategy, prevent_future, report_path
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


_CI_CONFIG_FILES = [
    ".github/workflows", ".gitlab-ci.yml", "Jenkinsfile",
    ".circleci/config.yml", "azure-pipelines.yml", "bitbucket-pipelines.yml",
    ".drone.yml", "buildkite.yml",
]


def _autodetect_ci(repo_path: str) -> tuple[str, str]:
    root = Path(repo_path or ".")
    for f in _CI_CONFIG_FILES:
        p = root / f
        if p.is_file():
            return f, p.read_text(encoding="utf-8", errors="ignore")[:4000]
        if p.is_dir():
            files = list(p.rglob("*.y*ml"))[:3]
            if files:
                txt = "\n\n".join(
                    f"# {q}\n" + q.read_text(encoding="utf-8", errors="ignore")[:1400]
                    for q in files)
                return f, txt[:5000]
    return "unknown", ""


def pipeline_healer(args: Dict[str, Any]) -> Dict[str, Any]:
    ci_log         = args.get("ci_log", "")
    ci_provider    = args.get("ci_provider", "auto")
    recent_commits = args.get("recent_commits", "")
    pipeline_cfg   = args.get("pipeline_config", "")
    repo_path      = args.get("repo_path", "")

    detected_file, detected_cfg = ("unknown", "")
    if not pipeline_cfg:
        detected_file, detected_cfg = _autodetect_ci(repo_path)
        pipeline_cfg = detected_cfg
        if ci_provider == "auto":
            if "workflows" in detected_file:        ci_provider = "github_actions"
            elif "gitlab" in detected_file:         ci_provider = "gitlab_ci"
            elif "Jenkins" in detected_file:        ci_provider = "jenkins"
            elif "circle" in detected_file:         ci_provider = "circleci"
            elif "azure" in detected_file:          ci_provider = "azure_pipelines"

    if not recent_commits and repo_path:
        recent_commits = _run(
            "git log --oneline --decorate -n 15 --pretty=format:'%h %s (%an, %ar)'",
            cwd=repo_path, timeout=8)[:2000]

    system = (
        "You are a CI/CD SRE who has triaged thousands of failed pipelines. "
        "Classify the failure into ONE of: flaky_test, dependency_conflict, "
        "oom_or_disk, network_or_dns, missing_secret_or_env, linter_or_format, "
        "container_build_cache, schema_or_migration, code_bug, infra_outage, "
        "timeout, unknown. Then emit a targeted code patch, a CI-config tweak, "
        "and a retry strategy that won't mask the bug. "
        "Output ONLY JSON: "
        "{classification:str, confidence:'high'|'medium'|'low', "
        "ci_provider:str, "
        "root_cause:str, evidence_lines:[str], "
        "correlated_commit:{sha,reason}, "
        "fix_patch:{file,unified_diff,explanation}, "
        "ci_config_patch:{file,unified_diff,explanation}, "
        "retry_strategy:{should_retry:bool,max_attempts:int,backoff_seconds:int,"
        "conditions:[str]}, "
        "prevent_future:[str], "
        "owner_to_page:str, "
        "fix_in_minutes_estimate:int}."
    )
    prompt = (
        f"CI provider: {ci_provider}\n"
        f"Detected CI config file: {detected_file}\n\n"
        f"Recent commits:\n{recent_commits or '(none)'}\n\n"
        f"Pipeline config:\n```yaml\n{pipeline_cfg[:3000]}\n```\n\n"
        f"FAILED BUILD LOG:\n```\n{ci_log[:6000]}\n```\n\n"
        "Diagnose ROOT cause (not symptom). Never recommend blind retry for "
        "code bugs; only retry on truly transient classes."
    )

    data = _parse_json(_llm(prompt, system, "pipeline_healer"), {
        "classification": "unknown",
        "fix_patch": {}, "ci_config_patch": {}, "retry_strategy": {},
    })

    ts = _ts()
    patch_path = ""
    cfg_path = ""
    if data.get("fix_patch", {}).get("unified_diff"):
        patch_path = _save("patches", f"pipeline_fix_{ts}.patch",
                           data["fix_patch"]["unified_diff"])
    if data.get("ci_config_patch", {}).get("unified_diff"):
        cfg_path = _save("patches", f"pipeline_cfg_{ts}.patch",
                         data["ci_config_patch"]["unified_diff"])

    report = (
        f"# Pipeline Healer — {ts}\n\n"
        f"**Classification:** {data.get('classification','?')} "
        f"({data.get('confidence','?')} confidence)  "
        f"**CI:** {data.get('ci_provider', ci_provider)}  "
        f"**ETA:** ~{data.get('fix_in_minutes_estimate','?')}m\n\n"
        f"## Root Cause\n{data.get('root_cause','')}\n\n"
        f"**Correlated commit:** `{data.get('correlated_commit',{}).get('sha','?')}` — "
        f"{data.get('correlated_commit',{}).get('reason','')}\n\n"
        "## Evidence\n"
        + "\n".join(f"- `{e}`" for e in data.get("evidence_lines", []))
        + "\n\n## Fix patch\n"
        f"```diff\n{data.get('fix_patch',{}).get('unified_diff','(no patch)')}\n```\n\n"
        f"_{data.get('fix_patch',{}).get('explanation','')}_\n\n"
        "## CI-config patch\n"
        f"```diff\n{data.get('ci_config_patch',{}).get('unified_diff','(no patch)')}\n```\n\n"
        "## Retry strategy\n"
        f"- Should retry: **{data.get('retry_strategy',{}).get('should_retry',False)}**\n"
        f"- Max attempts: {data.get('retry_strategy',{}).get('max_attempts','?')}\n"
        f"- Backoff: {data.get('retry_strategy',{}).get('backoff_seconds','?')}s\n"
        f"- Conditions: {', '.join(data.get('retry_strategy',{}).get('conditions',[]))}\n\n"
        "## Prevent Future\n"
        + "\n".join(f"- {p}" for p in data.get("prevent_future", []))
    )
    report_path = _save("reports", f"pipeline_healer_{ts}.md", report)

    _record("pipeline_healer", ci_provider or "ci",
            f"class={data.get('classification')} eta={data.get('fix_in_minutes_estimate')}m")

    return {
        "classification":        data.get("classification", "unknown"),
        "confidence":            data.get("confidence", "low"),
        "ci_provider":           data.get("ci_provider", ci_provider),
        "root_cause":            data.get("root_cause", ""),
        "evidence_lines":        data.get("evidence_lines", []),
        "correlated_commit":     data.get("correlated_commit", {}),
        "fix_patch":             data.get("fix_patch", {}),
        "ci_config_patch":       data.get("ci_config_patch", {}),
        "retry_strategy":        data.get("retry_strategy", {}),
        "prevent_future":        data.get("prevent_future", []),
        "owner_to_page":         data.get("owner_to_page", ""),
        "fix_patch_path":        patch_path,
        "ci_config_patch_path":  cfg_path,
        "report_path":           report_path,
        "summary": (
            f"Pipeline failure classified as `{data.get('classification','?')}`. "
            f"Patch ready → {patch_path or '(no fix patch)'}. Full report → {report_path}."
        ),
    }
