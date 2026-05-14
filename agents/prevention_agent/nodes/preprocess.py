"""
agents/prevention_agent/nodes/preprocess.py
─────────────────────────────────────────────────────────────────
Preprocess node — fetches all agent results from Redis and populates:
  - all_detected_patterns   (merged from NLP, Pricing, Behavioral, Visual)
  - pricing_breakdown       (from pricing agent aggregated result)
  - session_cart_data       (from behavioral agent cart events)
  - behavioral_data         (subscription_flow, billing_data, popup_events)
  - visual_data             (visual agent result for DP12)
"""
from __future__ import annotations
import json
import structlog
from agents.prevention_agent.state import PreventionAgentState
from backend.cache.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

# Redis key templates (must match the storage keys used by each agent)
_NLP_KEY        = "dg:detection:{scrape_id}"
_PRICING_KEY    = "dg:pricing-detection:{scrape_id}"
_BEHAVIORAL_KEY = "dg:behavioral-detection:{scrape_id}"
_VISUAL_KEY     = "dg:visual-detection:{scrape_id}"
_SCRAPE_KEY     = "dg:scrape:{scrape_id}"


async def _fetch_json(redis, key: str) -> dict:
    try:
        raw = await redis.get(key)
        return json.loads(raw) if raw else {}
    except Exception as exc:
        logger.warning("preprocess_redis_fetch_error", key=key, error=str(exc))
        return {}


async def preprocess_node(state: PreventionAgentState) -> dict:
    scrape_id  = state["scrape_id"]
    session_id = state["session_id"]
    log        = logger.bind(scrape_id=scrape_id)

    redis = await get_redis_client()

    # ── Fetch all agent results ───────────────────────────────
    nlp_result        = await _fetch_json(redis, _NLP_KEY.format(scrape_id=scrape_id))
    pricing_result    = await _fetch_json(redis, _PRICING_KEY.format(scrape_id=scrape_id))
    behavioral_result = await _fetch_json(redis, _BEHAVIORAL_KEY.format(scrape_id=scrape_id))
    visual_result     = await _fetch_json(redis, _VISUAL_KEY.format(scrape_id=scrape_id))

    # ── Merge all detected patterns ───────────────────────────
    all_detected: list[dict] = []

    for source_result in (nlp_result, pricing_result, behavioral_result, visual_result):
        for pattern in source_result.get("patterns", []):
            if pattern.get("detected"):
                all_detected.append(pattern)

    # ── Extract enrichment data ───────────────────────────────
    pricing_breakdown = {
        "base_price"         : pricing_result.get("base_price", ""),
        "total_price"        : pricing_result.get("total_price", ""),
        "fee_breakdown"      : pricing_result.get("fee_breakdown", []),
        "currency_symbol"    : pricing_result.get("currency_symbol", "₹"),
        "baseline_price"     : pricing_result.get("baseline_price", ""),
        "current_price"      : pricing_result.get("current_price", ""),
        "baseline_url"       : pricing_result.get("baseline_url", ""),
        "baseline_product_name": pricing_result.get("baseline_product_name", ""),
        "financial_impact"   : pricing_result.get("financial_impact", {}),
    }

    session_cart_data = {
        "sneaked_items": behavioral_result.get("sneaked_items", []),
        "cart_events"  : behavioral_result.get("cart_events", []),
    }

    behavioral_data = {
        "subscription_flow": behavioral_result.get("subscription_flow", {}),
        "billing_data"     : behavioral_result.get("billing_data", {}),
        "popup_events"     : behavioral_result.get("popup_events", []),
    }

    log.info(
        "prevention_preprocess_done",
        total_detected=len(all_detected),
        pattern_codes=[p.get("pattern_code") for p in all_detected],
    )

    return {
        "all_detected_patterns": all_detected,
        "pricing_breakdown"    : pricing_breakdown,
        "session_cart_data"    : session_cart_data,
        "behavioral_data"      : behavioral_data,
        "visual_data"          : visual_result,
    }
