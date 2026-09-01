const ipcRenderer = window.friday;

let ws = null;
let currentFilter = 'all';
let logEntries = [];
let autoScroll = true;
let serverStatus = 'stopped';
let fridaySettings = {};
let confirmationTimer = null;
const toolTimeline = new Map();

function send(channel, ...args) { ipcRenderer.send(channel, ...args); }

ipcRenderer.on('log-message', (event, data) => addLogEntry(data));
ipcRenderer.on('server-status', (event, status) => updateServerStatus(status));

// ===== CLOCK & DATE =====
function updateClock() {
  const now = new Date();
  const h = String(now.getHours()).padStart(2, '0');
  const m = String(now.getMinutes()).padStart(2, '0');
  const s = String(now.getSeconds()).padStart(2, '0');
  const timeEl = document.getElementById('tbTime');
  const dateEl = document.getElementById('tbDate');
  if (timeEl) timeEl.textContent = `${h}:${m}:${s}`;
  if (dateEl) {
    const y = now.getFullYear();
    const mo = String(now.getMonth() + 1).padStart(2, '0');
    const d = String(now.getDate()).padStart(2, '0');
    dateEl.textContent = `${y}.${mo}.${d}`;
  }
}
setInterval(updateClock, 1000);
updateClock();

// ===== COORDINATE SCRAMBLE =====
function scrambleCoord(el) {
  if (!el) return;
  const chars = '0123456789.';
  let i = 0;
  const target = el.textContent;
  const iv = setInterval(() => {
    if (i >= target.length) { clearInterval(iv); return; }
    let built = target.substring(0, i);
    for (let j = i; j < Math.min(i + 3, target.length); j++) {
      built += chars[Math.floor(Math.random() * chars.length)];
    }
    built += target.substring(Math.min(i + 3, target.length));
    el.textContent = built;
    i++;
  }, 30);
}

// ===== PANEL SWITCHING =====
function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sb-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.mobile-nav-btn').forEach(b => b.classList.toggle('active', b.dataset.panel === name));
  const panel = document.getElementById('panel-' + name);
  const btn = document.querySelector(`.sb-btn[data-panel="${name}"]`);
  if (panel) panel.classList.add('active');
  if (btn) btn.classList.add('active');
  if (name === 'memory') loadMemory();
  if (name === 'chat') initChat();
}

// ===== SERVER STATUS =====
function updateServerStatus(status) {
  serverStatus = status;
  const toggleBtn = document.getElementById('aiToggle');
  const activateText = document.getElementById('activateText');
  const aiStatusEl = document.getElementById('aiStatus');
  const coreStatus = document.getElementById('coreStatus');
  const fridayStatus = document.getElementById('fridayStatus');
  const portrait = document.querySelector('.ph-img');
  const bbNet = document.getElementById('bbNet');

  if (status === 'ready') {
    if (aiStatusEl) aiStatusEl.innerHTML = '<span class="dot on"></span>ONLINE';
    if (coreStatus) { coreStatus.textContent = 'ONLINE'; coreStatus.style.color = 'var(--gn)'; }
    if (fridayStatus) fridayStatus.textContent = 'ACTIVE';
    if (activateText) activateText.textContent = 'SHUTDOWN FRIDAY';
    if (toggleBtn) toggleBtn.classList.add('active-state');
    if (portrait) {
      portrait.style.borderColor = 'var(--gn)';
      portrait.style.boxShadow = '0 0 20px rgba(64,255,144,0.3), 0 0 40px rgba(64,255,144,0.1)';
    }
    connectWebSocket();
  } else if (status === 'error') {
    if (aiStatusEl) aiStatusEl.innerHTML = '<span class="dot off"></span>ERROR';
    if (coreStatus) { coreStatus.textContent = 'ERROR'; coreStatus.style.color = 'var(--rd)'; }
    if (fridayStatus) fridayStatus.textContent = 'ERROR';
    if (activateText) activateText.textContent = 'RETRY ACTIVATION';
    if (portrait) { portrait.style.borderColor = 'var(--rd)'; }
    if (bbNet) { bbNet.textContent = 'ERROR'; bbNet.classList.remove('bb-online'); }
  } else {
    if (aiStatusEl) aiStatusEl.innerHTML = '<span class="dot off"></span>OFFLINE';
    if (coreStatus) { coreStatus.textContent = 'STANDBY'; coreStatus.style.color = ''; }
    if (fridayStatus) fridayStatus.textContent = 'IDLE';
    if (activateText) activateText.textContent = 'ACTIVATE FRIDAY';
    if (toggleBtn) toggleBtn.classList.remove('active-state');
    if (portrait) { portrait.style.borderColor = ''; portrait.style.boxShadow = ''; }
    if (bbNet) { bbNet.textContent = 'OFFLINE'; bbNet.classList.remove('bb-online'); }
  }
}

