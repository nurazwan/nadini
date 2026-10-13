// Agent Dev UI — talks to /dev/api/* (see server/devui/routes.py).
// No build step. Markdown / sanitising / Mermaid load from a CDN when available
// and degrade to plain text when offline.

const $ = (sel) => document.querySelector(sel);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ---------------------------------------------------------------- libraries
const libs = { marked: null, purify: null, mermaid: null };
const libsReady = Promise.allSettled([
  import("https://cdn.jsdelivr.net/npm/marked/+esm").then((m) => (libs.marked = m.marked)),
  import("https://cdn.jsdelivr.net/npm/dompurify/+esm").then((m) => (libs.purify = m.default)),
]);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function renderMarkdown(text) {
  if (libs.marked && libs.purify) return libs.purify.sanitize(libs.marked.parse(text));
  return `<div style="white-space:pre-wrap">${escapeHtml(text)}</div>`;
}

// ---------------------------------------------------------------- api
function headers(extra = {}) {
  const token = store.get("devui.token");
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}
async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: headers(opts.headers) });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function* sse(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", Accept: "text/event-stream" }),
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const blocks = buf.split(/\r?\n\r?\n/);
    buf = blocks.pop();
    for (const block of blocks) {
      let event = "message";
      const data = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

// ---------------------------------------------------------------- state
const state = {
  info: null,
  sessionId: null,
  turns: [],          // {el, events[], trace, t0}
  selected: null,
  busy: false,
};

const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())).replace(/-/g, "");

// ---------------------------------------------------------------- sessions
async function refreshSessions() {
  let sessions = [];
  try { sessions = await api("/dev/api/sessions"); } catch (e) { console.warn(e); }
  if (!sessions.some((s) => s.id === state.sessionId)) sessions.unshift({ id: state.sessionId, updated_at: null });
  const ul = $("#sessions");
  ul.replaceChildren(...sessions.map((s) => {
    const li = document.createElement("li");
    li.className = s.id === state.sessionId ? "active" : "";
    li.innerHTML = `<span class="sid" title="${escapeHtml(s.id)}">${escapeHtml(s.id.slice(0, 12))}</span>
      <span class="when">${s.updated_at ? timeAgo(s.updated_at) : "new"}</span>
      <button class="del" title="Delete session" aria-label="Delete session">✕</button>`;
    li.addEventListener("click", () => openSession(s.id));
    li.querySelector(".del").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api(`/dev/api/sessions/${encodeURIComponent(s.id)}`, { method: "DELETE" }).catch(console.warn);
      if (s.id === state.sessionId) await openSession(uuid());
      else refreshSessions();
    });
    return li;
  }));
}

