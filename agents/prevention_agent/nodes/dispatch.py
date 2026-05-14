"""
agents/prevention_agent/nodes/dispatch.py
─────────────────────────────────────────────────────────────────
Dispatch node — routes each detected pattern to its strategy handler.

For every detected pattern in all_detected_patterns:
  1. Look up the strategy in STRATEGY_REGISTRY.
  2. Build the enrichment bundle for that pattern.
  3. Call strategy.build_patches(evidence, enrichment).
  4. Collect all raw patch dicts into raw_patch_instructions.
"""
from __future__ import annotations
import structlog
from agents.prevention_agent.state import PreventionAgentState
from agents.prevention_agent.strategy_registry import STRATEGY_REGISTRY

logger = structlog.get_logger(__name__)


def _build_enrichment(pattern_code: str, state: PreventionAgentState) -> dict:
    """
    Assemble the enrichment dict relevant to a specific pattern code.
    Strategies only need a subset of the total enrichment data.
    """
    return {
        "pricing_breakdown": state.get("pricing_breakdown", {}),
        "session_cart_data": state.get("session_cart_data", {}),
        "behavioral_data"  : state.get("behavioral_data", {}),
        "visual_data"      : state.get("visual_data", {}),
    }


async def dispatch_node(state: PreventionAgentState) -> dict:
    log = logger.bind(scrape_id=state["scrape_id"])
    raw_patches: list[dict] = []

    for pattern in state.get("all_detected_patterns", []):
        code     = pattern.get("pattern_code", "")
        evidence = pattern.get("evidence", [])

        # Attach confidence to each evidence item for strategies that branch on it
        for ev in evidence:
            ev.setdefault("confidence", pattern.get("confidence", 0.7))

        strategy = STRATEGY_REGISTRY.get(code)
        if not strategy:
            log.warning("no_strategy_for_pattern", pattern_code=code)
            continue

        try:
            enrichment = _build_enrichment(code, state)
            patches    = await strategy.build_patches(evidence, enrichment)
            raw_patches.extend(patches)
            log.info("strategy_dispatched", pattern_code=code, patches_built=len(patches))
        except Exception as exc:
            log.error("strategy_dispatch_error", pattern_code=code, error=str(exc))

    return {"raw_patch_instructions": raw_patches}
