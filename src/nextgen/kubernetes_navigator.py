"""
Kubernetes Navigator — diagnose and fix Kubernetes troubles.

Connects to the active kube-context, snapshots pod/event/node health,
classifies known failure modes (OOMKilled, CrashLoopBackOff, ImagePullBackOff,
PVC pending, DNS resolution, NetworkPolicy block, throttled CPU), suggests
right-sizing and a fix manifest, and emits a `kubectl` runbook.

Input:  namespace (str), context (str), focus (str), manifest_yaml (str),
        cluster_summary (str)
Output: cluster_health, hotspots, recommendations, fix_manifests,
        kubectl_runbook, helm_lint_notes, report_path
"""
from __future__ import annotations

from typing import Any, Dict, List

from src._helpers import _ts, _llm, _save, _parse_json, _record, _run


def _kctl(cmd: str, timeout: int = 8) -> str:
    """Run a kubectl command if available, else return a friendly stub."""
    out = _run(f"command -v kubectl >/dev/null 2>&1 && {cmd} || echo '__no_kubectl__'",
               timeout=timeout)
    return out[:3000]


def kubernetes_navigator(args: Dict[str, Any]) -> Dict[str, Any]:
    namespace      = args.get("namespace", "default")
    context        = args.get("context", "")
    focus          = args.get("focus", "auto")
    manifest_yaml  = args.get("manifest_yaml", "")
    cluster_summary = args.get("cluster_summary", "")

    ns_flag  = f"-n {namespace}" if namespace else ""
    ctx_flag = f"--context {context}" if context else ""

    pods    = _kctl(f"kubectl {ctx_flag} get pods {ns_flag} -o wide 2>&1 | head -40")
    events  = _kctl(f"kubectl {ctx_flag} get events {ns_flag} "
                    "--sort-by=.lastTimestamp 2>&1 | tail -25")
    nodes   = _kctl(f"kubectl {ctx_flag} get nodes "
                    "-o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,"
                    "MEM:.status.allocatable.memory,CPU:.status.allocatable.cpu 2>&1 | head -15")
    top_pod = _kctl(f"kubectl {ctx_flag} top pods {ns_flag} 2>&1 | head -20")
    deploy  = _kctl(f"kubectl {ctx_flag} get deploy {ns_flag} 2>&1 | head -20")

    if any(x.strip() == "__no_kubectl__" for x in [pods, events, nodes]):
        live_snapshot = "(no live kubectl available — analysing user-supplied data only)"
    else:
        live_snapshot = (
            f"### pods\n{pods}\n\n### events\n{events}\n\n"
            f"### nodes\n{nodes}\n\n### top pods\n{top_pod}\n\n"
            f"### deployments\n{deploy}"
        )

    system = (
        "You are a Kubernetes SRE. Diagnose the cluster snapshot and produce a "
        "ranked, actionable plan. Recognise and classify: OOMKilled, "
        "CrashLoopBackOff, ImagePullBackOff, PVC Pending, ContainerCreating stalls, "
        "throttled CPU, NetworkPolicy or DNS regressions, missing resource "
        "requests/limits, evicted pods, node pressure. Output ONLY JSON: "
        "{cluster_health:'healthy'|'degraded'|'critical', namespace:str, "
        "hotspots:[{kind,name,issue,evidence,probable_cause,severity:'critical'"
        "|'high'|'medium'|'low'}], "
        "recommendations:[{title,why,kubectl_command,manifest_patch_yaml,"
        "risk_if_wrong}], "
        "rightsizing:[{workload,current_request,current_limit,recommended_request,"
        "recommended_limit,reason}], "
        "deprecated_api_usage:[{kind,version,replacement,target_release}], "
        "fix_manifests:[{filename,yaml}], "
        "kubectl_runbook:str, "
        "helm_lint_notes:[str], "
        "post_fix_validation:[str]}."
    )
    prompt = (
        f"Context: {context or '(current)'}\nNamespace: {namespace}\nFocus: {focus}\n\n"
        f"Live snapshot:\n{live_snapshot}\n\n"
        f"User-supplied cluster summary:\n{cluster_summary or '(none)'}\n\n"
        f"User-supplied manifest:\n```yaml\n{manifest_yaml[:4000]}\n```\n\n"
        "Provide a concrete, copy-pasteable plan. Prefer the smallest safe change."
    )

    data = _parse_json(_llm(prompt, system, "kubernetes_navigator"), {
        "cluster_health": "unknown", "hotspots": [],
        "recommendations": [], "fix_manifests": [],
    })

    ts = _ts()

    # Save each fix manifest as a separate file for kubectl apply
    fix_paths: List[str] = []
    for m in data.get("fix_manifests", []):
        fname = (m.get("filename") or f"k8s_fix_{ts}.yaml").replace("/", "_")
        fix_paths.append(_save("manifests", fname, m.get("yaml", "") or ""))

    runbook_path = _save("scripts", f"kubectl_runbook_{ts}.sh",
        "#!/usr/bin/env bash\n"
        f"# Auto-generated kubectl runbook for ns={namespace}\n"
        "# Review each command before executing.\n"
        "set -euo pipefail\n\n"
        + (data.get("kubectl_runbook") or "echo 'no runbook generated'") + "\n")

    report = (
        f"# Kubernetes Navigator — {ts}\n\n"
        f"**Cluster health:** {data.get('cluster_health','?').upper()}  "
        f"**Namespace:** `{namespace}`  "
        f"**Hotspots:** {len(data.get('hotspots',[]))}\n\n"
        "## Hotspots\n"
        + "\n".join(
            f"- [{h.get('severity','?').upper()}] `{h.get('kind','?')}/"
            f"{h.get('name','?')}` — {h.get('issue','?')} "
            f"(cause: {h.get('probable_cause','?')})"
            for h in data.get("hotspots", [])
        )
        + "\n\n## Recommendations\n"
        + "\n".join(
            f"### {r.get('title','?')}\n{r.get('why','')}\n"
            f"```bash\n{r.get('kubectl_command','')}\n```"
            for r in data.get("recommendations", [])
        )
        + "\n\n## Right-sizing\n"
        + "\n".join(
            f"- `{rs.get('workload','?')}` requests "
            f"{rs.get('current_request','?')}/{rs.get('current_limit','?')} → "
            f"{rs.get('recommended_request','?')}/{rs.get('recommended_limit','?')} "
            f"({rs.get('reason','')})"
            for rs in data.get("rightsizing", [])
        )
        + "\n\n## Deprecated API Usage\n"
        + "\n".join(
            f"- `{d.get('kind','?')}` `{d.get('version','?')}` → "
            f"`{d.get('replacement','?')}` (removed in {d.get('target_release','?')})"
            for d in data.get("deprecated_api_usage", [])
        )
    )
    report_path = _save("reports", f"k8s_navigator_{ts}.md", report)

    _record("kubernetes_navigator", f"ns={namespace}",
            f"health={data.get('cluster_health')} hotspots={len(data.get('hotspots',[]))}")

    return {
        "cluster_health":         data.get("cluster_health", "unknown"),
        "namespace":              namespace,
        "hotspots":               data.get("hotspots", []),
        "recommendations":        data.get("recommendations", []),
        "rightsizing":            data.get("rightsizing", []),
        "deprecated_api_usage":   data.get("deprecated_api_usage", []),
        "fix_manifests":          data.get("fix_manifests", []),
        "fix_manifest_paths":     fix_paths,
        "kubectl_runbook":        data.get("kubectl_runbook", ""),
        "kubectl_runbook_path":   runbook_path,
        "helm_lint_notes":        data.get("helm_lint_notes", []),
        "post_fix_validation":    data.get("post_fix_validation", []),
        "report_path":            report_path,
        "summary": (
            f"K8s {data.get('cluster_health','?')} in `{namespace}`. "
            f"{len(data.get('hotspots',[]))} hotspots, "
            f"{len(data.get('recommendations',[]))} fixes, "
            f"{len(fix_paths)} manifests saved. → {report_path}."
        ),
    }
