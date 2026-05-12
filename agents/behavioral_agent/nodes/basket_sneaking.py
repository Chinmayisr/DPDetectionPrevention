"""
agents/behavioral_agent/nodes/basket_sneaking.py
Detects Basket Sneaking (DP07).
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
    Path(__file__).parent.parent / "prompts" / "basket_sneaking.txt"
).read_text()

_CODE = "DP07"
_NAME = "Basket Sneaking"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals      = state.get("basket_sneaking_signals", {})
    text_elements= state.get("text_elements", [])
    buttons      = state.get("buttons", [])
    curr_cart    = state.get("current_cart_items", [])
    prev_cart    = state.get("previous_cart_items", [])
    auto_cart    = state.get("current_auto_cart_mutations", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url','')}",
        f"Page Type: {state.get('current_page_type','')}",
        "",
        "=== PRE-COMPUTED BASKET SNEAKING SIGNALS ===",
        f"New items in cart (not in previous): {signals.get('new_item_count',0)}",
        f"Auto cart mutations (network):        {signals.get('auto_cart_mutation_count',0)}",
        f"Cart DOM mutations:                   {signals.get('cart_dom_mutations_count',0)}",
        f"Has auto mutations:                   {signals.get('has_auto_mutations')}",
        f"Has new items:                        {signals.get('has_new_items')}",
        "",
        "=== NEW ITEMS DETECTED IN CART ===",
    ]
    for item in signals.get("new_items_in_cart", []):
        parts.append(
            f"  name='{item.get('name','')}' "
            f"price='{item.get('price_text','')}' "
            f"qty='{item.get('quantity','')}'"
        )

    parts += ["", "=== AUTO CART MUTATION NETWORK REQUESTS ==="]
    for url in signals.get("cart_mutation_urls", []):
        parts.append(f"  {url}")

    parts += ["", "=== SNEAKING-RELATED TEXT SIGNALS ==="]
    for sig in signals.get("sneaking_text_signals", []):
        parts.append(f"  {sig}")

    parts += ["", "=== CURRENT CART ITEMS ==="]
    for item in curr_cart:
        parts.append(
            f"  '{item.get('name','')}' — {item.get('price_text','')} "
            f"qty={item.get('quantity','')}"
        )

    parts += ["", "=== PREVIOUS CART ITEMS (before this page) ==="]
    for item in prev_cart:
        parts.append(f"  '{item.get('name','')}' — {item.get('price_text','')}")

    parts += ["", "=== ALL TEXT ELEMENTS (tag | location | text) ==="]
    for t in text_elements[:200]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:120]}"
        )

    parts += ["", "=== BUTTONS ON PAGE ==="]
    for b in buttons[:30]:
        parts.append(
            f"[modal={b.get('is_in_modal')}] {b.get('text','')[:100]}"
        )

    return "\n".join(parts)


async def basket_sneaking_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("basket_sneaking_calling_llm", input_chars=len(user_msg))
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
            pattern_code=_CODE,
            pattern_name=_NAME,
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info("basket_sneaking_complete",
                 detected=detected, confidence=confidence,
                 evidence_count=len(evidence))
    except Exception as exc:
        log.error("basket_sneaking_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=False, confidence=0.0,
            error=str(exc), raw_llm_response=raw_response,
        )
    return {"basket_sneaking_result": result}