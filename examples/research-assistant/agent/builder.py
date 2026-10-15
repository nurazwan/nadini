"""Compiles the graph from agent/graph.py. You rarely need to touch this."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from agent.graph import graph


def build_agent(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    return graph.compile(checkpointer=checkpointer, name="research-assistant")
