"""End-to-end tests through the HTTP app: A2A, MCP and the dev UI API."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text, new_text_message
from a2a.types import Role, SendMessageRequest
from mcp import Client

from server.app import create_app
from server.config import ServerSettings

BASE = "http://testserver"


@asynccontextmanager
async def running_app(settings: ServerSettings | None = None):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            client.app = app
            yield client


async def test_health():
    async with running_app() as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        assert (await client.get("/readyz")).status_code == 200


async def test_bearer_auth():
    async with running_app(ServerSettings(auth_token="s3cret")) as client:
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/.well-known/agent-card.json")).status_code == 200
        assert (await client.post("/mcp", json={})).status_code == 401
        authed = await client.post("/", json={}, headers={"Authorization": "Bearer s3cret"})
        assert authed.status_code != 401
        card = (await client.get("/.well-known/agent-card.json")).json()
    assert "bearer" in card["securitySchemes"]


async def test_http_instrumentation_wiring():
    from server import telemetry

    app = create_app()
    telemetry.instrument_app(app)  # no exporter configured: uses the no-op provider
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            assert (await client.get("/.well-known/agent-card.json")).status_code == 200


async def test_agent_card():
    async with running_app() as client:
        card = (await client.get("/.well-known/agent-card.json")).json()
    assert card["name"]
    assert card["capabilities"]["streaming"] is True


@pytest.mark.parametrize("streaming", [False, True])
async def test_a2a_send_message(script_llm, streaming):
    script_llm("Hi from the agent")
    async with running_app() as http:
        card_json = (await http.get("/.well-known/agent-card.json")).json()
        card_json["supportedInterfaces"][0]["url"] = BASE + "/"
        a2a = await create_client(
            card_json_to_card(card_json),
            client_config=ClientConfig(streaming=streaming, httpx_client=http),
        )
        request = SendMessageRequest(message=new_text_message("hello", role=Role.ROLE_USER))
        responses = [r async for r in a2a.send_message(request)]

    if not streaming:
        task = next(r.task for r in reversed(responses) if r.HasField("task"))
        assert get_artifact_text(task.artifacts[0]) == "Hi from the agent"
    else:
        updates = [r.artifact_update for r in responses if r.HasField("artifact_update")]
        assert len(updates) > 1  # streamed chunks ...
        assert updates[-1].last_chunk  # ... then the full answer
        assert get_artifact_text(updates[-1].artifact) == "Hi from the agent"


def card_json_to_card(data: dict):
    from a2a.types import AgentCard
    from google.protobuf.json_format import ParseDict

    return ParseDict(data, AgentCard(), ignore_unknown_fields=True)


async def test_mcp_message_tool(script_llm):
    script_llm("MCP reply")
    async with running_app() as http:
        async with Client(http.app.state.mcp_server) as client:
            tools = await client.list_tools()
            assert [t.name for t in tools.tools] == ["message"]
            result = await client.call_tool("message", {"text": "hi", "context_id": "mcp-1"})
    assert result.structured_content == {"response": "MCP reply", "context_id": "mcp-1"}


async def test_dev_ui_run_sse(script_llm):
    script_llm("streamed answer")
    async with running_app() as client:
        assert (await client.get("/dev-ui/")).status_code == 200
        async with client.stream(
            "POST", "/dev/api/run_sse", json={"text": "hi", "context_id": "dev-1"}
        ) as resp:
            body = "".join([chunk async for chunk in resp.aiter_text()])
        events = [
            json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")
        ]
        sessions = (await client.get("/dev/api/sessions")).json()

    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["text"] == "streamed answer"
    assert any(e["type"] == "token" for e in events)
    assert any(s["id"] == "dev-1" for s in sessions)
