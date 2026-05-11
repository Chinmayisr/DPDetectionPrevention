"""
agents/pricing_agent/nodes/aggregate.py
Merges drip pricing + bait switch results.
Computes financial_impact and stores to Redis.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import structlog

from agents.shared.models import SinglePatternResult
from agents.pricing_agent.state import PricingAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

_DETECTION_TTL = 1800   # 30 minutes


async def aggregate_node(state: PricingAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"])
    start = time.perf_counter()

    results: list[SinglePatternResult] = []
    for key in ("drip_pricing_result", "bait_switch_result"):
        val = state.get(key)
        if val is not None:
            results.append(val)

    total_detected = sum(1 for r in results if r.detected)
    duration_ms = int((time.perf_counter() - start) * 1000)

    # ── Financial impact calculation ──────────────────────────
    drip_signals  = state.get("drip_pricing_signals", {})
    bait_signals  = state.get("bait_switch_signals", {})

    drip_impact = drip_signals.get("total_hidden_amount", 0.0)
    bait_impact = bait_signals.get("total_overcharge", 0.0)
    total_financial_impact = round(drip_impact + bait_impact, 2)

    aggregated = {
        "scrape_id":       state["scrape_id"],
        "session_id":      state["session_id"],
        "url":             state.get("current_url", ""),
        "page_type":       state.get("current_page_type", ""),
        "total_detected":  total_detected,
        "detection_duration_ms": duration_ms,
        "detected_at":     datetime.now(timezone.utc).isoformat(),
        "financial_impact": {
            "drip_pricing_hidden_amount": round(drip_impact, 2),
            "bait_switch_overcharge":     round(bait_impact, 2),
            "total_extra_charged":        total_financial_impact,
        },
        "patterns": [
            {
                "pattern_code": r.pattern_code
                    if isinstance(r.pattern_code, str)
                    else r.pattern_code.value,
                "pattern_name": r.pattern_name,
                "detected":     r.detected,
                "confidence":   r.confidence,
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

    # ── Store to Redis ────────────────────────────────────────
    try:
        redis = await get_redis_client()
        await redis.setex(
            f"dg:pricing-detection:{state['scrape_id']}",
            _DETECTION_TTL,
            json.dumps(aggregated, default=str),
        )
        log.info(
            "pricing_detection_stored",
            total_detected=total_detected,
            financial_impact=total_financial_impact,
        )
    except Exception as exc:
        log.error("pricing_aggregate_redis_error", error=str(exc))

    return {"aggregated_result": aggregated}