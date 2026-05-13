"""
agents/visual_agent/state.py
LangGraph state schema for the Visual Agent.
"""
from __future__ import annotations

from typing import Annotated
from typing_extensions import TypedDict

from agents.shared.models import SinglePatternResult


def _merge_result(
    existing: SinglePatternResult | None,
    new: SinglePatternResult | None,
) -> SinglePatternResult | None:
    return new if new is not None else existing


class VisualAgentState(TypedDict):
    # ── Core identity ──────────────────────────────────────────
    scrape_id:  str
    session_id: str

    # ── Page context ──────────────────────────────────────────
    url:       str
    page_type: str

    # ── Visual input ──────────────────────────────────────────
    screenshot_b64: str         # base64 JPEG — fetched from Redis by runner
    screenshot_key: str         # Redis key reference

    # ── DOM context passed to vision ─────────────────────────
    # These supplement the screenshot so the model has both
    # visual + structural signals simultaneously
    overlay_elements:       list[dict]  # overlays detected by scraper
    link_elements:          list[dict]  # all links (with sponsored flags)
    button_elements:        list[dict]  # all buttons (with color/size data)
    price_bounding_boxes:   list[dict]  # price element positions
    text_elements:          list[dict]  # all visible text nodes
    forms:                  list[dict]  # form elements

    # ── Pre-computed signals (built by preprocess) ─────────────
    disguised_ads_signals:       dict
    interface_interference_signals: dict

    # ── Detection results ──────────────────────────────────────
    disguised_ads_result:            Annotated[SinglePatternResult | None, _merge_result]
    interface_interference_result:   Annotated[SinglePatternResult | None, _merge_result]

    # ── Final output ───────────────────────────────────────────
    aggregated_result: dict | None
    errors: list[str]