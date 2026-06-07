"""Agri Commodity Forecaster — Indian mandi price forecaster.

Inputs:

* `commodity`     — e.g. "wheat", "soybean", "onion", "tomato", "turmeric"
* `mandi`         — e.g. "Indore", "Lasalgaon", "Azadpur" (or 'all')
* `horizon_days`  — forecast horizon in days (default 14)
* `state`         — optional state filter
* `series`        — optional pre-loaded series; otherwise fetches from
                    data.gov.in's open mandi-price API (requires API key)
                    or returns an offline heuristic forecast.

Outputs:

* 14-day forecast (point + 80% band) for the commodity
* Seasonal pattern detected
* Arrival-supply pressure index
* MSP reference if the commodity is MSP-covered
* Recommended action (sell now, hold, hedge)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

# MSP (₹/quintal) for 2025-26 rabi + kharif — rough reference
MSP_2025_26 = {
    "wheat":     2425,
    "paddy":     2369,
    "soybean":   4892,
    "turmeric": 13522,
    "cotton":    7521,
    "maize":     2225,
    "onion":     None,
    "tomato":    None,
}


def agri_commodity_forecaster(args: Dict[str, Any]) -> Dict[str, Any]:
    commodity = (args.get("commodity") or "").strip().lower()
    if not commodity:
        return {"summary": "No commodity supplied.", "error": "commodity is required",
                "forecast": []}

    mandi = (args.get("mandi") or "all").strip()
    state = args.get("state") or ""
    horizon = int(args.get("horizon_days") or 14)
    series = args.get("series") or []
    api_key = os.getenv("DATA_GOV_IN_KEY")

    if not series and api_key:
        series = _fetch_data_gov_in(commodity, state, api_key)

    if not series:
        series = _synthetic_series(commodity)

    forecast, lo, hi = _forecast(series, horizon)
    seasonal = _seasonality(series)
    pressure = _supply_pressure(series)
    msp = MSP_2025_26.get(commodity)
    action = _llm_action(commodity, mandi, forecast, msp, pressure)

    dates = [(datetime.utcnow() + timedelta(days=i + 1)).date().isoformat() for i in range(horizon)]
    payload = {
        "summary": _summary(commodity, mandi, forecast, msp, pressure),
        "commodity": commodity,
        "mandi": mandi,
        "state": state,
        "horizon_days": horizon,
        "msp_inr_per_quintal": msp,
        "supply_pressure_index": pressure,
        "seasonal_pattern": seasonal,
        "history": series[-30:],
        "forecast": [
            {"date": d, "price_inr_per_quintal": round(forecast[i], 2),
             "lo80": round(lo[i], 2), "hi80": round(hi[i], 2)}
            for i, d in enumerate(dates)
        ],
        "recommended_action": action,
        "data_source": "data.gov.in" if api_key and len(series) > 30 else "synthetic (offline)",
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", commodity).strip("_")[:40] or "crop"
    _save("phase7/agri", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("agri_commodity_forecaster", commodity, f"mandi={mandi} horizon={horizon} data={payload['data_source']}")
    return payload


# ---------------------------------------------------------------------------

def _fetch_data_gov_in(commodity: str, state: str, api_key: str) -> List[Dict[str, Any]]:
    """Best-effort fetch from data.gov.in's AGMARKET resource.  Returns [] on any error."""
    try:
        import requests
        url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": 200,
            "filters[commodity]": commodity,
        }
        if state:
            params["filters[state]"] = state
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        recs = (r.json() or {}).get("records") or []
        out: List[Dict[str, Any]] = []
        for rec in recs:
            try:
                p = float(rec.get("modal_price") or 0)
                d = str(rec.get("arrival_date") or "")
                if p > 0 and d:
                    out.append({"date": d, "price": p, "market": rec.get("market", "")})
            except Exception:
                continue
        out.sort(key=lambda x: x["date"])
        return out
    except Exception:
        return []


