"""
agents/orchestrator_agent/nodes/dispatcher.py
─────────────────────────────────────────────────────────────────
Dispatcher node — calls selected agents concurrently and writes
their raw results into state.

On the first iteration:   runs all agents in agents_to_invoke
On subsequent iterations: runs only agents in rerun_agents
                          (those flagged as low-confidence by
                           the confidence_checker node)

Each agent failure is isolated — a crashed agent sets its result
key to an error dict and adds to the errors list.  The other
agents are not affected.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from agents.orchestrator_agent.state import OrchestratorState
from agents.nlp_agent.runner import run_nlp_agent
from agents.pricing_agent.runner import run_pricing_agent
from agents.behavioral_agent.runner import run_behavioral_agent
from agents.visual_agent.runner import run_visual_agent
from agents.shared.models import AggregatedDetectionResult

logger = structlog.get_logger(__name__)


# ── Per-agent runner wrappers ─────────────────────────────────
# Each returns (agent_name, result_dict | error_dict, duration_ms)

async def _call_nlp(scrape_id: str, session_id: str) -> tuple[str, dict, int]:
    start = time.perf_counter()
    try:
        result: AggregatedDetectionResult = await run_nlp_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        # Normalise AggregatedDetectionResult → dict matching other agents' shape
        return "nlp", {
            "scrape_id":      result.scrape_id,
            "session_id":     result.session_id,
            "url":            result.url,
            "page_type":      result.page_type,
            "total_detected": result.total_detected,
            "patterns": [
                {
                    "pattern_code": p.code_str(),
                    "pattern_name": p.pattern_name,
                    "detected":     p.detected,
                    "confidence":   p.confidence,
                    "evidence":     [e.model_dump() for e in p.evidence],
                    "error":        p.error,
                }
                for p in result.patterns
            ],
        }, int((time.perf_counter() - start) * 1000)
    except Exception as exc:
        logger.error("dispatcher_nlp_error", error=str(exc), scrape_id=scrape_id)
        return "nlp", {"error": str(exc), "patterns": []}, int((time.perf_counter() - start) * 1000)


async def _call_pricing(scrape_id: str, session_id: str) -> tuple[str, dict, int]:
    start = time.perf_counter()
    try:
        result: dict = await run_pricing_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        return "pricing", result, int((time.perf_counter() - start) * 1000)
    except Exception as exc:
        logger.error("dispatcher_pricing_error", error=str(exc), scrape_id=scrape_id)
        return "pricing", {"error": str(exc), "patterns": []}, int((time.perf_counter() - start) * 1000)


async def _call_behavioral(scrape_id: str, session_id: str) -> tuple[str, dict, int]:
    start = time.perf_counter()
    try:
        result: dict = await run_behavioral_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        return "behavioral", result, int((time.perf_counter() - start) * 1000)
    except Exception as exc:
        logger.error("dispatcher_behavioral_error", error=str(exc), scrape_id=scrape_id)
        return "behavioral", {"error": str(exc), "patterns": []}, int((time.perf_counter() - start) * 1000)


async def _call_visual(scrape_id: str, session_id: str) -> tuple[str, dict, int]:
    start = time.perf_counter()
    try:
        result: dict = await run_visual_agent(
            scrape_id=scrape_id,
            session_id=session_id,
        )
        return "visual", result, int((time.perf_counter() - start) * 1000)
    except Exception as exc:
        logger.error("dispatcher_visual_error", error=str(exc), scrape_id=scrape_id)
        return "visual", {"error": str(exc), "patterns": []}, int((time.perf_counter() - start) * 1000)


_AGENT_CALLERS = {
    "nlp":        _call_nlp,
    "pricing":    _call_pricing,
    "behavioral": _call_behavioral,
    "visual":     _call_visual,
}

_RESULT_KEYS = {
    "nlp":        "nlp_result",
    "pricing":    "pricing_result",
    "behavioral": "behavioral_result",
    "visual":     "visual_result",
}


async def dispatcher_node(state: OrchestratorState) -> dict:
    """
    Run selected agents concurrently and write their results to state.

    First iteration  → runs state["agents_to_invoke"]
    Re-run iteration → runs state["rerun_agents"] only
    """
    scrape_id  = state["scrape_id"]
    session_id = state["session_id"]
    iteration  = state.get("iteration", 0)

    # Decide which agents to run this iteration
    if iteration > 0 and state.get("rerun_agents"):
        agents_this_run = state["rerun_agents"]
        logger.info(
            "dispatcher_rerun",
            scrape_id=scrape_id,
            iteration=iteration,
            agents=agents_this_run,
        )
    else:
        agents_this_run = state["agents_to_invoke"]
        logger.info(
            "dispatcher_first_run",
            scrape_id=scrape_id,
            agents=agents_this_run,
        )

    # Build coroutines for selected agents only
    coros = [
        _AGENT_CALLERS[agent](scrape_id, session_id)
        for agent in agents_this_run
        if agent in _AGENT_CALLERS
    ]

    # Run all concurrently — exceptions are caught inside each wrapper
    outcomes: list[tuple[str, dict, int]] = await asyncio.gather(*coros)

    # Build state update
    updates: dict[str, Any] = {
        "iteration":      iteration + 1,
        "rerun_agents":   [],               # reset — confidence_checker will repopulate
        "agents_invoked": agents_this_run,  # appended via operator.add reducer
        "errors":         [],
    }

    for agent_name, result, duration_ms in outcomes:
        result_key = _RESULT_KEYS[agent_name]
        updates[result_key] = result

        if "error" in result:
            updates["errors"].append(
                f"{agent_name}_agent_failed: {result['error']}"
            )
        else:
            logger.info(
                "agent_complete",
                agent=agent_name,
                detected=result.get("total_detected", 0),
                duration_ms=duration_ms,
                scrape_id=scrape_id,
            )

    return updates
