"""
agents/behavioral_agent/graph.py

Topology:
    START → preprocess → basket_sneaking    ──┐
                       → subscription_trap  ──┤
                       → nagging            ──┤→ aggregate → END
                       → saas_billing       ──┤
                       → rogue_malicious    ──┘
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.behavioral_agent.state import BehavioralAgentState
from agents.behavioral_agent.nodes.preprocess        import preprocess_node
from agents.behavioral_agent.nodes.basket_sneaking   import basket_sneaking_node
from agents.behavioral_agent.nodes.subscription_trap import subscription_trap_node
from agents.behavioral_agent.nodes.nagging           import nagging_node
from agents.behavioral_agent.nodes.saas_billing      import saas_billing_node
from agents.behavioral_agent.nodes.rogue_malicious   import rogue_malicious_node
from agents.behavioral_agent.nodes.aggregate         import aggregate_node


def build_behavioral_graph() -> StateGraph:
    builder = StateGraph(BehavioralAgentState)

    builder.add_node("preprocess",        preprocess_node)
    builder.add_node("basket_sneaking",   basket_sneaking_node)
    builder.add_node("subscription_trap", subscription_trap_node)
    builder.add_node("nagging",           nagging_node)
    builder.add_node("saas_billing",      saas_billing_node)
    builder.add_node("rogue_malicious",   rogue_malicious_node)
    builder.add_node("aggregate",         aggregate_node)

    builder.add_edge(START, "preprocess")

    for node in (
        "basket_sneaking",
        "subscription_trap",
        "nagging",
        "saas_billing",
        "rogue_malicious",
    ):
        builder.add_edge("preprocess", node)
        builder.add_edge(node, "aggregate")

    builder.add_edge("aggregate", END)
    return builder.compile()


behavioral_graph = build_behavioral_graph()