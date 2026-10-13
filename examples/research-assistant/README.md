# Research Assistant

Answers questions by searching Wikipedia and doing exact arithmetic, citing its sources.

A **LangGraph** agent served over **A2A** and **MCP**, with OpenTelemetry + Langfuse tracing and a dev chat UI.
Generated from [Nadini](https://github.com/<you>/nadini); run `uvx copier update --trust` to pull template improvements.

## Quickstart

```bash
cp .env.example .env      # set OPENAI_API_KEY and LLM_MODEL
make dev                  # http://localhost:8000/dev-ui
make test
```

## Where things live

| Path | What | Edit it? |
| --- | --- | --- |
| `agent/main.py` | The contract: `message`, `stream_message`, `stream_events`, `lifespan` | Keep the signatures |
| `agent/graph.py` | The StateGraph (nodes, edges, state) | Yes |
| `agent/tools.py` | Tools (add to `TOOLS`) | Yes |
| `agent/prompts.py` | System prompt | Yes |
| `agent/llm.py` | Chat model factory (OpenAI / OpenAI-compatible) | Yes |
| `agent/memory.py` | Conversation memory (in-memory checkpointer) | Rarely |
| `server/` | A2A, MCP, auth, telemetry, dev UI | Rarely |

## Endpoints

| Endpoint | Protocol |
| --- | --- |
| `POST /` | A2A JSON-RPC (`SendMessage`, `SendStreamingMessage`, `GetTask`, ...; header `A2A-Version: 1.0`) |
| `GET /.well-known/agent-card.json` | A2A agent card |
| `/mcp` | MCP streamable HTTP; tool `message(text, context_id?)` |
| `/dev-ui` | Dev chat UI (only when `DEV_UI_ENABLED=true`) |
| `GET /healthz`, `GET /readyz` | Liveness / readiness |

The conversation id is the A2A `contextId` or the MCP `context_id`. Turns with the same id share memory.

### A2A

```bash
curl -s localhost:8000/ -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
  "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "contextId": "demo",
             "parts": [{"text": "What time is it in Tokyo?"}]}}
}'
```

Use `"method": "SendStreamingMessage"` for SSE: the answer streams as artifact chunks, and the final chunk carries the full text.

### MCP

```bash
claude mcp add --transport http research-assistant http://localhost:8000/mcp
```

```python
from mcp import Client

async with Client("http://localhost:8000/mcp") as client:
    result = await client.call_tool("message", {"text": "hi"})
    print(result.structured_content)  # {"response": ..., "context_id": ...}
```

## Observability

- **Traces, metrics, logs** go over OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`: Grafana Alloy, an OTel Collector, or `grafana/otel-lgtm`. LangChain/LangGraph spans come from OpenInference, and logs carry trace ids.
- **Langfuse**: set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL`. Langfuse shares the OTel TracerProvider, so the trace id in Grafana is the same as in Langfuse, and conversations are grouped as Langfuse sessions.
- **PII**: `OPENINFERENCE_HIDE_INPUTS=true` and `OPENINFERENCE_HIDE_OUTPUTS=true` keep prompts and responses out of spans.
- `make up` starts the agent and Grafana LGTM. Grafana is at http://localhost:3000.

## Docker

```bash
make build                       # docker build -t research-assistant:latest .
docker run --env-file .env -p 127.0.0.1:8000:8000 research-assistant:latest
```

The image runs as a non-root user, has a `HEALTHCHECK` on `/healthz`, and the dev UI is off (`DEV_UI_ENABLED=false`).

## Dependencies

No versions are hardcoded. `scripts/deps.sh` adds packages by name, so `uv` resolves the latest releases and locks them in `uv.lock`.

- `make upgrade` bumps every package to its latest release.
- `make deps` re-runs the resolution from scratch.
