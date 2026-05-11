"""
agents/pricing_agent/runner.py
Public entry point for the Pricing Agent.

Usage:
    result = await run_pricing_agent(scrape_id="...", session_id="...")
"""
from __future__ import annotations

import json
import time

import structlog

from agents.pricing_agent.graph import pricing_graph
from agents.pricing_agent.state import PricingAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


async def run_pricing_agent(
    scrape_id: str,
    session_id: str,
) -> dict:
    """
    Fetch the pricing payload from Redis, run the LangGraph graph,
    and return the aggregated pricing detection result dict.

    Raises:
        KeyError: if the pricing payload does not exist in Redis
    """
    log = logger.bind(scrape_id=scrape_id, session_id=session_id)
    start = time.perf_counter()

    # ── Fetch pricing payload from Redis ──────────────────────
    redis = await get_redis_client()
    raw = await redis.get(f"dg:pricing:{session_id}:{scrape_id}")
    if not raw:
        raise KeyError(
            f"Pricing payload not found for "
            f"scrape_id={scrape_id} session_id={session_id}. "
            "Run scrape-test first and ensure the page is a CART or CHECKOUT."
        )

    payload = json.loads(raw)
    log.info(
        "pricing_agent_starting",
        current_url=payload.get("current_url", ""),
        page_type=payload.get("current_page_type", ""),
        has_previous=payload.get("previous_scrape_id") is not None,
    )

    # ── Fetch text_elements and buttons from the scrape DOM key
    # (they are stored separately in the DOM payload, not in the pricing payload)
    text_elements: list[dict] = []
    buttons: list[dict] = []

    dom_raw = await redis.get(f"dg:scrape:{scrape_id}:dom")
    if dom_raw:
        dom = json.loads(dom_raw)
        text_elements = dom.get("text_elements", [])
        buttons       = dom.get("buttons", [])

    # ── Build initial state ───────────────────────────────────
    initial_state: PricingAgentState = {
        # Identity
        "scrape_id":  scrape_id,
        "session_id": session_id,

        # Current page
        "current_url":        payload.get("current_url", ""),
        "current_page_type":  payload.get("current_page_type", "OTHER"),
        "current_prices":     payload.get("current_prices", []),
        "current_cart_items": payload.get("current_cart_items", []),
        "supplemental_charges": payload.get("supplemental_charges", []),
        "displayed_total":    payload.get("displayed_total"),
        "computed_subtotal":  payload.get("computed_subtotal"),
        "price_gap":          payload.get("price_gap"),

        # Extra scraped content (text + buttons from DOM)
        "text_elements": text_elements,
        "buttons":       buttons,

        # Previous product page
        "previous_scrape_id": payload.get("previous_scrape_id"),
        "previous_url":       payload.get("previous_url"),
        "previous_prices":    payload.get("previous_prices", []),
        "price_diffs":        payload.get("price_diffs", []),

        # Signals built by preprocess node
        "drip_pricing_signals": {},
        "bait_switch_signals":  {},

        # Detection results
        "drip_pricing_result": None,
        "bait_switch_result":  None,

        # Output
        "aggregated_result": None,
        "errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────
    final_state = await pricing_graph.ainvoke(initial_state)

    duration_ms = int((time.perf_counter() - start) * 1000)
    result: dict = final_state.get("aggregated_result") or {}
    log.info(
        "pricing_agent_complete",
        duration_ms=duration_ms,
        total_detected=result.get("total_detected", 0),
        financial_impact=result.get("financial_impact", {}).get(
            "total_extra_charged", 0
        ),
    )
    return result