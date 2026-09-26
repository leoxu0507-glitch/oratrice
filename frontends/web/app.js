const ENDPOINTS = Object.freeze({
  live: "/live",
  ready: "/ready",
  chat: "/chat",
});

const HEALTH_REQUEST_TIMEOUT_MS = 4_000;
const CHAT_REQUEST_TIMEOUT_MS = 120_000;
const HEALTH_INITIAL_DELAY_MS = 3_000;
const HEALTH_MAX_DELAY_MS = 30_000;

const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const conversation = document.getElementById("conversation");
const emptyState = document.getElementById("empty-state");
const notice = document.getElementById("notice");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");

let activeChatController = null;
let activeHealthController = null;
let healthTimer = null;
let healthDelay = HEALTH_INITIAL_DELAY_MS;
let pageUnloading = false;

function setNotice(message = "", kind = "") {
  notice.textContent = message;
  notice.className = kind ? `notice ${kind}` : "notice";
}

function setStatus(kind, label) {
  statusDot.className = `status-dot status-${kind}`;
  statusLabel.textContent = label;
}

function extractErrorMessage(payload, status) {
  const serverMessage = payload && payload.error && typeof payload.error.message === "string"
    ? payload.error.message.trim()
    : "";
  if (serverMessage && serverMessage.length < 240) return serverMessage;
  if (status === 408) return "The request timed out. Please try again.";
  if (status === 502 || status === 503) return "The model service is temporarily unavailable.";
  if (status >= 400 && status < 500) return "The request was not accepted. Check your input and try again.";
  return "The service is temporarily unavailable. Please try again.";
}

async function requestJson(url, options = {}, timeoutMs) {
  const controller = new AbortController();
  let externallyAborted = false;
  const abortFromCaller = () => {
    externallyAborted = true;
    controller.abort();
  };
  options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (options.signal?.aborted) abortFromCaller();
  const signal = controller.signal;
  const timer = setTimeout(() => controller?.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal, headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    }});
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const error = new Error(extractErrorMessage(payload, response.status));
      error.kind = "http";
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error && error.name === "AbortError") {
      const timeoutError = new Error(externallyAborted ? "The request was cancelled." : "The request timed out. Please try again.");
      timeoutError.kind = externallyAborted ? "cancelled" : "timeout";
      throw timeoutError;
    }
    if (error instanceof TypeError) {
      const networkError = new Error("Unable to reach Oratrice Core. Make sure the service is running.");
      networkError.kind = "network";
      throw networkError;
    }
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}

function appendMessage(role, text) {
  emptyState.hidden = true;
  const article = document.createElement("article");
  article.className = `message message-${role}`;
  article.setAttribute("aria-label", role === "user" ? "User message" : "Oratrice response");

  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Oratrice";
  const body = document.createElement("p");
  body.className = "message-body";
  body.textContent = text;
  article.append(label, body);
  conversation.append(article);
  article.scrollIntoView({ block: "end", behavior: "smooth" });
}

function responseText(payload) {
  if (payload && typeof payload.content === "string") return payload.content.trim();
  if (payload && Array.isArray(payload.content)) {
    return payload.content.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item.text === "string") return item.text;
      return "";
    }).join("").trim();
  }
  return "";
}

async function sendMessage(message) {
  activeChatController = new AbortController();
  try {
    const payload = await requestJson(ENDPOINTS.chat, {
      method: "POST",
      body: JSON.stringify({ message }),
      signal: activeChatController.signal,
    }, CHAT_REQUEST_TIMEOUT_MS);
    const answer = responseText(payload);
    appendMessage("assistant", answer || "The model returned no displayable text.");
    setNotice("");
  } catch (error) {
    if (error.kind !== "cancelled") setNotice(error.message || "The request failed. Please try again.", "notice-error");
  } finally {
    activeChatController = null;
  }
}

async function submit(event) {
  event.preventDefault();
  if (activeChatController) return;
  const message = input.value.trim();
  if (!message) {
    setNotice("Enter a message before sending.", "notice-error");
    input.focus();
    return;
  }
  appendMessage("user", message);
  input.value = "";
  sendButton.disabled = true;
  input.disabled = true;
  setNotice("Oratrice is thinking...", "notice-busy");
  try {
    await sendMessage(message);
  } finally {
    sendButton.disabled = false;
    input.disabled = false;
    input.focus();
  }
}

async function checkHealth() {
  if (pageUnloading) return;
  const healthController = new AbortController();
  activeHealthController = healthController;
  try {
    await requestJson(ENDPOINTS.live, { signal: healthController.signal }, HEALTH_REQUEST_TIMEOUT_MS);
    const ready = await requestJson(ENDPOINTS.ready, { signal: healthController.signal }, HEALTH_REQUEST_TIMEOUT_MS);
    const healthy = ready && ready.healthy === true;
    setStatus(healthy ? "ready" : "degraded", healthy ? "Ready" : "Degraded");
    healthDelay = healthy ? HEALTH_INITIAL_DELAY_MS * 2 : HEALTH_INITIAL_DELAY_MS;
  } catch (error) {
    if (error.kind === "cancelled" && pageUnloading) return;
    setStatus("offline", error.kind === "timeout" ? "Connection timed out" : "Service unavailable");
    healthDelay = Math.min(healthDelay * 2, HEALTH_MAX_DELAY_MS);
  } finally {
    if (activeHealthController === healthController) activeHealthController = null;
    if (!pageUnloading) healthTimer = setTimeout(checkHealth, healthDelay);
  }
}

form.addEventListener("submit", submit);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});
window.addEventListener("pagehide", () => {
  pageUnloading = true;
  if (healthTimer) clearTimeout(healthTimer);
  activeHealthController?.abort();
  activeChatController?.abort();
});

setStatus("unknown", "Checking services");
checkHealth();
