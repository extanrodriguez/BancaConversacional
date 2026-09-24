const DEV_MODE = new URLSearchParams(location.search).has("dev");
const DEFAULT_PORTFOLIO = "mvp_cuentas_multi.json";

const state = {
  apiBase: "",
  customerId: "",
  displayName: "",
  conversationId: "",
  contextLoaded: false,
  busy: false,
  users: [],
  abort: null,
  skipPasskeyNext: true,
  lastLoaded: null,
};

const $ = (id) => document.getElementById(id);

function initials(name) {
  const parts = (name || "VP").trim().split(/\s+/);
  return ((parts[0] || "V")[0] + (parts[1] || parts[0] || "P")[0]).toUpperCase();
}

function nowTime() {
  return new Date().toLocaleTimeString("es-DO", { hour: "2-digit", minute: "2-digit" });
}

function newConversationId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    try {
      return crypto.randomUUID();
    } catch {
      /* HTTP remoto no es contexto seguro */
    }
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function showScreen(name) {
  const map = {
    login: $("screenLogin"),
    passkey: $("screenPasskey"),
    chat: $("screenChat"),
  };
  for (const [key, el] of Object.entries(map)) {
    const on = key === name;
    el.hidden = !on;
    el.classList.toggle("hidden", !on);
  }
}

function apiUrl(path) {
  return `${state.apiBase}${path}`;
}

