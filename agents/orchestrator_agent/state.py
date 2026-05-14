"""
agents/orchestrator_agent/state.py
─────────────────────────────────────────────────────────────────
LangGraph state schema for the Orchestrator Agent.

State flows through:
    router → dispatcher → confidence_checker → (dispatcher loop) → synthesizer
"""
from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict

from agents.orchestrator_agent.models import OrchestratorReport


def _last_write_wins(existing, new):
    """Reducer: later write wins. Used for fields updated by a single node."""
    return new if new is not None else existing


class OrchestratorState(TypedDict):

    # ── Input — set once at graph entry ───────────────────────
    scrape_id:  str
    session_id: str
    url:        str
    page_type:  str

    # ── Routing — set by router node ──────────────────────────
    # Which agents the router decided to invoke for this page type
    agents_to_invoke: list[str]

    # ── Dispatcher control ────────────────────────────────────
    # Accumulates across iterations (operator.add = list concatenation)
    agents_invoked: Annotated[list[str], operator.add]

    # Which agents to re-run in the next iteration (set by confidence_checker)
    # Empty on first pass — dispatcher runs agents_to_invoke
    # Non-empty on re-run — dispatcher runs only these
    rerun_agents: list[str]

    # How many times the dispatcher has been called
    iteration: int

    # ── Raw agent results — each set by dispatcher ────────────
    # Using last-write-wins reducers so re-runs overwrite prior results
    nlp_result:        Annotated[dict | None, _last_write_wins]
    pricing_result:    Annotated[dict | None, _last_write_wins]
    behavioral_result: Annotated[dict | None, _last_write_wins]
    visual_result:     Annotated[dict | None, _last_write_wins]

    # ── Confidence checker output ─────────────────────────────
    # Patterns flagged as low confidence (code strings e.g. "DP01")
    low_confidence_patterns: list[str]

    # ── Final output — set by synthesizer ─────────────────────
    orchestrator_report: OrchestratorReport | None

    # ── Error log — non-fatal errors appended by any node ─────
    errors: Annotated[list[str], operator.add]
