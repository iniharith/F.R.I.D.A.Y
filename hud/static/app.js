const log = document.getElementById("chatLog");
const form = document.getElementById("inputBar");
const input = document.getElementById("textInput");
const heard = document.getElementById("heard");
const heardVal = document.getElementById("heardVal");
const micBtn = document.getElementById("micBtn");
const stopBtn = document.getElementById("stopBtn");
const memoryList = document.getElementById("memoryList");
const confirmationPanel = document.getElementById("confirmationPanel");
const confirmationBackdrop = document.getElementById("confirmationPanelBackdrop");
const confirmationTitle = document.getElementById("confirmationTitle");
const confirmationDescription = document.getElementById("confirmationDescription");
const approveBtn = document.getElementById("approveBtn");
const denyBtn = document.getElementById("denyBtn");
const visionWarning = document.getElementById("visionWarning");
const guardianAlert = document.getElementById("guardianAlert");
const guardianMessage = document.getElementById("guardianMessage");
const guardianDismiss = document.getElementById("guardianDismiss");
const feedbackBar = document.getElementById("feedbackBar");
const thumbUp = document.getElementById("thumbUp");
const thumbDown = document.getElementById("thumbDown");
const attachBtn = document.getElementById("attachBtn");
const fileInput = document.getElementById("fileInput");
const attachRow = document.getElementById("attachRow");
const inputBar = document.getElementById("inputBar");
const chatWrap = document.getElementById("panel-chat") || log;

const tbState = document.getElementById("tbState");
const tbMic = document.getElementById("tbMic");
const tbFacts = document.getElementById("tbFacts");
const fridayStatus = document.getElementById("fridayStatus");
const devMicStatus = document.getElementById("devMicStatus");
const dashState = document.getElementById("dashState");
const dashFacts = document.getElementById("dashFacts");
const dashEpisodes = document.getElementById("dashEpisodes");
const dashServer = document.getElementById("dashServer");
const dashSocket = document.getElementById("dashSocket");
const bbCore = document.getElementById("bbCore");
const bbSys = document.getElementById("bbSys");
const chatStatusText = document.getElementById("chatStatusText");
const chatStatusDot = document.getElementById("chatStatusDot");
const linkVal = document.getElementById("linkVal");
const aiStatus = document.getElementById("aiStatus");
const guardianStatus = document.getElementById("guardianStatus");
const tbMode = document.getElementById("tbMode");
const tbModeSwitch = document.getElementById("tbModeSwitch");
const dashEngineLink = document.getElementById("dashEngineLink");
const dashMode = document.getElementById("dashMode");
const dashReasoning = document.getElementById("dashReasoning");
const dashModel = document.getElementById("dashModel");
const dashModelShort = document.getElementById("dashModelShort");
const dashModelName = document.getElementById("dashModelName");
const confirmationExpiry = document.getElementById("confirmationExpiry");
const autoAcceptToggle = document.getElementById("autoAcceptToggle");
const ftModel = document.getElementById("ftModel");
const ftRank = document.getElementById("ftRank");
const ftAlpha = document.getElementById("ftAlpha");
const ftEpochs = document.getElementById("ftEpochs");
const ftLr = document.getElementById("ftLr");
const ftBatch = document.getElementById("ftBatch");
const ftSeq = document.getElementById("ftSeq");
const ftPairs = document.getElementById("ftPairs");
const ftStart = document.getElementById("ftStart");
const ftStop = document.getElementById("ftStop");
const ftStatus = document.getElementById("ftStatus");
const ftBar = document.getElementById("ftBar");
const ftApply = document.getElementById("ftApply");
const pinCurrent = document.getElementById("pinCurrent");
const pinNew = document.getElementById("pinNew");
const pinSave = document.getElementById("pinSave");
const pinClear = document.getElementById("pinClear");
const pinStatus = document.getElementById("pinStatus");

let lastAssistantTimestamp = 0;
let lastResponseId = "";
let ws = null;
let assistantBubble = null;
let confirmationId = null;
let confirmationTimer = null;
let confirmationDeadline = 0;
let confirmationReturnFocus = null;
let currentVolume = 0;
let connected = false;
let pendingAttachments = [];
let pinEnabled = false;
const toolEvents = new Map();

/* ============ IDE WORKSHOP ============ */
const idePanel = document.getElementById("idePanel");
const ideTabs = document.getElementById("ideTabs");
const ideBodyEls = document.querySelectorAll(".ide-pane");
const reasonSteps = document.getElementById("reasonSteps");
const todoList = document.getElementById("todoList");
const toolList = document.getElementById("toolList");
const diffStack = document.getElementById("diffStack");
const ideAgentStatus = document.getElementById("ideAgentStatus");
const ideCollapseBtn = document.getElementById("ideCollapse");
const ideReset = document.getElementById("ideReset");

const ideIntroEls = {
  reason: document.querySelector("#ideReason .ide-intro"),
  todos: document.querySelector("#ideTodos .ide-intro"),
  tools: document.querySelector("#ideTools .ide-intro"),
  diff: document.querySelector("#ideDiff .ide-intro"),
};

let agentSession = {
  active: false,
  file: "",
  reasons: [],
  todos: {},
  todoOrder: [],
  tools: [],
  diff: null,
};

