"""Podcast Show-Notes Writer — turns a podcast transcript into:

* Episode title (3 variants)
* 30-second elevator description
* 5-8 chapter markers with timestamps (auto-estimated if not provided)
* A long-form show notes block (300-500 words)
* Pull-quotes (3 short, tweetable)
* A 6-8 tweet thread
* SEO tags
* 3 guest-bio one-liners
* Newsletter blurb

The agent is LLM-driven and works fully offline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src._helpers import _llm, _parse_json, _record, _save, _ts

DOMAIN = "phase7"


def podcast_show_notes_writer(args: Dict[str, Any]) -> Dict[str, Any]:
    transcript = (args.get("transcript") or args.get("text") or args.get("request") or "").strip()
    if not transcript and args.get("path"):
        transcript = __import__("pathlib").Path(args["path"]).read_text(encoding="utf-8", errors="ignore")
    if not transcript:
        return {"summary": "No transcript supplied.", "error": "transcript or path is required",
                "show_notes_md": ""}

    episode = (args.get("episode") or "Ep. 1").strip()
    guest = (args.get("guest") or "").strip()
    show = (args.get("show") or "My Podcast").strip()
    chapters_input = args.get("chapters") or []  # [{time, label}]

    parsed = _parse(transcript, episode, guest, show)
    chapters = _chapters(transcript, chapters_input, parsed.get("topic_anchors") or [])
    quotes  = _pull_quotes(transcript)
    tweets  = _tweets(parsed, quotes)
    seo     = _seo_tags(parsed)
    md      = _render_md(parsed, chapters, quotes, seo, guest, show, episode)

    payload = {
        "summary": _summary(parsed, len(chapters), len(quotes), len(tweets)),
        "episode": episode,
        "show": show,
        "guest": guest,
        "titles": parsed.get("titles") or [],
        "elevator": parsed.get("elevator") or "",
        "chapters": chapters,
        "pull_quotes": quotes,
        "tweet_thread": tweets,
        "seo_tags": seo,
        "show_notes_md": md,
        "generated_at": _ts(),
    }
    slug = re.sub(r"[^a-z0-9_]+", "_", show.lower()).strip("_")[:40] or "podcast"
    _save("phase7/podcast_notes", f"{slug}_{_ts()}_summary.json", json.dumps(payload, indent=2))
    _save("phase7/podcast_notes", f"{slug}_{_ts()}_show_notes.md", md)
    _record("podcast_show_notes_writer", show, f"chapters={len(chapters)} tweets={len(tweets)}")
    return payload


# ---------------------------------------------------------------------------

def _parse(transcript: str, episode: str, guest: str, show: str) -> Dict[str, Any]:
    system = (
        "You are a senior podcast producer.  From the transcript produce:\n"
        "{\n"
        '  "titles":         [str, str, str],  // 3 different title variants\n'
        '  "elevator":       str,              // 30-second description\n'
        '  "topic_anchors":  [str],            // 5-8 topics covered, in order\n'
        '  "long_summary":   str,              // 300-500 words\n'
        '  "guest_bio":      str,              // 1-2 sentences, written in third person\n'
        '  "key_takeaways":  [str]             // 3-5 bullet points\n'
        "}\n\n"
        "No prose, no fences."
    )
    user = (
        f"Show: {show}\nEpisode: {episode}\nGuest: {guest or 'unspecified'}\n\n"
        f"Transcript (truncated to 10000 chars):\n{transcript[:10000]}"
    )
    raw = _llm(user, system, "podcast_show_notes_writer")
    return _parse_json(raw, fallback={"titles": [], "elevator": "", "topic_anchors": [], "long_summary": "", "guest_bio": "", "key_takeaways": []})


def _chapters(transcript: str, supplied: List[Dict[str, Any]], anchors: List[str]) -> List[Dict[str, str]]:
    if supplied:
        return [{"time": str(c.get("time", "00:00")), "label": str(c.get("label", ""))} for c in supplied]
    out: List[Dict[str, str]] = []
    # estimate per-topic chapter at equal intervals across the transcript length
    n = max(1, len(anchors))
    step = max(1, len(transcript) // n) if transcript else 0
    for i, a in enumerate(anchors[:8]):
        # naive time estimate — 150 wpm speech
        words_before = sum(len(t.split()) for t in (transcript[:i * step] if step else "").splitlines())
        secs = int(words_before / 150 * 60)
        mm, ss = divmod(secs, 60)
        out.append({"time": f"{mm:02d}:{ss:02d}", "label": a})
    return out


def _pull_quotes(transcript: str) -> List[str]:
    sents = re.split(r"(?<=[.!?])\s+", transcript)
    quotes = [s.strip() for s in sents if 12 <= len(s.split()) <= 35 and any(c in s for c in ('"', "“"))]
    if not quotes:
        # pick declarative sentences
        quotes = [s.strip() for s in sents if 10 <= len(s.split()) <= 25][:3]
    return quotes[:3]


def _tweets(parsed: Dict[str, Any], quotes: List[str]) -> List[str]:
    system = (
        "You write tweet threads for podcast episodes.  6-8 tweets, each ≤ 260 chars.  "
        "First tweet must hook.  Include one quote tweet (in quotes).  No hashtags in body.  "
        "Return ONLY a JSON object: {\"tweets\": [str]}  No fences."
    )
    user = f"Quotes available: {json.dumps(quotes)}\n\nLong summary: {parsed.get('long_summary','')}"
    raw = _llm(user, system, "podcast_show_notes_writer")
    obj = _parse_json(raw, fallback={"tweets": []})
    return obj.get("tweets") or []


def _seo_tags(parsed: Dict[str, Any]) -> List[str]:
    system = (
        "Return ONLY a JSON object: {\"tags\": [str]} of 8-12 SEO tags for a podcast episode.  "
        "No #, lowercase, max 2 words each."
    )
    user = parsed.get("long_summary", "")
    raw = _llm(user, system, "podcast_show_notes_writer")
    obj = _parse_json(raw, fallback={"tags": []})
    return obj.get("tags") or []


def _render_md(p: Dict[str, Any], chapters: List[Dict[str, str]], quotes: List[str], seo: List[str], guest: str, show: str, episode: str) -> str:
    out = [f"# {show} — {episode}", ""]
    if p.get("titles"):
        out += ["## Title options", "", *[f"- {t}" for t in p["titles"]], ""]
    if p.get("elevator"):
        out += ["## One-liner", "", p["elevator"], ""]
    if chapters:
        out += ["## Chapters", ""]
        for c in chapters:
            out.append(f"- **{c['time']}** — {c['label']}")
        out.append("")
    if p.get("long_summary"):
        out += ["## Episode notes", "", p["long_summary"], ""]
    if p.get("key_takeaways"):
        out += ["## Key takeaways", "", *[f"- {t}" for t in p["key_takeaways"]], ""]
    if quotes:
        out += ["## Pull quotes", "", *[f"> {q}" for q in quotes], ""]
    if guest and p.get("guest_bio"):
        out += [f"## About the guest — {guest}", "", p["guest_bio"], ""]
    if seo:
        out += ["## Tags", "", ", ".join(seo), ""]
    return "\n".join(out) + "\n"


def _summary(parsed: Dict[str, Any], n_ch: int, n_q: int, n_t: int) -> str:
    return f"Podcast notes: {len(parsed.get('titles',[]))} titles, {n_ch} chapters, {n_q} quotes, {n_t} tweets."
