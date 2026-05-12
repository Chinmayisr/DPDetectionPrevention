"""
agents/behavioral_agent/nodes/nagging.py
Detects Nagging (DP09).
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.models import EvidenceItem, SinglePatternResult
from agents.shared.openai_client import chat_complete_json
from agents.behavioral_agent.state import BehavioralAgentState

logger = structlog.get_logger(__name__)

_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "nagging.txt"
).read_text()

_CODE = "DP09"
_NAME = "Nagging"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals       = state.get("nagging_signals", {})
    popup_timeline= state.get("popup_timeline", [])
    curr_overlays = state.get("current_overlays", [])
    text_elements = state.get("text_elements", [])
    buttons       = state.get("buttons", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url','')}",
        f"Page Type: {state.get('current_page_type','')}",
        "",
        "=== PRE-COMPUTED NAGGING SIGNALS ===",
        f"Repeated popup groups:        {signals.get('repeated_popup_count',0)}",
        f"Max times same popup appeared:{signals.get('max_repeat_count',0)}",
        f"Total popups in session:      {signals.get('total_session_popups',0)}",
        f"Total autonomous popups:      {signals.get('total_autonomous_popups',0)}",
        f"Auto popups on current page:  {signals.get('auto_popup_count_current',0)}",
        f"Notification requests found:  {signals.get('notification_request_found')}",
        f"Is nagging detected:          {signals.get('is_nagging')}",
        "",
        "=== REPEATED POPUP GROUPS (same popup appeared multiple times) ===",
    ]
    for group in signals.get("repeated_popup_groups", []):
        parts.append(
            f"  Appeared {group['count']} times: '{group['text'][:100]}'"
        )
        for page in group.get("pages", []):
            parts.append(f"    - {page}")

    parts += ["", "=== FULL POPUP TIMELINE (all overlays across session) ==="]
    for entry in popup_timeline:
        parts.append(
            f"  [{entry.get('url','')[:60]}] "
            f"type={entry.get('type','')} | "
            f"autonomous={entry.get('autonomous',False)} | "
            f"delay={entry.get('delay_ms',0)}ms | "
            f"text='{str(entry.get('text',''))[:80]}'"
        )

    parts += ["", "=== CURRENT PAGE OVERLAYS ==="]
    for o in curr_overlays:
        parts.append(
            f"  [{o.get('overlay_type','?')}] "
            f"autonomous={o.get('appeared_autonomously')} | "
            f"coverage={o.get('viewport_coverage_pct',0):.1f}% | "
            f"text='{o.get('text','')[:100]}'"
        )

    parts += ["", "=== NOTIFICATION REQUEST SIGNALS ==="]
    for sig in signals.get("notification_requests", []):
        parts.append(f"  {sig}")

    parts += ["", "=== ALL TEXT ELEMENTS (tag | location | text) ==="]
    for t in text_elements[:200]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:120]}"
        )

    parts += ["", "=== BUTTONS ON PAGE ==="]
    for b in buttons[:30]:
        parts.append(
            f"[modal={b.get('is_in_modal')}|close={b.get('is_close_button')}] "
            f"{b.get('text','')[:100]}"
        )

    return "\n".join(parts)


async def nagging_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("nagging_calling_llm", input_chars=len(user_msg))
        data = await chat_complete_json(
            system_prompt=_PROMPT,
            user_message=user_msg,
        )
        raw_response = json.dumps(data)
        detected   = bool(data.get("detected", False))
        confidence = float(data.get("confidence", 0.0))
        if confidence < _CONFIDENCE_THRESHOLD:
            detected = False
        evidence = (
            [
                EvidenceItem(
                    text=e.get("text", ""),
                    location=e.get("location"),
                    reason=e.get("reason"),
                )
                for e in data.get("evidence", [])
                if isinstance(e, dict)
            ]
            if detected else []
        )
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=detected, confidence=confidence,
            evidence=evidence, raw_llm_response=raw_response,
        )
        log.info("nagging_complete",
                 detected=detected, confidence=confidence,
                 evidence_count=len(evidence))
    except Exception as exc:
        log.error("nagging_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=False, confidence=0.0,
            error=str(exc), raw_llm_response=raw_response,
        )
    return {"nagging_result": result}