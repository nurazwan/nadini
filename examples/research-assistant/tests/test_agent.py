"""Tests for the agent contract in agent/main.py."""

from agent import main as agent_main
from tests.conftest import tool_call


async def test_message_returns_reply(script_llm):
    script_llm("Hello there!")
    async with agent_main.lifespan():
        assert await agent_main.message("hi", "ctx-1") == "Hello there!"


async def test_stream_events_reports_tool_calls(script_llm):
    script_llm(tool_call("get_current_time", {"timezone": "UTC"}), "It is noon.")
    async with agent_main.lifespan():
        events = [e async for e in agent_main.stream_events("what time is it?", "ctx-2")]

    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    assert types[-1] == "final"
    assert events[-1]["data"] == {"text": "It is noon.", "context_id": "ctx-2"}
    tool_event = next(e for e in events if e["type"] == "tool_call")
    assert tool_event["name"] == "get_current_time"


async def test_memory_is_shared_within_a_context(script_llm):
    script_llm("first", "second")
    async with agent_main.lifespan():
        await agent_main.message("one", "ctx-3")
        await agent_main.message("two", "ctx-3")
        state = await agent_main.get_state("ctx-3")
        sessions = await agent_main.list_sessions()

    contents = [m["content"] for m in state["values"]["messages"]]
    assert contents == ["one", "first", "two", "second"]
    assert any(s["id"] == "ctx-3" for s in sessions)


async def test_graph_mermaid(script_llm):
    script_llm("x")
    async with agent_main.lifespan():
        assert "graph" in agent_main.graph_mermaid().lower()
