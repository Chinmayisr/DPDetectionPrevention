"""
agents/pricing_agent/nodes/bait_switch.py
Detects Bait & Switch pricing using pre-computed signals + GPT-4o.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.models import (
    EvidenceItem,
    SinglePatternResult,
)
from agents.shared.openai_client import chat_complete_json
from agents.pricing_agent.state import PricingAgentState

logger = structlog.get_logger(__name__)

_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "bait_switch.txt"
).read_text()

_CONFIDENCE_THRESHOLD = 0.70

_CODE = "DP06"
_NAME = "Bait and Switch"


def _build_user_message(state: PricingAgentState) -> str:
    signals       = state.get("bait_switch_signals", {})
    price_diffs   = state.get("price_diffs", [])
    text_elements = state.get("text_elements", [])
    buttons       = state.get("buttons", [])

    parts = [
        "=== PAGE JOURNEY ===",
        f"Product Page URL: {signals.get('previous_url', 'N/A')}",
        f"Cart/Checkout URL: {signals.get('current_url', '')}",
        f"Page Type: {state.get('current_page_type', '')}",
        f"Has previous product page: {signals.get('has_previous_page')}",
        "",
        "=== PRE-COMPUTED BAIT & SWITCH SIGNALS ===",
        f"Items with price increases: {signals.get('variance_count', 0)}",
        f"Max single-item variance:   {signals.get('max_variance_pct', 0):.2f}%",
        f"Total overcharge amount:    {signals.get('total_overcharge', 0)}",
        f"Bait-switch language found: {signals.get('has_bait_switch_language')}",
        "",
        "=== ITEM-BY-ITEM PRICE COMPARISON ===",
    ]
    for v in signals.get("significant_variances", []):
        parts.append(
            f"  Item:    '{v['item']}'  |  "
            f"Product page: {v['price_product_page']}  |  "
            f"Cart: {v['price_cart']}  |  "
            f"Increase: {v['variance_abs']} ({v['variance_pct']:.2f}%)"
        )

    parts += [
        "",
        "=== ALL PRICE DIFFS (raw) ===",
    ]
    for diff in price_diffs:
        parts.append(
            f"  '{diff.get('item','')}': "
            f"{diff.get('price_on_previous_page')} → "
            f"{diff.get('price_on_current_page')} | "
            f"variance={diff.get('variance')} ({diff.get('variance_pct','?')}%)"
        )

    parts += [
        "",
        "=== BAIT-SWITCH LANGUAGE FOUND ON PAGE ===",
    ]
    for sig in signals.get("bait_text_signals", []):
        parts.append(f"  {sig}")

    parts += [
        "",
        "=== ALL TEXT ELEMENTS (tag | location | text) ===",
    ]
    for t in text_elements[:200]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:120]}"
        )

    parts += [
        "",
        "=== BUTTONS ON PAGE ===",
    ]
    for b in buttons[:30]:
        parts.append(
            f"[modal={b.get('is_in_modal')}] {b.get('text','')[:100]}"
        )

    return "\n".join(parts)


async def bait_switch_node(state: PricingAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP06_BAIT")
    raw_response = ""

    try:
        user_msg = _build_user_message(state)
        log.debug("bait_switch_calling_llm", input_chars=len(user_msg))

        data = await chat_complete_json(
            system_prompt=_PROMPT,
            user_message=user_msg,
        )
        raw_response = json.dumps(data)

        detected   = bool(data.get("detected", False))
        confidence = float(data.get("confidence", 0.0))
        raw_ev     = data.get("evidence", [])

        if confidence < _CONFIDENCE_THRESHOLD:
            detected = False

        evidence = (
            [
                EvidenceItem(
                    text=e.get("text", ""),
                    location=e.get("location"),
                    reason=e.get("reason"),
                )
                for e in raw_ev
                if isinstance(e, dict)
            ]
            if detected
            else []
        )

        result = SinglePatternResult(
            pattern_code=_CODE,        # type: ignore[arg-type]
            pattern_name=_NAME,
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info(
            "bait_switch_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )

    except Exception as exc:
        log.error("bait_switch_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE,        # type: ignore[arg-type]
            pattern_name=_NAME,
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"bait_switch_result": result}