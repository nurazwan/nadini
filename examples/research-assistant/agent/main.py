"""Agent entrypoint - the ONLY module the server talks to.

Contract (keep these signatures; change anything behind them):

    message(text, context_id)        -> str                    one-shot reply
    stream_message(text, context_id) -> AsyncIterator[str]     reply tokens
    stream_events(text, context_id)  -> AsyncIterator[AgentEvent]  everything
                                        (nodes, LLM calls, tools, tokens, final)
    lifespan()                       async context manager run at server start

`context_id` is the conversation id (A2A contextId / MCP context_id / dev UI
session). Turns with the same id share memory.

Dev UI helpers: get_state, list_sessions, delete_session, graph_mermaid.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from agent.builder import build_agent
from agent.events import AgentEvent, convert, make_event, to_jsonable
from agent.memory import open_checkpointer
from agent.settings import get_settings

_agent: CompiledStateGraph | None = None
_checkpointer: BaseCheckpointSaver | None = None


@asynccontextmanager
async def lifespan() -> AsyncIterator[None]:
    """Build the agent once per process (and open/close its memory backend)."""
    global _agent, _checkpointer
    async with open_checkpointer() as checkpointer:
        _checkpointer = checkpointer
        _agent = build_agent(checkpointer)
        try:
            yield
        finally:
            _agent = _checkpointer = None


def is_ready() -> bool:
    return _agent is not None


def _get_agent() -> CompiledStateGraph:
    if _agent is None:
        raise RuntimeError("Agent not started - use `async with agent.main.lifespan():`")
    return _agent


def _config(context_id: str) -> RunnableConfig:
    return {
        "configurable": {"thread_id": context_id},
        "run_name": get_settings().agent_name,
        # `session_id` groups the conversation in Langfuse / OpenInference traces.
        "metadata": {"session_id": context_id},
    }


async def stream_events(text: str, context_id: str | None = None) -> AsyncIterator[AgentEvent]:
    """Run one turn and yield AgentEvents, ending with `final` (or `error`)."""
    agent = _get_agent()
    context_id = context_id or uuid.uuid4().hex
    config = _config(context_id)
    try:
        async for raw in agent.astream_events(
            {"messages": [{"role": "user", "content": text}]}, config, version="v2"
        ):
            if event := convert(raw):
                yield event
        state = await agent.aget_state(config)
        messages = state.values.get("messages", [])
        answer = messages[-1].text if messages else ""
        yield make_event("final", data={"text": answer, "context_id": context_id})
    except Exception as exc:
        yield make_event("error", data={"message": str(exc), "type": type(exc).__name__})
        raise


async def stream_message(text: str, context_id: str | None = None) -> AsyncIterator[str]:
    """Yield only the streamed answer text."""
    async for event in stream_events(text, context_id):
        if event["type"] == "token":
            yield event["data"]


async def message(text: str, context_id: str | None = None) -> str:
    """Run one turn and return the final answer."""
    async for event in stream_events(text, context_id):
        if event["type"] == "final":
            return event["data"]["text"]
    return ""


# --------------------------------------------------------------------------- #
# Introspection (used by the dev UI)
# --------------------------------------------------------------------------- #
async def get_state(context_id: str) -> dict[str, Any]:
    state = await _get_agent().aget_state(_config(context_id))
    return {
        "values": to_jsonable(state.values),
        "next": list(state.next),
        "created_at": state.created_at,
        "checkpoint_id": (state.config or {}).get("configurable", {}).get("checkpoint_id"),
    }


async def list_sessions(limit: int = 200) -> list[dict[str, Any]]:
    """Distinct conversations known to the checkpointer, newest first."""
    if _checkpointer is None:
        return []
    seen: dict[str, dict[str, Any]] = {}
    async for item in _checkpointer.alist(None, limit=limit * 20):
        thread_id = item.config["configurable"]["thread_id"]
        if thread_id not in seen:
            seen[thread_id] = {"id": thread_id, "updated_at": item.checkpoint.get("ts")}
        if len(seen) >= limit:
            break
    return sorted(seen.values(), key=lambda s: s["updated_at"] or "", reverse=True)


async def delete_session(context_id: str) -> None:
    if _checkpointer is not None:
        await _checkpointer.adelete_thread(context_id)


def graph_mermaid() -> str:
    return _get_agent().get_graph().draw_mermaid()
