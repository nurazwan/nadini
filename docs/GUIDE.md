# Nadini — Usage Guide

Nadini generates a production-ready agent service:

```
            ┌──────────────── your agent (agent/) ────────────────┐
 A2A  ──►   │                                                      │
 MCP  ──►   │  agent/main.py  ─►  LangGraph / LangChain  ─►  LLM   │ ─► OTLP ─► Grafana
 Dev UI ─►  │   message / stream_events        tools, memory       │ ─► Langfuse
            └──────────────────────────────────────────────────────┘
```

All three front doors (A2A, MCP, dev UI) call **one** function contract in
`agent/main.py`, so they always behave the same.

- [1. Prerequisites](#1-prerequisites)
- [2. Generate a project](#2-generate-a-project)
- [3. Project tour](#3-project-tour)
- [4. Customise the agent](#4-customise-the-agent)
- [5. Run locally and use the dev UI](#5-run-locally-and-use-the-dev-ui)
- [6. Call the agent (A2A, MCP, other agents)](#6-call-the-agent)
- [7. Observability (Grafana, Langfuse)](#7-observability)
- [8. Build and deploy](#8-build-and-deploy)
- [9. Keep it up to date](#9-keep-it-up-to-date)
- [10. Troubleshooting](#10-troubleshooting)
- [Configuration reference](#configuration-reference)

---

## 1. Prerequisites

| Tool | Why |
| --- | --- |
| [uv](https://docs.astral.sh/uv/) | Runs Copier and manages the generated project |
| Docker | Image builds and the local Grafana stack (optional for development) |
| An OpenAI API key **or** any OpenAI-compatible endpoint | Ollama, vLLM, LiteLLM, Azure OpenAI, ... via `OPENAI_BASE_URL` |

Network access is needed at generation time, because dependency versions are resolved then.

## 2. Generate a project

```bash
uvx copier copy --trust gh:nurazwan/nadini my-agent
# or from a local checkout:
uvx copier copy --trust ./nadini my-agent
```

`--trust` lets the template run its post-generation tasks (`uv add ...` and `git init`).

You'll be asked:

| Question | Choices | Effect |
| --- | --- | --- |
| `project_name` | free text | Agent name in the A2A card, MCP server info and traces |
| `project_slug` | derived | Package, image and service name |
| `description` | free text | Agent card / MCP tool description and system prompt |
| `framework` | `langgraph` / `langchain` | `agent/graph.py` (explicit `StateGraph`) or `agent/chain.py` (`create_agent`) |
| `checkpointer` | `memory` / `postgres` | Conversation memory backend. `postgres` adds a Postgres service to compose |
| `enable_langfuse` | yes / no | Adds the `langfuse` SDK, attached to the same OTel pipeline |
| `enable_devui` | yes / no | Adds the ADK-style chat UI at `/dev-ui` |
| `enable_auth` | yes / no | Sets `AUTH_TOKEN` in `.env.example` (the bearer middleware is always present) |
| `python_version` | e.g. `3.14` | `requires-python`, `.python-version` and the Docker base image |
| `port` | e.g. `8000` | Listening port |
| `bind_host` | `127.0.0.1` / `0.0.0.0` | Address `make dev` / `make run` listen on, and the address compose publishes ports on. The container itself always listens on `0.0.0.0` |
| `ci` | `none` / `test` / `dockerhub` | GitHub Actions: nothing; lint + test + docker build; or lint + test + multi-arch build and push to Docker Hub |
| `dockerhub_image` | e.g. `me/my-agent` | Docker Hub repository (asked when `ci=dockerhub`) |
| `docker_builder` | `runner` / `cloud` | Build amd64 + arm64 on the GitHub runner (QEMU) or on Docker Build Cloud (asked when `ci=dockerhub`) |
| `build_cloud_builder` | e.g. `myorg/default` | Docker Build Cloud builder (asked when `docker_builder=cloud`) |
| `install_deps` | yes / no | Run `uv add` now. If no, run `make deps` later |

Non-interactive (CI, scripts):

```bash
uvx copier copy --trust --defaults ./nadini my-agent \
  -d project_name="Support Bot" -d framework=langchain -d enable_langfuse=false
# or keep answers in a file:
uvx copier copy --trust --data-file answers.yml ./nadini my-agent
```

### How "never hardcode versions" works

The template lists package **names only** (`scripts/deps.py`). When you generate a project:

1. `uv add <names>` resolves the **latest** release of each package.
2. The versions are written as lower bounds in `pyproject.toml` (e.g. `mcp>=2.3.0`) and pinned exactly in `uv.lock`.
3. Docker builds use `uv sync --locked`, so the image is reproducible.

Upgrade later with `make upgrade`, which runs `uv lock --upgrade`.

## 3. Project tour

```
my-agent/
├── agent/                  ← YOUR CODE
│   ├── main.py             the contract (see below) — keep the signatures
│   ├── graph.py | chain.py the agent itself (LangGraph or LangChain)
│   ├── tools.py            tools; append to TOOLS
│   ├── prompts.py          system prompt
│   ├── llm.py              chat-model factory
│   ├── memory.py           checkpointer (memory / postgres)
│   ├── events.py           astream_events → stable AgentEvent schema
│   └── settings.py         agent env config
├── server/                 ← PLUMBING (rarely touched)
│   ├── app.py              Starlette app factory, routes, lifespan
│   ├── a2a_app.py          A2A executor + agent card (a2a-sdk)
│   ├── mcp_app.py          MCP server + `message` tool (mcp SDK)
│   ├── devui/              dev chat UI (static) + /dev/api
│   ├── telemetry.py        OTel traces/metrics/logs, Langfuse, HTTP instrumentation
│   ├── auth.py             optional bearer-token middleware
│   └── config.py           server env config
├── tests/                  fake-LLM tests for agent, A2A, MCP, dev UI
├── scripts/deps.py         dependency names (no versions)
├── Dockerfile  compose.yaml  Makefile  .env.example
```

### The contract (`agent/main.py`)

```python
async def message(text: str, context_id: str | None = None) -> str
async def stream_message(text: str, context_id: str | None = None) -> AsyncIterator[str]
async def stream_events(text: str, context_id: str | None = None) -> AsyncIterator[AgentEvent]
@asynccontextmanager
async def lifespan() -> AsyncIterator[None]   # builds the agent once per process
```

`context_id` is the conversation id. It's the A2A `contextId`, the MCP `context_id` argument, or the dev UI session. Turns that share an id share memory (it's the LangGraph `thread_id`).

`stream_events` yields these events, in order, per turn:

| `type` | `name` / `data` |
| --- | --- |
| `node_start` / `node_end` | LangGraph node name |
| `llm_start` / `llm_end` | model name; `llm_end.data` = `{usage, tool_calls}` |
| `token` | streamed text chunk |
| `tool_call` / `tool_result` | tool name; args / output |
| `final` | `{text, context_id}` (always last on success) |
| `error` | `{message, type}` |

The A2A adapter, the MCP adapter and the dev UI all consume this one stream.

## 4. Customise the agent

For every generated file (what it does, whether to edit it) and more recipes, see [Editing a generated project](EDITING.md).

### Add a tool

```python
# agent/tools.py
@tool
async def lookup_order(order_id: str) -> dict:
    """Fetch an order by id."""          # ← the docstring is what the LLM sees
    ...

TOOLS = [get_current_time, lookup_order]
```

Both frameworks pick up `TOOLS` automatically.

### Change the prompt

Edit `SYSTEM_PROMPT` in `agent/prompts.py`.

### Change or add graph logic (LangGraph)

`agent/graph.py` is a normal `StateGraph`. Add fields to `State`, then add nodes and edges:

```python
class State(MessagesState):
    tool_rounds: int                      # shows up in the dev UI "State" tab

graph.add_node("reviewer", review_answer)
graph.add_edge("agent", "reviewer")
```

The [worked example](EXAMPLE.md) adds a tool-budget guard this way.

### Middleware, structured output (LangChain)

`agent/chain.py` wraps `langchain.agents.create_agent`. Pass `middleware=[...]` for summarisation, human-in-the-loop or guardrails, or `response_format=` for structured output.

### Change model / provider

- **Model:** set `LLM_MODEL` in `.env`.
- **Any OpenAI-compatible server:** set `OPENAI_BASE_URL` (Ollama: `http://localhost:11434/v1`).
- **Another provider:** change `agent/llm.py` (e.g. `uv add langchain-anthropic` and return `ChatAnthropic(...)`).

Nothing else depends on the provider.

### Persistent memory

Generate with `checkpointer=postgres`. `make up` starts Postgres, and `DATABASE_URL` points the agent at it. Tables are created on startup.

## 5. Run locally and use the dev UI

```bash
cd my-agent
cp .env.example .env         # OPENAI_API_KEY, LLM_MODEL
make dev                     # uvicorn --reload with DEV_UI_ENABLED=true
open http://localhost:8000/dev-ui
```

The dev UI (modelled on Google ADK's `adk web`) has:

- **Sessions** (left): each session is a `context_id`. Create, switch and delete them. The list comes from the checkpointer, so it also shows conversations started over A2A or MCP.
- **Chat** (centre): streamed markdown answers, with tool-call chips (purple while running, green when done). Click any agent reply to inspect that turn.
- **Inspector** (right):
  - **Events:** timeline of the turn (nodes, LLM calls with token usage, tool args and results), with ms offsets. Click a row for its JSON.
  - **State:** the checkpointed graph state for the session.
  - **Graph:** a Mermaid render of the compiled graph.
  - **Trace:** the OTel trace id, with links to Grafana Tempo (and Langfuse, when enabled).

If `AUTH_TOKEN` is set, paste it into the box at the bottom-left of the UI.

> The dev UI exposes full conversation state. It's off unless `DEV_UI_ENABLED=true`, and the Docker image defaults to off.

## 6. Call the agent

### A2A (Agent2Agent, spec 1.0, JSON-RPC)

Discover the agent:

```bash
curl -s localhost:8000/.well-known/agent-card.json
```

Send a message (blocking):

```bash
curl -s localhost:8000/ -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
  "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "contextId": "demo",
             "parts": [{"text": "What time is it in Tokyo?"}]}}
}'
```

The reply is a `task` with `status.state = TASK_STATE_COMPLETED`. The answer is in `artifacts[0].parts[0].text`, and the tool activity is in `history` (`"Calling tool ..."`).

**Streaming:** use `"method": "SendStreamingMessage"`. You'll receive SSE events:

1. `task` (submitted), then `statusUpdate` (working)
2. `artifactUpdate` chunks with `append: true`, plus `statusUpdate`s for tool calls (`metadata.agent_event` holds the full event)
3. A final `artifactUpdate` with `lastChunk: true` carrying the **complete** answer, which replaces the chunks
4. `statusUpdate` → `TASK_STATE_COMPLETED`

Pre-1.0 clients (`message/send`) work too, because v0.3 compatibility is enabled.

**From Python** (official SDK):

```python
import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import Role, SendMessageRequest

async with httpx.AsyncClient(timeout=120) as http:
    card = await A2ACardResolver(http, "http://localhost:8000").get_agent_card()
    client = await create_client(card, client_config=ClientConfig(streaming=True, httpx_client=http))
    msg = new_text_message("hello", role=Role.ROLE_USER)
    async for event in client.send_message(SendMessageRequest(message=msg)):
        print(event)
```

Inspect the agent visually with [a2a-inspector](https://github.com/a2aproject/a2a-inspector).

### MCP (Model Context Protocol, streamable HTTP)

The agent is an MCP server at `/mcp` with one tool:

```
message(text: str, context_id: str | None) -> {"response": str, "context_id": str}
```

Reuse the returned `context_id` to continue a conversation.

**Claude Code:**

```bash
claude mcp add --transport http my-agent http://localhost:8000/mcp
# with auth:
claude mcp add --transport http my-agent http://localhost:8000/mcp --header "Authorization: Bearer $AUTH_TOKEN"
```

**VS Code** (`.vscode/mcp.json`) and **Cursor** (`.cursor/mcp.json`):

```jsonc
// VS Code
{ "servers": { "my-agent": { "type": "http", "url": "http://localhost:8000/mcp" } } }
// Cursor
{ "mcpServers": { "my-agent": { "url": "http://localhost:8000/mcp" } } }
```

**MCP Inspector:** run `npx @modelcontextprotocol/inspector`, choose *Streamable HTTP*, and enter `http://localhost:8000/mcp`.

**Python:**

```python
from mcp import Client

async with Client("http://localhost:8000/mcp") as client:
    r1 = await client.call_tool("message", {"text": "My name is Sam."})
    ctx = r1.structured_content["context_id"]
    r2 = await client.call_tool("message", {"text": "What's my name?", "context_id": ctx})
    print(r2.structured_content["response"])     # → "Your name is Sam."
```

When you deploy behind a hostname, set `MCP_ALLOWED_HOSTS` to enable DNS-rebinding protection.

### Agent-to-agent

Another agent (ADK, LangGraph, CrewAI, ...) can call this one through its A2A card URL. That's the Python client snippet above. To let *this* agent call others, wrap an A2A client call in a tool in `agent/tools.py`.

## 7. Observability

### Grafana (traces, metrics, logs)

```bash
make up            # agent + grafana/otel-lgtm (+ postgres)
open http://localhost:3000     # Explore → Tempo / Loki / Prometheus
```

What you get:

| Signal | Content |
| --- | --- |
| **Traces** (Tempo) | `POST /` (HTTP) → agent run → each graph node → each LLM call (model, tokens, prompts) → each tool call. Spans carry `session.id` = conversation id |
| **Logs** (Loki) | stdlib logging over OTLP, with `trace_id`/`span_id` on every record (jump from log to trace) |
| **Metrics** (Prometheus/Mimir) | `http_server_duration_*`, `http_server_active_requests`, ... |

In production, point `OTEL_EXPORTER_OTLP_ENDPOINT` at Grafana Alloy or an OTel Collector. Grafana Cloud's OTLP gateway also works; add `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic ...`.

### Langfuse

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` (Cloud, or [self-hosted](https://langfuse.com/self-hosting)). Langfuse attaches to the **same** OpenTelemetry `TracerProvider` and exports only LLM-related spans (OpenInference), which means:

- one instrumentation, with no duplicate callbacks
- the same trace id in Grafana and Langfuse
- conversations grouped as Langfuse **sessions** (by `context_id`)

Leave the keys empty to turn it off.

### Privacy

Set `OPENINFERENCE_HIDE_INPUTS=true` and `OPENINFERENCE_HIDE_OUTPUTS=true` to keep prompts and completions out of all traces. More `OPENINFERENCE_HIDE_*` switches exist. Set `OTEL_SDK_DISABLED=true` to turn telemetry off entirely.

## 8. Build and deploy

```bash
make build                                   # docker build -t my-agent:latest .
docker run --env-file .env -p 127.0.0.1:8000:8000 my-agent:latest   # drop 127.0.0.1: to expose on the network
```

The image:

- is multi-stage, built with `uv sync --locked`
- runs as a non-root user
- has a `HEALTHCHECK` on `/healthz`
- keeps the dev UI off
- handles graceful shutdown

Kubernetes probes:

```yaml
livenessProbe:  { httpGet: { path: /healthz, port: 8000 } }
readinessProbe: { httpGet: { path: /readyz,  port: 8000 } }
```

Set these in production:

- `PUBLIC_URL`: the URL other agents reach; it's advertised in the agent card.
- `AUTH_TOKEN`, or put an auth gateway in front.
- `MCP_ALLOWED_HOSTS`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `checkpointer=postgres` if you run more than one replica. In-memory memory isn't shared across pods.

A2A task state uses an in-memory task store. For multi-replica deployments, either use sticky sessions or swap in `a2a-sdk`'s `DatabaseTaskStore`.

### Publish to Docker Hub from CI

With `ci=dockerhub`, `.github/workflows/ci.yml` runs lint + tests, then builds a `linux/amd64` + `linux/arm64` image and pushes it to `dockerhub_image`:

| Trigger | Tags pushed |
| --- | --- |
| push to `main` | `latest`, `sha-<short sha>` |
| tag `v1.2.3` | `1.2.3`, `1.2` |
| pull request | none (build only) |

Add two repository secrets: `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token with Read & Write scope).

`docker_builder` picks where the image is built:

- `runner`: buildx on the GitHub runner, with QEMU emulating arm64 and the GitHub Actions cache. Free, but arm64 builds are slow.
- `cloud`: [Docker Build Cloud](https://docs.docker.com/build-cloud/) with native amd64 and arm64 builders. Create a builder in Docker Hub, then give its `ORG/NAME` as `build_cloud_builder`. The token's account needs access to it. Build Cloud needs a login even to build, so pull requests from forks (which get no secrets) fail at that step.

## 9. Keep it up to date

| Command | Effect |
| --- | --- |
| `make upgrade` | Every dependency to its latest release (`uv lock --upgrade`); then run `make test` |
| `make deps` | Re-resolve from the name list in `scripts/deps.py` |
| `uvx copier update --trust` | Pull template improvements into your project (3-way merge; your `agent/` changes are kept, conflicts are marked). Needs the template to be a git repo with commits (tags recommended), and your project committed first |

The template's CI renders every variant **weekly** against the latest SDK releases, so breaking upstream changes surface there first.

## 10. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `LLM_MODEL is not set` | Add `LLM_MODEL=...` to `.env` |
| A2A error `-32009 ... version '0.3' is not supported` | Add header `A2A-Version: 1.0` when using 1.0 methods (`SendMessage`). Without the header, use the 0.3 names (`message/send`) |
| MCP `421 Invalid Host header` | Add the Host you're calling with to `MCP_ALLOWED_HOSTS` (e.g. `"localhost:*"`), or leave it empty |
| `401 unauthorized` | `AUTH_TOKEN` is set; send `Authorization: Bearer <token>` |
| No traces in Grafana | Check `OTEL_EXPORTER_OTLP_ENDPOINT` (HTTP port **4318**). The app logs "OpenTelemetry enabled" at startup |
| Langfuse empty | Both keys must be set; check `LANGFUSE_BASE_URL` region; traces flush in batches (a few seconds) |
| Model rejects `temperature` | Unset `LLM_TEMPERATURE` (some reasoning models only allow the default) |
| Can't reach the agent from another machine | Generated with `bind_host=127.0.0.1`: change `--host` in the `Makefile` and the port mappings in `compose.yaml`, or regenerate with `0.0.0.0` |
| `/dev-ui` is 404 | `DEV_UI_ENABLED=true` (and the project was generated with `enable_devui`) |
| Generation failed at `uv add` | Re-run `make deps` in the project once the network is up |

## Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | LLM credentials |
| `LLM_MODEL` | — (required) | Chat model name |
| `OPENAI_BASE_URL` | OpenAI | Any OpenAI-compatible endpoint |
| `LLM_TEMPERATURE` | model default | Sampling temperature |
| `PORT` | 8000 | Listening port (Docker) |
| `HOST` | `bind_host` | Bind address the MCP app is told about. `make dev` / `make run` pass `--host` directly |
| `PUBLIC_URL` | `http://localhost:8000` | Advertised in the agent card |
| `AUTH_TOKEN` | — | Bearer token for A2A/MCP/dev API |
| `DEV_UI_ENABLED` | `false` | Enables `/dev-ui` |
| `MCP_ALLOWED_HOSTS` | `[]` | MCP DNS-rebinding allow-list (JSON list) |
| `DATABASE_URL` | local | Postgres checkpointer |
| `TRACE_URL_TEMPLATE` | Grafana Explore/Tempo | Dev UI trace link, `{trace_id}` substituted |
| `OTEL_ENABLED` | `true` | App-level telemetry switch |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP/HTTP endpoint |
| `OTEL_SERVICE_NAME` | project slug | Service name |
| `OTEL_SDK_DISABLED` | `false` | Standard OTel kill switch |
| `OPENINFERENCE_HIDE_INPUTS` / `_OUTPUTS` | `false` | Redact prompts/completions in spans |
| `LANGFUSE_PUBLIC_KEY` / `_SECRET_KEY` / `_BASE_URL` | — | Langfuse |
| `LANGFUSE_ENABLED` | `true` | Langfuse switch (keys also required) |
| `LOG_LEVEL` | `INFO` | Python logging level |
