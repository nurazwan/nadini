# Customising A2A

How to change what other agents see and get when they call yours over [A2A](https://a2a-protocol.org): the agent card, the replies, cancelling, task storage and auth. Also how your agent can call *other* A2A agents.

Every recipe here was tested against `a2a-sdk` 1.2.2, the version generated projects lock.

- [The map](#the-map)
- [The agent card](#the-agent-card)
- [The executor: what callers receive](#the-executor-what-callers-receive)
- [Cancelling tasks](#cancelling-tasks)
- [Task storage](#task-storage)
- [Auth](#auth)
- [Calling other A2A agents](#calling-other-a2a-agents)
- [Testing your changes](#testing-your-changes)
- [Keeping template updates easy](#keeping-template-updates-easy)

## The map

Everything A2A lives in **one file, `server/a2a_app.py`**, in three parts:

| Part | Where | What it does | You'd change it to… |
| --- | --- | --- | --- |
| **Agent card** | `build_agent_card()` | Describes the agent at `/.well-known/agent-card.json` | Advertise skills, provider, docs link |
| **Executor** | `AgentRunner.execute()` / `cancel()` | Runs your agent per message and turns its events into A2A updates | Change what callers see while it works and in the answer |
| **Routes** | `build_routes()` | Wires the card and executor to URLs; picks the task store | Persist tasks in a database |

A request flows like this:

```
caller ── SendMessage ──► "/"  (build_routes)
                           │
                           ▼
                   AgentRunner.execute()
                           │  agent_main.stream_events(text, context_id)
                           ▼
                   your graph (agent/graph.py)
                           │  AgentEvents: node_start, token, tool_call, final, …
                           ▼
                   execute() maps each event ──► A2A status / artifact updates ──► caller
```

The A2A `contextId` is the conversation id. Messages that share it share memory (it becomes the LangGraph `thread_id`).

## The agent card

The card is your agent's business card. Callers read it to learn its name, what it can do, and where to send messages.

### From settings, no code

| Card field | Setting (`.env` or environment) | Default |
| --- | --- | --- |
| `name` | `AGENT_NAME` | your `project_name` |
| `description` | `AGENT_DESCRIPTION` | your `description` |
| `version` | `AGENT_VERSION` | `0.1.0` |
| endpoint URL | `PUBLIC_URL` | `http://localhost:<port>` |

**Set `PUBLIC_URL` before you deploy.** Callers send messages to this address, so `localhost` only works on your own machine.

### `PUBLIC_URL` and deployment addresses

`PUBLIC_URL` is copied into the card as-is, so a domain name or an IP address both work:

```bash
PUBLIC_URL=https://agent.example.com        # domain behind HTTPS
PUBLIC_URL=http://203.0.113.10:8000         # public IP
PUBLIC_URL=http://192.168.1.50:8000         # private IP, same network only
```

1. **Include the scheme and port:** `http://203.0.113.10:8000`, not `203.0.113.10:8000`. You can leave the port out only for 80 (`http`) or 443 (`https`).
2. **Listen on all interfaces.** With `bind_host=127.0.0.1`, `make run` only accepts connections from the same machine. Re-answer with `uvx copier update --trust --defaults -d bind_host=0.0.0.0`. In Docker the server always listens on `0.0.0.0`, so check the `ports:` mapping in `compose.yaml` instead.
3. **The address must be reachable by callers.** A private IP works for agents on the same network. Over the internet you need a public IP, with the port open in your firewall or cloud security group.
4. **Plain `http` is unencrypted, `AUTH_TOKEN` included.** HTTPS certificates are normally issued for domain names, not IPs. Plain `http` is fine on a private network or for testing. For anything public, put the agent behind a domain with HTTPS, for example with Caddy or nginx as a reverse proxy.
5. **MCP only:** if you set `MCP_ALLOWED_HOSTS`, add the new address (e.g. `["203.0.113.10:*"]`), or MCP requests through it are rejected. A2A isn't affected.

### Skills

Skills tell callers what to ask your agent for. They are **descriptions only**: every message still goes to your one graph, and the graph decides what to do. Replace the default `Chat` skill in `build_agent_card()`:

```python
skills=[
    AgentSkill(
        id="order-status",
        name="Order status",
        description="Look up where an order is and when it will arrive.",
        tags=["orders"],
        examples=["Where is order 42?"],
    ),
    AgentSkill(
        id="refunds",
        name="Refunds",
        description="Explain the refund policy and start a refund.",
        tags=["orders", "refunds"],
        examples=["I want a refund for order 42"],
    ),
],
```

Write `description` and `examples` for another agent's LLM: it reads them to decide whether yours can help. A skill's `input_modes` / `output_modes` default to the card's `default_input_modes` / `default_output_modes` (`text/plain`), so only set them if a skill differs.

### Provider, docs link, icon

```python
from a2a.types import AgentProvider

card = AgentCard(
    ...,
    provider=AgentProvider(organization="Acme", url="https://acme.example.com"),
    documentation_url="https://acme.example.com/docs/agent",
    icon_url="https://acme.example.com/agent.png",
)
```

### Capabilities

`AgentCapabilities(streaming=True)` is already set, and it's true because the executor streams. Only advertise `push_notifications=True` after you wire up push notification config in `build_routes()`. Otherwise callers will try to use a feature that isn't there.

## The executor: what callers receive

`AgentRunner.execute()` reads your agent's events and turns them into A2A updates:

| Your agent's event | What the caller gets |
| --- | --- |
| `token` | An `answer` artifact chunk (`append=True`): the reply streaming in |
| `tool_call` / `tool_result` | A `working` status update: "Calling tool `x`" / "Finished tool `x`" (the full event is in `metadata.agent_event`) |
| `final` | The complete answer, which replaces the chunks (`last_chunk=True`), then the task is **completed** |
| an exception | The task is **failed**, with the error text |

The other event types (`node_start`, `node_end`, `llm_start`, `llm_end`) are ignored, but you can map them too. Each recipe below edits the `match event["type"]:` block. The event types are listed in `agent/events.py`.

### Hide tool activity

To keep your tools private, delete the `case "tool_call" | "tool_result":` branch. Callers then see only the streamed answer.

### Show step-by-step progress instead

Report each graph node as it starts. This helps when your graph has meaningful steps like `classify`, `research` or `review`:

```python
case "node_start":
    status = new_text_message(f"Step: {event['node']}", role=Role.ROLE_AGENT)
    await updater.update_status(TaskState.TASK_STATE_WORKING, message=status)
```

### Return structured data with the answer

An artifact can carry a JSON data part next to the text. That's useful when the caller is a program, not a person. Collect what you need while events go by, then attach it in `final`:

```python
from a2a.helpers import new_data_part

tools_used: list[str] = []   # before the `async for`
...
case "tool_call":
    tools_used.append(event["name"])
    # (keep the status update here too if you want it)
case "final":
    await updater.add_artifact(
        [
            new_text_part(event["data"]["text"]),
            new_data_part({"tools_used": tools_used}),
        ],
        artifact_id=artifact_id,
        name=ANSWER_ARTIFACT,
        append=False,
        last_chunk=True,
    )
    await updater.complete()
```

Callers read it with `a2a.helpers.get_data_parts(artifact.parts)`.

### Pass caller metadata into your graph

Callers can send request-level `metadata` (e.g. a user id) alongside the message. Passing it to the graph takes three small edits, because `agent/main.py` is the boundary between the server and your graph:

**1. `server/a2a_app.py`**: read it and pass it on:
```python
user_id = context.metadata.get("user_id", "anonymous")
async for event in agent_main.stream_events(
    context.get_user_input(), task.context_id, extra={"user_id": user_id}
):
```

**2. `agent/main.py`**: accept the optional `extra` and merge it into the graph input. Adding an optional argument keeps the contract working for MCP and the dev UI:
```python
async def stream_events(
    text: str, context_id: str | None = None, extra: dict[str, Any] | None = None
) -> AsyncIterator[AgentEvent]:
    ...
    async for raw in agent.astream_events(
        {"messages": [{"role": "user", "content": text}], **(extra or {})}, config, version="v2"
    ):
```

**3. `agent/graph.py`**: give the state a field to receive it:
```python
class State(MessagesState):
    user_id: str
```

Your nodes can now read `state["user_id"]`. A caller sends it like this:
```python
SendMessageRequest(message=new_text_message("hi", role=Role.ROLE_USER), metadata={"user_id": "u-7"})
```

## Cancelling tasks

By default `cancel()` raises `UnsupportedOperationError`, so callers get "not supported". To allow cancelling:

```python
async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
    # The SDK stops execute() right after this returns; we only record the state.
    updater = TaskUpdater(event_queue, context.task_id, context.context_id)
    await updater.cancel()
```

Then remove the now-unused `UnsupportedOperationError` import. The SDK calls `cancel()` first and then cancels the running `execute()`, which stops your graph mid-turn. Messages already saved for that conversation stay in memory.

## Task storage

A2A keeps a record of each **task** (status, artifacts, history) so callers can look it up later with `GetTask`. This is separate from **conversation memory**, which lives in the LangGraph checkpointer (`agent/memory.py`).

By default tasks go in `InMemoryTaskStore()`, so they're lost on restart and not shared between replicas. To keep them, use the SDK's `DatabaseTaskStore`, which creates its table on first use:

```bash
uv add "a2a-sdk[sqlite]"        # or "a2a-sdk[postgresql]"
```

```python
# server/a2a_app.py
from a2a.server.tasks import DatabaseTaskStore, TaskUpdater
from sqlalchemy.ext.asyncio import create_async_engine

def build_routes(settings: ServerSettings) -> list[Route]:
    card = build_agent_card(settings)
    handler = DefaultRequestHandler(
        agent_executor=AgentRunner(),
        task_store=DatabaseTaskStore(create_async_engine("sqlite+aiosqlite:///a2a_tasks.db")),
        agent_card=card,
    )
```

For PostgreSQL the URL needs the async driver: `postgresql+asyncpg://agent:agent@localhost:5432/agent`. If your project uses `checkpointer=postgres`, you can point both at the same database. Their tables don't clash. Put the URL in a setting rather than hard-coding it (see "Add a setting" in [EDITING.md](EDITING.md#add-a-setting)).

If you run more than one replica, you need a shared task store like this one, or sticky sessions.

## Auth

Set `AUTH_TOKEN` and every A2A request must send `Authorization: Bearer <token>`. The card then advertises a `bearer` security scheme automatically (the last lines of `build_agent_card()`), so callers know to send it.

The card itself stays public, so callers can discover the agent before authenticating. `PUBLIC_PREFIXES` in `server/auth.py` lists the public paths. To use a different scheme (OAuth, an API gateway header), replace `server/auth.py` and update the security part of the card to match.

## Calling other A2A agents

To let your agent use another agent, wrap the A2A client in a tool. The LLM then decides when to call it, like any other tool:

```python
# agent/tools.py
import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_artifact_text, new_text_message
from a2a.types import Role, SendMessageRequest

ORDERS_AGENT_URL = "http://orders-agent:8000"   # better: a setting in agent/settings.py


@tool
async def ask_orders_agent(question: str) -> str:
    """Ask the orders agent about an order's status or delivery date."""
    async with httpx.AsyncClient(timeout=120) as http:
        card = await A2ACardResolver(http, ORDERS_AGENT_URL).get_agent_card()
        config = ClientConfig(streaming=False, httpx_client=http)
        client = await create_client(card, client_config=config)
        request = SendMessageRequest(message=new_text_message(question, role=Role.ROLE_USER))
        answer = "The orders agent gave no answer."
        async for response in client.send_message(request):
            if response.HasField("task") and response.task.artifacts:
                answer = get_artifact_text(response.task.artifacts[-1])
        return answer
```

Add it to `TOOLS`. If the other agent needs a token, pass `headers={"Authorization": "Bearer ..."}` to `httpx.AsyncClient`. To keep one conversation on the other side across calls, set `context_id` on the message.

## Testing your changes

**By hand** (`make dev`):
```bash
curl -s localhost:8000/.well-known/agent-card.json      # check the card

curl -s localhost:8000/ -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
  "params": {"message": {"messageId": "m1", "role": "ROLE_USER", "contextId": "demo",
             "parts": [{"text": "Where is order 42?"}]}}
}'
```
For a visual check, point [a2a-inspector](https://github.com/a2aproject/a2a-inspector) at `http://localhost:8000`.

**In tests:** `tests/test_server.py` already has the pieces: `running_app()` starts the app in-process, `test_agent_card` reads the card, and `test_a2a_send_message` sends a message through the real A2A client with a scripted fake LLM (`script_llm`). Copy those to assert your own skills, status updates or data parts. One catch: the in-process test transport returns a streaming response only after the run ends. To test cancelling, send with `SendMessageConfiguration(return_immediately=True)`, then call `cancel_task`.

## Keeping template updates easy

`server/a2a_app.py` is template code, so `copier update` merges Nadini's changes into it (see [Pulling template updates](EDITING.md#pulling-template-updates)). To keep conflicts small:

- Prefer settings (`AGENT_*`, `PUBLIC_URL`) over code for the card.
- Keep edits inside `build_agent_card()`, the `match` block and `build_routes()`, rather than reshaping the file.
- Put helpers (data-part builders, settings) in your own modules and import them.
