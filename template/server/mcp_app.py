"""MCP adapter: exposes `agent.main.message` as an MCP tool over streamable HTTP (/mcp)."""

import uuid

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.applications import Starlette

from agent import main as agent_main
from agent.settings import get_settings as get_agent_settings
from server.config import ServerSettings


class MessageResult(BaseModel):
    response: str = Field(description="The agent's reply")
    context_id: str = Field(description="Pass back as `context_id` to continue this conversation")


def build_mcp(settings: ServerSettings) -> tuple[MCPServer, Starlette]:
    server = MCPServer(
        name=get_agent_settings().agent_name,
        description=settings.agent_description,
        version=settings.agent_version,
        instructions="Call the `message` tool to talk to this agent. Reuse the returned "
        "context_id to continue a conversation.",
    )

    @server.tool(description=f"Send a message to the agent. {settings.agent_description}")
    async def message(text: str, context_id: str | None = None) -> MessageResult:
        context_id = context_id or uuid.uuid4().hex
        reply = await agent_main.message(text, context_id)
        return MessageResult(response=reply, context_id=context_id)

    security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=settings.mcp_allowed_hosts
        )
        if settings.mcp_allowed_hosts
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp", transport_security=security, host=settings.host
    )
    return server, app