function toggleFriday() {
  if (serverStatus === 'ready' || serverStatus === 'starting') {
    send('stop-friday');
  } else {
    send('start-friday');
  }
}

// ===== WEBSOCKET CHAT =====
function connectWebSocket() {
  if (ws && ws.readyState <= 1) return;
  try {
    ws = new WebSocket(`${getBackendBase('ws')}/ws`);
    ws.onopen = () => {
      addLogEntry({ level: 'info', message: 'WebSocket connected to F.R.I.D.A.Y.', timestamp: Date.now() });
      updateChatStatus(true);
      refreshBackendHealth();
    };
    ws.onmessage = (e) => {
      try { handleWSMessage(JSON.parse(e.data)); }
      catch (error) {
        addLogEntry({ level: 'error', message: `Protocol error: ${error.message}`, timestamp: Date.now() });
      }
    };
    ws.onclose = () => {
      updateChatStatus(false);
      setTimeout(connectWebSocket, 3000);
    };
    ws.onerror = () => {};
  } catch {}
}

function handleWSMessage(msg) {
  const coreStatus = document.getElementById('coreStatus');
  const fridayStatus = document.getElementById('fridayStatus');
  if (window._handleChatDelta) window._handleChatDelta(msg);

  switch (msg.type) {
    case 'state': {
      const stateMap = { idle: 'STANDBY', listening: 'LISTENING', awake: 'YES BOSS', thinking: 'THINKING', speaking: 'SPEAKING', executing: 'EXECUTING', awaiting: 'CONFIRM' };
      const label = stateMap[msg.value] || msg.value.toUpperCase();
      if (coreStatus) coreStatus.textContent = label;
      if (fridayStatus) fridayStatus.textContent = label;

      const portrait = document.querySelector('.ph-img');
      if (portrait) {
        if (msg.value === 'thinking') {
          if (window._chatShowThinking) window._chatShowThinking();
          portrait.style.borderColor = 'var(--am)';
          portrait.style.boxShadow = '0 0 20px rgba(255,182,72,0.3), 0 0 40px rgba(255,182,72,0.1)';
        } else if (msg.value === 'speaking') {
          if (window._chatHideThinking) window._chatHideThinking();
          portrait.style.borderColor = 'var(--cyb)';
          portrait.style.boxShadow = '0 0 20px rgba(32,160,255,0.4), 0 0 40px rgba(32,160,255,0.15)';
        } else if (serverStatus === 'ready') {
          if (window._chatHideThinking) window._chatHideThinking();
          portrait.style.borderColor = 'var(--gn)';
          portrait.style.boxShadow = '0 0 20px rgba(64,255,144,0.3), 0 0 40px rgba(64,255,144,0.1)';
        }
      }
      break;
    }
    case 'memory_stats': {
      const facts = msg.facts || 0;
      const eps = msg.episodes || 0;
      const factsEl = document.getElementById('memoryFacts');
      const epsEl = document.getElementById('memoryEpisodes');
      const memStatus = document.getElementById('memStatus');
      if (factsEl) factsEl.textContent = facts;
      if (epsEl) epsEl.textContent = eps;
      if (memStatus) memStatus.textContent = `${facts}`;
      break;
    }
    case 'memory_list': {
      renderMemory(msg.facts || []);
      break;
    }
    case 'confirmation': {
      showChatConfirmation(msg.action);
      break;
    }
    case 'confirmation_resolved': {
      clearInterval(confirmationTimer);
      document.getElementById('chatConfirmation')?.remove();
      break;
    }
    case 'tool_started':
      addLogEntry({ level: 'info', message: `Running: ${msg.action?.title || 'tool'}`, timestamp: Date.now() });
      renderToolTimeline(msg.action || {});
      break;
    case 'tool_result':
      addLogEntry({ level: msg.result?.ok ? 'info' : 'error', message: msg.result?.message || 'Tool finished', timestamp: Date.now() });
      renderToolTimeline(msg.action || {}, msg.result || { ok: false, message: 'No result details were provided.' });
      break;
    case 'error':
      addLogEntry({ level: 'error', message: msg.text || 'Backend error', timestamp: Date.now() });
      break;
    case 'mic': {
      const micEl = document.getElementById('micStatus');
      const voiceStatus = document.getElementById('voiceStatus');
      if (micEl) micEl.innerHTML = msg.active
        ? '<span class="dot on"></span>ACTIVE'
        : '<span class="dot off"></span>MUTED';
      if (voiceStatus) voiceStatus.textContent = msg.active ? 'LISTENING' : 'KOKORO';
      break;
    }
    case 'guardian': {
      const gEl = document.getElementById('guardianStatus');
      const guardianBadge = document.getElementById('guardianBadge');
      const gDot = document.getElementById('guardianDot');
      const alert = document.getElementById('guardianAlert');
      const msgEl = document.getElementById('guardianMessage');
      if (msg.active) {
        if (gEl) gEl.innerHTML = '<span class="dot off"></span>ALERT';
        if (guardianBadge) guardianBadge.textContent = 'ALERT';
        if (gDot) { gDot.classList.add('hc-active'); gDot.style.background = 'var(--am)'; }
        if (alert) { alert.classList.add('open'); alert.setAttribute('aria-hidden', 'false'); }
        if (msgEl) msgEl.textContent = msg.message;
        addLogEntry({ level: 'warn', message: `Guardian: ${msg.message}`, timestamp: Date.now() });
      } else {
        if (gEl) gEl.innerHTML = '<span class="dot on"></span>ACTIVE';
        if (guardianBadge) guardianBadge.textContent = 'ACTIVE';
        if (gDot) { gDot.classList.remove('hc-active'); gDot.style.background = ''; }
        if (alert) { alert.classList.remove('open'); alert.setAttribute('aria-hidden', 'true'); }
      }
      break;
    }
    case 'vision': {
      const vw = document.getElementById('visionWarning');
      if (vw) {
        vw.classList.toggle('open', msg.active);
        vw.setAttribute('aria-hidden', String(!msg.active));
      }
      break;
    }
  }
}

