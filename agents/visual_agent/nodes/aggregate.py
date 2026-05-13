"""
agents/visual_agent/nodes/aggregate.py
Merges visual detection results and stores to Redis.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import structlog

from agents.shared.models import SinglePatternResult
from agents.visual_agent.state import VisualAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

_DETECTION_TTL = 1800   # 30 minutes


async def aggregate_node(state: VisualAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"])
    start = time.perf_counter()

    results: list[SinglePatternResult] = []
    for key in ("disguised_ads_result", "interface_interference_result"):
        val = state.get(key)
        if val is not None:
            results.append(val)

    total_detected = sum(1 for r in results if r.detected)
    duration_ms    = int((time.perf_counter() - start) * 1000)

    aggregated = {
        "scrape_id":      state["scrape_id"],
        "session_id":     state["session_id"],
        "url":            state.get("url", ""),
        "page_type":      state.get("page_type", ""),
        "total_detected": total_detected,
        "detection_duration_ms": duration_ms,
        "detected_at":    datetime.now(timezone.utc).isoformat(),
        "detection_method": "gpt4o_vision",
        "patterns": [
            {
                "pattern_code": r.code_str(),
                "pattern_name": r.pattern_name,
                "detected":     r.detected,
                "confidence":   round(r.confidence, 3),
                "evidence": [
                    {
                        "text":     e.text,
                        "location": e.location,
                        "reason":   e.reason,
                    }
                    for e in r.evidence
                ],
                "error": r.error,
            }
            for r in results
        ],
    }

    try:
        redis = await get_redis_client()
        await redis.setex(
            f"dg:visual-detection:{state['scrape_id']}",
            _DETECTION_TTL,
            json.dumps(aggregated, default=str),
        )
        log.info(
            "visual_detection_stored",
            total_detected=total_detected,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        log.error("visual_aggregate_redis_error", error=str(exc))

    return {"aggregated_result": aggregated}