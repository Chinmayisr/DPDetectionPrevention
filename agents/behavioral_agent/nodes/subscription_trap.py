"""
agents/behavioral_agent/nodes/subscription_trap.py
Detects Subscription Trap (DP08).
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
    Path(__file__).parent.parent / "prompts" / "subscription_trap.txt"
).read_text()

_CODE = "DP08"
_NAME = "Subscription Trap"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals       = state.get("subscription_trap_signals", {})
    text_elements = state.get("text_elements", [])
    buttons       = state.get("buttons", [])
    forms         = state.get("forms", [])
    prices        = state.get("prices", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url','')}",
        f"Page Type: {state.get('current_page_type','')}",
        "",
        "=== PRE-COMPUTED SUBSCRIPTION TRAP SIGNALS ===",
        f"Subscription keywords found:  {signals.get('total_subscription_signals',0)}",
        f"Fine-print subscription terms: {len(signals.get('fine_print_subscription',[]))}",
        f"Ambiguous CTA buttons:        {len(signals.get('ambiguous_cta_texts',[]))}",
        f"Pre-checked consent boxes:    {signals.get('pre_checked_consent_count',0)}",
        f"Zero/free price CTA:          {signals.get('is_zero_price_cta')}",
        f"Has fine-print terms:         {signals.get('has_fine_print_terms')}",
        "",
        "=== SUBSCRIPTION KEYWORDS IN TEXT ===",
    ]
    for kw in signals.get("subscription_kw_found", []):
        parts.append(f"  {kw}")

    parts += ["", "=== FINE PRINT SUBSCRIPTION TERMS ==="]
    for fp in signals.get("fine_print_subscription", []):
        parts.append(f"  {fp}")

    parts += ["", "=== AMBIGUOUS CTA BUTTON TEXTS ==="]
    for cta in signals.get("ambiguous_cta_texts", []):
        parts.append(f"  '{cta}'")

    parts += ["", "=== AUTO SUBSCRIPTION API CALLS ==="]
    for call in signals.get("subscription_api_calls", []):
        parts.append(f"  {call}")

    parts += ["", "=== FORM DATA (checkboxes and hidden fields) ==="]
    for form in forms:
        parts.append(
            f"  form: action={form.get('action','')} | "
            f"pre_checked={form.get('pre_checked_count',0)} | "
            f"hidden_consent={form.get('has_hidden_consent',False)}"
        )
        for field in form.get("fields", []):
            if field.get("input_type") in ("checkbox", "hidden"):
                parts.append(
                    f"    [{field.get('input_type')}] "
                    f"label='{field.get('label_text','')[:80]}' | "
                    f"pre_checked={field.get('is_pre_checked')} | "
                    f"value='{field.get('value','')[:40]}'"
                )

    parts += ["", "=== PRICES ON PAGE ==="]
    for p in prices[:10]:
        parts.append(
            f"  {p.get('text','')[:60]} | amount={p.get('amount')} | "
            f"location={p.get('location')}"
        )

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


async def subscription_trap_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("subscription_trap_calling_llm", input_chars=len(user_msg))
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
        log.info("subscription_trap_complete",
                 detected=detected, confidence=confidence,
                 evidence_count=len(evidence))
    except Exception as exc:
        log.error("subscription_trap_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE, pattern_name=_NAME,
            detected=False, confidence=0.0,
            error=str(exc), raw_llm_response=raw_response,
        )
    return {"subscription_trap_result": result}