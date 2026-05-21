"""
Knowledge Worker Agents — 10 specialist agents for the everyday digital grind.

These agents handle the communication, research, admin, and data tasks that
eat up the non-coding half of a professional's day.

Agents
------
  Inbox Gatekeeper      — triage emails: label urgent, draft routine replies
  Meeting Condenser     — transcript → action items → Jira/Notion tasks
  Calendar Tetris       — find optimal meeting slots for 3+ people
  Research Scout        — deep-dive a topic and return a structured brief
  Trend Monitor         — watch X/Reddit/HN for keyword spikes
  Data Wrangler         — messy CSV/PDF → clean JSON or DB-ready rows
  Expense Auditor       — match receipts to card statements, categorise
  Reference Checker     — verify citations/facts against reliable sources
  Client Liaison        — answer FAQs using a company knowledge base
  Competitor Tracker    — monitor pricing, features, and job postings
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(os.getenv("GENERATED_DIR", "generated"))
REPORTS_DIR   = GENERATED_DIR / "reports"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _router():
    from src.llm_router import LLMRouter
    return LLMRouter()


def _computer(agent_id: str):
    from src.computer_use import get_agent_computer
    return get_agent_computer(agent_id)


def _save(subdir: str, filename: str, content: str) -> str:
    path = GENERATED_DIR / subdir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


# ─────────────────────────────────────────────────────────────────────────────
# 1 — INBOX GATEKEEPER
# Input : raw email (or list of email summaries)
# Output: priority labels, auto-drafted replies, unsubscribe targets
# ─────────────────────────────────────────────────────────────────────────────

def inbox_gatekeeper(
    emails: List[Dict[str, str]],
    user_context: str = "",
) -> Dict[str, Any]:
    """
    Triage a batch of emails. Each email dict should have 'from', 'subject', 'body'.

    Returns:
        dict with 'urgent', 'to_reply', 'to_archive', 'drafted_replies',
                  'unsubscribe_list', 'summary'
    """
    logger.info("[Inbox] Triaging %d emails", len(emails))

    email_text = "\n\n---\n\n".join(
        f"FROM: {e.get('from','')}\nSUBJECT: {e.get('subject','')}\n\n{e.get('body','')[:400]}"
        for e in emails[:20]
    )

    system = (
        "You are a world-class executive assistant. Triage this inbox and "
        "return a JSON object with:\n"
        "  urgent          : list of {from, subject, reason} that need same-day reply\n"
        "  to_reply        : list of {from, subject, suggested_response_type}\n"
        "  to_archive      : list of subjects safe to archive without reading\n"
        "  drafted_replies : list of {subject, draft_reply} for routine emails\n"
        "  unsubscribe_list: list of sender domains that are pure newsletters\n"
        "  summary         : two-sentence inbox overview\n"
        "Output ONLY valid JSON."
    )
    context_block = f"\nUser context: {user_context}" if user_context else ""
    prompt = f"Emails:\n{email_text}{context_block}"
    raw = _router().call("inbox_gatekeeper", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"summary": raw}

    result["_agent"] = "inbox_gatekeeper"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2 — MEETING CONDENSER
# Input : meeting transcript (plain text)
# Output: action items, decisions, TLDR, task assignments
# ─────────────────────────────────────────────────────────────────────────────

def meeting_condenser(
    transcript: str,
    attendees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Condense a meeting transcript into a structured summary with action items.
    Designed for Zoom/Teams/Meet transcripts or hand-written notes.
    """
    logger.info("[MeetingCondenser] Processing transcript (%d chars)", len(transcript))

    attendee_list = ", ".join(attendees) if attendees else "not provided"

    system = (
        "You are a professional meeting facilitator and note-taker. "
        "Extract a structured summary from the meeting transcript. "
        "Return a JSON object with:\n"
        "  tldr             : one-paragraph executive summary\n"
        "  decisions_made   : list of concrete decisions (with who made them)\n"
        "  action_items     : list of {owner, task, due_date (if mentioned), priority}\n"
        "  open_questions   : list of unresolved questions to follow up on\n"
        "  meeting_duration_estimate : estimated meeting length in minutes\n"
        "  could_have_been_email : true | false\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Attendees: {attendee_list}\n\n"
        f"Transcript:\n{transcript[:5000]}"
    )
    raw = _router().call("meeting_condenser", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"tldr": raw}

    result["_agent"] = "meeting_condenser"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3 — CALENDAR TETRIS
# Input : availability windows for 3+ people + meeting requirements
# Output: ranked list of optimal meeting slots
# ─────────────────────────────────────────────────────────────────────────────

