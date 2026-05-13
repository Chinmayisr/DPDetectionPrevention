"""
agents/behavioral_agent/nodes/forced_action.py
Detects Forced Action (DP13).
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
    Path(__file__).parent.parent / "prompts" / "forced_action.txt"
).read_text()

_CODE = "DP13"
_NAME = "Forced Action"
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: BehavioralAgentState) -> str:
    signals       = state.get("forced_action_signals", {})
    text_elements = state.get("text_elements", [])
    buttons       = state.get("buttons", [])
    forms         = state.get("forms", [])
    overlays      = state.get("current_overlays", [])
    network_reqs  = state.get("current_network_requests", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('current_url', '')}",
        f"Page Type: {state.get('current_page_type', '')}",
        "",
        "=== PRE-COMPUTED FORCED ACTION SIGNALS ===",
        f"Gate text signals found:         {signals.get('gate_text_count', 0)}",
        f"Blocking overlays:               {signals.get('blocking_overlay_count', 0)}",
        f"Has blocking overlay:            {signals.get('has_blocking_overlay')}",
        f"Excessive required fields:       {signals.get('has_excessive_requirements')}",
        f"Notification gate detected:      {signals.get('has_notification_gate')}",
        f"Guest checkout blocked:          {signals.get('has_guest_checkout_blocked')}",
        f"Forced social login:             {signals.get('has_forced_social_login')}",
        f"Is likely forced action:         {signals.get('is_likely_forced_action')}",
        f"Total forced action signals:     {signals.get('total_forced_action_signals', 0)}",
        "",
        "=== GATE LANGUAGE FOUND IN TEXT ELEMENTS ===",
    ]
    for sig in signals.get("gate_text_signals", []):
        parts.append(f"  {sig}")

    parts += [
        "",
        "=== BLOCKING OVERLAYS (high coverage or interaction-blocking) ===",
    ]
    for o in signals.get("blocking_overlays", []):
        parts.append(
            f"  type={o['type']} | "
            f"coverage={o['coverage']:.1f}% | "
            f"has_close={o['has_close']} | "
            f"blocks_interaction={o['blocks']} | "
            f"text='{o['text']}'"
        )

    parts += [
        "",
        "=== GUEST CHECKOUT BLOCKED SIGNALS ===",
    ]
    for sig in signals.get("guest_checkout_blocked", []):
        parts.append(f"  {sig}")

    parts += [
        "",
        "=== NOTIFICATION GATE SIGNALS ===",
    ]
    for sig in signals.get("notification_gates", []):
        parts.append(f"  {sig}")

    parts += [
        "",
        "=== FORCED SOCIAL LOGIN BUTTONS ===",
    ]
    for sig in signals.get("forced_social_logins", []):
        parts.append(f"  '{sig}'")

    parts += [
        "",
        "=== EXCESSIVE REQUIRED FORM FIELDS ===",
    ]
    for f in signals.get("excessive_required_fields", []):
        parts.append(
            f"  form: {f['form_action']} | "
            f"phone_required={f['phone_required']} | "
            f"consent_required={f['consent_required']} | "
            f"field_count={f['field_count']}"
        )

    parts += [
        "",
        "=== ALL OVERLAYS ON PAGE ===",
    ]
    for o in overlays:
        parts.append(
            f"  [{o.get('overlay_type','?')}] "
            f"coverage={o.get('viewport_coverage_pct',0):.1f}% | "
            f"has_close={o.get('has_close_button')} | "
            f"blocks={o.get('blocks_interaction')} | "
            f"autonomous={o.get('appeared_autonomously')} | "
            f"text='{o.get('text','')[:120]}'"
        )

    parts += [
        "",
        "=== ALL FORMS (required fields and consent) ===",
    ]
    for form in forms:
        parts.append(
            f"  action={form.get('action','')} | "
            f"pre_checked={form.get('pre_checked_count',0)} | "
            f"hidden_consent={form.get('has_hidden_consent',False)}"
        )
        for field in form.get("fields", []):
            if field.get("is_required") or field.get("input_type") in ("checkbox", "hidden"):
                parts.append(
                    f"    [{field.get('input_type')}] "
                    f"label='{field.get('label_text','')[:80]}' | "
                    f"required={field.get('is_required')} | "
                    f"pre_checked={field.get('is_pre_checked')} | "
                    f"hidden={field.get('is_hidden')}"
                )

    parts += [
        "",
        "=== BUTTONS (CTAs that may be forced steps) ===",
    ]
    for b in buttons[:40]:
        parts.append(
            f"  text='{b.get('text','')[:100]}' | "
            f"modal={b.get('is_in_modal')} | "
            f"close={b.get('is_close_button')}"
        )

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
        "=== NETWORK REQUESTS (auto-triggered) ===",
    ]
    for req in network_reqs[:20]:
        if req.get("is_auto_triggered") or req.get("method") == "POST":
            parts.append(
                f"  {req.get('method','?')} {req.get('url','')[:120]} | "
                f"auto={req.get('is_auto_triggered')}"
            )

    return "\n".join(parts)


async def forced_action_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""

    try:
        user_msg = _build_user_message(state)
        log.debug("forced_action_calling_llm", input_chars=len(user_msg))

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
        log.info(
            "forced_action_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )

    except Exception as exc:
        log.error("forced_action_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE,
            pattern_name=_NAME,
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"forced_action_result": result}