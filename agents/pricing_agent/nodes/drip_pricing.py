"""
agents/pricing_agent/nodes/drip_pricing.py
Detects Drip Pricing using pre-computed signals + GPT-4o.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.models import (
    DarkPatternCode,
    EvidenceItem,
    SinglePatternResult,
)
from agents.shared.openai_client import chat_complete_json
from agents.pricing_agent.state import PricingAgentState

logger = structlog.get_logger(__name__)

_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "drip_pricing.txt"
).read_text()

_CONFIDENCE_THRESHOLD = 0.70

# Inject a new pattern code for pricing patterns
_CODE  = "DP05"
_NAME  = "Drip Pricing"


def _build_user_message(state: PricingAgentState) -> str:
    signals = state.get("drip_pricing_signals", {})
    supplemental = state.get("supplemental_charges", [])
    text_elements = state.get("text_elements", [])
    buttons = state.get("buttons", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url', '')}",
        f"Page Type: {state.get('current_page_type', '')}",
        "",
        "=== PRE-COMPUTED DRIP PRICING SIGNALS ===",
        f"Displayed Total:         {signals.get('displayed_total')}",
        f"Computed Subtotal:       {signals.get('computed_subtotal')}",
        f"Price Gap:               {signals.get('price_gap')} "
        f"({signals.get('price_gap_pct', 0):.2f}% of subtotal)",
        f"Gap is significant:      {signals.get('gap_is_significant')}",
        f"Total hidden amount:     {signals.get('total_hidden_amount')}",
        f"Pre-selected amount:     {signals.get('pre_selected_amount')}",
        f"Suspicious charge count: {signals.get('suspicious_charge_count')}",
        f"Has pre-selected charges:{signals.get('has_pre_selected_charges')}",
        "",
        "=== SUSPICIOUS CHARGES IDENTIFIED ===",
    ]
    for charge in signals.get("suspicious_charges", []):
        parts.append(
            f"  - '{charge['label']}': "
            f"{charge['amount']} | "
            f"pre_selected={charge['is_pre_selected']} | "
            f"optional={charge['is_optional']}"
        )

    parts += [
        "",
        "=== ALL SUPPLEMENTAL CHARGES ON PAGE ===",
    ]
    for charge in supplemental:
        parts.append(
            f"  - '{charge.get('label', '')}': "
            f"{charge.get('amount')} | "
            f"pre_selected={charge.get('is_pre_selected')} | "
            f"optional={charge.get('is_optional')}"
        )

    parts += [
        "",
        "=== FEE-RELATED TEXT SIGNALS FROM PAGE ===",
    ]
    for sig in signals.get("fee_text_signals", []):
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


async def drip_pricing_node(state: PricingAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP05_DRIP")
    raw_response = ""

    try:
        user_msg = _build_user_message(state)
        log.debug("drip_pricing_calling_llm", input_chars=len(user_msg))

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
            "drip_pricing_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )

    except Exception as exc:
        log.error("drip_pricing_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE,        # type: ignore[arg-type]
            pattern_name=_NAME,
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"drip_pricing_result": result}