"""
Model Performance Monitor — detect data drift, concept drift, and silent
performance degradation in deployed ML models.

Compares current production feature distributions / output distributions
against a baseline window using PSI, KL-divergence, KS-statistic, and
JS-distance heuristics. Surfaces drifted features, suggests retraining
triggers, and emits a monitoring config (Evidently / Arize / W&B /
MLflow) plus a Grafana alert pack.

Input:  baseline_stats (dict|str), current_stats (dict|str), model_name (str),
        prediction_drift (dict|str), labels_lag_days (int), library_hint (str)
Output: drift_findings, overall_drift_score, retrain_recommendation,
        monitoring_config, grafana_alerts, report_path
"""
from __future__ import annotations

import json
from typing import Any, Dict

from src._helpers import _ts, _llm, _save, _parse_json, _record


def _stringify(maybe_data: Any, limit: int = 3000) -> str:
    if maybe_data is None:
        return "(none)"
    if isinstance(maybe_data, (dict, list)):
        try:
            return json.dumps(maybe_data, indent=2, default=str)[:limit]
        except Exception:
            return str(maybe_data)[:limit]
    return str(maybe_data)[:limit]


def model_perf_monitor(args: Dict[str, Any]) -> Dict[str, Any]:
    baseline         = _stringify(args.get("baseline_stats"))
    current          = _stringify(args.get("current_stats"))
    pred_drift       = _stringify(args.get("prediction_drift"))
    model_name       = args.get("model_name", "model")
    labels_lag_days  = int(args.get("labels_lag_days", 7))
    library_hint     = args.get("library_hint", "auto")  # sklearn|pytorch|tf|xgboost|llm
    task_type        = args.get("task_type", "classification")  # classification|regression|llm

    system = (
        "You are an MLOps engineer specialising in production model monitoring. "
        "Given baseline vs. current feature/prediction statistics, compute / "
        "estimate per-feature drift using PSI, KS-statistic, JS-distance, "
        "KL-divergence, and Wasserstein distance, then classify each feature "
        "by severity. Detect concept drift via prediction-distribution shifts. "
        "Recommend retraining triggers and emit a complete monitoring config "
        "for Evidently AI or Arize, plus Grafana alerts. "
        "Output ONLY JSON: "
        "{model_name:str, task_type:str, "
        "overall_drift_score:float, "
        "data_drift_findings:[{feature,kind:'numeric'|'categorical',"
        "metric_used:'psi'|'ks'|'js'|'kl'|'wasserstein',value,"
        "severity:'critical'|'high'|'medium'|'low',interpretation}], "
        "concept_drift:{detected:bool,evidence,recommended_action}, "
        "performance_degradation:{primary_metric,baseline_value,current_value,"
        "delta_pct,significance}, "
        "retrain_recommendation:{should_retrain:bool,urgency:'now'|'this_week'"
        "|'monitor',reasoning,blocked_by_labels_lag_days:int}, "
        "monitoring_config:{tool:'evidently'|'arize'|'mlflow'|'wandb',"
        "yaml_or_python_snippet}, "
        "grafana_alerts:[{name,expr,for_minutes,severity,description}], "
        "feature_importance_shift:[str], "
        "next_diagnostic_steps:[str]}."
    )
    prompt = (
        f"Model: {model_name}  Task: {task_type}  Library: {library_hint}\n"
        f"Labels lag: {labels_lag_days}d\n\n"
        f"BASELINE STATS:\n{baseline}\n\n"
        f"CURRENT STATS:\n{current}\n\n"
        f"PREDICTION DRIFT SIGNAL:\n{pred_drift}\n\n"
        "Be quantitative. If a metric cannot be computed from supplied data, "
        "mark it 'insufficient_data' but still classify severity from any "
        "available signal."
    )

    data = _parse_json(_llm(prompt, system, "model_perf_monitor"), {
        "overall_drift_score": 0.0,
        "data_drift_findings": [], "grafana_alerts": [],
        "retrain_recommendation": {"should_retrain": False},
        "monitoring_config": {},
    })

    ts = _ts()
    cfg = data.get("monitoring_config", {})
    cfg_path = ""
    if cfg.get("yaml_or_python_snippet"):
        ext = "yml" if cfg.get("tool") in ("evidently", "arize") else "py"
        cfg_path = _save("monitoring",
                         f"model_monitor_{model_name}_{cfg.get('tool','tool')}_{ts}.{ext}",
                         cfg["yaml_or_python_snippet"])

    alerts_path = ""
    if data.get("grafana_alerts"):
        alerts_path = _save("monitoring", f"grafana_alerts_{model_name}_{ts}.json",
                            json.dumps(data["grafana_alerts"], indent=2))

    findings = data.get("data_drift_findings", [])
    crit = [f for f in findings if f.get("severity") in ("critical", "high")]
    retrain = data.get("retrain_recommendation", {})

    report = (
        f"# Model Performance Monitor — `{model_name}` — {ts}\n\n"
        f"**Overall drift score:** {data.get('overall_drift_score','?')}  "
        f"**Drifted features:** {len(findings)} ({len(crit)} critical/high)  "
        f"**Retrain:** {retrain.get('urgency','?')} "
        f"(should={retrain.get('should_retrain')})\n\n"
        f"## Concept drift\n"
        f"Detected: {data.get('concept_drift',{}).get('detected', False)}  \n"
        f"{data.get('concept_drift',{}).get('evidence','')}\n"
        f"Action: {data.get('concept_drift',{}).get('recommended_action','')}\n\n"
        "## Performance degradation\n"
        f"```json\n{json.dumps(data.get('performance_degradation',{}), indent=2)}\n```\n\n"
        "## Drifted features (ranked)\n"
        + "\n".join(
            f"- [{f.get('severity','?').upper()}] `{f.get('feature','?')}` "
            f"({f.get('kind','?')}) {f.get('metric_used','?')}="
            f"{f.get('value','?')} — {f.get('interpretation','')}"
            for f in findings
        )
        + "\n\n## Retrain recommendation\n"
        f"**Should retrain:** {retrain.get('should_retrain')}  "
        f"**Urgency:** {retrain.get('urgency','?')}  "
        f"**Blocked by labels lag:** "
        f"{retrain.get('blocked_by_labels_lag_days', labels_lag_days)}d\n"
        f"{retrain.get('reasoning','')}\n\n"
        "## Grafana alerts\n"
        + "\n".join(
            f"- **{a.get('name','?')}** [{a.get('severity','?')}] "
            f"`{a.get('expr','')}` for {a.get('for_minutes','?')}m"
            for a in data.get("grafana_alerts", [])
        )
        + "\n\n## Next diagnostic steps\n"
        + "\n".join(f"- {n}" for n in data.get("next_diagnostic_steps", []))
    )
    report_path = _save("reports", f"model_perf_monitor_{model_name}_{ts}.md", report)

    _record("model_perf_monitor", model_name,
            f"drift={data.get('overall_drift_score')} crit={len(crit)} "
            f"retrain={retrain.get('should_retrain')}")

    return {
        "model_name":              model_name,
        "task_type":               task_type,
        "overall_drift_score":     data.get("overall_drift_score"),
        "data_drift_findings":     findings,
        "critical_features":       crit,
        "concept_drift":           data.get("concept_drift", {}),
        "performance_degradation": data.get("performance_degradation", {}),
        "retrain_recommendation":  retrain,
        "monitoring_config":       cfg,
        "monitoring_config_path":  cfg_path,
        "grafana_alerts":          data.get("grafana_alerts", []),
        "grafana_alerts_path":     alerts_path,
        "feature_importance_shift": data.get("feature_importance_shift", []),
        "next_diagnostic_steps":   data.get("next_diagnostic_steps", []),
        "report_path":             report_path,
        "summary": (
            f"Model `{model_name}`: drift={data.get('overall_drift_score','?')}, "
            f"{len(findings)} drifted features, retrain={retrain.get('urgency','?')}. "
            f"→ {report_path}."
        ),
    }