function markdownToHtml(md, allowMarkup = true) {
  if (!md) return "";
  const codeBlocks = [];
  const text = String(md).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, body) => {
    const id = "`CB" + codeBlocks.length + "`";
    codeBlocks.push({ lang: lang || "", body: body.replace(/\n$/, "") });
    return id;
  })
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const lines = text.split("\n");
  let html = "";
  let inList = null;
  let startedListOpen = false;

  const closeList = () => {
    if (inList) { html += "</" + inList + ">"; inList = null; startedListOpen = false; }
  };

  const inline = (s) => {
    let t = s;
    t = t.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>');
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return t;
  };

  for (const raw of lines) {
    const line = raw;
    const trimmed = line.trim();
    if (/^```/.test(trimmed) || /^`CB\d+`$/.test(trimmed)) {
      const m = trimmed.match(/^`CB(\d+)`$/);
      if (m) {
        closeList();
        const block = codeBlocks[Number(m[1])];
        const cls = block.lang === "py" || block.lang === "python" ? " lang-py"
          : block.lang === "js" ? " lang-js" : "";
        html += `<pre class="md-code${cls}"><code>${escBlock(block.body)}</code></pre>`;
      }
      continue;
    }
    if (/^#{1,6}\s/.test(trimmed)) {
      closeList();
      const level = trimmed.match(/^(#{1,6})\s/)[1].length;
      html += `<h${level} class="md-h md-h${level}">${inline(trimmed.replace(/^#{1,6}\s/, ""))}</h${level}>`;
      continue;
    }
    if (/^[-*+]\s/.test(trimmed)) {
      if (inList !== "ul") { closeList(); inList = "ul"; html += "<ul" + (startedListOpen ? "" : ""); }
      html += `<li>${inline(trimmed.replace(/^[-*+]\s/, ""))}</li>`;
      continue;
    }
    if (/^\d+[.)]\s/.test(trimmed)) {
      if (inList !== "ol") { closeList(); inList = "ol"; html += "<ol>"; }
      html += `<li>${inline(trimmed.replace(/^\d+[.)]\s/, ""))}</li>`;
      continue;
    }
    if (/^&gt;\s/.test(trimmed)) {
      closeList();
      html += `<blockquote class="md-quote">${inline(trimmed.replace(/^&gt;\s/, ""))}</blockquote>`;
      continue;
    }
    if (trimmed === "") { closeList(); continue; }
    closeList();
    html += `<p class="md-p">${inline(line)}</p>`;
  }
  closeList();

  html = html.replace(/`CB\d+`/g, (id) => {
    const idx = Number(id.slice(2, -1));
    const block = codeBlocks[idx];
    const cls = block && (block.lang === "py" || block.lang === "python") ? " lang-py"
      : block && block.lang === "js" ? " lang-js" : "";
    return block ? `<pre class="md-code${cls}"><code>${escBlock(block.body)}</code></pre>` : id;
  });
  return html;
}

function escBlock(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderBubbleMarkdown(el, text) {
  el.innerHTML = markdownToHtml(text);
}

function addBubble(content, { cls = "", isHTML = false } = {}) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${cls}`;
  if (isHTML) bubble.innerHTML = content;
  else bubble.textContent = content;
  log.appendChild(bubble);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

/* ----- IDE helpers ----- */
function ideShow() {
  if (idePanel.classList.contains("ide-collapsed")) {
    idePanel.classList.remove("ide-collapsed");
    idePanel.setAttribute("aria-hidden", "false");
  }
  setState(agentSession.active ? "executing" : "idle");
  if (document.body.dataset.panel !== "chat") switchPanel("chat");
}

function ideHide() {
  idePanel.classList.add("ide-collapsed");
  idePanel.setAttribute("aria-hidden", "true");
}

function ideSwitchTab(name) {
  ideTabs.querySelectorAll(".ide-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  ideBodyEls.forEach((p) => p.classList.toggle("active", p.dataset.pane === name));
}

ideTabs.addEventListener("click", (e) => {
  const btn = e.target.closest(".ide-tab");
  if (btn) ideSwitchTab(btn.dataset.tab);
});

ideCollapseBtn.addEventListener("click", () => {
  if (idePanel.classList.contains("ide-collapsed")) ideShow();
  else ideHide();
});

const workshopToggle = document.getElementById("workshopToggle");
workshopToggle.addEventListener("click", () => {
  if (idePanel.classList.contains("ide-collapsed")) ideShow();
  else ideHide();
});

ideReset.addEventListener("click", () => {
  agentSession = { active: false, file: "", reasons: [], todos: {}, todoOrder: [], tools: [], diff: null };
  agentSessionReset();
});

function agentSessionReset() {
  reasonSteps.replaceChildren();
  todoList.replaceChildren();
  toolList.replaceChildren();
  diffStack.replaceChildren();
  toolEvents.clear();
  Object.values(ideIntroEls).forEach((el) => { if (el) el.style.display = "block"; });
  if (ideAgentStatus) { ideAgentStatus.textContent = "IDLE"; ideAgentStatus.className = "ide-agent-status"; }
}

function stripIntro(pane) {
  const el = ideIntroEls[pane];
  if (el) el.style.display = "none";
}

/* ----- Reasoning ----- */
function reasonEvent(text) {
  if (!agentSession.active) return;
  const step = document.createElement("div");
  step.className = "reason-step";
  const meta = document.createElement("div");
  meta.className = "rs-meta";
  const now = new Date();
  meta.textContent = "AGENT \u00b7 " + now.toLocaleTimeString("en-GB", { hour12: false });
  const body = document.createElement("div");
  body.className = "rs-any";
  body.textContent = text;
  step.append(meta, body);
  reasonSteps.appendChild(step);
  stripIntro("reason");
  reasonSteps.scrollTop = reasonSteps.scrollHeight;
}

/* ----- Todos ----- */
function renderTodos(items) {
  todoList.replaceChildren();
  stripIntro("todos");
  if (!items || !items.length) return;
  agentSession.todoOrder = Array.from(new Set(items.map((i) => i.id)));
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "todo-item status-" + (item.status || "pending");
    const check = document.createElement("span");
    check.className = "todo-check";
    check.textContent = item.status === "done" ? "\u2713" : "";
    const label = document.createElement("span");
    label.textContent = item.label || ("Task " + item.id);
    row.append(check, label);
    todoList.appendChild(row);
  });
}

/* ----- Tools ----- */
function renderToolCall(tc) {
  const el = document.createElement("div");
  el.className = "tool-call side-" + (tc.status === "done" ? "ok" : tc.status === "error" ? "err" : "run");
  const row = document.createElement("div");
  row.className = "tc-row";
  const name = document.createElement("span");
  name.className = "tc-name";
  name.textContent = tc.tool || "tool";
  const title = document.createElement("span");
  title.className = "tc-title";
  title.textContent = tc.title || "";
  const state = document.createElement("span");
  state.className = "tc-state";
  state.textContent = (tc.status || "running").toUpperCase();
  row.append(name, title, state);
  el.appendChild(row);
  if (tc.file) {
    const f = document.createElement("div");
    f.className = "tc-file";
    f.textContent = tc.file;
    el.appendChild(f);
  }
  if (tc.message) {
    const m = document.createElement("div");
    m.className = "tc-msg";
    m.textContent = tc.message;
    el.appendChild(m);
  }
  if (tc.backup) {
    const b = document.createElement("div");
    b.className = "tc-file";
    b.textContent = "backup: " + tc.backup;
    el.appendChild(b);
  }
  toolList.appendChild(el);
  stripIntro("tools");
  toolList.scrollTop = toolList.scrollHeight;
  return el;
}

function renderToolEvent(action, result = null) {
  const id = action?.id || `${action?.name || "tool"}-${Date.now()}`;
  let item = toolEvents.get(id);
  if (!item) {
    item = {
      id,
      tool: action?.name || "tool",
      title: action?.title || "Tool action",
      status: "running",
      message: action?.description || "",
      startedAt: new Date(),
    };
    toolEvents.set(id, item);
  }
  if (result) {
    item.status = result.ok ? "done" : "error";
    item.message = result.message || item.message;
  }
  let el = toolList.querySelector(`[data-tool-id="${CSS.escape(id)}"]`);
  if (el) el.remove();
  el = renderToolCall(item);
  el.dataset.toolId = id;
  const time = document.createElement("div");
  time.className = "tc-time";
  time.textContent = item.startedAt.toLocaleTimeString("en-GB", { hour12: false });
  el.appendChild(time);
  ideShow();
  ideSwitchTab("tools");
}

/* ----- Diff (LCS line diff) ----- */
function computeLineDiff(oldText, newText) {
  const a = String(oldText || "").split("\n");
  const b = String(newText || "").split("\n");
  const n = a.length, m = b.length;
  const lcs = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const lines = [];
  let oldLine = 0, newLine = 0, i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { lines.push({ type: "eq", oldLine: ++oldLine, newLine: ++newLine, text: a[i] }); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { lines.push({ type: "del", oldLine: ++oldLine, newLine: null, text: a[i] }); i++; }
    else { lines.push({ type: "add", oldLine: null, newLine: ++newLine, text: b[j] }); j++; }
  }
  while (i < n) { lines.push({ type: "del", oldLine: ++oldLine, newLine: null, text: a[i] }); i++; }
  while (j < m) { lines.push({ type: "add", oldLine: null, newLine: ++newLine, text: b[j] }); j++; }
  return lines;
}

function renderDiff(edit) {
  diffStack.replaceChildren();
  stripIntro("diff");
  const fileEl = document.createElement("div");
  fileEl.className = "diff-file";
  const head = document.createElement("div");
  head.className = "diff-file-head";
  const name = document.createElement("span");
  name.className = "diff-file-name";
  name.textContent = edit.file || "file";
  const badge = document.createElement("span");
  badge.className = "diff-file-badge";
  badge.textContent = "MODIFIED";
  head.append(name, badge);
  if (edit.backup) {
    const backup = document.createElement("div");
    backup.className = "diff-file-backup";
    backup.textContent = "backup: " + edit.backup;
    head.appendChild(backup);
  }
  fileEl.appendChild(head);
  const code = document.createElement("div");
  code.className = "diff-code";
  const lines = computeLineDiff(edit.old, edit.new);
  for (const ln of lines) {
    const row = document.createElement("div");
    row.className = "diff-line " + (ln.type === "add" ? "add" : ln.type === "del" ? "del" : "dm");
    const sig = document.createElement("span");
    sig.className = "dl-sig";
    sig.textContent = ln.type === "add" ? "+" : ln.type === "del" ? "-" : " ";
    const num = document.createElement("span");
    num.className = "dl-num";
    num.textContent = (ln.newLine || "") + " " + (ln.oldLine || "");
    const txt = document.createElement("span");
    txt.textContent = ln.text || "\u00a0";
    row.append(sig, num, txt);
    code.appendChild(row);
  }
  fileEl.appendChild(code);
  diffStack.appendChild(fileEl);
}

const STATES = {
  idle: "STANDBY",
  listening: "LISTENING",
  awake: "YES, BOSS?",
  thinking: "THINKING",
  speaking: "SPEAKING",
  executing: "EXECUTING",
  awaiting: "CONFIRMATION REQUIRED",
};

const DASH_STATES = {
  idle: "STANDBY",
  listening: "LISTENING",
  awake: "ARMED",
  thinking: "THINKING",
  speaking: "SPEAKING",
  executing: "EXECUTING",
  awaiting: "AWAITING",
};

function switchPanel(name) {
  document.body.dataset.panel = name;
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.querySelectorAll(".sb-btn").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".mobile-nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.panel === name));
  const panel = document.getElementById("panel-" + name);
  if (panel) panel.classList.add("active");
  const btn = document.querySelector('.sb-btn[data-panel="' + name + '"]');
  if (btn) btn.classList.add("active");
  if (name === "memory" && ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: "memory_list" }));
  }
  if (name === "settings") {
    fetchTrainStatus();
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "settings_get" }));
  }
}

function renderTrainStatus(t) {
  if (!ftStatus) return;
  const state = t.state || "idle";
  let text = state.toUpperCase();
  if (t.message) text += ` — ${t.message}`;
  if (t.total) {
    text += ` (step ${t.step}/${t.total}`;
    if (t.loss != null && t.loss !== undefined) text += `, loss ${Number(t.loss).toFixed(4)}`;
    text += ")";
  }
  if (t.gguf_path) text += `\nGGUF: ${t.gguf_path}`;
  if (state === "done" && t.gguf_path) text += " — READY";
  ftStatus.textContent = text;
  ftStatus.dataset.state = state;
  if (ftBar) {
    ftBar.style.width = t.total ? `${Math.min(100, (t.step / t.total) * 100)}%` : "0%";
  }
  if (ftApply) {
    const ready = state === "done" && !!t.gguf_path;
    ftApply.disabled = !ready;
    ftApply.title = ready ? `Hot-swap brain to ${t.gguf_path}` : "Available after fine-tune with GGUF export";
  }
}

async function fetchTrainStatus() {
  if (!ftStatus) return;
  try {
    const response = await fetch("/train/status", { cache: "no-store" });
    if (response.ok) renderTrainStatus(await response.json());
  } catch (_) {}
}

function setPerfMode(mode) {
  document.querySelectorAll(".perf-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
}

function setState(s) {
  document.body.dataset.state = s;
  const label = STATES[s] || s.toUpperCase();
  fridayStatus.textContent = label;
  tbState.textContent = label;
  bbCore.textContent = label;
  if (dashState) dashState.textContent = DASH_STATES[s] || label;
  const orb = document.getElementById("dashOrb");
  if (s === "speaking" || s === "idle") {
    assistantBubble?.classList.remove("streaming");
  }
  if (s === "thinking") {
    showThinking();
  } else {
    hideThinking();
  }
  if (orb) {
    orb.style.display = "block";
  }
}

function setConnected(ok) {
  connected = ok;
  linkVal.textContent = ok ? "LINKED" : "OFFLINE";
  if (chatStatusDot) chatStatusDot.classList.toggle("connected", ok);
  if (chatStatusText) chatStatusText.textContent = ok ? "NEURAL LINK ACTIVE" : "CONNECTING...";
  if (dashEngineLink) dashEngineLink.textContent = ok ? "LINKED" : "OFFLINE";
  if (aiStatus) {
    aiStatus.innerHTML = ok ? '<i class="dot on"></i>ONLINE' : '<i class="dot off"></i>OFFLINE';
    aiStatus.classList.toggle("on", ok);
  }
  if (bbSys) {
    bbSys.textContent = ok ? "ONLINE" : "OFFLINE";
    bbSys.classList.toggle("bb-online", ok);
  }
  if (ok) refreshEngineHealth();
}

async function refreshEngineHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) return;
    const health = await response.json();
    const mode = health.reasoning === "openrouter" ? "OPENROUTER" : "LOCAL";
    const model = mode === "OPENROUTER"
      ? (health.cloud_model || "NOT REPORTED")
      : (health.local_model || "LOCAL MODEL");
if (tbMode) tbMode.textContent = mode;
    if (dashMode) dashMode.textContent = mode;
    if (dashReasoning) dashReasoning.textContent = mode;
    if (dashModel) dashModel.textContent = model;
    if (dashModelShort) dashModelShort.textContent = model;
    if (dashModelName) dashModelName.textContent = model;
    if (tbModeSwitch) {
      const buttons = tbModeSwitch.querySelectorAll(".tb-mode-btn");
      buttons.forEach((b) => b.classList.toggle("active", b.dataset.mode === (health.reasoning || "local")));
    }
  } catch (_) {}
}

async function switchMode(mode) {
  const valid = mode === "local" || mode === "openrouter";
  if (!valid) return;
  if (tbModeSwitch) {
    tbModeSwitch.querySelectorAll(".tb-mode-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === mode);
    });
  }
  try {
    const response = await fetch("/settings/mode?mode=" + encodeURIComponent(mode), { method: "POST" });
    if (!response.ok) {
      heard.textContent = ("SWITCH FAILED: " + mode).toUpperCase();
      return;
    }
    refreshEngineHealth();
  } catch (error) {
    heard.textContent = ("SWITCH FAILED: " + (error.message || "NETWORK")).toUpperCase();
  }
}

function syncModeSwitch(mode) {
  if (!tbModeSwitch) return;
  tbModeSwitch.querySelectorAll(".tb-mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === mode);
    btn.setAttribute("aria-pressed", btn.dataset.mode === mode ? "true" : "false");
  });
}

async function switchMode(mode) {
  syncModeSwitch(mode);
  try {
    const response = await fetch("/settings/mode", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ mode }),
    });
    if (!response.ok) throw new Error(`status ${response.status}`);
    const data = await response.json();
    const active = data.reasoning === "openrouter" ? "openrouter" : "local";
    syncModeSwitch(active);
    if (tbMode) tbMode.textContent = active.toUpperCase();
    if (dashMode) dashMode.textContent = active.toUpperCase();
    if (dashReasoning) dashReasoning.textContent = active.toUpperCase();
    const label = active === "openrouter"
      ? (data.cloud_model || "OPENROUTER")
      : "LOCAL";
    if (dashModel) dashModel.textContent = label;
    if (dashModelShort) dashModelShort.textContent = label;
    if (dashModelName) dashModelName.textContent = label;
    addBubble(
      active === "openrouter"
        ? "Cloud reasoning enabled. Using OpenRouter for this session."
        : "Local mode enabled. Running fully offline on this machine.",
      { cls: "fri" }
    );
  } catch (error) {
    addBubble(`Mode switch failed: ${error.message || error}`, { cls: "fri" });
    refreshEngineHealth();
  }
}
window.switchMode = switchMode;

let typingBubble = null;

function showThinking() {
  hideThinking();
  typingBubble = document.createElement("div");
  typingBubble.className = "bubble fri typing";
  typingBubble.innerHTML =
    '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  log.appendChild(typingBubble);
  log.scrollTop = log.scrollHeight;
}

function hideThinking() {
  if (typingBubble) {
    typingBubble.remove();
    typingBubble = null;
  }
}

function renderMemories(facts) {
  memoryList.replaceChildren();
  if (!facts.length) {
    const empty = document.createElement("div");
    empty.className = "mem-empty";
    empty.textContent = "// NO FACTS STORED.";
    memoryList.appendChild(empty);
    return;
  }
  facts.forEach((fact) => {
    const item = document.createElement("article");
    item.className = "mem-item";
    const text = document.createElement("p");
    text.textContent = fact.text;
    const meta = document.createElement("div");
    meta.className = "mem-meta";
    const category = document.createElement("span");
    category.className = "mem-category";
    category.textContent = fact.category;
    const forget = document.createElement("button");
    forget.className = "forget-btn";
    forget.textContent = "FORGET";
    forget.addEventListener("click", () => {
      if (!confirm(`Forget this?\n\n${fact.text}`)) return;
      ws?.send(JSON.stringify({ type: "memory_forget", id: fact.id }));
    });
    meta.append(category, forget);
    item.append(text, meta);
    memoryList.appendChild(item);
  });
}

function wakeTone() {
  try {
    const audio = new AudioContext();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 820;
    gain.gain.setValueAtTime(0.05, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.12);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.12);
  } catch (_) {}
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);
  ws.onopen = () => setConnected(true);
  ws.onclose = () => { setConnected(false); setTimeout(connect, 1500); };
  ws.onmessage = (e) => {
    try { handle(JSON.parse(e.data)); }
    catch (_) { heard.textContent = "BACKEND PROTOCOL ERROR"; }
  };
}

function handle(msg) {
  switch (msg.type) {
    case "state":
      setState(msg.value);
      return;
    case "guardian": {
      if (guardianStatus) {
        guardianStatus.innerHTML = msg.active ? '<i class="dot off"></i>ALERT' : '<i class="dot on"></i>ACTIVE';
        guardianStatus.classList.toggle("on", !msg.active);
      }
      if (msg.active) {
        guardianMessage.textContent = msg.message;
        guardianAlert.classList.add("open");
        guardianAlert.setAttribute("aria-hidden", "false");
      } else {
        guardianAlert.classList.remove("open");
        guardianAlert.setAttribute("aria-hidden", "true");
      }
      return;
    }
    case "vision":
      visionWarning.classList.toggle("open", msg.active);
      visionWarning.setAttribute("aria-hidden", String(!msg.active));
      return;
    case "volume":
      currentVolume = msg.value;
      return;
    case "mic": {
      micBtn.classList.toggle("on", msg.active);
      tbMic.textContent = msg.active ? "ON" : "MUTED";
      if (devMicStatus) {
        devMicStatus.innerHTML = msg.active
          ? '<i class="dot on"></i>ONLINE'
          : '<i class="dot off"></i>MUTED';
        devMicStatus.classList.toggle("on", msg.active);
      }
      return;
    }
    case "voice_status":
      return;
    case "memory_stats": {
      tbFacts.textContent = msg.facts;
      if (dashFacts) dashFacts.textContent = msg.facts;
      if (dashEpisodes) dashEpisodes.textContent = msg.episodes || 0;
      return;
    }
    case "memory_saved":
      heard.textContent = `MEMORY STORED: ${msg.facts?.[0]?.text || "fact"}`;
      if (heardVal) heardVal.textContent = "SAVED";
      if (document.getElementById("panel-memory").classList.contains("active") && ws?.readyState === 1) {
        ws.send(JSON.stringify({ type: "memory_list" }));
      }
      return;
    case "memory_warning":
      heard.textContent = msg.text.toUpperCase();
      if (heardVal) heardVal.textContent = "WARN";
      return;
    case "memory_list":
      renderMemories(msg.facts);
      return;
    case "settings": {
      if (autoAcceptToggle) autoAcceptToggle.checked = !!msg.auto_accept_tools;
      pinEnabled = !!msg.pin_enabled;
      if (pinStatus) {
        pinStatus.textContent = pinEnabled ? "PIN: ACTIVE" : "PIN: NOT SET";
        pinStatus.dataset.state = pinEnabled ? "done" : "idle";
      }
      return;
    }
    case "settings_error":
      if (pinStatus) { pinStatus.textContent = msg.text || "REJECTED"; pinStatus.dataset.state = "error"; }
      heard.textContent = (msg.text || "SETTINGS REJECTED").toUpperCase();
      return;
    case "mode": {
      const selected = msg.selected_mode || msg.effective_mode || "local";
      const effective = msg.effective_mode || "local";
      syncModeSwitch(selected);
      if (tbMode) tbMode.textContent = effective.toUpperCase();
      if (dashMode) dashMode.textContent = effective.toUpperCase();
      if (dashReasoning) dashReasoning.textContent = effective.toUpperCase();
      return;
    }
    case "train_status":
      renderTrainStatus(msg);
      return;
    case "confirmation": {
      clearInterval(confirmationTimer);
      confirmationId = msg.action.id;
      confirmationTitle.textContent = msg.action.title || "Action requested";
      confirmationDescription.textContent = msg.action.description || "Review this action before allowing it.";
      confirmationReturnFocus = document.activeElement;
      confirmationDeadline = Date.now() + 60000;
      approveBtn.disabled = false;
      denyBtn.disabled = false;
      confirmationPanel.classList.add("open");
      confirmationPanel.setAttribute("aria-hidden", "false");
      confirmationBackdrop.classList.add("open");
      approveBtn.focus();
      updateConfirmationExpiry();
      confirmationTimer = setInterval(updateConfirmationExpiry, 1000);
      return;
    }
    case "confirmation_resolved": {
      closeConfirmation();
      return;
    }
    case "tool_started":
      heard.textContent = `RUNNING: ${msg.action?.title || "TOOL"}`;
      if (heardVal) heardVal.textContent = "RUN";
      renderToolEvent(msg.action || {});
      return;
    case "tool_result":
      heard.textContent = msg.result?.ok ? "TASK COMPLETE" : "TASK FAILED";
      if (heardVal) heardVal.textContent = msg.result?.ok ? "OK" : "FAIL";
      renderToolEvent(msg.action || {}, msg.result || { ok: false, message: "No result details were provided." });
      return;
    case "notification":
      heard.textContent = msg.text;
      return;
    case "assistant": {
      hideThinking();
      const bubble = addBubble("", { cls: "fri" });
      renderBubbleMarkdown(bubble, msg.text);
      assistantBubble = bubble;
      lastAssistantTimestamp = msg.timestamp || Date.now() / 1000;
      lastResponseId = msg.response_id || "";
      feedbackBar.classList.toggle("show", !!lastResponseId);
      thumbUp.classList.remove("active");
      thumbDown.classList.remove("active");
      return;
    }
    case "response_complete": {
      lastAssistantTimestamp = msg.timestamp || Date.now() / 1000;
      lastResponseId = msg.response_id || "";
      feedbackBar.classList.toggle("show", !!lastResponseId);
      if (assistantBubble && typeof msg.text === "string") {
        assistantBubble._full = msg.text;
        renderBubbleMarkdown(assistantBubble, msg.text);
      }
      assistantBubble?.classList.remove("streaming");
      assistantBubble = null;
      hideThinking();
      thumbUp.classList.remove("active");
      thumbDown.classList.remove("active");
      return;
    }
    case "wake":
      wakeTone();
      heard.textContent = "Wake phrase detected";
      if (heardVal) heardVal.textContent = "WAKE";
      return;
    case "transcript":
      heard.textContent = `HEARD: ${msg.text}`;
      if (heardVal) heardVal.textContent = "HEARD";
      return;
    case "user":
      if (msg.source === "voice") {
        addBubble(msg.text, { cls: "boss" });
        assistantBubble = null;
      }
      return;
    case "error":
      hideThinking();
      addBubble("", { cls: "fri", isHTML: true }).innerHTML = markdownToHtml(msg.text);
      if (agentSession.active) {
        if (ideAgentStatus) { ideAgentStatus.textContent = "ERROR"; ideAgentStatus.className = "ide-agent-status error"; }
      }
      return;
    case "interrupted":
      assistantBubble?.classList.remove("streaming");
      hideThinking();
      return;
    case "delta": {
      if (!assistantBubble) {
        hideThinking();
        assistantBubble = addBubble("", { cls: "fri streaming" });
        assistantBubble._full = "";
      }
      assistantBubble._full += msg.text;
      renderBubbleMarkdown(assistantBubble, assistantBubble._full);
      log.scrollTop = log.scrollHeight;
      return;
    }
    case "agent_begin":
      agentSession.active = true;
      agentSessionReset();
      if (ideAgentStatus) { ideAgentStatus.textContent = "RUNNING"; ideAgentStatus.className = "ide-agent-status running"; }
      ideShow();
      return;
    case "agent_end":
      agentSession.active = false;
      if (ideAgentStatus) { ideAgentStatus.textContent = "DONE"; ideAgentStatus.className = "ide-agent-status done"; }
      return;
    case "reason":
      reasonEvent(msg.text);
      return;
    case "todo":
      renderTodos(msg.items || []);
      return;
    case "toolcall":
      renderToolCall(msg);
      return;
    case "edit":
      agentSession.diff = msg;
      renderDiff(msg);
      return;
  }
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autoGrow);

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

attachBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  handleAttachFiles([...fileInput.files]);
  fileInput.value = "";
});

async function handleAttachFiles(files) {
  const list = files.slice(0, 10);
  for (const file of list) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    try {
      const res = await fetch("/upload", { method: "POST", body: fd });
      if (!res.ok) {
        let detail = `Upload failed (${res.status})`;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        heard.textContent = detail.toUpperCase();
        continue;
      }
      const meta = await res.json();
      pendingAttachments.push(meta);
      renderAttachmentChip(meta);
    } catch (error) {
      heard.textContent = `UPLOAD FAILED: ${error.message || "NETWORK ERROR"}`.toUpperCase();
    }
  }
}

function renderAttachmentChip(meta) {
  const chip = document.createElement("div");
  chip.className = "attach-chip" + (meta.kind === "image" ? " image" : "");
  if (meta.kind === "image") {
    const img = document.createElement("img");
    img.src = meta.url;
    img.alt = meta.name;
    chip.appendChild(img);
  } else {
    const label = document.createElement("span");
    label.className = "chip-name";
    label.textContent = meta.name;
    label.title = meta.name;
    chip.appendChild(label);
  }
  const x = document.createElement("button");
  x.type = "button";
  x.className = "chip-x";
  x.textContent = "\u00d7";
  x.title = "Remove attachment";
  x.addEventListener("click", () => {
    pendingAttachments = pendingAttachments.filter((a) => a.id !== meta.id);
    chip.remove();
  });
  chip.appendChild(x);
  attachRow.appendChild(chip);
}

function refreshAttachRow() {
  attachRow.replaceChildren();
  pendingAttachments.forEach(renderAttachmentChip);
}

let dragDepth = 0;
chatWrap.addEventListener("dragenter", (e) => {
  e.preventDefault();
  dragDepth++;
  chatWrap.classList.add("dragging");
});
chatWrap.addEventListener("dragover", (e) => e.preventDefault());
chatWrap.addEventListener("dragleave", (e) => {
  e.preventDefault();
  if (--dragDepth <= 0) { dragDepth = 0; chatWrap.classList.remove("dragging"); }
});
chatWrap.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  chatWrap.classList.remove("dragging");
  if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
    handleAttachFiles([...e.dataTransfer.files]);
  }
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  const hasAttach = pendingAttachments.length > 0;
  if ((!text && !hasAttach) || !ws || ws.readyState !== 1) return;
  const attachments = pendingAttachments.slice();
  pendingAttachments = [];
  refreshAttachRow();
  input.value = "";
  input.style.height = "auto";
  const label = text || (attachments.some((a) => a.kind === "image")
    ? "[image]"
    : attachments.map((a) => a.name).join(", "));
  addBubble(label, { cls: "boss" });
  assistantBubble = null;
  ws.send(JSON.stringify({ type: "chat", text, attachments }));
});

micBtn.addEventListener("click", () => {
  if (ws?.readyState === 1) ws.send(JSON.stringify({ type: "mic_toggle" }));
});

stopBtn.addEventListener("click", () => {
  if (ws?.readyState === 1) ws.send(JSON.stringify({ type: "stop" }));
});

approveBtn.addEventListener("click", () => {
  if (confirmationId && ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "tool_confirm", id: confirmationId }));
    setConfirmationPending("APPROVING...");
  }
});

denyBtn.addEventListener("click", () => {
  if (confirmationId && ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "tool_deny", id: confirmationId }));
    setConfirmationPending("DENYING...");
  }
});

autoAcceptToggle?.addEventListener("change", () => {
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({
      type: "settings_set",
      key: "auto_accept_tools",
      value: autoAcceptToggle.checked,
    }));
    heard.textContent = autoAcceptToggle.checked
      ? "AUTO-ACCEPT ENABLED — FRIDAY WILL NOT ASK"
      : "AUTO-ACCEPT DISABLED — FRIDAY WILL ASK";
  }
});

ftStart?.addEventListener("click", async () => {
  const body = {
    model: ftModel.value,
    lora_r: Number(ftRank.value),
    lora_alpha: Number(ftAlpha.value),
    epochs: Number(ftEpochs.value),
    learning_rate: Number(ftLr.value),
    batch_size: Number(ftBatch.value),
    max_seq: Number(ftSeq.value),
    max_pairs: Number(ftPairs.value),
  };
  try {
    const response = await fetch("/train/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    heard.textContent = (data.message || "TRAIN START").toUpperCase();
  } catch (_) {
    heard.textContent = "TRAIN START FAILED";
  }
});

ftStop?.addEventListener("click", async () => {
  try {
    await fetch("/train/stop", { method: "POST" });
    heard.textContent = "TRAIN STOP REQUESTED";
  } catch (_) {
    heard.textContent = "TRAIN STOP FAILED";
  }
});

ftApply?.addEventListener("click", async () => {
  if (ftApply.disabled) return;
  try {
    const response = await fetch("/train/apply", { method: "POST" });
    const data = await response.json();
    heard.textContent = (data.message || "APPLY REQUESTED").toUpperCase();
    if (data.ok) refreshEngineHealth();
  } catch (_) {
    heard.textContent = "APPLY FAILED";
  }
});

pinSave?.addEventListener("click", () => {
  const newPin = (pinNew?.value || "").trim();
  if (!/^\d{4,8}$/.test(newPin)) {
    if (pinStatus) { pinStatus.textContent = "NEW PIN MUST BE 4-8 DIGITS"; pinStatus.dataset.state = "error"; }
    return;
  }
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "settings_set", key: "session_pin_hash", value: newPin, pin: (pinCurrent?.value || "").trim() }));
    if (pinStatus) { pinStatus.textContent = "SAVING..."; pinStatus.dataset.state = "running"; }
    if (pinNew) pinNew.value = "";
  }
});

pinClear?.addEventListener("click", () => {
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "settings_set", key: "session_pin_hash", value: "", pin: (pinCurrent?.value || "").trim() }));
    if (pinStatus) { pinStatus.textContent = "CLEARING..."; pinStatus.dataset.state = "running"; }
    if (pinCurrent) pinCurrent.value = "";
  }
});

function setConfirmationPending(label) {
  approveBtn.disabled = true;
  denyBtn.disabled = true;
  confirmationExpiry.textContent = label;
}

function updateConfirmationExpiry() {
  const seconds = Math.max(0, Math.ceil((confirmationDeadline - Date.now()) / 1000));
  confirmationExpiry.textContent = seconds ? `Expires in ${seconds} seconds.` : "Confirmation expired.";
  if (!seconds) closeConfirmation();
}

function closeConfirmation() {
  clearInterval(confirmationTimer);
  confirmationTimer = null;
  confirmationId = null;
  confirmationPanel.classList.remove("open");
  confirmationPanel.setAttribute("aria-hidden", "true");
  confirmationBackdrop.classList.remove("open");
  if (confirmationReturnFocus?.focus) confirmationReturnFocus.focus();
  confirmationReturnFocus = null;
}

confirmationPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !denyBtn.disabled) {
    event.preventDefault();
    denyBtn.click();
  }
  if (event.key === "Tab") {
    const controls = [denyBtn, approveBtn].filter((button) => !button.disabled);
    if (!controls.length) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

guardianDismiss?.addEventListener("click", () => {
  guardianAlert.classList.remove("open");
  guardianAlert.setAttribute("aria-hidden", "true");
});

thumbUp?.addEventListener("click", () => {
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "feedback", response_id: lastResponseId, timestamp: lastAssistantTimestamp, score: 1 }));
    thumbUp.classList.add("active");
    thumbDown.classList.remove("active");
  }
});

thumbDown?.addEventListener("click", () => {
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ type: "feedback", response_id: lastResponseId, timestamp: lastAssistantTimestamp, score: -1 }));
    thumbDown.classList.add("active");
    thumbUp.classList.remove("active");
  }
});

function clock() {
  const now = new Date();
  const t = document.getElementById("tbTime");
  const d = document.getElementById("tbDate");
  if (t) {
    t.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
  }
  if (d) {
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    d.textContent = `${y}.${m}.${day}`;
  }
  if (dashServer) dashServer.textContent = location.host;
  if (dashSocket) dashSocket.textContent = connected ? "OPEN" : "CLOSED";
}
setInterval(clock, 1000);

setState("idle");
setConnected(false);
connect();
clock();
agentSessionReset();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
