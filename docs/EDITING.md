# Editing a generated project

You ran `copier copy` and now have a project. This guide covers every generated file: whether to edit it, what to change, and what to leave alone so A2A, MCP, the dev UI and `copier update` keep working.

- [The three rules](#the-three-rules)
- [File by file](#file-by-file)
- [What `agent/events.py` is for](#what-agenteventspy-is-for)
- [Recipes](#recipes)
- [Changing a generation answer later](#changing-a-generation-answer-later)
- [Pulling template updates](#pulling-template-updates)
- [Editing Nadini itself](#editing-nadini-itself)

## The three rules

1. **`agent/` is yours.** Edit anything in it.
2. **Keep the signatures in `agent/main.py`.** `message()`, `stream_message()`, `stream_events()` and `lifespan()` are the contract that A2A, MCP and the dev UI call. Change what happens inside them, not how they're called.
3. **`server/` is plumbing.** You rarely need to touch it. When you do, keep the change small: `copier update` merges template changes into these files, and big local edits mean merge conflicts.

## File by file

✏️ edit freely · ⚠️ edit with care · 🔒 leave alone unless you know why

### `agent/` (your code)

| File | | What it is | Typical edits |
| --- | --- | --- | --- |
| `tools.py` | ✏️ | Functions the LLM can call | Add `@tool` functions and append them to `TOOLS` |
| `prompts.py` | ✏️ | `SYSTEM_PROMPT` | Rewrite the persona, rules and output format |
| `graph.py` (LangGraph) | ✏️ | An explicit, uncompiled `StateGraph`: `agent ⇄ tools` | Add state fields, nodes, edges, routing |
| `chain.py` (LangChain) | ✏️ | `create_agent(model, TOOLS, ...)` | Add `middleware=[...]` or `response_format=` |
| `llm.py` | ✏️ | Builds the chat model | Switch provider (Anthropic, Gemini, ...) or add model options |
| `settings.py` | ✏️ | Agent config from env / `.env` | Add your own settings (API keys, limits) |
| `memory.py` | ⚠️ | Opens the conversation store (checkpointer) | Swap the backend, e.g. SQLite. Must yield a LangGraph checkpointer |
| `builder.py` (LangGraph) | 🔒 | Compiles `graph` from `graph.py` with the checkpointer | Nothing, usually |
| `main.py` | ⚠️ | The contract + dev UI helpers | Change the input you send to the agent, or what counts as the final answer. Keep the signatures |
| `events.py` | ⚠️ | Translates raw LangChain events into `AgentEvent`s | Add new event types ([see below](#what-agenteventspy-is-for)) |

### `server/` (plumbing)

| File | | What it is | When you'd edit it |
| --- | --- | --- | --- |
| `config.py` | ⚠️ | Server settings (host, port, public URL, auth, dev UI, OTel) | Add a server-level setting |
| `a2a_app.py` | ⚠️ | A2A executor and agent card | Advertise skills, change what callers receive, allow cancelling. See [A2A.md](A2A.md) |
| `mcp_app.py` | ⚠️ | MCP server with the `message` tool | Expose more MCP tools or resources |
| `app.py` | ⚠️ | Starlette app: routes, middleware, startup | Add an HTTP route (e.g. a webhook) |
| `auth.py` | 🔒 | Bearer-token middleware | Swap in another auth scheme (OAuth, API gateway headers) |
| `telemetry.py` | 🔒 | OpenTelemetry + Langfuse setup | Rarely. Configure with `OTEL_*` env vars instead |
| `devui/` | 🔒 | Dev chat UI and its API | Only to change the UI itself |

### Project files

| File | | Notes |
| --- | --- | --- |
| `.env` | ✏️ | Your local config and secrets. Never committed |
| `.env.example` | ✏️ | Committed template for `.env`. Add new settings here so others know they exist |
| `scripts/deps.py` | ✏️ | Dependency **names** (no versions). Add new packages here too ([recipe](#add-a-dependency)) |
| `pyproject.toml`, `uv.lock` | ⚠️ | Managed by `uv add` / `uv lock`. Don't hand-edit versions |
| `tests/` | ✏️ | Fake-LLM tests. Add tests for your tools and graph |
| `Makefile` | ✏️ | Shortcuts. Add targets freely |
| `Dockerfile` | ⚠️ | Multi-stage, non-root. Add system packages in the runtime stage if a tool needs them |
| `compose.yaml` | ⚠️ | Agent + Grafana LGTM (+ Postgres). Add services your agent depends on |
| `.github/workflows/ci.yml` | ⚠️ | Lint, test, build (and push) |
| `.copier-answers.yml` | 🔒 | Your generation answers. **Never edit by hand.** `copier update` needs it |

## What `agent/events.py` is for

When the agent runs, LangChain emits a firehose of low-level events (`on_chat_model_stream`, `on_tool_start`, `on_chain_end`, ...), each with a different shape. `events.py` turns that stream into a small, stable set of `AgentEvent`s:

```
LangChain astream_events ──► events.convert() ──► AgentEvent ──┬──► A2A    (token → artifact chunks, tool_* → status updates, final → complete)
   (dozens of raw kinds)       (drops noise)       (9 types)   ├──► dev UI (event timeline, chat, tool chips)
                                                               └──► MCP    (via message(): waits for final)
```

| `type` | Comes from | `name` / `data` |
| --- | --- | --- |
| `node_start` / `node_end` | a LangGraph node starting / finishing | node name |
| `llm_start` / `llm_end` | a chat model call | model; `llm_end.data` = `{usage, tool_calls}` |
| `token` | streamed model output | the text chunk |
| `tool_call` / `tool_result` | a tool starting / finishing | tool name; args / output |
| `final` | added by `main.stream_events()` | `{text, context_id}`, always last on success |
| `error` | added by `main.stream_events()` | `{message, type}` |

**Why it exists:** without it, A2A, MCP and the dev UI would each parse raw LangChain events themselves and slowly drift apart. LangChain can also change its event format between releases; with this layer, only `convert()` needs to change.

**When to edit it:** when you want something new to show up in the stream. For example, to report progress from inside a long-running tool:

```python
# agent/tools.py
from langchain_core.callbacks import adispatch_custom_event

@tool
async def crawl_site(url: str) -> str:
    """Crawl a website and summarise it."""
    for i, page in enumerate(pages):
        await adispatch_custom_event("progress", {"done": i + 1, "total": len(pages)})
    ...
```

```python
# agent/events.py
EventType = Literal[..., "progress"]          # 1. add the type

def convert(raw):
    ...
    match kind:
        ...
        case "on_custom_event":                   # 2. map the raw event
            return make_event("progress", name=name, node=node, data=to_jsonable(data))
```

The dev UI timeline shows any event type automatically. A2A ignores types it doesn't handle; to send progress to A2A clients too, add a `case "progress":` in `server/a2a_app.py` that calls `updater.update_status(...)`, like the existing `tool_call` case.

## Recipes

### Add a tool

```python
# agent/tools.py
@tool
async def lookup_order(order_id: str) -> dict:
    """Fetch an order by its id."""           # ← the LLM reads this docstring and the type hints
    ...

TOOLS = [get_current_time, lookup_order]
```

Both frameworks pick up `TOOLS`. Return short, plain data, because everything a tool returns goes back into the model's context. Test it without an LLM:

```python
# tests/test_tools.py
async def test_lookup_order():
    assert (await lookup_order.ainvoke({"order_id": "42"}))["id"] == "42"
```

To test the agent calling it, script the fake LLM (see `tests/test_agent.py`):

```python
script_llm(tool_call("lookup_order", {"order_id": "42"}), "Order 42 has shipped.")
```

### Change the system prompt

Edit `SYSTEM_PROMPT` in `agent/prompts.py`. For a prompt that changes per turn (e.g. today's date), build it in the model node instead:

```python
# agent/graph.py
async def call_model(state: State, config: RunnableConfig) -> dict:
    prompt = SYSTEM_PROMPT + f"\nToday is {date.today():%A %d %B %Y}."
    messages = [SystemMessage(prompt), *state["messages"]]
    ...
```

### Add state and nodes (LangGraph)

```python
# agent/graph.py
class State(MessagesState):
    tool_rounds: int                           # shows up in the dev UI State tab

async def review(state: State) -> dict:
    ...
    return {"messages": [...]}

graph.add_node("review", review)
graph.add_conditional_edges("agent", route)    # replace tools_condition with your own router
graph.add_edge("review", END)
```

`graph.py` is plain LangGraph: restructure it however you like, as long as it keeps a module-level `graph`, a state that extends `MessagesState`, and no `.compile()` call (`builder.py` compiles it with the checkpointer that gives each conversation its memory).

The dev UI Graph tab redraws from the compiled graph, so you can check the wiring there. [`EXAMPLE.md`](EXAMPLE.md) walks through a full tool-budget guard.

### Use middleware or structured output (LangChain)

```python
# agent/chain.py
from langchain.agents.middleware import SummarizationMiddleware

return create_agent(
    llm.get_llm(), TOOLS,
    system_prompt=SYSTEM_PROMPT,
    middleware=[SummarizationMiddleware(model=llm.get_llm(), trigger=("tokens", 4000))],
    checkpointer=checkpointer,
    name="my-agent",
)
```

If you set `response_format=`, also change `main.stream_events()` so `final.data.text` comes from `state.values["structured_response"]` instead of the last message.

### Switch LLM provider

```bash
uv add langchain-anthropic
```

```python
# agent/llm.py
from langchain_anthropic import ChatAnthropic

def get_llm() -> BaseChatModel:
    s = get_settings()
    return ChatAnthropic(model=s.llm_model, streaming=True)   # reads ANTHROPIC_API_KEY
```

Nothing else depends on the provider. For any OpenAI-compatible server (Ollama, vLLM, LiteLLM) you don't need code changes: just set `OPENAI_BASE_URL` in `.env`.

### Add a setting

```python
# agent/settings.py
class AgentSettings(BaseSettings):
    ...
    orders_api_url: str = "https://orders.internal"
    orders_api_key: SecretStr | None = None
```

These are read from `ORDERS_API_URL` / `ORDERS_API_KEY` in the environment or `.env`. Use `get_settings().orders_api_url` in your code, and add both names to `.env.example`. Agent concerns go in `agent/settings.py`; HTTP-server concerns go in `server/config.py`.

### Add a dependency

```bash
uv add pandas
```

Then add `"pandas"` to `RUNTIME` in `scripts/deps.py` (or `DEV` for test-only tools). `uv add` updates `pyproject.toml` and `uv.lock` right away; the line in `deps.py` keeps the name list complete for `make deps`. Don't pin versions. `make upgrade` moves everything to the latest release.

### Add an HTTP route

```python
# server/app.py, in create_app()
async def webhook(request: Request) -> JSONResponse:
    body = await request.json()
    reply = await agent_main.message(body["text"], body.get("thread"))
    return JSONResponse({"reply": reply})

routes = [
    Route("/healthz", healthz),
    Route("/readyz", readyz),
    Route("/webhook", webhook, methods=["POST"]),
    ...
]
```

Keep A2A last in the list, because it's mounted at `/`. The bearer-token middleware covers new routes too.

### Customise A2A (agent card, replies, cancel, task storage)

See [A2A.md](A2A.md).

## Changing a generation answer later

Don't edit `.copier-answers.yml`. Re-answer through Copier, which re-renders the affected files and keeps your edits:

```bash
git commit -am "wip"                                       # commit first
uvx copier update --trust --defaults -d enable_langfuse=true
uvx copier update --trust --defaults -d port=9000 -d bind_host=0.0.0.0
uvx copier update --trust                                  # or re-answer everything
```

Switching `framework` **deletes** the old file (`graph.py` or `chain.py`), even if you edited it, and creates the new one. Port your logic across before committing; the old version is still in git history. Then run `make deps` so the dependency list matches.

## Pulling template updates

When Nadini gets a new release:

```bash
git commit -am "wip"
uvx copier update --trust --defaults
```

Copier does a 3-way merge: template changes since your version are applied on top of your edits. Where both changed the same lines, you get conflict markers (`<<<<<<<`) to resolve, as in a git merge. The smaller your edits to `server/`, the fewer conflicts you'll see.

## Editing Nadini itself

To change what **every future project** gets, edit the template repo instead. Files live under `template/`. Names ending in `.jinja` are rendered with the generation answers (`{{ project_slug }}`, `{% if framework == 'langgraph' %}`); others are copied as-is. Questions live in `copier.yml`. See [Developing the template](../README.md#developing-the-template).
