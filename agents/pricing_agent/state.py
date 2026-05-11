"""
agents/pricing_agent/state.py
LangGraph state schema for the Pricing Agent.
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


class PricingAgentState(TypedDict):
    # ── Core identity ──────────────────────────────────────────
    scrape_id:    str
    session_id:   str

    # ── Current page ──────────────────────────────────────────
    current_url:       str
    current_page_type: str
    current_prices:    list[dict]
    current_cart_items:list[dict]
    supplemental_charges: list[dict]
    displayed_total:   float | None
    computed_subtotal: float | None
    price_gap:         float | None

    # ── Extra scraped content (per user requirement) ──────────
    text_elements: list[dict]   # all visible text nodes
    buttons:       list[dict]   # all button elements

    # ── Previous product page (may be empty) ──────────────────
    previous_scrape_id: str | None
    previous_url:       str | None
    previous_prices:    list[dict]
    price_diffs:        list[dict]   # pre-computed by session_store

    # ── Pre-computed signals (built by preprocess node) ────────
    drip_pricing_signals: dict
    bait_switch_signals:  dict

    # ── Detection results ──────────────────────────────────────
    drip_pricing_result:  Annotated[SinglePatternResult | None, _merge_result]
    bait_switch_result:   Annotated[SinglePatternResult | None, _merge_result]

    # ── Final output ───────────────────────────────────────────
    aggregated_result: dict | None
    errors: list[str]