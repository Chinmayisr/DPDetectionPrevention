"""
agents/behavioral_agent/nodes/saas_billing.py
Detects SaaS Billing dark patterns (DP10).
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
    Path(__file__).parent.parent / "prompts" / "saas_billing.txt"
).read_text()

_CODE = "DP10"
_NAME = "SaaS Billing"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals       = state.get("saas_billing_signals", {})
    text_elements = state.get("text_elements", [])
    buttons       = state.get("buttons", [])
    prices        = state.get("prices", [])
    forms         = state.get("forms", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url','')}",
        f"Page Type: {state.get('current_page_type','')}",
        "",
        "=== PRE-COMPUTED SAAS BILLING SIGNALS ===",
        f"Total SaaS billing signals:   {signals.get('total_saas_signals',0)}",
        f"Annual billed as monthly:     {signals.get('billing_period_mismatch')}",
        f"Per-seat pricing hidden:      {signals.get('has_per_seat_hidden')}",
        f"Introductory pricing found:   {signals.get('has_intro_price')}",
        f"Price anchoring detected:     {signals.get('has_price_anchoring')}",
        "",
        "=== ANNUAL-BILLED-AS-MONTHLY SIGNALS ===",
    ]
    for sig in signals.get("annual_billed_as_monthly", []):
        parts.append(f"  {sig}")

    parts += ["", "=== PER-SEAT / PER-USER PRICING SIGNALS ==="]
    for sig in signals.get("per_seat_signals", []):
        parts.append(f"  {sig}")

    parts += ["", "=== INTRODUCTORY / ESCALATING PRICE SIGNALS ==="]
    for sig in signals.get("intro_price_signals", []):
        parts.append(f"  {sig}")

    parts += ["", "=== PRICE ANCHORING (crossed-out prices) ==="]
    for p in signals.get("price_anchoring", []):
        parts.append(
            f"  original={p['original']} current={p['current']} "
            f"discount={p['discount_pct']}% text='{p['text']}'"
        )

    parts += ["", "=== ALL SAAS BILLING KEYWORD MATCHES ==="]
    for sig in signals.get("saas_kw_found", []):
        parts.append(f"  {sig}")

    parts += ["", "=== PRICES ON PAGE ==="]
    for p in prices[:15]:
        parts.append(
            f"  '{p.get('text','')[:60]}' | amount={p.get('amount')} | "
            f"orig={p.get('original_price')} | location={p.get('location')}"
        )

    parts += ["", "=== FORMS (billing period selectors) ==="]
    for form in forms:
        for field in form.get("fields", []):
            if field.get("input_type") in ("radio", "select", "checkbox"):
                parts.append(
                    f"  [{field.get('input_type')}] "
                    f"label='{field.get('label_text','')[:80]}' | "
                    f"value='{field.get('value','')[:40]}'"
                )

    parts += ["", "=== ALL TEXT ELEMENTS (tag | location | text) ==="]
    for t in text_elements[:200]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:120]}"
        )

    parts += ["", "=== BUTTONS / PLAN CTAs ==="]
    for b in buttons[:30]:
        parts.append(f"  {b.get('text','')[:100]}")

    return "\n".join(parts)


async def saas_billing_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("saas_billing_calling_llm", input_chars=len(user_msg))
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
        log.info("saas_billing_complete",
                 detected=detected, confidence=confidence,
                 evidence_count=len(evidence))
    except Exception as exc:
        log.error("saas_billing_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=False, confidence=0.0,
            error=str(exc), raw_llm_response=raw_response,
        )
    return {"saas_billing_result": result}