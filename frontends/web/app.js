const ENDPOINTS = Object.freeze({
  live: "/live",
  ready: "/ready",
  chat: "/chat",
});

const MAX_HISTORY_MESSAGES = 12;
const MAX_CONTEXT_BYTES = 1536;
const MESSAGE_OVERHEAD_BYTES = 32;
const MAX_REPLY_TOKENS = 256;
const MAX_CONVERSATION_PAIRS = (MAX_HISTORY_MESSAGES / 2) + 1;

const HEALTH_REQUEST_TIMEOUT_MS = 4_000;
const CHAT_REQUEST_TIMEOUT_MS = 120_000;
const HEALTH_INITIAL_DELAY_MS = 3_000;
const HEALTH_MAX_DELAY_MS = 30_000;

const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const newConversationButton = document.getElementById("new-conversation-button");
const conversation = document.getElementById("conversation");
const emptyState = document.getElementById("empty-state");
const notice = document.getElementById("notice");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const utf8Encoder = new TextEncoder();

let chatHistory = [];
let activeChatController = null;
let activeHealthController = null;
let healthTimer = null;
let healthDelay = HEALTH_INITIAL_DELAY_MS;
let healthCheckInFlight = false;
let chatInFlight = false;
let chatSequence = 0;
let pageUnloading = false;
let pagehiddenDuringChat = false;
let inputComposing = false;

function setNotice(message = "", kind = "") {
  notice.textContent = message;
  notice.className = kind ? "notice " + kind : "notice";
}

function setStatus(kind, label) {
  statusDot.className = "status-dot status-" + kind;
  statusLabel.textContent = label;
}

function apiErrorCode(payload) {
  return payload && payload.error && typeof payload.error.code === "string"
    ? payload.error.code.toLowerCase()
    : "";
}

function chatErrorMessage(error) {
  const code = apiErrorCode(error.payload);

  if (code === "context_limit" || code === "context_limit_exceeded") {
    return "This conversation is over the context limit. Shorten your message or start a new conversation.";
  }
  if (error.kind === "timeout" || error.status === 408 || code === "timeout") {
    return "The browser wait timed out. Cancelling the wait does not stop model computation; another request may be busy until it finishes.";
  }
  if (error.kind === "network") {
    return "Cannot connect to Oratrice Core. The service may not be started; start it and try again.";
  }
  if (error.status === 503 && (code === "chat_busy" || code === "route_busy")) {
    return "Oratrice is busy with another request. Wait, then send your message again.";
  }
  if (error.status === 502 || code === "upstream_error" || code === "provider_error") {
    return "The model service failed to complete this request. Check the model service and try again.";
  }
  if (error.status === 503) {
    return "The model service is starting or unavailable. Wait for it to become ready, then try again.";
  }
  if (error.status >= 500) {
    return "Oratrice Core could not complete this request. Please try again.";
  }
  if (error.kind === "cancelled") {
    return "The browser wait ended. Model computation may continue, and another request may be busy until it finishes.";
  }
  if (error.status === 422) {
    return "The request was not accepted. Shorten your message or start a new conversation.";
  }
  return "The request failed. Check your message and try again.";
}

async function requestJson(url, options = {}, timeoutMs = HEALTH_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const callerSignal = options.signal;
  let timedOut = false;
  const abortFromCaller = () => controller.abort();

  callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  if (callerSignal?.aborted) abortFromCaller();

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      if (error instanceof TypeError) throw error;
      payload = null;
    }
    if (!response.ok) {
      const error = new Error("The request failed.");
      error.kind = "http";
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error && error.name === "AbortError") {
      const cancelled = callerSignal?.aborted === true;
      const requestError = new Error(
        cancelled
          ? "The browser wait was cancelled."
          : "The browser wait timed out."
      );
      requestError.kind = cancelled ? "cancelled" : (timedOut ? "timeout" : "cancelled");
      throw requestError;
    }
    if (error instanceof TypeError) {
      const networkError = new Error("Cannot connect to Oratrice Core.");
      networkError.kind = "network";
      throw networkError;
    }
    throw error;
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

function appendMessage(role, text, pending = false) {
  emptyState.hidden = true;
  const article = document.createElement("article");
  article.className = "message message-" + role + (pending ? " message-pending" : "");
  article.setAttribute("aria-label", role === "user" ? "Your message" : "Oratrice response");

  const label = document.createElement("span");
  label.className = "message-label";
  label.textContent = role === "user" ? "You" : "Oratrice";

  const body = document.createElement("p");
  body.className = "message-body";
  body.textContent = text;

  article.append(label, body);
  conversation.append(article);
  if (typeof article.scrollIntoView === "function") {
    article.scrollIntoView({ block: "end", behavior: "smooth" });
  }
  return article;
}

