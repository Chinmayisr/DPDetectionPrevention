"""
agents/prevention_agent/runner.py
─────────────────────────────────────────────────────────────────
Public entry point for the Prevention Agent.

    from agents.prevention_agent.runner import run_prevention_agent

    result = await run_prevention_agent(
        scrape_id  = "abc-123",
        session_id = "sess-456",
    )
    # result is a dict matching PreventionResult shape

The runner:
  1. Fetches the scrape metadata from Redis to get url + page_type.
  2. Initialises the LangGraph state.
  3. Runs the prevention_graph.
  4. Stamps duration and returns the aggregated result dict.
"""
from __future__ import annotations
import json
import time
import structlog

from agents.prevention_agent.graph import prevention_graph
from agents.prevention_agent.state import PreventionAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


async def run_prevention_agent(
    scrape_id : str,
    session_id: str,
) -> dict:
    """
    Run the Prevention Agent for a completed scan.

    Args:
        scrape_id  : ID of the scrape (must already exist in Redis).
        session_id : Session ID for cross-page context.

    Returns:
        PreventionResult dict with patch_instructions ready for the
        browser extension content script.
    """
    wall_start = time.perf_counter()
    log        = logger.bind(scrape_id=scrape_id, session_id=session_id)
    log.info("prevention_agent_started")

    # ── Fetch scrape metadata ─────────────────────────────────
    redis = await get_redis_client()
    url       = ""
    page_type = ""
    try:
        raw_scrape = await redis.get(f"dg:scrape:{scrape_id}")
        if raw_scrape:
            scrape_meta = json.loads(raw_scrape)
            url       = scrape_meta.get("url", "")
            page_type = scrape_meta.get("page_type", "")
    except Exception as exc:
        log.warning("runner_scrape_meta_fetch_failed", error=str(exc))

    # ── Build initial state ───────────────────────────────────
    initial_state: PreventionAgentState = {
        "scrape_id"   : scrape_id,
        "session_id"  : session_id,
        "url"         : url,
        "page_type"   : page_type,

        # Populated by preprocess node
        "all_detected_patterns"    : [],
        "pricing_breakdown"        : {},
        "session_cart_data"        : {},
        "behavioral_data"          : {},
        "visual_data"              : {},

        # Populated by dispatch and conflict_resolver nodes
        "raw_patch_instructions"      : [],
        "resolved_patch_instructions" : [],

        # Populated by aggregate node
        "aggregated_result": None,
    }

    # ── Run the graph ─────────────────────────────────────────
    try:
        final_state = await prevention_graph.ainvoke(initial_state)
    except Exception as exc:
        log.error("prevention_graph_error", error=str(exc))
        return {
            "scrape_id"         : scrape_id,
            "session_id"        : session_id,
            "url"               : url,
            "patch_instructions": [],
            "patterns_addressed": [],
            "total_patches"     : 0,
            "prevention_duration_ms": int((time.perf_counter() - wall_start) * 1000),
            "error"             : str(exc),
        }

    # ── Stamp duration and return ─────────────────────────────
    duration_ms = int((time.perf_counter() - wall_start) * 1000)
    result      = final_state.get("aggregated_result") or {}
    result["prevention_duration_ms"] = duration_ms

    log.info(
        "prevention_agent_complete",
        total_patches      =result.get("total_patches", 0),
        patterns_addressed =result.get("patterns_addressed", []),
        duration_ms        =duration_ms,
    )

    return result
