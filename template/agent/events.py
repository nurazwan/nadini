"""Translate LangChain/LangGraph `astream_events` into a small, stable event schema.

Every consumer (A2A streaming, dev UI, MCP) reads these events, so they never
drift apart. Event types:

    node_start / node_end   a LangGraph node began / finished
    llm_start / llm_end     a chat model call (llm_end carries usage + tool calls)
    token                   streamed text from a chat model
    tool_call / tool_result a tool invocation and its output
    final                   the turn's final answer (always last on success)
    error                   the turn failed
"""

import time
from typing import Any, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

EventType = Literal[
    "node_start",
    "node_end",
    "llm_start",
    "llm_end",
    "token",
    "tool_call",
    "tool_result",
    "final",
    "error",
]


class AgentEvent(TypedDict):
    type: EventType
    ts: float
    name: NotRequired[str]
    node: NotRequired[str]
    run_id: NotRequired[str]
    data: NotRequired[Any]


def make_event(type_: EventType, **fields: Any) -> AgentEvent:
    present = {k: v for k, v in fields.items() if v is not None}
    return AgentEvent(type=type_, ts=time.time(), **present)


def to_jsonable(value: Any) -> Any:
    """Best-effort conversion of LangChain objects into JSON-friendly data."""
    if isinstance(value, BaseMessage):
        out: dict[str, Any] = {"role": value.type, "content": value.text}
        for attr in ("tool_calls", "tool_call_id", "name", "usage_metadata"):
            if v := getattr(value, attr, None):
                out[attr] = to_jsonable(v)
        return out
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(v) for v in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def convert(raw: dict[str, Any]) -> AgentEvent | None:
    """Map one `astream_events(version="v2")` event to an AgentEvent (or None to skip)."""
    kind = raw["event"]
    name = raw.get("name")
    meta = raw.get("metadata") or {}
    node = meta.get("langgraph_node")
    data = raw.get("data") or {}
    run_id = str(raw.get("run_id")) if raw.get("run_id") else None

    match kind:
        case "on_chat_model_stream":
            chunk = data.get("chunk")
            text = chunk.text if chunk is not None else ""
            return make_event("token", node=node, data=text) if text else None
        case "on_chat_model_start":
            return make_event(
                "llm_start",
                name=name,
                node=node,
                run_id=run_id,
                data={"model": meta.get("ls_model_name")},
            )
        case "on_chat_model_end":
            output = data.get("output")
            return make_event(
                "llm_end",
                name=name,
                node=node,
                run_id=run_id,
                data={
                    "usage": to_jsonable(getattr(output, "usage_metadata", None)),
                    "tool_calls": to_jsonable(getattr(output, "tool_calls", None)),
                },
            )
        case "on_tool_start":
            return make_event(
                "tool_call",
                name=name,
                node=node,
                run_id=run_id,
                data=to_jsonable(data.get("input")),
            )
        case "on_tool_end":
            return make_event(
                "tool_result",
                name=name,
                node=node,
                run_id=run_id,
                data=to_jsonable(data.get("output")),
            )
        case "on_chain_start" | "on_chain_end" if node and name == node:
            type_ = "node_start" if kind == "on_chain_start" else "node_end"
            return make_event(type_, name=name, node=node, run_id=run_id)
    return None
