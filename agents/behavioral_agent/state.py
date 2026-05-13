"""
agents/behavioral_agent/state.py
LangGraph state schema for the Behavioral Agent.
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


class BehavioralAgentState(TypedDict):
    # ── Core identity ──────────────────────────────────────────
    scrape_id:  str
    session_id: str

    # ── Current page ──────────────────────────────────────────
    current_url:       str
    current_page_type: str
    full_text:         str

    # ── Behavioral signals from scraper ───────────────────────
    current_mutations:          list[dict]
    current_network_requests:   list[dict]
    current_auto_cart_mutations:list[dict]
    current_overlays:           list[dict]
    redirect_traps:             list[dict]
    auto_popup_count:           int
    popup_timeline:             list[dict]   # cross-session overlay history

    # ── Previous page behavioral data ─────────────────────────
    previous_scrape_id:       str | None
    previous_url:             str | None
    previous_mutations:       list[dict]
    previous_network_requests:list[dict]

    # ── Cart comparison ───────────────────────────────────────
    current_cart_items:  list[dict]
    previous_cart_items: list[dict]

    # ── Extra scraped content (per requirement) ───────────────
    text_elements: list[dict]   # all visible text nodes
    buttons:       list[dict]   # all button elements
    forms:         list[dict]   # all form elements
    prices:        list[dict]   # price elements
    links:         list[dict]   # all links

    # ── Pre-computed signals (built by preprocess) ─────────────
    basket_sneaking_signals:    dict
    subscription_trap_signals:  dict
    nagging_signals:            dict
    saas_billing_signals:       dict
    rogue_malicious_signals:    dict
    forced_action_signals:      dict 

    # ── Detection results ──────────────────────────────────────
    basket_sneaking_result:   Annotated[SinglePatternResult | None, _merge_result]
    subscription_trap_result: Annotated[SinglePatternResult | None, _merge_result]
    nagging_result:           Annotated[SinglePatternResult | None, _merge_result]
    saas_billing_result:      Annotated[SinglePatternResult | None, _merge_result]
    rogue_malicious_result:   Annotated[SinglePatternResult | None, _merge_result]

    # ── Final output ───────────────────────────────────────────
    aggregated_result: dict | None
    errors: list[str]