function updateEmptyState() {
  const hasMessages = conversation.querySelector(".message") !== null;
  emptyState.hidden = hasMessages;
}

function responseText(payload) {
  if (payload && typeof payload.content === "string") {
    return payload.content.trim() ? payload.content : "";
  }
  if (payload && Array.isArray(payload.content)) {
    const content = payload.content.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item.text === "string") return item.text;
      return "";
    }).join("");
    return content.trim() ? content : "";
  }
  return "";
}

function contextSizeBytes(history = chatHistory, currentMessage = "") {
  let total = 0;
  for (const item of history) {
    total += utf8Encoder.encode(item.content).length + MESSAGE_OVERHEAD_BYTES;
  }
  total += utf8Encoder.encode(currentMessage).length + MESSAGE_OVERHEAD_BYTES;
  return total;
}

function setComposerState() {
  const atPairLimit = chatHistory.length > MAX_HISTORY_MESSAGES;
  const noContextRoom = !atPairLimit && contextSizeBytes(chatHistory, "") >= MAX_CONTEXT_BYTES;
  input.disabled = chatInFlight || pageUnloading || atPairLimit || noContextRoom;
  sendButton.disabled = chatInFlight || pageUnloading || atPairLimit || noContextRoom;
  newConversationButton.disabled = chatInFlight || pageUnloading;
  conversation.setAttribute("aria-busy", chatInFlight ? "true" : "false");
}

function resetConversation(options = {}) {
  const preserveDraft = options.preserveDraft === true;
  const force = options.force === true;
  const focus = options.focus !== false;

  if (chatInFlight && !force) return false;
  if (force) {
    chatSequence += 1;
    activeChatController?.abort();
    activeChatController = null;
    chatInFlight = false;
  }

  chatHistory = [];
  conversation.replaceChildren(emptyState);
  emptyState.hidden = false;
  conversation.setAttribute("aria-busy", "false");
  if (!preserveDraft) input.value = "";
  setNotice("");
  setComposerState();
  if (focus && !pageUnloading) input.focus();
  return true;
}

async function sendMessage(message, history = chatHistory) {
  const controller = new AbortController();
  activeChatController = controller;
  const priorMessages = history.map((item) => ({
    role: item.role,
    content: item.content,
  }));

  const payload = await requestJson(ENDPOINTS.chat, {
    method: "POST",
    body: JSON.stringify({
      message,
      history: priorMessages,
      max_tokens: MAX_REPLY_TOKENS,
    }),
    signal: controller.signal,
  }, CHAT_REQUEST_TIMEOUT_MS);

  return responseText(payload);
}

async function submit(event) {
  event.preventDefault();
  if (chatInFlight || pageUnloading) return false;

  if (chatHistory.length > MAX_HISTORY_MESSAGES) {
    setNotice("This conversation has reached its limit. Start a new conversation to continue.", "notice-error");
    newConversationButton.focus();
    return false;
  }

  if (contextSizeBytes(chatHistory, "") >= MAX_CONTEXT_BYTES) {
    setNotice("There is no context space for another message. Start a new conversation to continue.", "notice-limit");
    newConversationButton.focus();
    return false;
  }

  const message = input.value;
  if (!message.trim()) {
    setNotice("Enter a message before sending.", "notice-error");
    input.focus();
    return false;
  }

  if (contextSizeBytes(chatHistory, message) > MAX_CONTEXT_BYTES) {
    setNotice("This message and conversation exceed the context limit. Shorten your message or start a new conversation.", "notice-error");
    input.focus();
    return false;
  }

  const pendingMessage = appendMessage("user", message, true);
  const requestHistory = chatHistory.slice();
  const requestId = ++chatSequence;
  chatInFlight = true;
  setComposerState();
  setNotice(
    "Oratrice is thinking. If you leave or reload, the browser wait ends but model work may continue; another request may be busy until it finishes.",
    "notice-busy"
  );

  try {
    const answer = await sendMessage(message, requestHistory);
    if (requestId !== chatSequence || pageUnloading) return false;
    if (!answer) {
      const emptyResponseError = new Error("The model returned no displayable text.");
      emptyResponseError.kind = "empty_response";
      throw emptyResponseError;
    }

    pendingMessage.classList.remove("message-pending");
    appendMessage("assistant", answer);
    chatHistory.push(
      { role: "user", content: message },
      { role: "assistant", content: answer }
    );
    input.value = "";
    if (chatHistory.length > MAX_HISTORY_MESSAGES) {
      setNotice("You have reached the limit of " + MAX_CONVERSATION_PAIRS + " exchanges. Start a new conversation to continue.", "notice-limit");
    } else if (contextSizeBytes(chatHistory, "") >= MAX_CONTEXT_BYTES) {
      setNotice("There is no context space for another message. Start a new conversation to continue.", "notice-limit");
    } else {
      setNotice("");
    }
    return true;
  } catch (error) {
    if (requestId !== chatSequence || pageUnloading) return false;
    pendingMessage.remove();
    updateEmptyState();
    if (!(error.kind === "cancelled" && (pageUnloading || pagehiddenDuringChat))) {
      setNotice(
        error.kind === "empty_response"
          ? "Oratrice returned no displayable text. Your draft is still here; try again."
          : chatErrorMessage(error),
        "notice-error"
      );
    }
    return false;
  } finally {
    if (requestId === chatSequence) {
      chatInFlight = false;
      if (activeChatController) activeChatController = null;
      setComposerState();
      if (!pageUnloading) {
        if (!input.disabled) input.focus();
        else newConversationButton.focus();
      }
    }
  }
}