def _synthetic_series(commodity: str) -> List[Dict[str, Any]]:
    """When offline, generate a plausible seasonal walk anchored to a known base price."""
    base = MSP_2025_26.get(commodity) or {
        "wheat": 2400, "paddy": 2200, "soybean": 4700, "turmeric": 13000,
        "cotton": 7200, "maize": 2100, "onion": 1800, "tomato": 1500,
    }.get(commodity, 2500)
    import math
    today = datetime.utcnow().date()
    out: List[Dict[str, Any]] = []
    for i in range(180, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        season = math.sin(i / 30) * 0.05
        noise = ((i * 31) % 17 - 8) / 200  # pseudo-noise
        price = base * (1 + season + noise)
        out.append({"date": d, "price": price, "market": "synthetic"})
    return out


def _forecast(series: List[Dict[str, Any]], horizon: int) -> tuple:
    prices = [s["price"] for s in series]
    n = len(prices)
    if n < 7:
        return ([prices[-1] if prices else 0] * horizon,
                [0] * horizon, [0] * horizon)
    # Simple: last-7 average as the level + a tiny trend
    last7 = prices[-7:]
    level = mean(last7)
    trend = (mean(last7) - mean(prices[-14:-7])) / 7 if n >= 14 else 0.0
    sigma = pstdev(prices[-30:]) if n >= 30 else pstdev(prices) or 1.0
    fc: List[float] = []
    lo: List[float] = []
    hi: List[float] = []
    for h in range(1, horizon + 1):
        p = max(1.0, level + trend * h)
        fc.append(p)
        band = 1.28 * sigma * (h ** 0.5)
        lo.append(max(1.0, p - band)); hi.append(p + band)
    return fc, lo, hi


def _seasonality(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(series) < 60:
        return {"detected": False, "note": "Not enough history."}
    by_month: Dict[str, List[float]] = {}
    for s in series:
        m = s["date"][5:7] if len(s["date"]) >= 7 else ""
        if m: by_month.setdefault(m, []).append(s["price"])
    if not by_month:
        return {"detected": False, "note": "No monthly aggregation possible."}
    month_avg = {m: round(mean(v), 2) for m, v in by_month.items()}
    peak = max(month_avg, key=month_avg.get)
    trough = min(month_avg, key=month_avg.get)
    return {
        "detected": True,
        "monthly_avg_inr_per_quintal": month_avg,
        "peak_month": peak,
        "trough_month": trough,
        "amplitude_pct": round(100 * (month_avg[peak] - month_avg[trough]) / month_avg[trough], 1),
    }


def _supply_pressure(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Heuristic: recent slope + volatility vs the prior month."""
    if len(series) < 30:
        return {"index": 0, "note": "Insufficient data."}
    recent = [s["price"] for s in series[-14:]]
    prior  = [s["price"] for s in series[-30:-14]]
    delta_pct = 100 * (mean(recent) - mean(prior)) / max(1.0, mean(prior))
    vol_pct   = 100 * pstdev(recent) / max(1.0, mean(recent))
    if delta_pct > 5 and vol_pct < 10:  label = "tight supply, prices rising"
    elif delta_pct < -5:                 label = "supply easing, prices falling"
    elif vol_pct > 15:                   label = "volatile, mixed signals"
    else:                                 label = "balanced"
    return {"recent_pct_change_14d": round(delta_pct, 1),
            "volatility_pct": round(vol_pct, 1),
            "label": label}


def _llm_action(commodity: str, mandi: str, forecast: List[float], msp: Any, pressure: Dict[str, Any]) -> Dict[str, Any]:
    if not forecast:
        return {"text": "No forecast available."}
    last = forecast[0]
    peak = max(forecast); trough = min(forecast)
    system = (
        "You are an Indian agri-marketing advisor.  Return ONLY a JSON object: "
        "{\"summary\": str, \"actions\": [str], \"risks\": [str]}  No fences."
    )
    user = (
        f"Commodity: {commodity}\nMandi: {mandi}\n"
        f"MSP: ₹{msp}/quintal (if covered) — {'YES' if msp else 'no MSP'}\n"
        f"Forecast next {len(forecast)}d: start ₹{last:.0f}, peak ₹{peak:.0f}, trough ₹{trough:.0f}\n"
        f"Supply pressure: {json.dumps(pressure)}"
    )
    raw = _llm(user, system, "agri_commodity_forecaster")
    parsed = _parse_json(raw, fallback={"summary": "", "actions": [], "risks": []})
    return parsed


def _summary(commodity: str, mandi: str, fc: List[float], msp: Any, pressure: Dict[str, Any]) -> str:
    if not fc:
        return f"Agri forecaster ({commodity}, {mandi}): no data."
    return f"Agri ({commodity}, {mandi}): {len(fc)}-day forecast from ₹{fc[0]:.0f}; MSP ₹{msp or 'n/a'}; supply={pressure.get('label', 'n/a')}."
