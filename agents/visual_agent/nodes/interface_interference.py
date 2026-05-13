"""
agents/visual_agent/nodes/interface_interference.py
Detects Interface Interference (DP12) using GPT-4o vision.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.models import EvidenceItem, SinglePatternResult
from agents.shared.openai_client import chat_complete_vision_json
from agents.visual_agent.state import VisualAgentState

logger = structlog.get_logger(__name__)

_PROMPT = (
    Path(__file__).parent.parent / "prompts" / "interface_interference.txt"
).read_text()

_CODE = "DP12"
_NAME = "Interface Interference"
_CONFIDENCE_THRESHOLD = 0.70


def _build_text_context(state: VisualAgentState) -> str:
    """
    Build structured DOM context for interface interference detection.
    Includes button color/size data, overlay info, and form states
    so the vision model can correlate visual observations with DOM truth.
    """
    signals       = state.get("interface_interference_signals", {})
    text_elements = state.get("text_elements", [])
    overlays      = state.get("overlay_elements", [])
    forms         = state.get("forms", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('url', '')}",
        f"Page Type: {state.get('page_type', '')}",
        "",
        "=== PRE-COMPUTED INTERFACE INTERFERENCE SIGNALS ===",
        f"Accept-type buttons found:         {signals.get('accept_button_count', 0)}",
        f"Decline-type buttons found:        {signals.get('decline_button_count', 0)}",
        f"Has asymmetry (accept no decline): {signals.get('has_asymmetry')}",
        f"Overlays without close button:     {len(signals.get('overlays_without_close', []))}",
        f"Overlays with hidden close:        {len(signals.get('overlays_with_hidden_close', []))}",
        f"Pre-checked consent fields:        {len(signals.get('pre_checked_fields', []))}",
        f"Interaction-blocking overlays:     {len(signals.get('blocking_overlays', []))}",
        f"Has blocking overlays:             {signals.get('has_blocking_overlays')}",
        "",
        "=== ACCEPT-TYPE BUTTONS (with computed CSS) ===",
        "These should be visually compared against DECLINE buttons in the screenshot.",
    ]
    for btn in signals.get("accept_buttons", []):
        parts.append(
            f"  text='{btn['text']}' | "
            f"bg={btn.get('bg_color')} | "
            f"color={btn.get('text_color')} | "
            f"font={btn.get('font_size')} | "
            f"modal={btn.get('is_in_modal')} | "
            f"bbox={btn.get('bbox')}"
        )

    parts += [
        "",
        "=== DECLINE-TYPE / CLOSE BUTTONS (with computed CSS) ===",
        "Compare these visually against ACCEPT buttons above.",
    ]
    for btn in signals.get("decline_buttons", []):
        parts.append(
            f"  text='{btn['text']}' | "
            f"bg={btn.get('bg_color')} | "
            f"color={btn.get('text_color')} | "
            f"font={btn.get('font_size')} | "
            f"modal={btn.get('is_in_modal')} | "
            f"close={btn.get('is_close')} | "
            f"bbox={btn.get('bbox')}"
        )

    parts += [
        "",
        "=== OVERLAYS WITHOUT CLOSE BUTTON ===",
    ]
    for o in signals.get("overlays_without_close", []):
        parts.append(
            f"  type={o['type']} | "
            f"coverage={o['coverage']:.1f}% | "
            f"text='{o['text']}'"
        )

    parts += [
        "",
        "=== OVERLAYS WITH NON-PROMINENT CLOSE ===",
    ]
    for o in signals.get("overlays_with_hidden_close", []):
        parts.append(
            f"  type={o['type']} | "
            f"coverage={o['coverage']:.1f}% | "
            f"text='{o['text']}'"
        )

    parts += [
        "",
        "=== PRE-CHECKED CONSENT CHECKBOXES ===",
    ]
    for field in signals.get("pre_checked_fields", []):
        parts.append(
            f"  label='{field['label']}' | "
            f"value='{field['value']}' | "
            f"hidden={field['hidden']}"
        )

    parts += [
        "",
        "=== INTERACTION-BLOCKING OVERLAYS ===",
    ]
    for o in signals.get("blocking_overlays", []):
        parts.append(
            f"  type={o['type']} | "
            f"coverage={o['coverage']:.1f}% | "
            f"text='{o['text']}'"
        )

    parts += [
        "",
        "=== ALL OVERLAYS / POPUPS ON PAGE ===",
    ]
    for o in overlays:
        parts.append(
            f"  [{o.get('overlay_type','?')}] "
            f"coverage={o.get('viewport_coverage_pct',0):.1f}% | "
            f"has_close={o.get('has_close_button')} | "
            f"close_prominent={o.get('close_button_prominent')} | "
            f"blocks={o.get('blocks_interaction')} | "
            f"autonomous={o.get('appeared_autonomously')} | "
            f"text='{o.get('text','')[:100]}'"
        )

    parts += [
        "",
        "=== FORMS WITH CHECKBOXES ===",
    ]
    for form in forms:
        pre_checked = form.get("pre_checked_count", 0)
        if pre_checked > 0 or form.get("has_hidden_consent"):
            parts.append(
                f"  action={form.get('action','')} | "
                f"pre_checked={pre_checked} | "
                f"hidden_consent={form.get('has_hidden_consent')}"
            )
            for field in form.get("fields", []):
                if field.get("input_type") == "checkbox":
                    parts.append(
                        f"    [checkbox] pre_checked={field.get('is_pre_checked')} | "
                        f"label='{field.get('label_text','')[:80]}'"
                    )

    parts += [
        "",
        "=== ALL TEXT ELEMENTS (tag | location | text) ===",
    ]
    for t in text_elements[:150]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}] "
            f"{t.get('text','')[:100]}"
        )

    parts += [
        "",
        "=== INSTRUCTION ===",
        "Now examine the screenshot carefully.",
        "Focus on: button visual asymmetry, close button visibility,",
        "consent dialog design, checkbox visual states.",
        "Cross-reference the CSS color/size data above with what you",
        "actually see rendered in the screenshot.",
        "A button with grey bg_color that is barely visible = strong evidence.",
    ]

    return "\n".join(parts)


async def interface_interference_node(state: VisualAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern=_CODE)
    raw_response = ""

    try:
        screenshot = state.get("screenshot_b64", "")
        if not screenshot:
            raise ValueError(
                "No screenshot available. "
                "The screenshot may have expired in Redis (TTL=2min). "
                "Re-run the scrape to generate a fresh screenshot."
            )

        text_context = _build_text_context(state)
        log.debug(
            "interface_interference_vision_call",
            context_chars=len(text_context),
            screenshot_kb=len(screenshot) // 1024,
        )

        data = await chat_complete_vision_json(
            system_prompt=_PROMPT,
            text_context=text_context,
            image_b64=screenshot,
            image_media_type="image/jpeg",
        )
        raw_response = json.dumps(data)

        detected   = bool(data.get("detected", False))
        confidence = float(data.get("confidence", 0.0))
        raw_ev     = data.get("visual_evidence", [])

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
            "interface_interference_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
            visual_analysis=data.get("visual_analysis", "")[:100],
        )

    except Exception as exc:
        log.error("interface_interference_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE,
            pattern_name=_NAME,
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"interface_interference_result": result}