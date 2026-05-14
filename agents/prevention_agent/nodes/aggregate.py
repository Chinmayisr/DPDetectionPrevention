"""
agents/prevention_agent/nodes/aggregate.py
─────────────────────────────────────────────────────────────────
Aggregate node — assembles the final PreventionResult and stores
it in Redis under key: dg:prevention:{scrape_id}
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timezone
import structlog
from agents.prevention_agent.state import PreventionAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

_PREVENTION_TTL = 1800  # 30 minutes


async def aggregate_node(state: PreventionAgentState) -> dict:
    scrape_id  = state["scrape_id"]
    session_id = state["session_id"]
    log        = logger.bind(scrape_id=scrape_id)

    patches           = state.get("resolved_patch_instructions", [])
    detected_patterns = state.get("all_detected_patterns", [])

    patterns_addressed = list({
        p.get("pattern_code", "")
        for p in patches
        if p.get("pattern_code")
    })

    result = {
        "scrape_id"             : scrape_id,
        "session_id"            : session_id,
        "url"                   : state.get("url", ""),
        "patch_instructions"    : patches,
        "patterns_addressed"    : patterns_addressed,
        "total_patches"         : len(patches),
        "prevention_duration_ms": 0,   # will be overwritten by runner
        "prevented_at"          : datetime.now(timezone.utc).isoformat(),
    }

    # Store in Redis
    try:
        redis = await get_redis_client()
        await redis.setex(
            f"dg:prevention:{scrape_id}",
            _PREVENTION_TTL,
            json.dumps(result, default=str),
        )
        log.info(
            "prevention_stored",
            total_patches      =len(patches),
            patterns_addressed =patterns_addressed,
        )
    except Exception as exc:
        log.error("prevention_aggregate_redis_error", error=str(exc))

    return {"aggregated_result": result}
