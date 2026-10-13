#!/usr/bin/env sh
# Resolve the LATEST version of every dependency and lock it in uv.lock.
# Package names only - versions are never hardcoded in this template.
# Re-run any time (`make deps`); use `make upgrade` to bump an existing lock.
set -eu

RUNTIME="
langchain
langchain-openai
langgraph
a2a-sdk[http-server]
mcp
starlette
uvicorn[standard]
sse-starlette
pydantic-settings
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-http
opentelemetry-instrumentation-asgi
opentelemetry-instrumentation-logging
openinference-instrumentation-langchain
langfuse
"

DEV="
pytest
pytest-asyncio
httpx
ruff
"

# shellcheck disable=SC2086
uv add --no-sync $RUNTIME
# shellcheck disable=SC2086
uv add --no-sync --dev $DEV
uv sync
