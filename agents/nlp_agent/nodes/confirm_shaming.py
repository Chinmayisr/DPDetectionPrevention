"""
agents/nlp_agent/nodes/confirm_shaming.py
Detects Confirm Shaming (DP02).
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from agents.shared.models import (
    DarkPatternCode, EvidenceItem, PATTERN_NAMES, SinglePatternResult,
)
from agents.shared.openai_client import chat_complete_json
from agents.nlp_agent.state import NLPAgentState

logger = structlog.get_logger(__name__)

_PROMPT = (Path(__file__).parent.parent / "prompts" / "confirm_shaming.txt").read_text()
_CONFIDENCE_THRESHOLD = 0.70


def _build_user_message(state: NLPAgentState) -> str:
    parts = [
        "=== PAGE INFO ===",
        f"URL: {state['url']}",
        f"Page Type: {state['page_type']}",
        "",
        "=== ALL TEXT ELEMENTS (tag | location | text) ===",
    ]
    for t in state.get("text_elements", [])[:300]:
        parts.append(f"[{t.get('tag','?')}|{t.get('location','?')}] {t.get('text','')[:150]}")

    parts += [
        "",
        "=== CONFIRM SHAMING FOCUSED SLICE (pre-filtered) ===",
    ]
    for item in state.get("confirm_shaming_slice", []):
        parts.append(item)

    parts += [
        "",
        "=== ALL BUTTONS (text | in_modal | is_close) ===",
    ]
    for b in state.get("buttons", []):
        parts.append(
            f"text='{b.get('text','')[:150]}' | "
            f"modal={b.get('is_in_modal')} | "
            f"close={b.get('is_close_button')}"
        )

    parts += [
        "",
        "=== OVERLAYS / POPUPS ===",
    ]
    for o in state.get("overlays", []):
        parts.append(f"[{o.get('overlay_type','?')}|coverage={o.get('viewport_coverage_pct',0):.1f}%] {o.get('text','')[:300]}")

    parts += [
        "",
        "=== FULL PAGE TEXT (first 3000 chars) ===",
        state.get("full_text", "")[:3000],
    ]
    return "\n".join(parts)


async def confirm_shaming_node(state: NLPAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP02")
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("confirm_shaming_calling_llm", input_chars=len(user_msg))

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

        evidence = [
            EvidenceItem(
                text=e.get("text", ""),
                location=e.get("location"),
                reason=e.get("reason"),
            )
            for e in raw_ev
            if isinstance(e, dict)
        ] if detected else []

        result = SinglePatternResult(
            pattern_code=DarkPatternCode.CONFIRM_SHAMING,
            pattern_name=PATTERN_NAMES[DarkPatternCode.CONFIRM_SHAMING],
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info(
            "confirm_shaming_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )
    except Exception as exc:
        log.error("confirm_shaming_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=DarkPatternCode.CONFIRM_SHAMING,
            pattern_name=PATTERN_NAMES[DarkPatternCode.CONFIRM_SHAMING],
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"confirm_shaming_result": result}