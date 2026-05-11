"""
agents/nlp_agent/nodes/disguised_ads.py
Detects Disguised Ads (DP03).
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

_PROMPT = (Path(__file__).parent.parent / "prompts" / "disguised_ads.txt").read_text()
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
        "=== DISGUISED ADS FOCUSED SLICE (pre-filtered) ===",
    ]
    for item in state.get("disguised_ads_slice", []):
        parts.append(item)

    parts += [
        "",
        "=== LINKS WITH SPONSORSHIP / DOMAIN MISMATCH FLAGS ===",
    ]
    for link in state.get("links", []):
        if link.get("is_sponsored") or link.get("domain_mismatch"):
            parts.append(
                f"text='{link.get('text','')[:100]}' | "
                f"href='{link.get('actual_href','')[:100]}' | "
                f"sponsored={link.get('is_sponsored')} | "
                f"mismatch={link.get('domain_mismatch')}"
            )

    parts += [
        "",
        "=== FULL PAGE TEXT (first 3000 chars) ===",
        state.get("full_text", "")[:3000],
    ]
    return "\n".join(parts)


async def disguised_ads_node(state: NLPAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"], pattern="DP03")
    raw_response = ""
    try:
        user_msg = _build_user_message(state)
        log.debug("disguised_ads_calling_llm", input_chars=len(user_msg))

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
            pattern_code=DarkPatternCode.DISGUISED_ADS,
            pattern_name=PATTERN_NAMES[DarkPatternCode.DISGUISED_ADS],
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            raw_llm_response=raw_response,
        )
        log.info(
            "disguised_ads_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
        )
    except Exception as exc:
        log.error("disguised_ads_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=DarkPatternCode.DISGUISED_ADS,
            pattern_name=PATTERN_NAMES[DarkPatternCode.DISGUISED_ADS],
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"disguised_ads_result": result}