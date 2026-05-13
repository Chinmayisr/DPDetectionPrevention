"""
agents/visual_agent/graph.py

Topology:
    START → preprocess → disguised_ads           ──┐
                       → interface_interference  ──┘→ aggregate → END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.visual_agent.state import VisualAgentState
from agents.visual_agent.nodes.preprocess              import preprocess_node
from agents.visual_agent.nodes.disguised_ads           import disguised_ads_node
from agents.visual_agent.nodes.interface_interference  import interface_interference_node
from agents.visual_agent.nodes.aggregate               import aggregate_node


def build_visual_graph() -> StateGraph:
    builder = StateGraph(VisualAgentState)

    builder.add_node("preprocess",              preprocess_node)
    builder.add_node("disguised_ads",           disguised_ads_node)
    builder.add_node("interface_interference",  interface_interference_node)
    builder.add_node("aggregate",               aggregate_node)

    builder.add_edge(START,         "preprocess")
    builder.add_edge("preprocess",  "disguised_ads")
    builder.add_edge("preprocess",  "interface_interference")
    builder.add_edge("disguised_ads",          "aggregate")
    builder.add_edge("interface_interference", "aggregate")
    builder.add_edge("aggregate",   END)

    return builder.compile()


visual_graph = build_visual_graph()