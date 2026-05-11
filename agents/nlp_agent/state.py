"""
agents/nlp_agent/state.py
LangGraph state schema for the NLP Agent.
"""
from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict

from agents.shared.models import SinglePatternResult


def _merge_result(
    existing: SinglePatternResult | None,
    new: SinglePatternResult | None,
) -> SinglePatternResult | None:
    """Reducer — later write wins (each node writes its own field once)."""
    return new if new is not None else existing


class NLPAgentState(TypedDict):
    # ── Input (populated once at graph entry) ──────────────────
    scrape_id:     str
    session_id:    str
    url:           str
    page_type:     str
    full_text:     str

    # Structured extractions from scraper
    buttons:       list[dict]
    overlays:      list[dict]
    forms:         list[dict]
    timers:        list[dict]
    links:         list[dict]
    text_elements: list[dict]   # ALL text nodes — sent to every detector

    # Focused slices built by preprocess node
    urgency_slice:         list[str]
    confirm_shaming_slice: list[str]
    disguised_ads_slice:   list[str]
    trick_question_slice:  list[str]

    # ── Detection results (one per detector node) ──────────────
    false_urgency_result:   Annotated[SinglePatternResult | None, _merge_result]
    confirm_shaming_result: Annotated[SinglePatternResult | None, _merge_result]
    disguised_ads_result:   Annotated[SinglePatternResult | None, _merge_result]
    trick_question_result:  Annotated[SinglePatternResult | None, _merge_result]

    # ── Control ────────────────────────────────────────────────
    errors: list[str]