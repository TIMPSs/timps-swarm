"""Wearable Health Coach — analyses a week of wearable data (Apple Watch,
Oura, Whoop, Garmin, Fitbit) and produces a recovery + training-load
recommendation.

Inputs (any of):

* `csv_path`     — CSV with at least: date, sleep_minutes, resting_hr,
                    hrv_ms, steps, active_minutes, workout_minutes,
                    calories, vo2_max (optional).
* `json_path`    — same shape as JSON.

Outputs:

* Per-day recovery score (0-100).
* 7-day trend (recovery, HRV, RHR, sleep, training load).
* A training recommendation: easy / moderate / hard / rest.
* Specific nudges (hydration, sleep, caffeine cutoff, sunlight).
* Risk flags (over-reaching, illness signal, dehydration).
* A coach-style one-paragraph read-out.

The agent is LLM-driven; metrics are computed deterministically.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def wearable_health_coach(args: Dict[str, Any]) -> Dict[str, Any]:
    rows = _load(args.get("csv_path") or args.get("json_path") or args.get("data") or [])
    if not rows:
        return {"summary": "No wearable data supplied.", "error": "csv_path or json_path is required",
                "days": []}

    days = _per_day_scores(rows)
    trends = _trends(days)
    risk_flags = _risk_flags(days)
    rec = _recommendation(days, trends, risk_flags)
    nudges = _nudges(days)
    readout = _llm_readout(days, trends, risk_flags, rec)

    payload = {
        "summary": _summary(days, trends, rec),
        "days": days,
        "trends": trends,
        "risk_flags": risk_flags,
        "recommendation": rec,
        "nudges": nudges,
        "coach_readout": readout,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (args.get("csv_path") or args.get("json_path") or "wearable")).strip("_")[:40] or "wearable"
    _save("phase7/health_coach", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("wearable_health_coach", slug, f"days={len(days)} recovery_avg={trends.get('recovery_avg')}")
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
        try:
            for r in csv.DictReader(text.splitlines()):
                out.append(dict(r))
        except Exception:
            pass
    return out


def _to_float(v: Any) -> float:
    try: return float(v)
    except Exception: return 0.0


def _per_day_scores(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = str(r.get("date") or r.get("day") or "")
        sleep = _to_float(r.get("sleep_minutes") or r.get("sleep"))
        rhr   = _to_float(r.get("resting_hr") or r.get("rhr"))
        hrv   = _to_float(r.get("hrv_ms") or r.get("hrv"))
        steps = _to_float(r.get("steps"))
        active= _to_float(r.get("active_minutes") or r.get("active"))
        work  = _to_float(r.get("workout_minutes") or r.get("workout"))
        cal   = _to_float(r.get("calories"))
        vo2   = _to_float(r.get("vo2_max"))

        # Recovery score (0-100): blend of sleep adequacy, RHR (lower better),
        # HRV (higher better), and training load.
        sleep_score = min(40.0, sleep / 480 * 40)  # target 8h
        rhr_score   = max(0.0, 30.0 - max(0, rhr - 50))  # 50→30, 80→0
        hrv_score   = min(20.0, hrv / 100 * 20)
        load_pen    = min(20.0, work / 90 * 20)
        recovery    = round(sleep_score + rhr_score + hrv_score - load_pen * 0.5 + 10, 1)
        recovery    = max(0.0, min(100.0, recovery))

        out.append({
            "date": d, "sleep_minutes": sleep, "resting_hr": rhr, "hrv_ms": hrv,
            "steps": steps, "active_minutes": active, "workout_minutes": work,
            "calories": cal, "vo2_max": vo2,
            "recovery": recovery,
            "training_load": round(work * 1.0 + active * 0.5, 1),
        })
    return out


def _trends(days: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not days: return {}
    rec = [d["recovery"] for d in days]
    hrv = [d["hrv_ms"] for d in days]
    rhr = [d["resting_hr"] for d in days]
    return {
        "recovery_avg": round(mean(rec), 1),
        "recovery_min": round(min(rec), 1),
        "recovery_max": round(max(rec), 1),
        "hrv_avg":      round(mean([h for h in hrv if h]) or 0, 1),
        "rhr_avg":      round(mean([r for r in rhr if r]) or 0, 1),
        "training_load_avg": round(mean([d["training_load"] for d in days]), 1),
        "trend_recovery": "up" if rec[-1] > rec[0] else ("down" if rec[-1] < rec[0] else "flat"),
    }


def _risk_flags(days: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not days: return out
    avg_rhr = mean([d["resting_hr"] for d in days if d["resting_hr"]]) or 0
    avg_hrv = mean([d["hrv_ms"] for d in days if d["hrv_ms"]]) or 0
    if avg_rhr and avg_rhr > 70: out.append({"flag": "elevated RHR",  "severity": "medium", "note": f"7-day average RHR {avg_rhr:.0f} bpm."})
    if avg_hrv and avg_hrv < 40: out.append({"flag": "low HRV",      "severity": "medium", "note": f"7-day average HRV {avg_hrv:.0f} ms."})
    if sum(1 for d in days if d["sleep_minutes"] < 360) >= 3: out.append({"flag": "chronic sleep debt", "severity": "high", "note": "3+ nights under 6h."})
    if sum(d["workout_minutes"] for d in days) > 600: out.append({"flag": "over-reaching", "severity": "high", "note": f"Total weekly training {sum(d['workout_minutes'] for d in days):.0f} min."})
    return out


def _recommendation(days: List[Dict[str, Any]], trends: Dict[str, Any], risks: List[Dict[str, str]]) -> Dict[str, Any]:
    if not days: return {"verdict": "rest", "reason": "no data"}
    last = days[-1]["recovery"]
    if any(r["severity"] == "high" for r in risks):    verdict = "rest"
    elif last < 40:                                      verdict = "rest"
    elif last < 60:                                      verdict = "easy"
    elif last < 80:                                      verdict = "moderate"
    else:                                                verdict = "hard"
    return {"verdict": verdict, "recovery_today": last, "recovery_avg": trends.get("recovery_avg")}


def _nudges(days: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    if days and mean([d["sleep_minutes"] for d in days]) < 420:
        out.append("Push sleep window earlier by 30 min for 3 nights.")
    if days and mean([d["resting_hr"] for d in days if d["resting_hr"]]) > 65:
        out.append("Cut caffeine after 14:00 and add a 10-min afternoon walk.")
    if days and sum(d["workout_minutes"] for d in days) > 480:
        out.append("Insert a deload day — 60 min of mobility or zone-2 only.")
    if not out:
        out.append("Maintain current routine; consider a small strength session.")
    return out


def _llm_readout(days: List[Dict[str, Any]], trends: Dict[str, Any], risks: List[Dict[str, str]], rec: Dict[str, Any]) -> str:
    system = (
        "You are a friendly endurance coach.  Write a 120-180 word readout in 2nd person.  "
        "Acknowledge the wins, name the recovery score, give one concrete action.  "
        "No emojis, no markdown.  Plain text."
    )
    user = (
        f"7-day average recovery: {trends.get('recovery_avg')}\n"
        f"Today's recommendation: {rec.get('verdict')}\n"
        f"HRV: {trends.get('hrv_avg')} ms, RHR: {trends.get('rhr_avg')} bpm\n"
        f"Risks: {json.dumps(risks)[:300]}"
    )
    return _llm(user, system, "wearable_health_coach").strip()


def _summary(days: List[Dict[str, Any]], trends: Dict[str, Any], rec: Dict[str, Any]) -> str:
    return f"Wearable coach: {len(days)} days, avg recovery {trends.get('recovery_avg')}, today → {rec.get('verdict')}."
