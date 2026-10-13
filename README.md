# Nadini

**ناديني — make your agent callable from anywhere: A2A · MCP · UI**

Nadini is an interactive [Copier](https://copier.readthedocs.io) template for AI agent services. You write the agent logic in `agent/`, and Nadini provides:

- **A2A** endpoint (official `a2a-sdk`, spec 1.0 + 0.3 compat, streaming, agent card)
- **MCP** endpoint (official `mcp` SDK, streamable HTTP, `message` tool)
- **LangGraph or LangChain**, chosen at generation time
- **Dev chat UI**, ADK-style: sessions, event timeline, state, graph, trace links
- **OpenTelemetry** traces, metrics and logs to Grafana (Tempo/Loki/Mimir via Alloy or LGTM), plus optional **Langfuse** on the same pipeline
- **Dockerfile** (multi-stage, uv, non-root, healthcheck) and a compose stack with Grafana LGTM
- **No hardcoded versions**: dependencies are added by name and resolved to the latest releases at generation time, then locked in `uv.lock`

```bash
uvx copier copy --trust gh:<you>/nadini my-agent
cd my-agent && cp .env.example .env && make dev   # → http://localhost:8000/dev-ui
```

📖 **[Usage guide](docs/GUIDE.md)** · 🧪 **[Worked example: Research Assistant](docs/EXAMPLE.md)**

## Why the name

**Nadini** (ناديني) is Palestinian Arabic for **"call me"**. It comes from *nāda* (نادى), to call out to someone.

That is the template's whole job: making your agent *callable*.

- Other agents call it over **A2A**.
- Assistants and tools call it over **MCP**.
- You call it from the **dev UI**.

One agent answers on every line.

## Layout

```
copier.yml            questions + post-generation tasks
template/             the project skeleton (rendered with Jinja)
docs/                 GUIDE.md, EXAMPLE.md
examples/             research-assistant (generated + customised) and its answers file
.github/workflows/    template CI: renders 4 variants weekly against the latest SDKs
```

## Developing the template

```bash
# render a variant and test it
uvx copier copy --trust --defaults . /tmp/agent -d framework=langchain -d checkpointer=postgres
cd /tmp/agent && uv run ruff check . && uv run pytest -q
```

`copier copy` uses the latest git tag of a template repo (or `HEAD` with `--vcs-ref HEAD`). Commit, and tag releases, so generated projects can `copier update`.

---

**Free Palestine** 🇵🇸
