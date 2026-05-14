"""
agents/prevention_agent/state.py
LangGraph TypedDict state for the Prevention Agent.
"""
from __future__ import annotations
from typing import Any
from typing_extensions import TypedDict


class PreventionAgentState(TypedDict):
    # Scan identity
    scrape_id   : str
    session_id  : str
    url         : str
    page_type   : str

    # All detected patterns (merged from all 4 agents)
    all_detected_patterns : list[dict[str, Any]]

    # Enrichment pulled from Redis by preprocess node
    pricing_breakdown : dict[str, Any]   # from pricing agent
    session_cart_data : dict[str, Any]   # cart_events + sneaked_items
    behavioral_data   : dict[str, Any]   # popup_events, subscription_flow, billing
    visual_data       : dict[str, Any]   # visual agent result for DP12

    # Per-node outputs
    raw_patch_instructions     : list[dict[str, Any]]
    resolved_patch_instructions: list[dict[str, Any]]

    # Final result
    aggregated_result : dict[str, Any] | None
