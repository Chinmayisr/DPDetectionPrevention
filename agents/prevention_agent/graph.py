"""
agents/prevention_agent/graph.py
─────────────────────────────────────────────────────────────────
LangGraph StateGraph for the Prevention Agent.

Topology (linear pipeline):
    START → preprocess → dispatch → conflict_resolver → aggregate → END

  preprocess      : fetch all agent results from Redis, merge detected patterns
  dispatch        : route each pattern to its strategy → produce raw patches
  conflict_resolver: merge/deduplicate patches on same selector
  aggregate       : assemble PreventionResult, store in Redis
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.prevention_agent.state             import PreventionAgentState
from agents.prevention_agent.nodes.preprocess  import preprocess_node
from agents.prevention_agent.nodes.dispatch    import dispatch_node
from agents.prevention_agent.nodes.conflict_resolver import conflict_resolver_node
from agents.prevention_agent.nodes.aggregate   import aggregate_node


def build_prevention_graph() -> StateGraph:
    builder = StateGraph(PreventionAgentState)

    builder.add_node("preprocess",        preprocess_node)
    builder.add_node("dispatch",          dispatch_node)
    builder.add_node("conflict_resolver", conflict_resolver_node)
    builder.add_node("aggregate",         aggregate_node)

    builder.add_edge(START,              "preprocess")
    builder.add_edge("preprocess",       "dispatch")
    builder.add_edge("dispatch",         "conflict_resolver")
    builder.add_edge("conflict_resolver","aggregate")
    builder.add_edge("aggregate",        END)

    return builder.compile()


prevention_graph = build_prevention_graph()