function updateChatStatus(connected) {
  const dot = document.getElementById('chatStatusDot');
  const text = document.getElementById('chatStatusText');
  const conn = document.getElementById('chatConnecting');
  const frame = document.getElementById('chatFrame');
  const bbNet = document.getElementById('bbNet');
  if (connected) {
    if (dot) dot.classList.add('connected');
    if (text) text.textContent = 'NEURAL LINK ACTIVE';
    if (conn) conn.style.display = 'none';
    if (frame) frame.style.display = 'flex';
    if (bbNet) { bbNet.textContent = 'LINKED'; bbNet.classList.add('bb-online'); }
  } else {
    if (dot) dot.classList.remove('connected');
    if (text) text.textContent = 'RECONNECTING...';
    if (conn) conn.style.display = 'flex';
    if (frame) frame.style.display = 'none';
    if (bbNet) { bbNet.textContent = 'OFFLINE'; bbNet.classList.remove('bb-online'); }
  }
}

function initChatLogic(container) {
  const chatLog = container.querySelector ? container.querySelector('#chatLog') : document.getElementById('chatLog');
  const inputBar = container.querySelector ? container.querySelector('#inputBar') : document.getElementById('inputBar');
  const textInput = container.querySelector ? container.querySelector('#chatInput') : document.getElementById('chatInput');
  const fileInput = container.querySelector ? container.querySelector('#chatFile') : document.getElementById('chatFile');
  const attachBtn = container.querySelector ? container.querySelector('#attachBtn') : document.getElementById('attachBtn');
  if (!chatLog || !inputBar || !textInput) return;

  let assistantBubble = null;
  let typingBubble = null;
  let pendingAttachments = [];

  const showThinking = () => {
    if (typingBubble) return;
    typingBubble = document.createElement('div');
    typingBubble.className = 'bubble fri typing';
    typingBubble.innerHTML =
      '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
    chatLog.appendChild(typingBubble);
    chatLog.scrollTop = chatLog.scrollHeight;
  };
  const hideThinking = () => {
    if (typingBubble) {
      typingBubble.remove();
      typingBubble = null;
    }
  };
  window._chatShowThinking = showThinking;
  window._chatHideThinking = hideThinking;

  attachBtn?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', async () => {
    for (const file of [...fileInput.files].slice(0, 10)) {
      const form = new FormData();
      form.append('file', file, file.name);
      try {
        const response = await fetch(`${getBackendBase('http')}/upload`, { method: 'POST', body: form });
        if (!response.ok) {
          let detail = `Upload failed (${response.status})`;
          try { detail = (await response.json()).detail || detail; } catch {}
          addChatBubble(chatLog, 'fri', detail);
          continue;
        }
        const attachment = await response.json();
        pendingAttachments.push(attachment);
        addChatBubble(chatLog, 'boss', `Attached: ${attachment.name}`);
      } catch (error) {
        addChatBubble(chatLog, 'fri', `Upload failed: ${error.message || 'network error'}`);
      }
    }
    fileInput.value = '';
  });

  inputBar.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if ((!text && !pendingAttachments.length) || !ws || ws.readyState !== 1) return;
    const attachments = pendingAttachments;
    pendingAttachments = [];
    textInput.value = '';
    addChatBubble(chatLog, 'boss', text || '[image]');
    assistantBubble = null;
    ws.send(JSON.stringify({ type: 'chat', text, attachments }));
  });

  window._handleChatDelta = (msg) => {
    if (msg.type === 'delta') {
      hideThinking();
      if (!assistantBubble) {
        assistantBubble = addChatBubble(chatLog, 'fri streaming', '');
        assistantBubble._full = '';
      }
      assistantBubble._full += msg.text;
      assistantBubble.textContent = assistantBubble._full;
      chatLog.scrollTop = chatLog.scrollHeight;
    } else if (msg.type === 'assistant') {
      hideThinking();
      if (assistantBubble) {
        assistantBubble.classList.remove('streaming');
        assistantBubble = null;
      } else {
        addChatBubble(chatLog, 'fri', msg.text);
      }
    } else if (msg.type === 'response_complete') {
      hideThinking();
      if (assistantBubble && typeof msg.text === 'string') {
        assistantBubble._full = msg.text;
        assistantBubble.textContent = msg.text;
      }
      if (assistantBubble) assistantBubble.classList.remove('streaming');
      assistantBubble = null;
    } else if (msg.type === 'error') {
      hideThinking();
      if (assistantBubble) assistantBubble.remove();
      assistantBubble = null;
      addChatBubble(chatLog, 'fri', msg.text || 'The backend could not complete that request.');
    } else if (msg.type === 'user' && msg.source === 'voice') {
      addChatBubble(chatLog, 'boss', msg.text);
      assistantBubble = null;
    } else if (msg.type === 'interrupted') {
      hideThinking();
      if (assistantBubble) assistantBubble.classList.remove('streaming');
    }
  };
}

