"""
agents/orchestrator_agent/nodes/router.py
─────────────────────────────────────────────────────────────────
Router node — always invokes all 4 agents regardless of page type.
"""
from __future__ import annotations

import structlog

from agents.orchestrator_agent.state import OrchestratorState

logger = structlog.get_logger(__name__)

_ALL_AGENTS = ["nlp", "pricing", "behavioral", "visual"]


async def router_node(state: OrchestratorState) -> dict:
    """
    Always run all 4 agents on every page.
    """
    logger.info(
        "orchestrator_routing",
        scrape_id=state["scrape_id"],
        page_type=state.get("page_type", "OTHER"),
        agents_selected=_ALL_AGENTS,
    )

    return {
        "agents_to_invoke": _ALL_AGENTS,
        "rerun_agents":     [],
        "iteration":        0,
    }