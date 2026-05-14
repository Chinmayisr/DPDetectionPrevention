"""
agents/orchestrator_agent/nodes/confidence_checker.py
─────────────────────────────────────────────────────────────────
Confidence checker node — inspects all agent results and flags any
detected patterns whose confidence falls in the re-run band
(LOW_CONFIDENCE_THRESHOLD ≤ confidence < RERUN_CONFIDENCE_BAND).

If such patterns exist AND the iteration limit has not been reached,
sets rerun_agents so the dispatcher is called again with only those
specific agents.

This is pure Python logic — no LLM call.
"""
from __future__ import annotations

import structlog

from agents.orchestrator_agent.models import (
    LOW_CONFIDENCE_THRESHOLD,
    MAX_ITERATIONS,
    RERUN_CONFIDENCE_BAND,
)
from agents.orchestrator_agent.state import OrchestratorState

logger = structlog.get_logger(__name__)

# Which result key holds patterns for each agent
_AGENT_RESULT_KEYS = {
    "nlp":        "nlp_result",
    "pricing":    "pricing_result",
    "behavioral": "behavioral_result",
    "visual":     "visual_result",
}


async def confidence_checker_node(state: OrchestratorState) -> dict:
    """
    Scan all agent results for low-confidence detections.

    A pattern is flagged for re-run if:
        detected == True
        AND LOW_CONFIDENCE_THRESHOLD <= confidence < RERUN_CONFIDENCE_BAND

    Patterns below LOW_CONFIDENCE_THRESHOLD are ignored entirely
    (too weak to be worth re-running).

    If re-run candidates exist AND iteration < MAX_ITERATIONS:
        → Sets rerun_agents to the agents that own those patterns
        → Graph routes back to dispatcher

    Otherwise:
        → Sets rerun_agents to []
        → Graph proceeds to synthesizer
    """
    iteration       = state.get("iteration", 1)
    agents_invoked  = set(state.get("agents_to_invoke", []))

    low_confidence_patterns: list[str] = []
    rerun_agents: list[str] = []

    # Only check agents that were actually invoked
    for agent_name, result_key in _AGENT_RESULT_KEYS.items():
        if agent_name not in agents_invoked:
            continue

        result = state.get(result_key)
        if not result or "error" in result:
            continue

        patterns = result.get("patterns", [])
        for p in patterns:
            confidence = p.get("confidence", 0.0)
            detected   = p.get("detected", False)
            code       = p.get("pattern_code", "")

            if (
                detected
                and LOW_CONFIDENCE_THRESHOLD <= confidence < RERUN_CONFIDENCE_BAND
            ):
                low_confidence_patterns.append(code)
                if agent_name not in rerun_agents:
                    rerun_agents.append(agent_name)

    # Respect the iteration cap
    if rerun_agents and iteration >= MAX_ITERATIONS:
        logger.info(
            "confidence_checker_max_iterations_reached",
            iteration=iteration,
            low_confidence_patterns=low_confidence_patterns,
        )
        rerun_agents = []

    if rerun_agents:
        logger.info(
            "confidence_checker_rerun_triggered",
            scrape_id=state["scrape_id"],
            iteration=iteration,
            rerun_agents=rerun_agents,
            low_confidence_patterns=low_confidence_patterns,
        )
    else:
        logger.info(
            "confidence_checker_all_confident",
            scrape_id=state["scrape_id"],
            iteration=iteration,
        )

    return {
        "low_confidence_patterns": low_confidence_patterns,
        "rerun_agents":            rerun_agents,
    }


def should_rerun(state: OrchestratorState) -> str:
    """
    Conditional edge function used by the LangGraph graph.

    Returns:
        "dispatcher" if agents need to be re-run
        "synthesizer" if all results are confident enough
    """
    if state.get("rerun_agents"):
        return "dispatcher"
    return "synthesizer"