async function api(path, options = {}) {
  const res = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    signal: options.signal,
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg =
      data.error ||
      (typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : "") ||
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

/** Resuelve customerId lab o usa el valor digitado tal cual (como APK). */
function resolveLabUser(raw) {
  const value = (raw || "").trim();
  if (!value) return null;
  const lower = value.toLowerCase();
  const byId = state.users.find((u) => u.customer_id.toLowerCase() === lower);
  if (byId) return byId;
  return {
    customer_id: value,
    label: value,
    portfolio: DEFAULT_PORTFOLIO,
  };
}

/** Texto de selección con dígitos del ref (evita labels ambiguos → LLM lento). */
function optionSelectionText(opt) {
  const ref = String(opt.ref || "");
  const label = String(opt.label || opt.ref || "producto");
  const digits = (ref.match(/(\d{4,})$/) || [])[1] || (label.match(/(\d{4,})\s*$/) || [])[1] || "";
  if (digits) {
    if (/\d{4,}/.test(label)) return label;
    return `${label.replace(/\s*···\d+\s*$/, "").trim()} terminada en ${digits}`;
  }
  return ref || label;
}

function scrollChatToEnd() {
  const body = $("chatBody") || document.querySelector(".chat-body");
  if (body) body.scrollTop = body.scrollHeight;
}

function appendUser(text) {
  const chat = $("chat");
  const row = document.createElement("div");
  row.className = "row user";
  row.innerHTML = `<div class="col"><div class="bubble"></div><div class="meta-time">${nowTime()}</div></div>`;
  row.querySelector(".bubble").textContent = text;
  chat.appendChild(row);
  scrollChatToEnd();
}

function appendTyping() {
  const chat = $("chat");
  const row = document.createElement("div");
  row.className = "row bot";
  row.id = "typingRow";
  row.innerHTML = `<div class="typing" aria-label="Escribiendo"><span></span></div>`;
  chat.appendChild(row);
  scrollChatToEnd();
}

function removeTyping() {
  $("typingRow")?.remove();
}

function renderMarkdownLite(text) {
  const esc = String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function appendBot(text, options = [], suggestions = [], meta = {}) {
  removeTyping();
  const chat = $("chat");
  const row = document.createElement("div");
  row.className = "row bot";
  const col = document.createElement("div");
  col.className = "col";
  const wrap = document.createElement("div");
  wrap.style.display = "flex";
  wrap.style.gap = "8px";
  wrap.style.alignItems = "flex-end";
  wrap.innerHTML = `<span class="bot-mark"></span>`;
  const bubble = document.createElement("div");
  bubble.className = "bubble product-rich";
  const fmt = (meta && meta.content_format) || (/\*\*|• /.test(text || "") ? "markdown" : "plain");
  if (fmt === "markdown") {
    bubble.innerHTML = renderMarkdownLite(text);
  } else {
    bubble.textContent = text;
  }
  wrap.appendChild(bubble);
  col.appendChild(wrap);
  if (options.length) {
    const cards = document.createElement("div");
    cards.className = "cards";
    for (const opt of options) {
      const btn = document.createElement("button");
      btn.className = "option-card";
      btn.type = "button";
      const label = opt.label || opt.ref;
      btn.innerHTML = `<span><strong></strong><small></small></span><span class="chev">›</span>`;
      btn.querySelector("strong").textContent = label;
      btn.querySelector("small").textContent = `${opt.product_type || "PRODUCTO"} · ${opt.currency || ""}`.trim();
      btn.addEventListener("click", () => sendText(optionSelectionText(opt)));
      cards.appendChild(btn);
    }
    col.appendChild(cards);
  }
  if (suggestions.length) {
    const chips = document.createElement("div");
    chips.className = "cards suggestions";
    for (const s of suggestions) {
      const btn = document.createElement("button");
      btn.className = "option-card";
      btn.type = "button";
      btn.textContent = s.question || s.label || "";
      btn.addEventListener("click", () => sendText(s.question || s.label || ""));
      chips.appendChild(btn);
    }
    col.appendChild(chips);
  }
  const time = document.createElement("div");
  time.className = "meta-time";
  time.textContent = nowTime();
  col.appendChild(time);
  row.appendChild(col);
  chat.appendChild(row);
  scrollChatToEnd();
}

function setBusy(busy) {
  state.busy = busy;
  const locked = busy || !state.contextLoaded;
  $("input").disabled = locked;
  $("btnSend").disabled = locked;
  $("btnQaScript").disabled = locked;
  $("btnExcel").disabled = locked;
  $("btnLogin").disabled = busy;
}

function renderSession(loaded) {
  const meta = $("sessionMeta");
  const first = state.displayName.split(/\s+/)[0] || "Cliente";
  $("heroGreeting").textContent = `Hola, ${first}`;
  $("avatar").textContent = initials(state.displayName);
  $("connStatus").textContent =
    loaded.context_source === "core_websocket"
      ? "Contexto vía WebSocket Core"
      : loaded.context_source === "core_http"
        ? "Contexto vía HTTP Core"
      : loaded.context_source === "lab_fallback"
        ? "Contexto lab (Core WS no alcanzable)"
        : "Conectado al asistente";
  meta.querySelectorAll("dd").forEach((dd, i) => {
    const vals = [
      state.displayName || state.customerId,
      state.customerId,
      state.conversationId,
      String(loaded.products_count ?? "—"),
    ];
    dd.textContent = vals[i] ?? "—";
  });
}

async function loadUsuarios() {
  state.apiBase = $("apiBase").value;
  const select = $("customerSelect");
  select.innerHTML = "";
  try {
    state.users = await api("/lab/usuarios");
    for (const user of state.users) {
      const opt = document.createElement("option");
      opt.value = user.customer_id;
      opt.textContent = `${user.label} (${user.customer_id})`;
      select.appendChild(opt);
    }
    const preferred = state.users.find((u) => u.customer_id === "TEST-QA-001") || state.users[0];
    if (preferred) {
      select.value = preferred.customer_id;
      $("loginUser").value = preferred.customer_id;
      $("customerId").value = preferred.customer_id;
    }
  } catch (err) {
    $("loginStatus").textContent = `Sin usuarios de lab: ${err.message}`;
    $("loginUser").value = "TEST-QA-001";
  }
}

async function fillContextFromUser(customerId) {
  const user = state.users.find((u) => u.customer_id === customerId);
  if (!user || !user.portfolio) return;
  const data = await api(`/lab/portfolios/${user.portfolio}`);
  $("contextJson").value = JSON.stringify(data, null, 2);
  $("customerId").value = customerId;
  $("loginUser").value = customerId;
}

/**
 * Arranque estilo orquestador/APK:
 * 1) customerId → el backend abre WebSocket Core (wss://.../ws/?customerId=)
 * 2) Con el portafolio → POST /turn context_info=true, question=null
 * 3) Preguntas: context_info=false + question → /orch/chat/front
 */
async function startOrchestratorSession(labUser) {
  const conversationId = newConversationId();
  const loaded = await api("/orch/context", {
    method: "POST",
    body: JSON.stringify({
      customer_id: labUser.customer_id,
      conversation_id: conversationId,
      allow_lab_fallback: true,
      portfolio: labUser.portfolio || DEFAULT_PORTFOLIO,
    }),
  });
  if (loaded.status !== "CONTEXT_LOADED" && loaded.status !== "CONTEXT_REFRESHED") {
    throw new Error(loaded.error || loaded.status || "No se pudo iniciar la sesión");
  }
  state.customerId = loaded.customer_id || labUser.customer_id;
  state.conversationId = loaded.conversation_id || conversationId;
  state.displayName = loaded.display_name || labUser.customer_id;
  state.contextLoaded = true;
  state.lastLoaded = loaded;
  $("customerId").value = state.customerId;
  if (loaded.context_source === "lab_fallback") {
    console.warn("[pruebas] WebSocket Core no alcanzable; usando portafolio lab", loaded.core_error);
  } else if (loaded.context_source === "core_websocket") {
    console.info("[pruebas] Contexto cargado vía WebSocket Core", loaded.core_websocket_url);
  }
  return loaded;
}

/** Payload canal delgado (APK) hacia orquestador /chat/front. */
function apkEnvelope(question) {
  return {
    question,
    message: question,
    raw_text: question,
    customer_id: state.customerId,
    client_id: state.customerId,
    subject_token: state.customerId,
    conversation_id: state.conversationId,
    force_core_query: false,
    context_info: false,
    channel: { type: "web", entrypoint: "pruebas_simulator" },
  };
}

function extractReply(data) {
  const app = data.app_channel || {};
  return (
    data.reply ||
    data.message ||
    data.content ||
    app.client_response ||
    data.error ||
    app.status ||
    "Sin respuesta"
  );
}

function extractOptions(data) {
  const app = data.app_channel || {};
  return app.options || data.options || [];
}

function extractContentFormat(data) {
  const app = data.app_channel || {};
  return data.content_format || app.content_format || (/\*\*|• /.test(extractReply(data) || "") ? "markdown" : "plain");
}

function extractSuggestions(data) {
  const app = data.app_channel || {};
  return app.suggested_questions || data.suggested_questions || [];
}

function enterChat(loaded) {
  renderSession(loaded);
  $("chat").innerHTML = "";
  $("runLog").innerHTML = "";
  showScreen("chat");
  setBusy(false);
  closeDrawer();
  $("input").focus();
}

async function handleLogin({ skipPasskey = true } = {}) {
  state.apiBase = $("apiBase").value;
  const customerRaw = $("loginUser").value.trim();
  const labUser = resolveLabUser(customerRaw);
  $("loginStatus").textContent = "";
  if (!labUser || !labUser.customer_id) {
    $("loginStatus").textContent = "Ingresa el customerId.";
    return;
  }

  setBusy(true);
  $("loginStatus").textContent = "Conectando WebSocket al Core (customerId)…";
  try {
    const loaded = await startOrchestratorSession(labUser);
    state.skipPasskeyNext = skipPasskey;
    enterChat(loaded);
    $("loginStatus").textContent = "";
  } catch (err) {
    state.contextLoaded = false;
    $("loginStatus").textContent = err.message;
    setBusy(false);
  }
}

async function sendText(text, { silent = false } = {}) {
  const question = (text || "").trim();
  if (!question || state.busy) return null;
  if (!state.contextLoaded) {
    showScreen("login");
    $("loginStatus").textContent = "Debes iniciar sesión para conversar.";
    return null;
  }
  if (!silent) {
    $("input").value = "";
    appendUser(question);
  }
  setBusy(true);
  if (!silent) appendTyping();
  try {
    // Canal delgado → orquestador MCP (igual que el APK), expuesto en /orch/chat/front
    const data = await api("/orch/chat/front", {
      method: "POST",
      body: JSON.stringify(apkEnvelope(question)),
      signal: state.abort ? state.abort.signal : undefined,
    });
    if (data.error && !extractReply(data)) {
      throw new Error(typeof data.detail === "string" ? data.detail : data.error);
    }
    if (!silent) appendBot(extractReply(data), extractOptions(data), extractSuggestions(data), { content_format: extractContentFormat(data) });
    return data;
  } catch (err) {
    if (err.name === "AbortError") return null;
    removeTyping();
    if (!silent) appendBot(`No pude completar el turno: ${err.message}`);
    throw err;
  } finally {
    setBusy(false);
  }
}

function summarizeTurn(data) {
  const app = (data && data.app_channel) || {};
  return {
    status: app.status || data.status || "ERROR",
    intent: app.intent_id || "—",
    reply:
      data.reply ||
      data.message ||
      data.content ||
      app.client_response ||
      data.error ||
      "Sin respuesta",
    ms: (data.audit && data.audit.total_ms) || 0,
  };
}

function logRun(html) {
  $("runLog").insertAdjacentHTML("afterbegin", html);
}

async function runQuestions(questions, title) {
  if (!state.contextLoaded || state.busy) return;
  state.abort = new AbortController();
  $("btnStop").disabled = false;
  $("runLog").innerHTML = `<p class="run-title">${title}</p>`;
  setBusy(true);
  let ok = 0;
  try {
    for (let i = 0; i < questions.length; i += 1) {
      if (state.abort.signal.aborted) break;
      const question = questions[i];
      appendUser(question);
      appendTyping();
      try {
        const data = await api("/orch/chat/front", {
          method: "POST",
          body: JSON.stringify(apkEnvelope(question)),
          signal: state.abort.signal,
        });
        const reply = extractReply(data);
        appendBot(reply, extractOptions(data), extractSuggestions(data), { content_format: extractContentFormat(data) });
        const row = summarizeTurn(data);
        const pass = row.status === "VALID_CONTRACT" || row.status === "NON_OPERATIONAL" || row.status === "CLARIFICATION_REQUIRED" || row.status === "requires_selection";
        if (pass) ok += 1;
        logRun(
          `<article class="${pass ? "ok" : "fail"}"><strong>#${i + 1} ${row.status}</strong><span>${row.intent} · ${row.ms} ms</span><p>${question}</p><p>${row.reply}</p></article>`
        );
      } catch (err) {
        if (err.name === "AbortError") break;
        removeTyping();
        appendBot(`No pude completar el turno: ${err.message}`);
        logRun(`<article class="fail"><strong>#${i + 1} ERROR</strong><p>${question}</p><p>${err.message}</p></article>`);
      }
    }
  } finally {
    logRun(`<p class="run-title">Listo: ${ok}/${questions.length} con respuesta de contrato.</p>`);
    $("btnStop").disabled = true;
    state.abort = null;
    setBusy(false);
  }
}

async function runQaScript() {
  const scripts = await api("/lab/scripts");
  const script = scripts.find((s) => s.id === "qa_andres") || scripts[0];
  if (!script) throw new Error("No hay scripts de QA");
  closeDrawer();
  await runQuestions(script.questions, script.label);
}

async function runExcel() {
  const casos = await api("/lab/excel-casos");
  const limit = $("excelCount").value;
  const slice = limit === "all" ? casos : casos.slice(0, Number(limit));
  closeDrawer();
  await runQuestions(
    slice.map((c) => c.question),
    `Excel · ${slice.length} casos`
  );
}

function openDrawer() {
  $("drawer").hidden = false;
  $("drawerBackdrop").hidden = false;
  $("drawer").classList.remove("hidden");
  $("drawerBackdrop").classList.remove("hidden");
}

function closeDrawer() {
  $("drawer").hidden = true;
  $("drawerBackdrop").hidden = true;
  $("drawer").classList.add("hidden");
  $("drawerBackdrop").classList.add("hidden");
}

function logout() {
  state.contextLoaded = false;
  state.customerId = "";
  state.displayName = "";
  state.conversationId = "";
  state.lastLoaded = null;
  $("chat").innerHTML = "";
  $("loginStatus").textContent = "";
  closeDrawer();
  showScreen("login");
  setBusy(false);
}

function initDevMode() {
  if (DEV_MODE) {
    $("devPanel").open = true;
    $("devLab").hidden = false;
    $("devLab").classList.remove("hidden");
  }
}

$("loginForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  handleLogin({ skipPasskey: true });
});
$("btnCreatePasskey")?.addEventListener("click", () => {
  if (state.contextLoaded && state.lastLoaded) enterChat(state.lastLoaded);
});
$("btnSkipPasskey")?.addEventListener("click", () => {
  if (state.contextLoaded && state.lastLoaded) enterChat(state.lastLoaded);
});
$("btnSend").addEventListener("click", () => sendText($("input").value));
$("input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") sendText($("input").value);
});
$("btnMenu").addEventListener("click", openDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
$("btnLogout").addEventListener("click", logout);
$("customerSelect").addEventListener("change", async (ev) => {
  const id = ev.target.value;
  $("loginUser").value = id;
  $("customerId").value = id;
  $("loginStatus").textContent = "";
  try {
    await fillContextFromUser(id);
  } catch (err) {
    $("loginStatus").textContent = err.message;
  }
});
$("apiBase").addEventListener("change", () => {
  state.apiBase = $("apiBase").value;
  loadUsuarios();
});
$("quickGrid").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".quick-chip");
  if (btn) sendText(btn.dataset.q || btn.textContent);
});
$("btnQaScript").addEventListener("click", () => {
  runQaScript().catch((err) => { $("runLog").textContent = err.message; });
});
$("btnExcel").addEventListener("click", () => {
  runExcel().catch((err) => { $("runLog").textContent = err.message; });
});
$("btnStop").addEventListener("click", () => {
  if (state.abort) state.abort.abort();
});

initDevMode();
loadUsuarios();
setBusy(false);
