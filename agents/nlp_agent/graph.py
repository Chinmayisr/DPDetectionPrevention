"""
agents/nlp_agent/graph.py
LangGraph StateGraph for the NLP Agent.
Wires preprocess → parallel fan-out → aggregate.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from agents.nlp_agent.state import NLPAgentState
from agents.nlp_agent.nodes.preprocess      import preprocess_node
from agents.nlp_agent.nodes.false_urgency   import false_urgency_node
from agents.nlp_agent.nodes.confirm_shaming import confirm_shaming_node
from agents.nlp_agent.nodes.disguised_ads   import disguised_ads_node
from agents.nlp_agent.nodes.trick_question  import trick_question_node
from agents.nlp_agent.nodes.aggregate       import aggregate_node


def build_nlp_graph() -> StateGraph:
    """
    Build and compile the NLP Agent StateGraph.

    Graph topology:
        START → preprocess → false_urgency   ──┐
                           → confirm_shaming  ──┤
                           → disguised_ads    ──┤→ aggregate → END
                           → trick_question   ──┘
    """
    builder = StateGraph(NLPAgentState)

    # Register nodes
    builder.add_node("preprocess",      preprocess_node)
    builder.add_node("false_urgency",   false_urgency_node)
    builder.add_node("confirm_shaming", confirm_shaming_node)
    builder.add_node("disguised_ads",   disguised_ads_node)
    builder.add_node("trick_question",  trick_question_node)
    builder.add_node("aggregate",       aggregate_node)

    # Entry edge
    builder.add_edge(START, "preprocess")

    # Fan-out: preprocess → all four detectors in parallel
    builder.add_edge("preprocess", "false_urgency")
    builder.add_edge("preprocess", "confirm_shaming")
    builder.add_edge("preprocess", "disguised_ads")
    builder.add_edge("preprocess", "trick_question")

    # Fan-in: all four → aggregate
    builder.add_edge("false_urgency",   "aggregate")
    builder.add_edge("confirm_shaming", "aggregate")
    builder.add_edge("disguised_ads",   "aggregate")
    builder.add_edge("trick_question",  "aggregate")

    # Exit
    builder.add_edge("aggregate", END)

    return builder.compile()


# Module-level compiled graph — imported by runner.py
nlp_graph = build_nlp_graph()