function scheduleHealthCheck(delay = healthDelay) {
  if (healthTimer !== null) clearTimeout(healthTimer);
  if (pageUnloading) {
    healthTimer = null;
    return;
  }
  healthTimer = setTimeout(() => {
    healthTimer = null;
    checkHealth();
  }, delay);
}

async function checkHealth() {
  if (pageUnloading || healthCheckInFlight) return;
  healthCheckInFlight = true;
  const controller = new AbortController();
  activeHealthController = controller;

  try {
    let live;
    try {
      live = await requestJson(ENDPOINTS.live, { signal: controller.signal }, HEALTH_REQUEST_TIMEOUT_MS);
    } catch (error) {
      if (pageUnloading || error.kind === "cancelled") return;
      setStatus("offline", "Core unavailable");
      healthDelay = Math.min(healthDelay * 2, HEALTH_MAX_DELAY_MS);
      return;
    }

    if (!live || live.healthy !== true) {
      setStatus("offline", "Core unavailable");
      healthDelay = Math.min(healthDelay * 2, HEALTH_MAX_DELAY_MS);
      return;
    }

    try {
      const ready = await requestJson(ENDPOINTS.ready, { signal: controller.signal }, HEALTH_REQUEST_TIMEOUT_MS);
      const readyNow = ready && ready.healthy === true;
      setStatus(readyNow ? "ready" : "degraded", readyNow ? "Ready" : "Model starting or unavailable");
      healthDelay = readyNow ? HEALTH_INITIAL_DELAY_MS * 2 : HEALTH_INITIAL_DELAY_MS;
    } catch (error) {
      if (pageUnloading || error.kind === "cancelled") return;
      setStatus(
        "degraded",
        error.status === 503 ? "Model starting or unavailable" : "Readiness unavailable"
      );
      healthDelay = HEALTH_INITIAL_DELAY_MS;
    }
  } finally {
    if (activeHealthController === controller) {
      activeHealthController = null;
      healthCheckInFlight = false;
      if (!pageUnloading) scheduleHealthCheck();
    }
  }
}

form.addEventListener("submit", submit);
newConversationButton.addEventListener("click", () => resetConversation());
input.addEventListener("compositionstart", () => {
  inputComposing = true;
});
input.addEventListener("compositionend", () => {
  inputComposing = false;
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    if (event.isComposing || inputComposing || event.keyCode === 229) return;
    event.preventDefault();
    form.requestSubmit();
  }
});

window.addEventListener("pagehide", () => {
  pageUnloading = true;
  if (healthTimer !== null) clearTimeout(healthTimer);
  healthTimer = null;
  activeHealthController?.abort();
  if (chatInFlight) {
    pagehiddenDuringChat = true;
    activeChatController?.abort();
  }
});

window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  pageUnloading = false;
  activeHealthController = null;
  healthCheckInFlight = false;
  if (pagehiddenDuringChat) {
    pagehiddenDuringChat = false;
    resetConversation({ preserveDraft: true, force: true, focus: false });
    setNotice(
      "The browser wait ended when this page was hidden. Model work may continue, and another request may be busy until it finishes.",
      "notice-error"
    );
  }
  setComposerState();
  healthDelay = HEALTH_INITIAL_DELAY_MS;
  checkHealth();
});

setComposerState();
setStatus("unknown", "Checking Core");
checkHealth();
