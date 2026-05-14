"""
agents/orchestrator_agent/runner.py
─────────────────────────────────────────────────────────────────
Public entry point for the Orchestrator Agent.

Usage:
    report = await run_orchestrator(
        scrape_id="...",
        session_id="...",
        url="https://...",
        page_type="PRODUCT",
    )

The caller is responsible for running the scraper and persisting
data to Redis (via SessionStore.save_scrape) BEFORE calling this.
All four specialist agents read their payloads from Redis by scrape_id.
"""
from __future__ import annotations

import time

import structlog

from agents.orchestrator_agent.graph import orchestrator_graph
from agents.orchestrator_agent.models import OrchestratorReport
from agents.orchestrator_agent.state import OrchestratorState

logger = structlog.get_logger(__name__)


async def run_orchestrator(
    scrape_id:  str,
    session_id: str,
    url:        str,
    page_type:  str,
) -> OrchestratorReport:
    """
    Run the full orchestration pipeline for a scraped page.

    Steps (handled by the graph internally):
      1. Router    — selects which agents to invoke for this page_type
      2. Dispatcher — calls selected agents concurrently
      3. ConfidenceChecker — re-runs low-confidence agents (up to 1 extra pass)
      4. Synthesizer — deduplicates, scores, generates LLM summary

    Args:
        scrape_id  : ID of an already-scraped page stored in Redis
        session_id : Browsing session ID (links cross-page comparisons)
        url        : The URL that was scraped (for reporting only)
        page_type  : Page type string from the scraper
                     (PRODUCT / CART / CHECKOUT / PAYMENT / HOME / OTHER / ...)

    Returns:
        OrchestratorReport — fully populated unified detection report

    Raises:
        RuntimeError: if the graph fails to produce a report
                      (individual agent errors are non-fatal and captured
                       in report.errors)
    """
    start = time.perf_counter()
    log   = logger.bind(scrape_id=scrape_id, session_id=session_id)

    log.info("orchestrator_starting", url=url, page_type=page_type)

    # ── Build initial state ───────────────────────────────────
    initial_state: OrchestratorState = {
        # Input
        "scrape_id":  scrape_id,
        "session_id": session_id,
        "url":        url,
        "page_type":  page_type,

        # Routing (populated by router node)
        "agents_to_invoke": [],
        "agents_invoked":   [],
        "rerun_agents":     [],
        "iteration":        0,

        # Agent results (populated by dispatcher)
        "nlp_result":        None,
        "pricing_result":    None,
        "behavioral_result": None,
        "visual_result":     None,

        # Confidence checker output
        "low_confidence_patterns": [],

        # Final output
        "orchestrator_report": None,

        # Error log
        "errors": [],
    }

    # ── Run the graph ─────────────────────────────────────────
    final_state = await orchestrator_graph.ainvoke(initial_state)

    report: OrchestratorReport | None = final_state.get("orchestrator_report")

    if report is None:
        raise RuntimeError(
            f"Orchestrator graph completed without producing a report. "
            f"scrape_id={scrape_id}. "
            f"Errors: {final_state.get('errors', [])}"
        )

    # Stamp total wall-clock duration
    report.scan_duration_ms = int((time.perf_counter() - start) * 1000)

    log.info(
        "orchestrator_complete",
        total_detected=report.total_detected,
        severity=report.overall_severity_label,
        score=report.overall_severity_score,
        agents=report.agents_invoked,
        iterations=report.iterations_run,
        duration_ms=report.scan_duration_ms,
    )

    return report
