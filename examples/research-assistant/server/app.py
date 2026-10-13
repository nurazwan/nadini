"""ASGI app: A2A (JSON-RPC at /, card at /.well-known/agent-card.json), MCP (/mcp),
health probes and the dev UI (/dev-ui).

Run:  uvicorn server.app:app --host 127.0.0.1 --port 8000
"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agent import main as agent_main
from server import telemetry
from server.a2a_app import build_routes as build_a2a_routes
from server.auth import BearerAuthMiddleware
from server.config import ServerSettings, get_settings
from server.devui.routes import build_routes as build_devui_routes
from server.mcp_app import build_mcp


async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_: Request) -> JSONResponse:
    ready = agent_main.is_ready()
    return JSONResponse({"ready": ready}, status_code=200 if ready else 503)


def create_app(settings: ServerSettings | None = None) -> Starlette:
    settings = settings or get_settings()
    telemetry.setup(settings)
    mcp_server, mcp_app = build_mcp(settings)

    @asynccontextmanager
    async def lifespan(_: Starlette):
        async with agent_main.lifespan(), mcp_server.session_manager.run():
            yield
        telemetry.shutdown()

    routes = [
        Route("/healthz", healthz),
        Route("/readyz", readyz),
        *mcp_app.routes,
    ]
    if settings.dev_ui_enabled:
        routes += build_devui_routes(settings)
    routes += build_a2a_routes(settings)  # JSON-RPC is mounted at "/" so keep it last

    token = settings.auth_token.get_secret_value() if settings.auth_token else None
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        middleware=[Middleware(BearerAuthMiddleware, token=token)],
    )
    app.state.mcp_server = mcp_server

    if settings.otel_enabled:
        telemetry.instrument_app(app)
    return app


app = create_app()
