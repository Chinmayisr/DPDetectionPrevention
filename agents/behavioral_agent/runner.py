"""
agents/behavioral_agent/runner.py
Public entry point for the Behavioral Agent.
"""
from __future__ import annotations

import json
import time

import structlog

from agents.behavioral_agent.graph import behavioral_graph
from agents.behavioral_agent.state import BehavioralAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


async def run_behavioral_agent(
    scrape_id: str,
    session_id: str,
) -> dict:
    """
    Fetch behavioral payload + DOM data + session popup history from Redis,
    run the LangGraph graph, and return the aggregated detection result.

    Raises:
        KeyError: if the behavioral payload does not exist in Redis
    """
    log = logger.bind(scrape_id=scrape_id, session_id=session_id)
    start = time.perf_counter()

    redis = await get_redis_client()

    # ── Source 1: Behavioral payload ──────────────────────────
    raw = await redis.get(f"dg:behavioral:{session_id}:{scrape_id}")
    if not raw:
        raise KeyError(
            f"Behavioral payload not found for "
            f"scrape_id={scrape_id} session_id={session_id}. "
            "Run scrape-test first."
        )
    payload = json.loads(raw)

    # ── Source 2: DOM payload for text_elements, buttons, etc. ─
    text_elements: list[dict] = []
    buttons:       list[dict] = []
    forms:         list[dict] = []
    prices:        list[dict] = []
    links:         list[dict] = []
    cart_items:    list[dict] = []

    dom_raw = await redis.get(f"dg:scrape:{scrape_id}:dom")
    if dom_raw:
        dom = json.loads(dom_raw)
        text_elements = dom.get("text_elements", [])
        buttons       = dom.get("buttons", [])
        forms         = dom.get("forms", [])
        prices        = dom.get("prices", [])
        links         = dom.get("links", [])
        cart_items    = dom.get("cart_line_items", [])

    # ── Source 3: Session popup history for nagging detection ──
    popup_timeline: list[dict] = []
    session_ids_raw = await redis.lrange(
        f"dg:session:{session_id}:scrape_ids", 0, -1
    )
    if session_ids_raw:
        for sid in session_ids_raw:
            meta_raw = await redis.get(f"dg:scrape:{sid}:meta")
            if not meta_raw:
                continue
            meta = json.loads(meta_raw)
            # Fetch overlay data from behavioral payload for each past scrape
            bhv_raw = await redis.get(f"dg:behavioral:{session_id}:{sid}")
            if bhv_raw:
                bhv = json.loads(bhv_raw)
                for overlay in bhv.get("current_overlays", []):
                    popup_timeline.append({
                        "scrape_id": sid,
                        "url":       meta.get("url", ""),
                        "type":      overlay.get("overlay_type", ""),
                        "text":      overlay.get("text", "")[:200],
                        "delay_ms":  overlay.get("trigger_delay_ms", 0),
                        "autonomous":overlay.get("appeared_autonomously", False),
                    })

    # Previous cart items (from previous scrape in session)
    previous_cart_items: list[dict] = []
    prev_scrape_id = payload.get("previous_scrape_id")
    if prev_scrape_id:
        prev_dom_raw = await redis.get(f"dg:scrape:{prev_scrape_id}:dom")
        if prev_dom_raw:
            prev_dom = json.loads(prev_dom_raw)
            previous_cart_items = prev_dom.get("cart_line_items", [])

    log.info(
        "behavioral_agent_starting",
        current_url=payload.get("current_url", ""),
        page_type=payload.get("current_page_type", ""),
        popup_timeline_length=len(popup_timeline),
        text_elements=len(text_elements),
    )

    # ── Build initial state ───────────────────────────────────
    initial_state: BehavioralAgentState = {
        "scrape_id":  scrape_id,
        "session_id": session_id,

        "current_url":       payload.get("current_url", ""),
        "current_page_type": payload.get("current_page_type", "OTHER"),
        "full_text":         "",   # not needed separately — covered by text_elements

        "current_mutations":           payload.get("current_mutations", []),
        "current_network_requests":    payload.get("current_network_requests", []),
        "current_auto_cart_mutations": payload.get("current_auto_cart_mutations", []),
        "current_overlays":            payload.get("current_overlays", []),
        "redirect_traps":              payload.get("redirect_traps", []),
        "auto_popup_count":            payload.get("auto_popup_count", 0),
        "popup_timeline":              popup_timeline,

        "previous_scrape_id":       payload.get("previous_scrape_id"),
        "previous_url":             payload.get("previous_url"),
        "previous_mutations":       payload.get("previous_mutations", []),
        "previous_network_requests":payload.get("previous_network_requests", []),

        "current_cart_items":  cart_items,
        "previous_cart_items": previous_cart_items,

        "text_elements": text_elements,
        "buttons":       buttons,
        "forms":         forms,
        "prices":        prices,
        "links":         links,

        "basket_sneaking_signals":   {},
        "subscription_trap_signals": {},
        "nagging_signals":           {},
        "saas_billing_signals":      {},
        "rogue_malicious_signals":   {},
        "forced_action_signals":     {},    

        "basket_sneaking_result":   None,
        "subscription_trap_result": None,
        "nagging_result":           None,
        "saas_billing_result":      None,
        "rogue_malicious_result":   None,
        "forced_action_result":     None,

        "aggregated_result": None,
        "errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────
    final_state = await behavioral_graph.ainvoke(initial_state)

    duration_ms = int((time.perf_counter() - start) * 1000)
    result: dict = final_state.get("aggregated_result") or {}

    log.info(
        "behavioral_agent_complete",
        duration_ms=duration_ms,
        total_detected=result.get("total_detected", 0),
        severity=result.get("severity_label", "none"),
        score=result.get("behavioral_severity_score", 0),
    )
    return result