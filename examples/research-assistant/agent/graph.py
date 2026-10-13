"""LangGraph agent: an explicit StateGraph you can extend with your own nodes/edges.

Flow: START -> agent --(tool calls?)--> tools -> agent ... -> END

Customised for the example: the state counts tool rounds, and once
MAX_TOOL_ROUNDS is reached the agent must answer with what it has
(a budget guard that the dev UI's State tab makes visible).
"""

from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent import llm
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS

MAX_TOOL_ROUNDS = 4


class State(MessagesState):
    """Graph state. Add your own fields here (they show up in the dev UI State tab)."""

    tool_rounds: int


def build_agent(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    base_model = llm.get_llm()
    model = base_model.bind_tools(TOOLS)

    async def call_model(state: State, config: RunnableConfig) -> dict:
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        rounds = state.get("tool_rounds", 0)
        if rounds >= MAX_TOOL_ROUNDS:
            # Budget spent: answer without tools.
            messages.append(SystemMessage("Tool budget exhausted. Answer now with what you have."))
            response = await base_model.ainvoke(messages, config)
            # Some models emit tool calls even with no tools bound; drop them so the
            # turn really ends here instead of looping back to the tools node.
            answer = AIMessage(
                content=response.text or "I ran out of research steps before finding an answer.",
                id=response.id,
            )
            return {"messages": [answer], "tool_rounds": 0}
        response = await model.ainvoke(messages, config)
        # A final answer resets the budget for the next user turn.
        return {"messages": [response], "tool_rounds": rounds + 1 if response.tool_calls else 0}

    def route(state: State) -> Literal["tools", "__end__"]:
        return "tools" if tools_condition(state) == "tools" else END

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer, name="research-assistant")