function timeAgo(ts) {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

async function openSession(id) {
  state.sessionId = id;
  state.turns = [];
  state.selected = null;
  store.set("devui.session", id);
  $("#session-id").textContent = id.slice(0, 12);
  $("#messages").replaceChildren($("#empty") || emptyEl());
  $("#empty").hidden = false;
  renderEvents();
  renderTrace();
  $("#sidebar").classList.remove("open");
  await loadHistory();
  refreshSessions();
  if (activeTab() === "state") loadState();
}

function emptyEl() {
  const d = document.createElement("div");
  d.className = "empty"; d.id = "empty";
  d.innerHTML = "<h2>Start a conversation</h2>";
  return d;
}

async function loadHistory() {
  let st;
  try { st = await api(`/dev/api/sessions/${encodeURIComponent(state.sessionId)}/state`); } catch { return; }
  const messages = st?.values?.messages || [];
  if (!messages.length) return;
  $("#empty").hidden = true;
  let pendingTools = [];
  for (const m of messages) {
    if (m.role === "human") addUser(m.content);
    else if (m.role === "ai" && m.tool_calls?.length && !m.content) pendingTools.push(...m.tool_calls.map((t) => t.name));
    else if (m.role === "ai") {
      const turn = addAgent();
      for (const name of pendingTools) addChip(turn, name, true);
      pendingTools = [];
      setAgentText(turn, m.content, true);
    }
  }
}

// ---------------------------------------------------------------- chat
function addUser(text) {
  const el = document.createElement("div");
  el.className = "msg user";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  $("#messages").append(el);
  scroll();
}

function addAgent() {
  const el = document.createElement("div");
  el.className = "msg agent";
  el.innerHTML = `<div class="chips"></div><div class="bubble"><span class="typing"></span></div>`;
  const turn = { el, events: [], trace: null, t0: performance.now(), text: "", chips: {} };
  el.addEventListener("click", () => selectTurn(turn));
  state.turns.push(turn);
  $("#messages").append(el);
  scroll();
  return turn;
}

function addChip(turn, name, done = false) {
  const chip = document.createElement("span");
  chip.className = `chip${done ? " done" : ""}`;
  chip.innerHTML = `<span class="dot"></span>${escapeHtml(name)}`;
  turn.el.querySelector(".chips").append(chip);
  (turn.chips[name] ||= []).push(chip);
}

function setAgentText(turn, text, finished) {
  turn.text = text;
  const bubble = turn.el.querySelector(".bubble");
  bubble.innerHTML = renderMarkdown(text) + (finished ? "" : '<span class="typing"></span>');
  scroll();
}

function scroll() {
  const m = $("#messages");
  m.scrollTop = m.scrollHeight;
}

function selectTurn(turn) {
  state.turns.forEach((t) => t.el.classList.toggle("selected", t === turn));
  state.selected = turn;
  renderEvents();
  renderTrace();
}

async function send(text) {
  if (state.busy || !text.trim()) return;
  state.busy = true;
  $("#send").disabled = true;
  $("#empty").hidden = true;
  addUser(text);
  const turn = addAgent();
  selectTurn(turn);
  let streamed = "";
  try {
    for await (const { event, data } of sse("/dev/api/run_sse", { text, context_id: state.sessionId })) {
      if (event === "meta") { turn.trace = data; if (state.selected === turn) renderTrace(); continue; }
      turn.events.push(data);
      if (state.selected === turn) appendEvent(data, turn);
      switch (data.type) {
        case "token": streamed += data.data; setAgentText(turn, streamed, false); break;
        case "tool_call": addChip(turn, data.name); streamed = ""; break;
        case "tool_result": {
          const chip = (turn.chips[data.name] || []).find((c) => !c.classList.contains("done"));
          chip?.classList.add("done");
          break;
        }
        case "final": setAgentText(turn, data.data.text, true); break;
        case "error":
          turn.el.classList.add("error");
          setAgentText(turn, `**${data.data.type}**: ${data.data.message}`, true);
          break;
      }
    }
  } catch (err) {
    turn.el.classList.add("error");
    setAgentText(turn, `Request failed: ${err.message}`, true);
  } finally {
    turn.el.querySelector(".typing")?.remove();
    state.busy = false;
    $("#send").disabled = false;
    refreshSessions();
    if (activeTab() === "state") loadState();
  }
}

// ---------------------------------------------------------------- inspector
const TYPE_CLASS = {
  node_start: "t-node", node_end: "t-node", llm_start: "t-llm", llm_end: "t-llm",
  tool_call: "t-tool", tool_result: "t-tool", final: "t-final", error: "t-error", token: "",
};

function renderEvents() {
  const ol = $("#events");
  ol.replaceChildren();
  const turn = state.selected;
  $("#events-hint").hidden = !!turn?.events.length;
  if (!turn) return;
  turn.tokenRow = null;
  turn.events.forEach((e) => appendEvent(e, turn));
}

function appendEvent(e, turn) {
  // Collapse consecutive tokens into one row so the timeline stays readable.
  if (e.type === "token" && turn.tokenRow) {
    turn.tokenRow.count += 1;
    turn.tokenRow.text += e.data;
    turn.tokenRow.li.querySelector(".name").textContent = `${turn.tokenRow.count} chunks`;
    turn.tokenRow.li.querySelector(".json").textContent = turn.tokenRow.text;
    return;
  }
  $("#events-hint").hidden = true;
  const t0 = turn.events[0]?.ts ?? e.ts;
  const li = document.createElement("li");
  const label = e.type === "token" ? "1 chunk" : (e.name || e.node || "");
  const payload = e.type === "token" ? e.data : JSON.stringify(e.data ?? e, null, 2);
  li.innerHTML = `<div class="head"><span class="type ${TYPE_CLASS[e.type] || ""}">${e.type}</span>
    <span class="name">${escapeHtml(label)}</span><span class="t">+${((e.ts - t0) * 1000).toFixed(0)}ms</span></div>
    <div class="body"><pre class="json"></pre></div>`;
  li.querySelector(".json").textContent = payload;
  li.querySelector(".head").addEventListener("click", () => li.classList.toggle("open"));
  $("#events").append(li);
  turn.tokenRow = e.type === "token" ? { li, count: 1, text: e.data } : null;
}

function renderTrace() {
  const box = $("#trace");
  const tr = state.selected?.trace;
  if (!tr) {
    box.innerHTML = '<div class="panel-hint">Trace links appear after a turn runs (requires OpenTelemetry).</div>';
    return;
  }
  const links = Object.entries(tr.links || {})
    .map(([k, url]) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">Open in ${escapeHtml(k)} ↗</a>`)
    .join("");
  box.innerHTML = `<div class="trace-links"><div>Trace id <code>${escapeHtml(tr.trace_id)}</code></div>${links}</div>`;
}

async function loadState() {
  $("#state").textContent = "Loading…";
  try {
    const st = await api(`/dev/api/sessions/${encodeURIComponent(state.sessionId)}/state`);
    $("#state").textContent = JSON.stringify(st, null, 2);
  } catch (e) {
    $("#state").textContent = String(e);
  }
}

let graphLoaded = false;
async function loadGraph() {
  if (graphLoaded) return;
  graphLoaded = true;
  try {
    const { mermaid: src } = await api("/dev/api/graph");
    $("#graph-src").textContent = src;
    if (!libs.mermaid) {
      libs.mermaid = (await import("https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.esm.min.mjs")).default;
      const dark = matchMedia("(prefers-color-scheme: dark)").matches;
      libs.mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "default" });
    }
    const { svg } = await libs.mermaid.render("agent-graph", src);
    $("#graph").innerHTML = svg;
  } catch (e) {
    $("#graph").innerHTML = `<div class="panel-hint">Graph rendering unavailable (${escapeHtml(e.message)}). See the Mermaid source below.</div>`;
  }
}