function addChatBubble(log, cls, text) {
  const b = document.createElement('div');
  b.className = 'bubble ' + cls;
  b.textContent = text;
  log.appendChild(b);
  log.scrollTop = log.scrollHeight;
  return b;
}

function initChat() {
  if (ws && ws.readyState === 1) updateChatStatus(true);
}

// ===== LOGGING =====
function addLogEntry(data) {
  logEntries.push(data);
  renderLogEntry(data);
}

function renderLogEntry(data) {
  const container = document.getElementById('logsContainer');
  if (!container) return;
  const empty = container.querySelector('.log-empty');
  if (empty) empty.remove();
  if (currentFilter !== 'all' && data.level !== currentFilter) return;

  const entry = document.createElement('div');
  entry.className = `log-entry log-${data.level}`;
  const time = new Date(data.timestamp);
  const ts = time.toLocaleTimeString('en-US', { hour12: false }) + '.' + String(time.getMilliseconds()).padStart(3, '0');
  entry.innerHTML = `<span class="log-time">${ts}</span><span class="log-level">${data.level.toUpperCase().padEnd(5)}</span><span class="log-msg">${escapeHtml(data.message)}</span>`;
  container.appendChild(entry);
  if (autoScroll) container.scrollTop = container.scrollHeight;
  document.getElementById('logCount').textContent = logEntries.length;
}

