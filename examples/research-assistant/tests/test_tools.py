"""Tests for the example's custom tools and tool-budget guard."""

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent import graph
from agent import main as agent_main
from agent.tools import calculator, search_wikipedia
from tests.conftest import tool_call


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("2 + 3 * 4", "14"), ("(1969 - 1903) * 12", "792"), ("2 ** 10", "1024"), ("-7 // 2", "-4")],
)
def test_calculator(expr, expected):
    assert calculator.invoke({"expression": expr}) == expected


@pytest.mark.parametrize("expr", ["__import__('os')", "1 / 0", "2 ** 1000", "open('x')"])
def test_calculator_rejects_unsafe_or_invalid(expr):
    assert calculator.invoke({"expression": expr}).startswith("Error")


async def test_search_wikipedia_parses_results(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "2": {"index": 2, "title": "B", "fullurl": "https://w/B", "extract": "b"},
                "1": {"index": 1, "title": "A", "fullurl": "https://w/A", "extract": "a"},
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["gsrsearch"] == "apollo"
        return httpx.Response(200, json=payload)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "agent.tools.httpx.AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    results = await search_wikipedia.ainvoke({"query": "apollo"})
    assert [r["title"] for r in results] == ["A", "B"]


async def test_tool_budget_forces_an_answer(script_llm, monkeypatch):
    monkeypatch.setattr(graph, "MAX_TOOL_ROUNDS", 2)
    script_llm(
        tool_call("calculator", {"expression": "1+1"}, "c1"),
        tool_call("calculator", {"expression": "2+2"}, "c2"),
        # Third call is the forced answer; simulate a model that still emits a tool call.
        AIMessage(
            content="Answer after budget.",
            tool_calls=[{"name": "calculator", "args": {"expression": "3+3"}, "id": "c3"}],
        ),
    )
    async with agent_main.lifespan():
        events = [e async for e in agent_main.stream_events("loop forever", "budget")]
        state = await agent_main.get_state("budget")

    assert sum(e["type"] == "tool_call" for e in events) == 2
    assert events[-1]["data"]["text"] == "Answer after budget."
    assert state["values"]["tool_rounds"] == 0
