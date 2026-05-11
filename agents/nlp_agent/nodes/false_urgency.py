"""
agents/nlp_agent/nodes/false_urgency.py
Detects False Urgency (DP01).
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

_PROMPT = (Path(__file__).parent.parent / "prompts" / "false_urgency.txt").read_text()
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
        "=== URGENCY-FOCUSED SLICE (pre-filtered) ===",
    ]
    for item in state.get("urgency_slice", []):
        parts.append(item)

    parts += [
        "",
        "=== TIMERS DETECTED ===",
    ]
    for t in state.get("timers", []):
        parts.append(f"text='{t.get('text','')}' | countdown={t.get('is_counting_down')} | context='{t.get('context','')[:100]}'")

    parts += [
        "",
        "=== OVERLAYS / BANNERS ===",
    ]
    for o in state.get("overlays", []):
        parts.append(f"[{o.get('overlay_type','?')}] {o.get('text','')[:200]}")

    parts += [
        "",
        "=== FULL PAGE TEXT (first 3000 chars) ===",
        state.get("full_text", "")[:3000],
    ]
    return "\n".join(parts)


async def false_urgency_node(state: NLPAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP01")
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("false_urgency_calling_llm", input_chars=len(user_msg))

        data = await chat_complete_json(
            system_prompt=_PROMPT,
            user_message=user_msg,
        )
        raw_response = json.dumps(data)

        detected    = bool(data.get("detected", False))
        confidence  = float(data.get("confidence", 0.0))
        raw_evidence= data.get("evidence", [])

        if confidence < _CONFIDENCE_THRESHOLD:
            detected = False

        evidence = [
            EvidenceItem(
                text=e.get("text", ""),
                location=e.get("location"),
                reason=e.get("reason"),
            )
            for e in raw_evidence
            if isinstance(e, dict)
        ] if detected else []

        result = SinglePatternResult(
            pattern_code=DarkPatternCode.FALSE_URGENCY,
            pattern_name=PATTERN_NAMES[DarkPatternCode.FALSE_URGENCY],
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info(
            "false_urgency_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )
    except Exception as exc:
        log.error("false_urgency_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=DarkPatternCode.FALSE_URGENCY,
            pattern_name=PATTERN_NAMES[DarkPatternCode.FALSE_URGENCY],
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"false_urgency_result": result}