function filterLogs(filter) {
  currentFilter = filter;
  document.querySelectorAll('.lf').forEach(b => b.classList.remove('active'));
  document.querySelector(`.lf[data-filter="${filter}"]`)?.classList.add('active');
  const container = document.getElementById('logsContainer');
  container.innerHTML = '';
  const filtered = filter === 'all' ? logEntries : logEntries.filter(e => e.level === filter);
  if (filtered.length === 0) { container.innerHTML = '<div class="log-empty">// NO ENTRIES FOR THIS FILTER.</div>'; return; }
  filtered.forEach(e => renderLogEntry(e));
}

function clearLogs() {
  logEntries = [];
  document.getElementById('logsContainer').innerHTML = '<div class="log-empty">// LOGS CLEARED.</div>';
  document.getElementById('logCount').textContent = '0';
}

function exportLogs() {
  const text = logEntries.map(e => `[${new Date(e.timestamp).toISOString()}] [${e.level.toUpperCase()}] ${e.message}`).join('\n');
  const blob = new Blob([text], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `friday-logs-${new Date().toISOString().slice(0, 10)}.txt`;
  a.click();
}

// ===== MEMORY =====
function loadMemory() {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'memory_list' }));
    return;
  }
}

function renderMemory(facts) {
  const list = document.getElementById('memoryList');
  if (!list) return;
  if (!facts.length) {
    list.innerHTML = '<div class="mem-empty">// NO FACTS STORED.</div>';
    return;
  }
  list.innerHTML = '';
  facts.forEach(fact => {
    const item = document.createElement('article');
    item.className = 'mem-item';
    const text = document.createElement('p');
    text.textContent = fact.text;
    const meta = document.createElement('div');
    meta.className = 'mem-meta';
    const category = document.createElement('span');
    category.className = 'mem-cat';
    category.textContent = (fact.category || 'GENERAL').toUpperCase();
    const forget = document.createElement('button');
    forget.className = 'mem-forget';
    forget.textContent = 'FORGET';
    forget.addEventListener('click', () => ws?.send(JSON.stringify({ type: 'memory_forget', id: fact.id })));
    meta.append(category, forget);
    item.append(text, meta);
    list.appendChild(item);
  });
}

function showChatConfirmation(action) {
  const log = document.getElementById('chatLog');
  if (!log || !action) return;
  document.getElementById('chatConfirmation')?.remove();
  const panel = document.createElement('div');
  panel.id = 'chatConfirmation';
  panel.className = 'chat-confirmation';
  panel.setAttribute('role', 'alertdialog');
  panel.setAttribute('aria-label', 'Confirm action');
  const title = document.createElement('strong');
  title.textContent = action.title || 'CONFIRM ACTION';
  const description = document.createElement('span');
  description.textContent = action.description || '';
  const actions = document.createElement('div');
  const expiry = document.createElement('small');
  let seconds = 60;
  expiry.textContent = `Expires in ${seconds} seconds.`;
  const deny = document.createElement('button');
  deny.textContent = 'DENY';
  const decide = (approved) => {
    if (ws?.readyState !== 1) return;
    ws.send(JSON.stringify({ type: approved ? 'tool_confirm' : 'tool_deny', id: action.id }));
    deny.disabled = true;
    approve.disabled = true;
    expiry.textContent = approved ? 'APPROVING...' : 'DENYING...';
  };
  deny.addEventListener('click', () => decide(false));
  const approve = document.createElement('button');
  approve.textContent = 'APPROVE';
  approve.addEventListener('click', () => decide(true));
  actions.append(deny, approve);
  panel.append(title, description, actions, expiry);
  log.appendChild(panel);
  log.scrollTop = log.scrollHeight;
  approve.focus();
  clearInterval(confirmationTimer);
  confirmationTimer = setInterval(() => {
    seconds -= 1;
    expiry.textContent = seconds > 0 ? `Expires in ${seconds} seconds.` : 'Confirmation expired.';
    if (seconds <= 0) { clearInterval(confirmationTimer); panel.remove(); }
  }, 1000);
  panel.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !deny.disabled) deny.click();
  });
}

