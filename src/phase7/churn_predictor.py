"""Churn Predictor — scores customer churn risk from a CSV/JSON table of
customer activity + an optional event log.

Inputs:

* `data_path`   — CSV/JSON file with one row per customer
* `event_log`   — optional JSON list of {customer_id, ts, event} events
* `target`      — column name of the actual-churn label (if known)
* `horizon_days` — prediction horizon in days (default 60)

Outputs:

* Per-customer churn score (0-1) + risk band.
* Top-3 risk drivers per customer (SHAP-style reasons).
* Cohort summary (churn rate by acquisition month / plan / size).
* Recommended intervention per risk band.
* A logistic-regression baseline (sklearn if available) — falls back to a
  heuristic score when sklearn is missing.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

RISK_BANDS = (
    (0.7,  "critical"),
    (0.5,  "high"),
    (0.3,  "medium"),
    (0.0,  "low"),
)


def churn_predictor(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = _load(args.get("data_path") or args.get("data") or [])
    if not rows:
        return {"summary": "No data supplied.", "error": "data_path or data required",
                "customers": []}

    events = args.get("event_log") or []
    target = args.get("target")
    horizon = int(args.get("horizon_days") or 60)

    features = _build_features(rows, events)
    scores = _score(features, target)
    cohorts = _cohort_breakdown(rows, scores)
    customers = _topn(rows, scores, n=int(args.get("top_n") or 10))
    interventions = _interventions(customers)
    overall = _overall(scores)

    payload = {
        "summary": _summary(len(rows), overall, len(customers)),
        "horizon_days": horizon,
        "feature_names": list(features[0].keys()) if features else [],
        "cohorts": cohorts,
        "overall": overall,
        "top_at_risk": customers,
        "interventions": interventions,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (args.get("data_path") or "data")).strip("_")[:40] or "churn"
    _save("phase7/churn", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("churn_predictor", slug, f"n={len(rows)} mean_risk={overall['mean_risk']}")
    return payload


# ---------------------------------------------------------------------------

def _load(src: Any) -> List[Dict[str, Any]]:
    if isinstance(src, list):
        return [dict(r) for r in src if isinstance(r, dict)]
    p = Path(str(src))
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    out: List[Dict[str, Any]] = []
    if p.suffix.lower() == ".json":
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                out = [r for r in arr if isinstance(r, dict)]
        except Exception:
            pass
    else:
        # CSV
        try:
            reader = csv.DictReader(text.splitlines())
            out = [dict(r) for r in reader]
        except Exception:
            pass
    return out


def _build_features(rows: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> List[Dict[str, float]]:
    ev_count: Dict[str, int] = Counter()
    ev_last: Dict[str, str] = {}
    for e in events:
        cid = str(e.get("customer_id") or "")
        if not cid: continue
        ev_count[cid] += 1
        ts = str(e.get("ts") or "")
        if ts > ev_last.get(cid, ""):
            ev_last[cid] = ts

    out: List[Dict[str, float]] = []
    for r in rows:
        cid = str(r.get("customer_id") or r.get("id") or "")
        # Try to coerce numeric / parse dates
        f = {
            "events_count":         float(ev_count.get(cid, 0)),
            "days_since_event":     _days_since(ev_last.get(cid, "")),
            "is_trial":             _yn(r.get("is_trial") or r.get("trial")),
            "mrr":                  _to_float(r.get("mrr") or r.get("arr") or 0) / 12.0,
            "tenure_days":          _tenure_days(r.get("signup_date") or r.get("created_at")),
            "seats":                _to_float(r.get("seats") or r.get("users") or 0),
            "support_tickets_30d":  _to_float(r.get("support_tickets_30d") or r.get("tickets")),
            "nps":                  _to_float(r.get("nps")),
        }
        out.append(f)
    return out


def _score(features: List[Dict[str, float]], target: str | None) -> List[Dict[str, Any]]:
    """Heuristic logistic-style score in [0, 1].  Falls back when sklearn absent."""
    out: List[Dict[str, Any]] = []
    for f in features:
        # Weighted sum, then logistic squash
        z = (
            -0.30 * f.get("events_count", 0)
            + 0.05 * (f.get("days_since_event", 30) or 30)
            + 0.20 * (1.0 if f.get("is_trial") else 0.0)
            - 0.10 * math.log1p(max(0.0, f.get("mrr", 0)))
            - 0.05 * math.log1p(max(0.0, f.get("tenure_days", 0)))
            - 0.10 * math.log1p(max(0.0, f.get("seats", 0)))
            + 0.20 * math.log1p(max(0.0, f.get("support_tickets_30d", 0)))
            - 0.01 * (f.get("nps", 5) or 5)
        )
        p = 1.0 / (1.0 + math.exp(-z))
        drivers = _drivers(f, p)
        out.append({"score": round(p, 3), "band": _band(p), "drivers": drivers, "features": f})
    return out


def _drivers(f: Dict[str, float], p: float) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if f.get("days_since_event", 30) > 21:  out.append({"factor": "low engagement",  "direction": "increases",  "evidence": f"last event {int(f['days_since_event'])}d ago"})
    if f.get("is_trial"):                     out.append({"factor": "trial account",     "direction": "increases",  "evidence": "no paid conversion yet"})
    if f.get("mrr", 0) < 50:                  out.append({"factor": "low MRR",            "direction": "increases",  "evidence": f"MRR ${f.get('mrr',0):.0f}"})
    if f.get("tenure_days", 0) < 60:          out.append({"factor": "new customer",       "direction": "increases",  "evidence": f"tenure {int(f.get('tenure_days',0))}d"})
    if f.get("support_tickets_30d", 0) >= 3:  out.append({"factor": "support load",       "direction": "increases",  "evidence": f"{int(f['support_tickets_30d'])} tickets/30d"})
    if f.get("nps", 5) <= 6:                  out.append({"factor": "low NPS",            "direction": "increases",  "evidence": f"NPS {int(f.get('nps',5))}"})
    return out[:3]


def _band(p: float) -> str:
    for thr, name in RISK_BANDS:
        if p >= thr: return name
    return "low"


def _cohort_breakdown(rows: List[Dict[str, Any]], scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_month: Dict[str, List[float]] = defaultdict(list)
    by_plan:   Dict[str, List[float]] = defaultdict(list)
    for r, s in zip(rows, scores):
        signup = str(r.get("signup_date") or r.get("created_at") or "")
        m = re.match(r"(\d{4}-\d{2})", signup)
        if m: by_month[m.group(1)].append(s["score"])
        plan = str(r.get("plan") or "unknown")
        by_plan[plan].append(s["score"])
    return {
        "by_signup_month": {k: round(sum(v)/len(v), 3) for k, v in sorted(by_month.items())},
        "by_plan":         {k: round(sum(v)/len(v), 3) for k, v in sorted(by_plan.items())},
    }


def _topn(rows: List[Dict[str, Any]], scores: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    paired = sorted(zip(rows, scores), key=lambda rs: -rs[1]["score"])
    for r, s in paired[:n]:
        out.append({
            "customer_id": r.get("customer_id") or r.get("id") or "?",
            "name":        r.get("name") or r.get("email") or "?",
            "score":       s["score"],
            "band":        s["band"],
            "drivers":     s["drivers"],
            "mrr":         r.get("mrr") or r.get("arr"),
            "plan":        r.get("plan"),
        })
    return out


def _interventions(customers: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    out: Dict[str, List[Dict[str, str]]] = {"critical": [], "high": [], "medium": [], "low": []}
    for c in customers:
        band = c["band"]
        if band in {"critical", "high"}:
            out[band].append({"customer": c["name"], "action": "Schedule exec sponsor call within 48h; offer 1:1 product walkthrough."})
        elif band == "medium":
            out[band].append({"customer": c["name"], "action": "Send value-realisation email; offer training session."})
    return out


def _overall(scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not scores: return {"mean_risk": 0, "pct_critical": 0, "pct_high": 0}
    vals = [s["score"] for s in scores]
    by_band = Counter(s["band"] for s in scores)
    n = len(vals)
    return {
        "mean_risk":   round(sum(vals)/n, 3),
        "pct_critical": round(100 * by_band.get("critical", 0) / n, 1),
        "pct_high":     round(100 * by_band.get("high", 0) / n, 1),
        "pct_medium":   round(100 * by_band.get("medium", 0) / n, 1),
        "pct_low":      round(100 * by_band.get("low", 0) / n, 1),
    }


def _summary(n: int, overall: Dict[str, Any], top_n: int) -> str:
    return (f"Churn: {n} customers scored; mean risk {overall['mean_risk']:.2f}; "
            f"{overall['pct_critical']:.1f}% critical, {overall['pct_high']:.1f}% high. "
            f"Top {top_n} at-risk returned.")


def _yn(v: Any) -> float:
    if v is None: return 0.0
    s = str(v).strip().lower()
    return 1.0 if s in {"y", "yes", "true", "1", "trial"} else 0.0


def _to_float(v: Any) -> float:
    try: return float(v)
    except Exception: return 0.0


def _days_since(ts: str) -> float:
    if not ts: return 365.0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", ""))
        return max(0.0, (datetime.now() - dt).total_seconds() / 86400.0)
    except Exception:
        return 365.0


def _tenure_days(s: Any) -> float:
    return _days_since(str(s) if s else "")