def calendar_tetris(
    attendee_availability: Dict[str, List[str]],
    meeting_duration_minutes: int = 60,
    preferred_time_range: str = "9am-5pm",
    timezone: str = "UTC",
) -> Dict[str, Any]:
    """
    Find the best meeting slots without the back-and-forth email chain.

    attendee_availability: {name: [list of "YYYY-MM-DD HH:MM" free slots]}
    """
    logger.info("[CalTetris] Finding slots for %d attendees", len(attendee_availability))

    avail_text = "\n".join(
        f"{name}: {', '.join(slots[:10])}"
        for name, slots in attendee_availability.items()
    )

    system = (
        "You are a scheduling assistant. Find the best meeting times for all attendees. "
        "Return a JSON object with:\n"
        "  top_slots    : list of {datetime_utc, local_times_per_attendee, overlap_quality}\n"
        "  conflicts    : list of attendees with limited availability\n"
        "  recommendation : the single best slot with reasoning\n"
        "  invite_draft : a brief calendar invite description\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Duration needed: {meeting_duration_minutes} minutes\n"
        f"Preferred window: {preferred_time_range} {timezone}\n\n"
        f"Availability:\n{avail_text}"
    )
    raw = _router().call("calendar_tetris", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"recommendation": raw}

    result["_agent"] = "calendar_tetris"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4 — RESEARCH SCOUT
# Input : research topic or question
# Output: structured brief with sources, key findings, confidence
# ─────────────────────────────────────────────────────────────────────────────

