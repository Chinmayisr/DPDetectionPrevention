"""
agents/behavioral_agent/nodes/rogue_malicious.py
Detects Rogue and Malicious Content (DP11).
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
    Path(__file__).parent.parent / "prompts" / "rogue_malicious.txt"
).read_text()

_CODE = "DP11"
_NAME = "Rogue and Malicious Content"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals       = state.get("rogue_malicious_signals", {})
    redirect_traps= state.get("redirect_traps", [])
    links         = state.get("links", [])
    buttons       = state.get("buttons", [])
    text_elements = state.get("text_elements", [])
    mutations     = state.get("current_mutations", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url','')}",
        f"Page Type: {state.get('current_page_type','')}",
        "",
        "=== PRE-COMPUTED ROGUE/MALICIOUS SIGNALS ===",
        f"High-severity redirect traps:  {signals.get('high_trap_count',0)}",
        f"Medium-severity redirect traps:{signals.get('medium_trap_count',0)}",
        f"Total redirect traps:          {signals.get('total_redirect_traps',0)}",
        f"Suspicious download buttons:   {len(signals.get('suspicious_download_buttons',[]))}",
        f"JS-injected links:             {signals.get('injected_link_count',0)}",
        f"Has high severity traps:       {signals.get('has_high_severity')}",
        "",
        "=== HIGH-SEVERITY REDIRECT TRAPS ===",
    ]
    for trap in signals.get("high_severity_traps", []):
        parts.append(
            f"  text='{trap['text']}' | "
            f"href='{trap['actual_href']}' | "
            f"sponsored={trap['is_sponsored']}"
        )

    parts += ["", "=== MEDIUM-SEVERITY REDIRECT TRAPS ==="]
    for trap in signals.get("medium_severity_traps", []):
        parts.append(
            f"  text='{trap['text']}' | "
            f"href='{trap['actual_href']}'"
        )

    parts += ["", "=== SUSPICIOUS DOWNLOAD BUTTONS ==="]
    for btn in signals.get("suspicious_download_buttons", []):
        parts.append(f"  {btn}")

    parts += ["", "=== JS-INJECTED LINKS (added after page load) ==="]
    for link in signals.get("injected_links", []):
        parts.append(f"  {link}")

    parts += ["", "=== ALL REDIRECT TRAPS (raw) ==="]
    for trap in redirect_traps[:15]:
        parts.append(
            f"  text='{trap.get('text','')[:80]}' | "
            f"displayed='{trap.get('displayed_url','')[:60]}' | "
            f"actual='{trap.get('actual_href','')[:80]}' | "
            f"mismatch={trap.get('domain_mismatch')} | "
            f"sponsored={trap.get('is_sponsored')}"
        )

    parts += ["", "=== ALL LINKS WITH FLAGS ==="]
    for link in links[:30]:
        if link.get("domain_mismatch") or link.get("is_sponsored"):
            parts.append(
                f"  '{link.get('text','')[:60]}' → "
                f"'{link.get('actual_href','')[:80]}' | "
                f"mismatch={link.get('domain_mismatch')} | "
                f"sponsored={link.get('is_sponsored')}"
            )

    parts += ["", "=== ALL TEXT ELEMENTS (tag | location | text) ==="]
    for t in text_elements[:200]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:120]}"
        )

    parts += ["", "=== BUTTONS (href and data attributes) ==="]
    for b in buttons[:30]:
        href = b.get("actual_href") or b.get("href") or ""
        parts.append(
            f"  text='{(b.get('text') or '')[:80]}' | "
            f"href='{href[:80]}' | "
            f"mismatch={b.get('domain_mismatch')} | "
            f"close={b.get('is_close_button')}"
        )

    parts += ["", "=== DOM MUTATIONS (elements added by JS) ==="]
    for m in mutations[:20]:
        if m.get("added_nodes_count", 0) > 0:
            parts.append(
                f"  selector={m.get('target_selector','')} | "
                f"added={m.get('added_nodes_count',0)} nodes | "
                f"at {m.get('timestamp_ms',0):.0f}ms"
            )

    return "\n".join(parts)


async def rogue_malicious_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("rogue_malicious_calling_llm", input_chars=len(user_msg))
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
        log.info("rogue_malicious_complete",
                 detected=detected, confidence=confidence,
                 evidence_count=len(evidence))
    except Exception as exc:
        log.error("rogue_malicious_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=False, confidence=0.0,
            error=str(exc), raw_llm_response=raw_response,
        )
    return {"rogue_malicious_result": result}