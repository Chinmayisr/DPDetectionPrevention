"""
agents/nlp_agent/nodes/trick_question.py
Detects Trick Questions (DP04).
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

_PROMPT = (Path(__file__).parent.parent / "prompts" / "trick_question.txt").read_text()
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
        "=== TRICK QUESTION FOCUSED SLICE (pre-filtered) ===",
    ]
    for item in state.get("trick_question_slice", []):
        parts.append(item)

    parts += [
        "",
        "=== FORMS WITH CHECKBOXES AND HIDDEN FIELDS ===",
    ]
    for form in state.get("forms", []):
        parts.append(
            f"form: action={form.get('action','')} | "
            f"pre_checked_count={form.get('pre_checked_count',0)} | "
            f"hidden_consent={form.get('has_hidden_consent',False)}"
        )
        for field in form.get("fields", []):
            if field.get("input_type") in ("checkbox", "hidden"):
                parts.append(
                    f"  [{field.get('input_type')}] "
                    f"label='{field.get('label_text','')[:100]}' | "
                    f"pre_checked={field.get('is_pre_checked')} | "
                    f"hidden={field.get('is_hidden')} | "
                    f"value='{field.get('value','')[:50]}'"
                )

    parts += [
        "",
        "=== FULL PAGE TEXT (first 3000 chars) ===",
        state.get("full_text", "")[:3000],
    ]
    return "\n".join(parts)


async def trick_question_node(state: NLPAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP04")
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("trick_question_calling_llm", input_chars=len(user_msg))

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
            pattern_code=DarkPatternCode.TRICK_QUESTION,
            pattern_name=PATTERN_NAMES[DarkPatternCode.TRICK_QUESTION],
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info(
            "trick_question_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )
    except Exception as exc:
        log.error("trick_question_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=DarkPatternCode.TRICK_QUESTION,
            pattern_name=PATTERN_NAMES[DarkPatternCode.TRICK_QUESTION],
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"trick_question_result": result}