function renderToolTimeline(action, result = null) {
  const log = document.getElementById('chatLog');
  if (!log) return;
  const id = action.id || `${action.name || 'tool'}-${Date.now()}`;
  let item = toolTimeline.get(id);
  if (!item) {
    const el = document.createElement('article');
    el.className = 'tool-event';
    const name = document.createElement('span');
    name.className = 'tool-event-name';
    const title = document.createElement('span');
    title.className = 'tool-event-title';
    const state = document.createElement('span');
    state.className = 'tool-event-state';
    const message = document.createElement('div');
    message.className = 'tool-event-message';
    name.textContent = action.name || 'tool';
    title.textContent = action.title || 'Tool action';
    state.textContent = 'RUNNING';
    message.textContent = action.description || '';
    el.append(name, title, state, message);
    item = { el, state, message };
    toolTimeline.set(id, item);
    log.appendChild(el);
  }
  if (result) {
    item.el.classList.add(result.ok ? 'done' : 'error');
    item.state.textContent = result.ok ? 'COMPLETE' : 'FAILED';
    item.message.textContent = result.message || item.message.textContent;
  }
  log.scrollTop = log.scrollHeight;
}

function getBackendBase(protocol = 'http') {
  const port = Number(fridaySettings.port) || 8000;
  return `${protocol}://127.0.0.1:${port}`;
}

async function refreshBackendHealth() {
  try {
    const response = await fetch(`${getBackendBase('http')}/health`, { cache: 'no-store' });
    if (!response.ok) return;
    const health = await response.json();
    const mode = health.reasoning === 'openrouter' ? 'OPENROUTER' : 'LOCAL';
    document.getElementById('engineModeDisplay').textContent = mode;
    document.getElementById('engineModelDisplay').textContent = mode === 'OPENROUTER'
      ? (health.cloud_model || 'OpenRouter model')
      : (health.local_model || 'Local backend model');
    document.getElementById('cloudModelDisplay').textContent = health.cloud_model || 'Not in use';
    syncModeSwitch(health.reasoning === 'openrouter' ? 'openrouter' : 'local');
  } catch {}
}

function syncModeSwitch(mode) {
  const enabled = mode === 'openrouter' ? 'openrouter' : 'local';
  document.querySelectorAll('#tbModeSwitch .tb-mode-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.mode === enabled);
  });
  const select = document.getElementById('setReasoningMode');
  if (select) select.value = enabled;
}

async function switchMode(mode) {
  if (mode !== 'local' && mode !== 'openrouter') return;
  syncModeSwitch(mode);
  try {
    const response = await fetch(`${getBackendBase('http')}/settings/mode?mode=${encodeURIComponent(mode)}`, { method: 'POST' });
    if (response.ok) {
      addLogEntry({ level: 'info', message: `Mode switched to ${mode}.`, timestamp: Date.now() });
    } else {
      addLogEntry({ level: 'warn', message: `Mode switch to ${mode} rejected by backend.`, timestamp: Date.now() });
    }
  } catch {
    addLogEntry({ level: 'warn', message: `Backend offline; mode will apply on next start (${mode}).`, timestamp: Date.now() });
  }
  fridaySettings = Object.assign({}, fridaySettings, { reasoningMode: mode });
  const cloudModelInput = document.getElementById('setCloudModel');
  if (cloudModelInput) cloudModelInput.disabled = mode === 'local';
  updateConfiguredModelDisplay(Object.assign({}, fridaySettings, { reasoningMode: mode }));
  try { await ipcRenderer.invoke('save-settings', fridaySettings); } catch {}
}

function sendWs(type) {
  if (ws?.readyState === 1) ws.send(JSON.stringify({ type }));
}

