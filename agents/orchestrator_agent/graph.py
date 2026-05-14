"""
agents/orchestrator_agent/graph.py
─────────────────────────────────────────────────────────────────
LangGraph StateGraph for the Orchestrator Agent.

Graph topology:

    START
      │
      ▼
    router          ← decides which agents to invoke (pure Python)
      │
      ▼
    dispatcher      ← calls selected agents concurrently (asyncio.gather)
      │
      ▼
    confidence_checker ── rerun_agents non-empty? ──→ dispatcher
      │                                               (max 2 total iterations)
      │  rerun_agents empty
      ▼
    synthesizer     ← deduplicates, scores, calls GPT-4o for summary
      │
      ▼
    END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.orchestrator_agent.nodes.confidence_checker import (
    confidence_checker_node,
    should_rerun,
)
from agents.orchestrator_agent.nodes.dispatcher import dispatcher_node
from agents.orchestrator_agent.nodes.router import router_node
from agents.orchestrator_agent.nodes.synthesizer import synthesizer_node
from agents.orchestrator_agent.state import OrchestratorState


def build_orchestrator_graph() -> StateGraph:
    """
    Build and compile the Orchestrator Agent StateGraph.
    """
    builder = StateGraph(OrchestratorState)

    # ── Register nodes ────────────────────────────────────────
    builder.add_node("router",             router_node)
    builder.add_node("dispatcher",         dispatcher_node)
    builder.add_node("confidence_checker", confidence_checker_node)
    builder.add_node("synthesizer",        synthesizer_node)

    # ── Fixed edges ───────────────────────────────────────────
    builder.add_edge(START,        "router")
    builder.add_edge("router",     "dispatcher")
    builder.add_edge("dispatcher", "confidence_checker")
    builder.add_edge("synthesizer", END)

    # ── Conditional edge: confidence_checker → dispatcher | synthesizer
    # should_rerun() returns "dispatcher" if rerun_agents is non-empty,
    # "synthesizer" otherwise.
    builder.add_conditional_edges(
        "confidence_checker",
        should_rerun,
        {
            "dispatcher":  "dispatcher",
            "synthesizer": "synthesizer",
        },
    )

    return builder.compile()


# Module-level compiled graph — imported by runner.py
orchestrator_graph = build_orchestrator_graph()
