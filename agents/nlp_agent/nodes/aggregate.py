"""
agents/nlp_agent/nodes/aggregate.py
Merges all four detection results and stores to Redis.
"""
from __future__ import annotations

import json
import time

import structlog

from agents.shared.models import AggregatedDetectionResult, SinglePatternResult
from agents.nlp_agent.state import NLPAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

_DETECTION_TTL = 1800  # 30 minutes


async def aggregate_node(state: NLPAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"])
    start = time.perf_counter()

    results: list[SinglePatternResult] = []
    for key in (
        "false_urgency_result",
        "confirm_shaming_result",
        "disguised_ads_result",
        "trick_question_result",
    ):
        val = state.get(key)
        if val is not None:
            results.append(val)

    total_detected = sum(1 for r in results if r.detected)
    duration_ms = int((time.perf_counter() - start) * 1000)

    aggregated = AggregatedDetectionResult(
        scrape_id=state["scrape_id"],
        session_id=state["session_id"],
        url=state["url"],
        page_type=state["page_type"],
        patterns=results,
        total_detected=total_detected,
        detection_duration_ms=duration_ms,
    )

    # Store result in Redis
    try:
        redis = await get_redis_client()
        await redis.setex(
            f"dg:detection:{state['scrape_id']}",
            _DETECTION_TTL,
            aggregated.model_dump_json(),
        )
        log.info(
            "detection_stored",
            total_detected=total_detected,
            patterns=[r.pattern_code for r in results if r.detected],
        )
    except Exception as exc:
        log.error("aggregate_redis_error", error=str(exc))

    return {"aggregated_result": aggregated}