"""
agents/visual_agent/nodes/disguised_ads.py
Detects Disguised Ads (DP03) using GPT-4o vision.
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
    Path(__file__).parent.parent / "prompts" / "disguised_ads.txt"
).read_text()

_CODE = "DP03"
_NAME = "Disguised Ads"
_CONFIDENCE_THRESHOLD = 0.70


def _build_text_context(state: VisualAgentState) -> str:
    """
    Build the structured DOM context that accompanies the screenshot.
    The vision model receives both this text AND the image simultaneously.
    """
    signals       = state.get("disguised_ads_signals", {})
    text_elements = state.get("text_elements", [])
    links         = state.get("link_elements", [])

    parts = [
        "=== PAGE INFO ===",
        f"URL: {state.get('url', '')}",
        f"Page Type: {state.get('page_type', '')}",
        "",
        "=== PRE-COMPUTED DISGUISED ADS DOM SIGNALS ===",
        f"Sponsored links flagged by scraper: {signals.get('sponsored_link_count', 0)}",
        f"Domain mismatch links:              {signals.get('domain_mismatch_count', 0)}",
        f"Has sponsored content:              {signals.get('has_sponsored_content')}",
        f"Has domain mismatches:              {signals.get('has_domain_mismatches')}",
        "",
        "=== SPONSORED LINKS (flagged by DOM analysis) ===",
    ]
    for link in signals.get("sponsored_links", []):
        parts.append(
            f"  text='{link['text']}' | "
            f"href='{link['href']}' | "
            f"bbox={link.get('bbox')}"
        )

    parts += [
        "",
        "=== DOMAIN MISMATCH LINKS ===",
    ]
    for link in signals.get("domain_mismatch_links", []):
        parts.append(
            f"  text='{link['text']}' | "
            f"displayed='{link['displayed_url']}' | "
            f"actual='{link['actual_href']}'"
        )

    parts += [
        "",
        "=== AD-RELATED TEXT LABELS FOUND IN DOM ===",
    ]
    for label in signals.get("ad_label_texts", []):
        parts.append(f"  {label}")

    parts += [
        "",
        "=== ALL TEXT ELEMENTS (tag | location | visible | text) ===",
        "Use these to correlate with what you see in the screenshot.",
    ]
    for t in text_elements[:150]:
        parts.append(
            f"[{t.get('tag','?')}|{t.get('location','?')}|"
            f"vis={t.get('is_visible')}] {t.get('text','')[:100]}"
        )

    parts += [
        "",
        "=== ALL LINKS (sponsored and domain_mismatch flagged) ===",
    ]
    for link in links[:50]:
        if link.get("is_sponsored") or link.get("domain_mismatch"):
            parts.append(
                f"  '{link.get('text','')[:60]}' → "
                f"'{link.get('actual_href','')[:80]}' | "
                f"sponsored={link.get('is_sponsored')} | "
                f"mismatch={link.get('domain_mismatch')}"
            )

    parts += [
        "",
        "=== INSTRUCTION ===",
        "Now examine the screenshot carefully.",
        "Look for the visual signals described in your system prompt.",
        "Cross-reference the DOM signals above with what you see visually.",
        "A 'Sponsored' label in the DOM that is visually tiny/grey = strong evidence.",
    ]

    return "\n".join(parts)


async def disguised_ads_node(state: VisualAgentState) -> dict:
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
            "disguised_ads_vision_call",
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
            "disguised_ads_complete",
            detected=detected,
            confidence=confidence,
            evidence_count=len(evidence),
            visual_analysis=data.get("visual_analysis", "")[:100],
        )

    except Exception as exc:
        log.error("disguised_ads_error", error=str(exc), exc_info=True)
        result = SinglePatternResult(
            pattern_code=_CODE,
            pattern_name=_NAME,
            detected=False,
            confidence=0.0,
            error=str(exc),
            raw_llm_response=raw_response,
        )

    return {"disguised_ads_result": result}