// ===== SETTINGS =====
async function loadSettings() {
  try { fridaySettings = await ipcRenderer.invoke('get-settings'); applySettingsToUI(fridaySettings); } catch {}
}

function applySettingsToUI(s) {
  const set = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.value = v; };
  const setChk = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.checked = v; };
  set('setWakeWord', s.wakeWord); set('setTtsMode', s.ttsMode); set('setLocalVoice', s.localVoice);
  set('setLanguage', s.language); set('setPort', s.port); set('setHost', s.host);
  set('setPairingToken', s.pairingToken);
  set('setReasoningMode', s.reasoningMode || 'local'); set('setCloudModel', s.cloudModel || '');
  set('setMaxTokens', s.maxTokens); set('setContextTurns', s.contextTurns);
  setChk('setMicDefault', s.micDefaultOn); set('setWakeWindow', s.wakeWindow);
  set('setMinRms', s.minRms); set('setVadThreshold', s.vadThreshold);
  set('setMemFacts', s.memFacts); set('setMemEpisodes', s.memEpisodes);
  set('setCpuThreshold', s.cpuThreshold); set('setRamThreshold', s.ramThreshold);
  set('setGpuThreshold', s.gpuThreshold); set('setGuardianInterval', s.guardianInterval);
  setChk('setAutoStart', s.autoStart);
  updateConfiguredModelDisplay(s);
}

function updateConfiguredModelDisplay(settings) {
  const mode = settings.reasoningMode === 'openrouter' ? 'OPENROUTER' : 'LOCAL';
  const cloudModelInput = document.getElementById('setCloudModel');
  document.getElementById('engineModeDisplay').textContent = mode;
  document.getElementById('engineModelDisplay').textContent = mode === 'LOCAL' ? 'Configured by backend' : (settings.cloudModel || 'Not specified');
  document.getElementById('cloudModelDisplay').textContent = mode === 'OPENROUTER' ? (settings.cloudModel || 'Not specified') : 'Not in use';
  if (cloudModelInput) {
    cloudModelInput.disabled = mode === 'LOCAL';
    cloudModelInput.setAttribute('aria-disabled', String(mode === 'LOCAL'));
  }
}

async function saveSettings() {
  const g = (id) => document.getElementById(id);
  const val = (id) => g(id)?.value || '';
  const num = (id) => parseInt(val(id)) || 0;
  const fnum = (id) => parseFloat(val(id)) || 0;
  const chk = (id) => g(id)?.checked || false;
  const settings = {
    wakeWord: val('setWakeWord'), ttsMode: val('setTtsMode'), localVoice: val('setLocalVoice'),
    language: val('setLanguage'), port: num('setPort'), host: val('setHost'),
    reasoningMode: val('setReasoningMode'), cloudModel: val('setCloudModel'),
    maxTokens: num('setMaxTokens'), contextTurns: num('setContextTurns'),
    micDefaultOn: chk('setMicDefault'), wakeWindow: fnum('setWakeWindow'),
    minRms: fnum('setMinRms'), vadThreshold: fnum('setVadThreshold'),
    memFacts: num('setMemFacts'), memEpisodes: num('setMemEpisodes'),
    cpuThreshold: fnum('setCpuThreshold'), ramThreshold: fnum('setRamThreshold'),
    gpuThreshold: fnum('setGpuThreshold'), guardianInterval: fnum('setGuardianInterval'),
    autoStart: chk('setAutoStart'),
  };
  await ipcRenderer.invoke('save-settings', settings);
  fridaySettings = settings;
  updateConfiguredModelDisplay(settings);
  addLogEntry({ level: 'info', message: 'Configuration saved.', timestamp: Date.now() });
}

function resetSettings() {
  applySettingsToUI({
    wakeWord: 'friday', ttsMode: 'local', localVoice: 'bf_isabella', language: 'ms', reasoningMode: 'local', cloudModel: 'z-ai/glm-5.3-flash',
    port: 8000, host: '127.0.0.1', maxTokens: 512, contextTurns: 10, micDefaultOn: true,
    wakeWindow: 8, minRms: 280, vadThreshold: 0.5, memFacts: 6, memEpisodes: 2,
    cpuThreshold: 85, ramThreshold: 90, gpuThreshold: 85, guardianInterval: 30, autoStart: false,
  });
}

