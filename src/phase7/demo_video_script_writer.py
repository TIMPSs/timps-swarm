"""Demo Video Script Writer — turns a product description into a complete
demo video script with shot list, voiceover, on-screen text, and
deliverables per format (60s social cut, 2-min demo, 5-min walkthrough).

Outputs:

* Hook (5 seconds, 1-2 lines)
* Three format variants:
    - 60-second social cut (3 scenes)
    - 2-minute product demo (5-7 scenes)
    - 5-minute walkthrough (10-12 scenes)
* Per scene: shot type, on-screen action, voiceover, on-screen text, duration
* A B-roll list
* A CTA + end-card copy
* Three thumbnail concepts
* Captions SRT

The agent is LLM-driven and works fully offline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"

FORMAT_LENGTHS = {
    "social_60s":  {"scenes": 3,  "per_scene_s": 18},
    "demo_2m":     {"scenes": 6,  "per_scene_s": 18},
    "walkthrough_5m": {"scenes": 12, "per_scene_s": 22},
}


def demo_video_script_writer(args: Dict[str, Any]) -> Dict[str, Any]:
    product = (args.get("product") or args.get("description") or "").strip()
    audience = (args.get("audience") or "B2B SaaS buyers").strip()
    cta = (args.get("cta") or "Start free trial").strip()
    if not product:
        return {"summary": "No product description supplied.", "error": "product is required",
                "scripts": []}

    hook = _hook(product, audience)
    scripts: Dict[str, Any] = {}
    for fmt, cfg in FORMAT_LENGTHS.items():
        scripts[fmt] = _build_format(product, audience, cta, hook, cfg)
    broll = _broll(product, audience)
    thumbnails = _thumbnails(product, audience)
    captions = _captions(scripts.get("demo_2m", {}).get("scenes") or [])

    payload = {
        "summary": _summary(product, scripts, broll, thumbnails),
        "product": product,
        "audience": audience,
        "cta": cta,
        "hook": hook,
        "scripts": scripts,
        "broll_suggestions": broll,
        "thumbnails": thumbnails,
        "captions_srt": captions,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", product.lower()).strip("_")[:40] or "demo"
    _save("phase7/demo_script", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _record("demo_video_script_writer", product[:60], f"formats={list(scripts.keys())} scenes={sum(len(v.get('scenes',[])) for v in scripts.values())}")
    return payload


# ---------------------------------------------------------------------------

def _hook(product: str, audience: str) -> Dict[str, str]:
    system = (
        "You write the opening 5 seconds of a product demo video.  Return ONLY "
        "JSON: {\"voiceover\": str, \"on_screen_text\": str, \"thumbnail_alt\": str}.  "
        "Voiceover ≤ 18 words, on-screen text ≤ 6 words.  No fences."
    )
    raw = _llm(f"Product: {product}\nAudience: {audience}", system, "demo_video_script_writer")
    return _parse_json(raw, fallback={"voiceover": "Tired of doing this the slow way?", "on_screen_text": product, "thumbnail_alt": ""})


def _build_format(product: str, audience: str, cta: str, hook: Dict[str, str], cfg: Dict[str, int]) -> Dict[str, Any]:
    system = (
        f"You write a {cfg['scenes']}-scene product demo video script.  "
        f"Each scene ~{cfg['per_scene_s']}s.  Each scene has: shot, action, "
        f"voiceover, on_screen_text, duration_s.  Open with the hook.  End with "
        f"a CTA.  Return ONLY JSON: {{\"scenes\": [...]}}.  No fences."
    )
    user = (
        f"Product: {product}\nAudience: {audience}\nCTA: {cta}\n"
        f"Hook: {json.dumps(hook)}\n\n"
        f"Scenes needed: {cfg['scenes']}.  Vary shot types (close-up, screen-rec, "
        f"talking head, B-roll)."
    )
    raw = _llm(user, system, "demo_video_script_writer")
    parsed = _parse_json(raw, fallback={"scenes": []})
    return parsed


def _broll(product: str, audience: str) -> List[str]:
    return [
        f"Wide shot of a {audience.lower()} at their desk, looking frustrated with the old way.",
        "Close-up: cursor clicking through the product's main dashboard.",
        "Side-by-side: spreadsheet vs the product's clean view.",
        "Hand-held walk-through of a real customer's office (need release).",
        "Time-lapse of the setup flow (cut to 4 seconds).",
        "Macro: keyboard typing the killer feature.",
    ]


def _thumbnails(product: str, audience: str) -> List[Dict[str, str]]:
    return [
        {"concept": "Face + Result",  "description": f"Smiling {audience.lower()} pointing at a giant '10× faster' number on screen."},
        {"concept": "Before/After",   "description": f"Split screen: messy spreadsheet vs the product, with a green check on the right."},
        {"concept": "Bold claim",     "description": f"Plain yellow background with one giant claim: 'Replace 4 tools with {product}'."},
    ]


def _captions(scenes: List[Dict[str, Any]]) -> str:
    srt: List[str] = []
    t = 0
    for i, sc in enumerate(scenes, start=1):
        dur = int(sc.get("duration_s") or 12)
        vo = (sc.get("voiceover") or "").strip()
        start_h, start_m, start_s = _secs_to_hms(t)
        end_h, end_m, end_s = _secs_to_hms(t + dur)
        srt += [str(i), f"{start_h:02d}:{start_m:02d}:{start_s:02d},000 --> {end_h:02d}:{end_m:02d}:{end_s:02d},000", vo, ""]
        t += dur
    return "\n".join(srt) + ("\n" if srt else "")


def _secs_to_hms(s: int) -> tuple:
    return s // 3600, (s % 3600) // 60, s % 60


def _summary(product: str, scripts: Dict[str, Any], broll: List[str], thumbs: List[Dict[str, str]]) -> str:
    n_scenes = sum(len(v.get("scenes", [])) for v in scripts.values())
    return f"Demo script for '{product[:30]}': {len(scripts)} formats, {n_scenes} scenes, {len(broll)} B-roll ideas, {len(thumbs)} thumbnails."