const activeTab = () => document.querySelector(".tab.active")?.dataset.tab;
function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  store.set("devui.tab", name);
  if (name === "state") loadState();
  if (name === "graph") loadGraph();
}

// ---------------------------------------------------------------- boot
async function boot() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#refresh-state").addEventListener("click", loadState);
  $("#new-session").addEventListener("click", () => openSession(uuid()));
  $("#toggle-sidebar").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#toggle-inspector").addEventListener("click", () => $("#inspector").classList.toggle("open"));

  const input = $("#input");
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight}px`; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "auto";
    send(text);
  });

  const tokenInput = $("#auth-token");
  tokenInput.value = store.get("devui.token") || "";
  tokenInput.addEventListener("change", () => { store.set("devui.token", tokenInput.value); openSession(state.sessionId); });

  await libsReady;
  try {
    state.info = await api("/dev/api/info");
  } catch {
    state.info = { name: "Agent", auth_required: true };
  }
  const info = state.info;
  document.title = `${info.name} · Dev UI`;
  $("#agent-name").textContent = info.name;
  $("#agent-meta").textContent = [info.framework, info.model].filter(Boolean).join(" · ");
  $("#auth-box").hidden = !info.auth_required;
  $("#endpoints").innerHTML = `
    <a href="${info.a2a_card || "/.well-known/agent-card.json"}" target="_blank">A2A agent card ↗</a>
    <span>MCP: <code>${escapeHtml(location.origin + (info.mcp_endpoint || "/mcp"))}</code></span>`;

  showTab(store.get("devui.tab") || "events");
  await openSession(store.get("devui.session") || uuid());
  input.focus();
}

boot();