// ===== SYSTEM MONITORING =====
async function updateSystemInfo() {
  try {
    const info = await ipcRenderer.invoke('get-system-info');
    const usedPct = ((1 - parseFloat(info.freeMemory) / parseFloat(info.totalMemory)) * 100).toFixed(0);
    const usedGB = (parseFloat(info.totalMemory) - parseFloat(info.freeMemory)).toFixed(1);
    const totalGB = info.totalMemory;
    updateMeter('ram', usedPct);
    updateMeter('cpu', info.cpuUsage || 0);
    document.getElementById('tbCpu').textContent = `${info.cpuUsage || 0}%`;
    document.getElementById('tbMem').textContent = `${usedPct}%`;
    document.getElementById('cpuLabel').textContent = info.cpuModel;
    const cpuCores = document.getElementById('cpuCores');
    if (cpuCores && info.cpus) cpuCores.textContent = info.cpus;
    const ramLabel = document.getElementById('ramLabel');
    if (ramLabel) ramLabel.textContent = `${totalGB}GB SYSTEM MEMORY`;
    const ramUsed = document.getElementById('ramUsed');
    const ramUsedStat = document.getElementById('ramUsedStat');
    const ramFreeStat = document.getElementById('ramFreeStat');
    if (ramUsed) ramUsed.textContent = `${usedGB}GB / ${totalGB}GB`;
    if (ramUsedStat) ramUsedStat.textContent = `${usedGB}GB`;
    if (ramFreeStat) ramFreeStat.textContent = `${info.freeMemory}GB`;
    const uptimeEl = document.getElementById('uptimeVal');
    if (uptimeEl) uptimeEl.textContent = `${info.uptime}h`;
  } catch {}
}

function updateMeter(type, pct, label) {
  const p = Math.min(100, Math.max(0, parseFloat(pct)));
  const circumference = 534;
  const offset = circumference - (p / 100) * circumference;
  const arc = document.querySelector('.gauge-arc[data-type="' + type + '"]');
  const val = document.getElementById(type + 'Val');
  if (arc) arc.setAttribute('stroke-dashoffset', offset);
  if (val) val.textContent = Math.round(p) + '%';
}

function setPerfMode(mode) {
  document.querySelectorAll('.perf-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.perf-btn[data-mode="${mode}"]`)?.classList.add('active');
  addLogEntry({ level: 'info', message: `Performance mode: ${mode.toUpperCase()}`, timestamp: Date.now() });
}

setInterval(updateSystemInfo, 5000);

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ===== GUARDIAN DISMISS =====
document.getElementById('guardianDismiss')?.addEventListener('click', () => {
  const a = document.getElementById('guardianAlert');
  if (a) { a.classList.remove('open'); a.setAttribute('aria-hidden', 'true'); }
});

// ===== ANIMATED COORDINATE SCRAMBLE =====
document.addEventListener('DOMContentLoaded', () => {
  const coordEl = document.getElementById('bbCoord');
  if (coordEl) scrambleCoord(coordEl);
});

// ===== INIT =====
document.addEventListener('DOMContentLoaded', () => {
  const chatFrame = document.getElementById('chatFrame');
  if (chatFrame) initChatLogic(chatFrame);
  document.getElementById('setReasoningMode')?.addEventListener('change', (event) => {
    updateConfiguredModelDisplay({
      reasoningMode: event.target.value,
      cloudModel: document.getElementById('setCloudModel')?.value || '',
    });
  });
  document.getElementById('setCloudModel')?.addEventListener('input', (event) => {
    updateConfiguredModelDisplay({ reasoningMode: 'openrouter', cloudModel: event.target.value });
  });
});

document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  updateSystemInfo();
  addLogEntry({ level: 'info', message: 'F.R.I.D.A.Y. HUD Launcher v3.0 initialized.', timestamp: Date.now() });
  addLogEntry({ level: 'info', message: 'Stark Industries Neural Interface Protocol loaded.', timestamp: Date.now() });
  addLogEntry({ level: 'info', message: 'Initializing backend server...', timestamp: Date.now() });
  if (fridaySettings.autoStart !== false) send('start-friday');
});
