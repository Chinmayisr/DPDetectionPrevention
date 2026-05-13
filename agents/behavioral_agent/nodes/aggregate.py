"""
agents/behavioral_agent/nodes/aggregate.py
Merges all six results, computes severity score, stores to Redis.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import structlog

from agents.shared.models import SinglePatternResult
from agents.behavioral_agent.state import BehavioralAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

_DETECTION_TTL = 1800

_SEVERITY_WEIGHTS = {
    "DP07": 8,    # Basket Sneaking
    "DP08": 7,    # Subscription Trap
    "DP11": 9,    # Rogue/Malicious
    "DP09": 4,    # Nagging
    "DP10": 6,    # SaaS Billing
    "DP13": 8,    # Forced Action  ← NEW
}


async def aggregate_node(state: BehavioralAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"])
    start = time.perf_counter()

    results: list[SinglePatternResult] = []
    for key in (
        "basket_sneaking_result",
        "subscription_trap_result",
        "nagging_result",
        "saas_billing_result",
        "rogue_malicious_result",
        "forced_action_result",      # ← NEW
    ):
        val = state.get(key)
        if val is not None:
            results.append(val)

    total_detected = sum(1 for r in results if r.detected)
    duration_ms    = int((time.perf_counter() - start) * 1000)

    severity_score = 0.0
    detected_results = [r for r in results if r.detected]
    if detected_results:
        weighted_sum = sum(
            _SEVERITY_WEIGHTS.get(
                r.pattern_code if isinstance(r.pattern_code, str)
                else r.pattern_code.value,
                5
            ) * r.confidence
            for r in detected_results
        )
        max_possible = sum(_SEVERITY_WEIGHTS.values())
        severity_score = min(10.0, round((weighted_sum / max_possible) * 10, 2))

    aggregated = {
        "scrape_id":      state["scrape_id"],
        "session_id":     state["session_id"],
        "url":            state.get("current_url", ""),
        "page_type":      state.get("current_page_type", ""),
        "total_detected": total_detected,
        "behavioral_severity_score": severity_score,
        "severity_label": (
            "critical" if severity_score >= 7 else
            "high"     if severity_score >= 5 else
            "medium"   if severity_score >= 3 else
            "low"      if severity_score > 0 else
            "none"
        ),
        "detection_duration_ms": duration_ms,
        "detected_at":    datetime.now(timezone.utc).isoformat(),
        "patterns": [
            {
                "pattern_code": r.pattern_code
                    if isinstance(r.pattern_code, str)
                    else r.pattern_code.value,
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
            f"dg:behavioral-detection:{state['scrape_id']}",
            _DETECTION_TTL,
            json.dumps(aggregated, default=str),
        )
        log.info(
            "behavioral_detection_stored",
            total_detected=total_detected,
            severity=aggregated["severity_label"],
            score=severity_score,
        )
    except Exception as exc:
        log.error("behavioral_aggregate_redis_error", error=str(exc))

    return {"aggregated_result": aggregated}