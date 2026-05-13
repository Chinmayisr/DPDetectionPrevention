"""
agents/visual_agent/runner.py
Public entry point for the Visual Agent.

Fetches the visual payload + screenshot from Redis,
runs the LangGraph vision graph, returns aggregated result.
"""
from __future__ import annotations

import json
import time

import structlog

from agents.visual_agent.graph import visual_graph
from agents.visual_agent.state import VisualAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


async def run_visual_agent(
    scrape_id: str,
    session_id: str,
) -> dict:
    """
    Fetch visual payload + screenshot from Redis, run the graph,
    return the aggregated detection result dict.

    Raises:
        KeyError:  if visual payload not found in Redis
        ValueError: if screenshot has expired (TTL=2min shorter than DOM TTL)
    """
    log = logger.bind(scrape_id=scrape_id, session_id=session_id)
    start = time.perf_counter()

    redis = await get_redis_client()

    # ── Source 1: Visual payload (pre-built by session_store) ─
    raw = await redis.get(f"dg:visual:{scrape_id}")
    if not raw:
        raise KeyError(
            f"Visual payload not found for scrape_id={scrape_id}. "
            "Run scrape-test first (TTL=10min)."
        )
    payload = json.loads(raw)

    # ── Source 2: Screenshot (short TTL=2min) ─────────────────
    screenshot_b64 = await redis.get(
        f"dg:scrape:{scrape_id}:screenshot"
    )
    if not screenshot_b64:
        raise ValueError(
            f"Screenshot has expired for scrape_id={scrape_id}. "
            "Screenshots have a 2-minute TTL. "
            "Re-run /scrape-test to generate a fresh screenshot, "
            "then call /visual-detect-test immediately."
        )

    # ── Source 3: Full DOM for text_elements, buttons, forms ──
    text_elements: list[dict] = []
    button_elements: list[dict] = []
    forms: list[dict] = []

    dom_raw = await redis.get(f"dg:scrape:{scrape_id}:dom")
    if dom_raw:
        dom = json.loads(dom_raw)
        text_elements   = dom.get("text_elements", [])
        button_elements = dom.get("buttons", [])
        forms           = dom.get("forms", [])

    log.info(
        "visual_agent_starting",
        url=payload.get("url", ""),
        page_type=payload.get("page_type", ""),
        screenshot_kb=len(screenshot_b64) // 1024,
        text_elements=len(text_elements),
        overlay_count=len(payload.get("overlay_elements", [])),
    )

    # ── Build initial state ───────────────────────────────────
    initial_state: VisualAgentState = {
        "scrape_id":  scrape_id,
        "session_id": session_id,
        "url":        payload.get("url", ""),
        "page_type":  payload.get("page_type", "OTHER"),

        # Visual input
        "screenshot_b64": screenshot_b64,
        "screenshot_key": f"dg:scrape:{scrape_id}:screenshot",

        # DOM context
        "overlay_elements":     payload.get("overlay_elements", []),
        "link_elements":        payload.get("link_elements", []),
        "button_elements":      button_elements,
        "price_bounding_boxes": payload.get("price_bounding_boxes", []),
        "text_elements":        text_elements,
        "forms":                forms,

        # Signals (built by preprocess)
        "disguised_ads_signals":              {},
        "interface_interference_signals":     {},

        # Detection results
        "disguised_ads_result":           None,
        "interface_interference_result":  None,

        # Output
        "aggregated_result": None,
        "errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────
    final_state = await visual_graph.ainvoke(initial_state)

    duration_ms = int((time.perf_counter() - start) * 1000)
    result: dict = final_state.get("aggregated_result") or {}

    log.info(
        "visual_agent_complete",
        duration_ms=duration_ms,
        total_detected=result.get("total_detected", 0),
    )
    return result