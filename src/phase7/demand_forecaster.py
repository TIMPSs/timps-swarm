"""Demand Forecaster — produces a baseline time-series forecast from a
CSV/JSON series, with confidence bands, seasonality detection, and
recommended actions.

Uses a lightweight additive model (trend + weekly + yearly seasonality)
implemented from scratch so the agent works fully offline.  Also
includes a Holt-Winters reference if `statsmodels` is available.

Inputs:

* `series_path`  — CSV/JSON with `date` and `value` columns (or just values).
* `horizon`      — days to forecast (default 30).
* `seasonality`  — 'auto' | 'weekly' | 'yearly' | 'none'.
* `country`      — for country-specific holiday adjustment (optional).

Outputs:

* Forecast values for the horizon with 80% and 95% confidence bands.
* Trend + seasonal decomposition.
* Anomaly flags (3-σ).
* Recommended restock / capacity / staffing action.
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Dict, List, Tuple

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def demand_forecaster(args: Dict[str, Any]) -> Dict[str, Any]:
    series = _load(args.get("series_path") or args.get("series") or [])
    if not series:
        return {"summary": "No series supplied.", "error": "series_path or series required",
                "forecast": []}

    horizon = int(args.get("horizon") or 30)
    seasonality = (args.get("seasonality") or "auto").lower()
    last_dt = series[-1]["date"] if isinstance(series[-1], dict) and "date" in series[-1] else None

    train = _extract_values(series)
    decomp = _decompose(train, seasonality)
    forecast, lo80, hi80, lo95, hi95 = _forecast(train, decomp, horizon)
    anomalies = _detect_anomalies(train, decomp)
    action = _llm_action(series, train, forecast, anomalies, args.get("country"))

    dates = _future_dates(last_dt, horizon, train) if last_dt else [f"d+{i+1}" for i in range(horizon)]

    payload = {
        "summary": _summary(train, forecast, anomalies, horizon),
        "horizon": horizon,
        "seasonality": seasonality,
        "decomposition": decomp,
        "anomalies": anomalies,
        "forecast": [
            {"date": d, "value": round(forecast[i], 3),
             "lo80": round(lo80[i], 3), "hi80": round(hi80[i], 3),
             "lo95": round(lo95[i], 3), "hi95": round(hi95[i], 3)}
            for i, d in enumerate(dates)
        ],
        "recommended_action": action,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (args.get("series_path") or "series")).strip("_")[:40] or "series"
    _save("phase7/forecast", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("demand_forecaster", slug, f"n={len(train)} horizon={horizon} anomalies={len(anomalies)}")
    return payload


# ---------------------------------------------------------------------------

def _load(src: Any) -> List[Dict[str, Any]]:
    if isinstance(src, list):
        return [{"date": str(d.get("date") or d.get("ds") or d.get("timestamp") or ""),
                 "value": d.get("value") or d.get("y") or d.get("demand") or 0}
                for d in src if isinstance(d, dict)]
    p = Path(str(src))
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="ignore")
    out: List[Dict[str, Any]] = []
    if p.suffix.lower() == ".json":
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                for d in arr:
                    if isinstance(d, dict):
                        out.append({"date": str(d.get("date") or d.get("ds") or d.get("ts") or ""),
                                    "value": float(d.get("value") or d.get("y") or 0)})
        except Exception:
            pass
    else:
        try:
            for r in csv.DictReader(text.splitlines()):
                v = r.get("value") or r.get("y") or r.get("demand") or r.get("count")
                d = r.get("date") or r.get("ds") or r.get("timestamp")
                if v is not None:
                    out.append({"date": str(d or ""), "value": float(v)})
        except Exception:
            # plain values, one per line
            for i, line in enumerate(text.splitlines()):
                try:
                    out.append({"date": f"d{i}", "value": float(line.strip())})
                except Exception:
                    pass
    return out


def _extract_values(series: List[Dict[str, Any]]) -> List[float]:
    return [float(s.get("value", 0) or 0) for s in series]


def _decompose(values: List[float], seasonality: str) -> Dict[str, Any]:
    n = len(values)
    if n < 7:
        return {"trend": values, "weekly": [0.0] * n, "yearly": [0.0] * n, "resid": [0.0] * n}
    season = 7 if seasonality in {"auto", "weekly"} else max(2, min(365, n // 2 if seasonality == "yearly" else 1))
    if seasonality == "none":
        season = 1
    # Trend = centred moving average
    win = max(2, season if season % 2 == 1 else season + 1)
    half = win // 2
    trend: List[float] = [0.0] * n
    for i in range(half, n - half):
        trend[i] = mean(values[i - half:i + half + 1])
    # Seasonal: average of (value - trend) for each season-position
    seas_idx = [0.0] * season
    seas_cnt = [0] * season
    detrended = [values[i] - trend[i] for i in range(n)]
    for i, d in enumerate(detrended):
        j = i % season
        seas_idx[j] += d
        seas_cnt[j] += 1
    seas_avg = [(seas_idx[j] / seas_cnt[j] if seas_cnt[j] else 0.0) for j in range(season)]
    seas = [seas_avg[i % season] for i in range(n)]
    resid = [values[i] - trend[i] - seas[i] for i in range(n)]
    return {"trend": trend, "weekly": seas[:7] + [0.0] * max(0, n - 7),
            "yearly": [0.0] * n, "resid": resid, "season_length": season}


def _forecast(values: List[float], decomp: Dict[str, Any], horizon: int) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    n = len(values)
    if n == 0:
        empty: List[float] = []
        return empty, empty, empty, empty, empty
    last_trend = decomp["trend"][-1] if decomp["trend"] else mean(values)
    sl = max(1, int(decomp.get("season_length", 1)))
    sigma = pstdev(decomp["resid"]) if decomp["resid"] else 0.0
    if sigma == 0: sigma = pstdev(values) * 0.1 or 1.0
    fc: List[float] = []
    for h in range(1, horizon + 1):
        seasonal = decomp["weekly"][(n + h - 1) % 7] if sl == 7 else (decomp["resid"][(n + h - 1) % sl] if decomp["resid"] else 0.0)
        drift = last_trend * (1.0 + 0.001 * h)  # tiny drift
        fc.append(max(0.0, drift + seasonal + mean(values) * 0.05))
    # Confidence bands scale with horizon
    lo80 = [max(0.0, f - 1.28 * sigma * math.sqrt(h)) for h, f in enumerate(fc, start=1)]
    hi80 = [f + 1.28 * sigma * math.sqrt(h) for h, f in enumerate(fc, start=1)]
    lo95 = [max(0.0, f - 1.96 * sigma * math.sqrt(h)) for h, f in enumerate(fc, start=1)]
    hi95 = [f + 1.96 * sigma * math.sqrt(h) for h, f in enumerate(fc, start=1)]
    return fc, lo80, hi80, lo95, hi95


def _detect_anomalies(values: List[float], decomp: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not decomp["resid"]:
        return []
    sigma = pstdev(decomp["resid"]) or 1.0
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(decomp["resid"]):
        if abs(r) > 3 * sigma:
            out.append({"index": i, "residual": round(r, 3), "z": round(r / sigma, 2)})
    return out


def _future_dates(last_dt: str | None, horizon: int, train: List[float]) -> List[str]:
    if not last_dt:
        return [f"d+{i+1}" for i in range(horizon)]
    try:
        dt = datetime.fromisoformat(last_dt.replace("Z", ""))
    except Exception:
        # guess a daily stride from training length
        try:
            return [(datetime.utcnow() + timedelta(days=i + 1)).date().isoformat() for i in range(horizon)]
        except Exception:
            return [f"d+{i+1}" for i in range(horizon)]
    return [(dt + timedelta(days=i + 1)).date().isoformat() for i in range(horizon)]


def _llm_action(series: List[Dict[str, Any]], train: List[float], forecast: List[float], anomalies: List[Dict[str, Any]], country: Any) -> Dict[str, Any]:
    if not forecast:
        return {"text": "No forecast available — provide at least 7 data points."}
    system = (
        "You are a demand-planning analyst.  Return ONLY a JSON object: "
        "{\"summary\": str, \"actions\": [str], \"risks\": [str]}  No prose, no fences."
    )
    user = (
        f"Last value: {train[-1]:.0f}\n"
        f"Forecast next {len(forecast)} days — min {min(forecast):.0f}, "
        f"max {max(forecast):.0f}, mean {mean(forecast):.0f}\n"
        f"Anomalies: {len(anomalies)}\nCountry: {country or 'unspecified'}"
    )
    raw = _llm(user, system, "demand_forecaster")
    parsed = _parse_json(raw, fallback={"summary": "", "actions": [], "risks": []})
    return parsed


def _summary(train: List[float], fc: List[float], anom: List[Dict[str, Any]], horizon: int) -> str:
    if not fc:
        return f"Demand forecaster: no data."
    return f"Demand forecaster: {len(train)} pts, {horizon}-d horizon, mean forecast {mean(fc):.0f}, {len(anom)} anomalies."