def research_scout(
    topic: str,
    depth: str = "medium",
    output_format: str = "brief",
) -> Dict[str, Any]:
    """
    Do a deep dive on a specific topic and return a structured research brief.

    depth: 'quick' (1 source), 'medium' (3-5 sources), 'deep' (10+ sources)
    output_format: 'brief' | 'report' | 'bullets'
    """
    logger.info("[ResearchScout] Researching: %.80s… (depth=%s)", topic, depth)

    follow_links = {"quick": 0, "medium": 1, "deep": 2}.get(depth, 1)

    computer = _computer("research_scout")
    web_data = computer.research_sync(topic, follow_links=follow_links)

    system = (
        "You are an expert research analyst. Synthesise the web research into a "
        "structured brief. Return a JSON object with:\n"
        "  key_findings    : list of the most important facts and insights\n"
        "  consensus_view  : what most sources agree on\n"
        "  controversies   : where sources disagree or things are uncertain\n"
        "  recommended_actions : practical next steps based on the research\n"
        "  sources_used    : list of source domains found\n"
        "  confidence      : 'high' | 'medium' | 'low' (based on source quality)\n"
        "  executive_summary : 3-sentence summary for a busy executive\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Research topic: {topic}\n"
        f"Depth: {depth}\n\n"
        f"Web research data:\n{web_data[:5000]}"
    )
    raw = _router().call("research_scout", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"executive_summary": raw}

    path = _save("reports", "research_scout.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "research_scout"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 5 — TREND MONITOR
# Input : list of keywords to track
# Output: trend spikes, sentiment, volume change
# ─────────────────────────────────────────────────────────────────────────────

def trend_monitor(keywords: List[str], sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Monitor keywords across tech communities and flag spikes in interest.
    Sources default to Hacker News, Reddit r/programming, and X/Twitter.
    """
    logger.info("[TrendMonitor] Tracking %d keywords", len(keywords))

    default_sources = sources or ["Hacker News", "Reddit", "GitHub trending", "Dev.to"]
    source_list = ", ".join(default_sources)

    computer = _computer("trend_monitor")
    trend_data = computer.research_sync(
        " OR ".join(keywords[:5]) + f" trending 2025 {source_list}", follow_links=0
    )

    system = (
        "You are a technology trend analyst. Analyse trending signals for the given keywords. "
        "Return a JSON object with:\n"
        "  trending_keywords : list of {keyword, trend_direction ('up'|'flat'|'down'), "
        "                              volume_signal, notable_discussions}\n"
        "  emerging_topics   : related topics gaining traction\n"
        "  community_sentiment : overall sentiment ('positive'|'mixed'|'negative')\n"
        "  alert_worthy      : list of items with sudden spikes that need attention\n"
        "  digest_summary    : paragraph summary of the tech landscape right now\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Keywords to track: {', '.join(keywords)}\n"
        f"Sources: {source_list}\n\n"
        f"Collected trend data:\n{trend_data[:4000]}"
    )
    raw = _router().call("trend_monitor", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"digest_summary": raw}

    result["_agent"] = "trend_monitor"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 6 — DATA WRANGLER
# Input : messy CSV, JSON, or plain text data
# Output: cleaned, validated, normalised records
# ─────────────────────────────────────────────────────────────────────────────

def data_wrangler(
    raw_data: str,
    target_schema: Optional[Dict[str, str]] = None,
    input_format: str = "auto",
) -> Dict[str, Any]:
    """
    Clean and normalise messy data (CSV, JSON, PDF extracts, copy-pasted tables).
    Maps to a target schema if provided.

    target_schema: dict mapping field_name → expected_type
    """
    logger.info("[DataWrangler] Cleaning %s data (%d chars)", input_format, len(raw_data))

    schema_block = (
        f"\nTarget schema: {json.dumps(target_schema)}" if target_schema else ""
    )

    system = (
        "You are a data engineer. Clean, deduplicate, and normalise the input data. "
        "Fix encoding issues, inconsistent date formats, missing values, and type mismatches. "
        "Return a JSON object with:\n"
        "  cleaned_records  : list of clean records (as dicts)\n"
        "  records_count    : number of records\n"
        "  issues_found     : list of {field, issue_type, row_count, how_fixed}\n"
        "  data_quality_score : 0-100\n"
        "  sql_insert_hint  : example SQL INSERT for the first record\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Input format: {input_format}{schema_block}\n\n"
        f"Raw data:\n{raw_data[:4000]}"
    )
    raw = _router().call("data_wrangler", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"data_quality_score": 0, "issues_found": [raw]}

    result["_agent"] = "data_wrangler"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 7 — EXPENSE AUDITOR
# Input : receipt list + card statement
# Output: matched pairs, unmatched items, category totals, anomalies
# ─────────────────────────────────────────────────────────────────────────────

def expense_auditor(
    receipts: List[Dict[str, Any]],
    card_statement: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Match receipts to card transactions, flag anomalies, and categorise spend.

    receipts: list of {vendor, amount, date, description}
    card_statement: list of {merchant, amount, date, transaction_id}
    """
    logger.info("[ExpenseAuditor] Auditing %d receipts vs %d transactions",
                len(receipts), len(card_statement))

    receipts_text = json.dumps(receipts[:30], default=str)
    statement_text = json.dumps(card_statement[:50], default=str)

    system = (
        "You are a corporate expense auditor. Match receipts to card transactions "
        "and flag issues. Return a JSON object with:\n"
        "  matched_pairs   : list of {receipt_vendor, transaction_merchant, amount, date, confidence}\n"
        "  unmatched_receipts : list of receipts with no matching transaction\n"
        "  unmatched_charges  : list of charges with no receipt (potential policy violation)\n"
        "  category_totals : dict of {category: total_amount}\n"
        "  anomalies       : list of {description, amount, reason_flagged}\n"
        "  total_receipts  : total amount on receipts\n"
        "  total_charges   : total on card statement\n"
        "  discrepancy     : difference between totals\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Receipts:\n{receipts_text}\n\n"
        f"Card statement:\n{statement_text}"
    )
    raw = _router().call("expense_auditor", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"discrepancy": raw}

    path = _save("reports", "expense_auditor.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "expense_auditor"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 8 — REFERENCE CHECKER
# Input : document with claims/citations
# Output: verified facts, questionable claims, confidence per claim
# ─────────────────────────────────────────────────────────────────────────────

def reference_checker(document: str) -> Dict[str, Any]:
    """
    Extract and verify factual claims in a document against web sources.
    Flags statistics, dates, attributions, and technical assertions.
    """
    logger.info("[RefChecker] Checking document (%d chars)", len(document))

    computer = _computer("reference_checker")

    # Extract claims first with a lightweight call
    claims_prompt = (
        "Extract all verifiable factual claims from this document as a JSON array. "
        "Each item: {claim, type ('statistic'|'date'|'attribution'|'technical')}. "
        f"Document:\n{document[:3000]}\nReturn ONLY the JSON array."
    )
    claims_raw = _router().call("reference_checker", claims_prompt, "Extract claims as JSON array.")

    claims: List[Dict] = []
    try:
        start = claims_raw.find("["); end = claims_raw.rfind("]") + 1
        claims = json.loads(claims_raw[start:end]) if start >= 0 else []
    except Exception:
        pass

    # Spot-check a few claims against the web
    verification_context = ""
    for claim_obj in claims[:5]:
        claim_text = claim_obj.get("claim", "")
        if claim_text:
            ctx = computer.research_sync(f"verify: {claim_text[:100]}", follow_links=0)
            verification_context += f"\n\nClaim: {claim_text}\nWeb context: {ctx[:300]}"

    system = (
        "You are a fact-checking journalist. Verify the claims based on the web context. "
        "Return a JSON object with:\n"
        "  verified_claims     : list of {claim, verdict ('true'|'false'|'misleading'|'unverifiable'), source}\n"
        "  overall_accuracy    : 0-100\n"
        "  red_flags           : list of claims that are clearly wrong or misleading\n"
        "  missing_citations   : list of claims that need a citation but have none\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Claims extracted:\n{json.dumps(claims[:10])}\n\n"
        f"Web verification results:{verification_context}"
    )
    raw = _router().call("reference_checker", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"overall_accuracy": 50, "red_flags": [raw]}

    result["_agent"] = "reference_checker"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 9 — CLIENT LIAISON
# Input : customer question + company knowledge base
# Output: accurate answer drawn only from the KB, with escalation logic
# ─────────────────────────────────────────────────────────────────────────────

def client_liaison(
    customer_question: str,
    knowledge_base: str,
    company_name: str = "Our Company",
    escalation_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Answer customer FAQs using only the provided knowledge base.
    Escalates to human support when confidence is low or keywords are detected.
    """
    logger.info("[ClientLiaison] Answering: %.80s…", customer_question)

    escalation_kws = escalation_keywords or ["refund", "lawsuit", "legal", "cancel account", "data breach"]
    should_escalate = any(kw.lower() in customer_question.lower() for kw in escalation_kws)

    system = (
        f"You are a helpful customer support agent for {company_name}. "
        "Answer ONLY from the knowledge base provided — do not invent information. "
        "If the answer is not in the KB, say so clearly. "
        "Return a JSON object with:\n"
        "  answer          : the customer-facing response (friendly, concise)\n"
        "  confidence      : 'high' | 'medium' | 'low'\n"
        "  kb_sections_used : list of KB section titles referenced\n"
        "  escalate        : true | false (true if answer is not in KB or question is sensitive)\n"
        "  escalation_reason : reason for escalation if applicable\n"
        "Output ONLY valid JSON."
    )
    escalation_note = (
        "\nNOTE: This question contains escalation keywords — set escalate=true." 
        if should_escalate else ""
    )
    prompt = (
        f"Customer question: {customer_question}{escalation_note}\n\n"
        f"Knowledge base:\n{knowledge_base[:3000]}"
    )
    raw = _router().call("client_liaison", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"answer": raw, "confidence": "low", "escalate": True}

    if should_escalate:
        result["escalate"] = True

    result["_agent"] = "client_liaison"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 10 — COMPETITOR TRACKER
# Input : list of competitor names/URLs
# Output: changes in pricing, features, job postings, and public sentiment
# ─────────────────────────────────────────────────────────────────────────────

def competitor_tracker(
    competitors: List[str],
    focus_areas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Monitor competitors for changes in pricing, features, hiring, and sentiment.

    competitors: list of company names or URLs
    focus_areas: e.g. ['pricing', 'job postings', 'new features', 'reviews']
    """
    logger.info("[CompTracker] Tracking %d competitors", len(competitors))

    focus = focus_areas or ["pricing", "new features", "job postings", "product updates"]
    focus_str = ", ".join(focus)

    computer = _computer("competitor_tracker")
    intel_parts: List[str] = []
    for comp in competitors[:5]:
        data = computer.research_sync(
            f"{comp} {focus_str} 2025 news updates", follow_links=0
        )
        intel_parts.append(f"=== {comp} ===\n{data[:600]}")
    combined_intel = "\n\n".join(intel_parts)

    system = (
        "You are a competitive intelligence analyst. Synthesise the collected intel. "
        "Return a JSON object with:\n"
        "  competitor_profiles : list of {company, key_updates, pricing_changes, "
        "                                  new_features, hiring_signals, sentiment}\n"
        "  market_shifts       : any significant market changes to be aware of\n"
        "  opportunities       : gaps or weaknesses in competitors you could exploit\n"
        "  threats             : moves that could hurt your position\n"
        "  executive_briefing  : 3-paragraph summary for a product decision meeting\n"
        "Output ONLY valid JSON."
    )
    prompt = (
        f"Competitors: {', '.join(competitors)}\n"
        f"Focus: {focus_str}\n\n"
        f"Collected intelligence:\n{combined_intel[:4000]}"
    )
    raw = _router().call("competitor_tracker", prompt, system)

    try:
        start = raw.find("{"); end = raw.rfind("}") + 1
        result: Dict[str, Any] = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        result = {"executive_briefing": raw}

    path = _save("reports", "competitor_tracker.md", json.dumps(result, indent=2))
    result["_report_path"] = path
    result["_agent"] = "competitor_tracker"
    result["_timestamp"] = datetime.utcnow().isoformat()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Registry — for the MCP server and swarm dispatcher
# ─────────────────────────────────────────────────────────────────────────────

KNOWLEDGE_AGENTS: Dict[str, Any] = {
    "inbox_gatekeeper":   inbox_gatekeeper,
    "meeting_condenser":  meeting_condenser,
    "calendar_tetris":    calendar_tetris,
    "research_scout":     research_scout,
    "trend_monitor":      trend_monitor,
    "data_wrangler":      data_wrangler,
    "expense_auditor":    expense_auditor,
    "reference_checker":  reference_checker,
    "client_liaison":     client_liaison,
    "competitor_tracker": competitor_tracker,
}
