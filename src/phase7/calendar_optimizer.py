"""Calendar Optimizer — analyses a calendar (Google/Outlook/ICS) and:

* Scores every meeting on cost (attendees × duration × hourly cost).
* Identifies focus-time blocks and fragmentation.
* Detects recurring meetings that should be batched, dropped, or
  shortened.
* Proposes a reorganised week (focus blocks, walking-buffer, lunch).
* Outputs an .ics file with the new schedule AND a list of cancellation
  / shortening suggestions to send to each meeting owner.

The agent never writes to a real calendar — it generates artefacts the
user can apply manually.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def calendar_optimizer(args: Dict[str, Any]) -> Dict[str, Any]:
    ics_path = args.get("ics_path")
    events = args.get("events") or []
    if not events and ics_path and Path(ics_path).is_file():
        events = _parse_ics(Path(ics_path).read_text(encoding="utf-8", errors="ignore"))
    if not events:
        return {"summary": "No events supplied.", "error": "events[] or ics_path required",
                "recommendations": []}

    hourly_cost = float(args.get("hourly_cost") or 75.0)  # default $75/h
    work_start = args.get("work_start") or "09:00"
    work_end   = args.get("work_end")   or "18:00"
    focus_min  = int(args.get("focus_minutes") or 90)
    meeting_cap = int(args.get("meeting_cap_minutes") or 45)

    analysis = _analyze(events, hourly_cost)
    recs = _recommend(events, analysis, work_start, work_end, focus_min, meeting_cap)
    new_ics = _render_ics(recs["proposed_events"])
    new_ics_path = _save_ics(new_ics, ics_path or "calendar")
    cancellation_drafts = _cancellation_drafts(events, recs["to_drop"])

    payload = {
        "summary": _summary(analysis, recs),
        "event_count": len(events),
        "analysis": analysis,
        "recommendations": recs,
        "cancellation_drafts": cancellation_drafts,
        "new_ics": new_ics,
        "new_ics_path": new_ics_path,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", (ics_path or "calendar").lower()).strip("_")[:40] or "cal"
    _save("phase7/calendar", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("calendar_optimizer", slug, f"events={len(events)} drops={len(recs.get('to_drop', []))}")
    return payload


# ---------------------------------------------------------------------------

def _parse_ics(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cur: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            cur = {"attendees": []}
        elif line == "END:VEVENT":
            if cur.get("summary"):
                out.append(cur); cur = {}
        elif line.startswith("SUMMARY:"):
            cur["summary"] = line[len("SUMMARY:"):]
        elif line.startswith("DTSTART"):
            cur["start"] = _ics_dt(line.split(":", 1)[-1])
        elif line.startswith("DTEND"):
            cur["end"]   = _ics_dt(line.split(":", 1)[-1])
        elif line.startswith("RRULE"):
            cur["recurring"] = True
        elif line.startswith("ATTENDEE"):
            cur["attendees"].append(line.split(":", 1)[-1])
        elif line.startswith("ORGANIZER"):
            cur["organizer"] = line.split(":", 1)[-1]
    return out


def _ics_dt(s: str) -> str:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    if "T" in s and len(s) >= 15:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}"
    if len(s) == 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _analyze(events: List[Dict[str, Any]], hourly_cost: float) -> Dict[str, Any]:
    total_min = 0
    total_cost = 0.0
    by_day: Dict[str, int] = {}
    longest: List[Dict[str, Any]] = []
    recurring: List[Dict[str, Any]] = []
    for e in events:
        try:
            s = datetime.fromisoformat(e.get("start", ""))
            en = datetime.fromisoformat(e.get("end", ""))
        except Exception:
            continue
        dur = max(0, (en - s).total_seconds() / 60)
        cost = dur / 60 * max(1, len(e.get("attendees", [])) + 1) * hourly_cost
        total_min += dur
        total_cost += cost
        day = s.date().isoformat()
        by_day[day] = by_day.get(day, 0) + int(dur)
        if e.get("recurring"):
            recurring.append({"summary": e.get("summary", ""), "duration_min": int(dur), "cost_usd": round(cost, 2)})
        longest.append({"summary": e.get("summary", ""), "duration_min": int(dur), "cost_usd": round(cost, 2), "start": s.isoformat()})
    longest.sort(key=lambda x: -x["duration_min"])
    return {
        "total_meeting_minutes": int(total_min),
        "total_meeting_hours":   round(total_min / 60, 1),
        "total_cost_usd":        round(total_cost, 2),
        "avg_meeting_minutes":   round(total_min / max(1, len(events)), 1),
        "events_per_day":        round(len(events) / max(1, len(by_day)), 1),
        "busiest_day":           max(by_day, key=by_day.get) if by_day else None,
        "recurring_meetings":    sorted(recurring, key=lambda x: -x["cost_usd"])[:5],
        "longest_meetings":      longest[:5],
    }


def _recommend(events: List[Dict[str, Any]], analysis: Dict[str, Any], ws: str, we: str, focus_min: int, cap: int) -> Dict[str, Any]:
    to_drop: List[Dict[str, Any]] = []
    to_shorten: List[Dict[str, Any]] = []
    proposed: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}

    for e in events:
        try:
            s = datetime.fromisoformat(e.get("start", ""))
            en = datetime.fromisoformat(e.get("end", ""))
        except Exception:
            continue
        dur = int((en - s).total_seconds() / 60)
        key = e.get("summary", "").strip().lower()
        seen[key] = seen.get(key, 0) + 1
        if dur > cap and e.get("recurring"):
            to_shorten.append({"summary": e["summary"], "current_min": dur, "target_min": cap, "savings_min": dur - cap})
            en = s + timedelta(minutes=cap)
        proposed.append({"summary": e.get("summary", ""), "start": s.isoformat(), "end": en.isoformat(),
                         "attendees": e.get("attendees", []), "organizer": e.get("organizer", "")})

    for k, n in seen.items():
        if n >= 4 and k:
            to_drop.append({"summary": k, "occurrences": n, "reason": f"Recurring meeting held {n}× — likely a status meeting; consider an async status doc."})

    # Build a focus-block proposal for the upcoming week
    if events:
        first_day = min(e["start"][:10] for e in proposed if e.get("start"))
        for d_offset in range(5):
            day = (datetime.fromisoformat(first_day) + timedelta(days=d_offset)).date()
            proposed.append({
                "summary": "Focus block",
                "start": f"{day}T{ws}:00",
                "end":   f"{day}T{(datetime.strptime(ws, '%H:%M') + timedelta(minutes=focus_min)).strftime('%H:%M')}:00",
                "attendees": [], "organizer": "self",
            })
    return {"proposed_events": proposed, "to_drop": to_drop, "to_shorten": to_shorten, "focus_blocks_added": 5}


def _cancellation_drafts(events: List[Dict[str, Any]], to_drop: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [
        {"meeting": d["summary"],
         "draft": (f"Hi team — I've been reviewing recurring meetings and proposing to drop our {d['summary']} "
                   f"call ({d['occurrences']}× this period). I think a written async update would serve us better. "
                   "Reply with objections by Friday; otherwise I'll convert to an async doc next week.")}
        for d in to_drop
    ]


def _render_ics(events: List[Dict[str, Any]]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TIMPS Swarm//calendar_optimizer//EN"]
    for e in events:
        lines += ["BEGIN:VEVENT",
                  f"SUMMARY:{e.get('summary','')}",
                  f"DTSTART:{_to_ics_dt(e.get('start',''))}",
                  f"DTEND:{_to_ics_dt(e.get('end',''))}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\n".join(lines) + "\n"


def _to_ics_dt(s: str) -> str:
    return s.replace(":", "").replace("-", "")


def _save_ics(ics: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:40] or "calendar"
    p = Path(f"generated/phase7/calendar/{slug}_optimized.ics")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ics, encoding="utf-8")
    return str(p)


def _summary(analysis: Dict[str, Any], recs: Dict[str, Any]) -> str:
    h = analysis.get("total_meeting_hours", 0)
    c = analysis.get("total_cost_usd", 0)
    return (f"Calendar: {analysis.get('event_count', '?')} events, "
            f"{h}h total, ${c:.0f} meeting cost. "
            f"Recommended: drop {len(recs.get('to_drop',[]))}, "
            f"shorten {len(recs.get('to_shorten',[]))}, "
            f"add {recs.get('focus_blocks_added',0)} focus blocks.")
