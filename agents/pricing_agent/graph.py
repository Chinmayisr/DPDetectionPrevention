"""
agents/pricing_agent/graph.py
LangGraph StateGraph for the Pricing Agent.

Topology:
    START → preprocess → drip_pricing  ──┐
                       → bait_switch   ──┘→ aggregate → END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.pricing_agent.state import PricingAgentState
from agents.pricing_agent.nodes.preprocess   import preprocess_node
from agents.pricing_agent.nodes.drip_pricing import drip_pricing_node
from agents.pricing_agent.nodes.bait_switch  import bait_switch_node
from agents.pricing_agent.nodes.aggregate    import aggregate_node


def build_pricing_graph() -> StateGraph:
    builder = StateGraph(PricingAgentState)

    builder.add_node("preprocess",   preprocess_node)
    builder.add_node("drip_pricing", drip_pricing_node)
    builder.add_node("bait_switch",  bait_switch_node)
    builder.add_node("aggregate",    aggregate_node)

    builder.add_edge(START,        "preprocess")
    builder.add_edge("preprocess", "drip_pricing")
    builder.add_edge("preprocess", "bait_switch")
    builder.add_edge("drip_pricing","aggregate")
    builder.add_edge("bait_switch", "aggregate")
    builder.add_edge("aggregate",   END)

    return builder.compile()


pricing_graph = build_pricing_graph()