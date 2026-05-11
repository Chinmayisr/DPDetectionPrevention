"""
agents/nlp_agent/runner.py
Public entry point for the NLP Agent.

Usage:
    result = await run_nlp_agent(scrape_id="...", session_id="...")
"""
from __future__ import annotations

import json
import time

import structlog

from agents.nlp_agent.graph import nlp_graph
from agents.nlp_agent.state import NLPAgentState
from agents.shared.models import AggregatedDetectionResult
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


async def run_nlp_agent(
    scrape_id: str,
    session_id: str,
) -> AggregatedDetectionResult:
    """
    Fetch the NLP payload from Redis, run the LangGraph graph,
    and return the aggregated detection result.

    Raises:
        KeyError: if the NLP payload key does not exist in Redis
        ValueError: if the payload cannot be deserialised
    """
    log = logger.bind(scrape_id=scrape_id, session_id=session_id)
    start = time.perf_counter()

    # ── Fetch payload from Redis ──────────────────────────────
    redis = await get_redis_client()
    raw = await redis.get(f"dg:nlp:{scrape_id}")
    if not raw:
        raise KeyError(
            f"NLP payload not found in Redis for scrape_id={scrape_id}. "
            "It may have expired (TTL=10min) or the scrape failed."
        )

    payload = json.loads(raw)
    log.info("nlp_agent_starting", url=payload.get("url", ""))

    # ── Build initial state ───────────────────────────────────
    initial_state: NLPAgentState = {
        "scrape_id":     scrape_id,
        "session_id":    session_id,
        "url":           payload.get("url", ""),
        "page_type":     payload.get("page_type", "OTHER"),
        "full_text":     payload.get("full_text", ""),
        "buttons":       payload.get("buttons", []),
        "overlays":      payload.get("overlays", []),
        "forms":         payload.get("forms", []),
        "timers":        payload.get("timers", []),
        "links":         payload.get("links", []),
        "text_elements": payload.get("text_elements", []),
        # Slices populated by preprocess node
        "urgency_slice":         [],
        "confirm_shaming_slice": [],
        "disguised_ads_slice":   [],
        "trick_question_slice":  [],
        # Detection results — populated by detector nodes
        "false_urgency_result":   None,
        "confirm_shaming_result": None,
        "disguised_ads_result":   None,
        "trick_question_result":  None,
        # Control
        "errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────
    final_state = await nlp_graph.ainvoke(initial_state)

    duration_ms = int((time.perf_counter() - start) * 1000)
    log.info(
        "nlp_agent_complete",
        duration_ms=duration_ms,
        total_detected=final_state.get("aggregated_result", {}).total_detected
        if hasattr(final_state.get("aggregated_result"), "total_detected")
        else 0,
    )

    result: AggregatedDetectionResult = final_state["aggregated_result"]
    return result