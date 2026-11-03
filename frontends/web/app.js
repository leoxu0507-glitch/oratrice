const ENDPOINTS = Object.freeze({
  status: "/status",
  chat: "/chat",
  stream: "/chat/stream",
});

const MAX_HISTORY_MESSAGES = 12;
const MAX_CONTEXT_BYTES = 1536;
const MESSAGE_OVERHEAD_BYTES = 32;
const MAX_REPLY_TOKENS = 256;
const MAX_CONVERSATION_PAIRS = (MAX_HISTORY_MESSAGES / 2) + 1;

const STATUS_REQUEST_TIMEOUT_MS = 4_000;
const CHAT_REQUEST_TIMEOUT_MS = 120_000;
const STATUS_INITIAL_DELAY_MS = 3_000;
const STATUS_MAX_DELAY_MS = 30_000;
const STATUS_ACTIVE_DELAY_MS = 2_500;

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
const conversationData = globalThis.OratriceConversationData;
const conversationStoreAPI = globalThis.OratriceConversationStore;
const budgetStatus = document.getElementById("context-budget");
const saveToggle = document.getElementById("save-conversations");
const streamToggle = document.getElementById("stream-replies");
const stopButton = document.getElementById("stop-button");
const savedSelect = document.getElementById("saved-conversations");
const openSavedButton = document.getElementById("open-conversation");
const deleteSavedButton = document.getElementById("delete-conversation");
const clearSavedButton = document.getElementById("clear-conversations");
const exportJsonButton = document.getElementById("export-json");
const exportMarkdownButton = document.getElementById("export-markdown");
const storageStatus = document.getElementById("storage-status");
let browserStorage = null;
try { browserStorage = window.localStorage; } catch { /* Page-memory chat remains available. */ }
const conversationStore = conversationStoreAPI.createStore(browserStorage, window.navigator?.locks);
let savedState = { version: 1, enabled: false, activeId: null, conversations: [] };
let storageReady = false;
let storageFault = false;
let storageBusy = false;
let saveBlocked = false;
let activeSaved = false;
let unsavedChanges = false;
let activeRecord = freshRecord();
const downloadUrls = new Set();


let chatHistory = [];
let activeChatController = null;
let activeStatusController = null;
let statusTimer = null;
let statusDelay = STATUS_INITIAL_DELAY_MS;
let statusCheckInFlight = false;
let statusRefreshRequested = false;
let localChatStatusVersion = 0;
let chatInFlight = false;
let streamingActive = false;
let chatStopRequested = false;
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

  if (error.kind === "incomplete") {
    return "The stream ended before the reply was complete. Your draft is still here; partial text is excluded from history and exports. Model work may continue.";
  }
  if (error.kind === "protocol" || error.kind === "stream") {
    return "The streamed reply could not be read safely. Your draft is still here; turn off Stream replies or try again. Model work may continue.";
  }
  if (error.kind === "limit") {
    return "The streamed reply reached a delivery limit. Your draft is still here; partial text is excluded from history and exports. Model work may continue.";
  }
  if (error.kind === "unsupported") {
    return "This browser cannot read streamed replies. Turn off Stream replies and send again.";
  }
  if (code === "context_limit" || code === "context_limit_exceeded") {
    return "This conversation is over the context limit. Shorten your message or start a new conversation.";
  }
  if (code === "stream_unsupported") {
    return "The configured provider does not support streaming. Turn off Stream replies and send again.";
  }
  if (error.kind === "remote_cancelled") {
    return "The streaming service stopped delivery. Model work may continue, and Oratrice may stay busy until it finishes.";
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

async function requestJson(url, options = {}, timeoutMs = STATUS_REQUEST_TIMEOUT_MS) {
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

function appendMessage(role, text, pending = false, finishReason = null) {
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
  article._oratriceLabel = label;
  article._oratriceBody = body;
  if (role === "assistant" && finishReason === "length") {
    const status = document.createElement("span");
    status.className = "message-status";
    status.textContent = "Incomplete reply: length limit reached";
    article.append(status);
  }
  conversation.append(article);
  if (typeof article.scrollIntoView === "function") {
    article.scrollIntoView({ block: "end", behavior: "smooth" });
  }
  return article;
}

function markPartialMessage(article) {
  article.classList.remove("message-pending");
  article.classList.add("message-partial");
  article._oratriceLabel.textContent = "Oratrice (partial)";
  const status = document.createElement("span");
  status.className = "message-status";
  status.textContent = "Incomplete reply. This text is excluded from conversation history and exports.";
  article.append(status);
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
  const draftTooLarge = contextSizeBytes(chatHistory, input.value) > MAX_CONTEXT_BYTES;
  input.disabled = chatInFlight || pageUnloading || atPairLimit || noContextRoom || storageBusy;
  sendButton.disabled = input.disabled || draftTooLarge;
  newConversationButton.disabled = chatInFlight || pageUnloading || storageBusy;
  conversation.setAttribute("aria-busy", chatInFlight ? "true" : "false");
  const used = contextSizeBytes(chatHistory, input.value);
  budgetStatus.textContent = "Next request budget: " + used + " / " + MAX_CONTEXT_BYTES +
    " units; " + chatHistory.length + " / " + MAX_HISTORY_MESSAGES + " prior messages";
  budgetStatus.className = "budget-status" + (draftTooLarge || atPairLimit ? " budget-exceeded" : "");
  const locked = chatInFlight || pageUnloading || storageBusy;
  saveToggle.disabled = locked || !storageReady;
  streamToggle.disabled = locked;
  stopButton.hidden = !chatInFlight || !streamingActive;
  stopButton.disabled = !chatInFlight || !streamingActive || chatStopRequested;
  savedSelect.disabled = locked || savedState.conversations.length === 0;
  openSavedButton.disabled = locked || !savedSelect.value;
  deleteSavedButton.disabled = locked || !savedSelect.value;
  clearSavedButton.disabled = locked || (!storageFault && !savedState.enabled && savedState.conversations.length === 0);
  exportJsonButton.disabled = locked || activeRecord.messages.length === 0;
  exportMarkdownButton.disabled = exportJsonButton.disabled;
}

function freshRecord() {
  const now = new Date().toISOString();
  const id = window.crypto?.randomUUID?.() || ("c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2));
  return { id, title: "New conversation", createdAt: now, updatedAt: now, revision: 0, messages: [] };
}

function setStorageStatus(message, error = false) {
  storageStatus.textContent = message;
  storageStatus.className = "storage-status" + (error ? " storage-error" : "");
}

function storageError(code) {
  const messages = {
    conflict: "This saved conversation changed in another tab. Saving is paused; export this page or reopen the saved version.",
    missing: "This saved conversation was deleted in another tab. Saving is paused; export this page or start a new conversation.",
    too_many: "The 20-conversation limit is reached. Export this page, or delete a saved conversation before saving.",
    too_large: "The browser history size limit is reached. Export this page, or delete saved conversations before saving.",
    corrupt: "Saved data could not be read. It has been preserved. Chat still works; clear saved data only if you want to remove it.",
    unsupported: "This browser has saved data from an unsupported version. It has been preserved; page-only chat still works.",
    lock_unavailable: "Local saving needs browser Web Locks. Page-only chat and export still work.",
    unavailable: "Browser storage is unavailable. Page-only chat and export still work.",
  };
  return messages[code] || "Local saving failed. This conversation is still on this page; export it before leaving.";
}

function applySavedState(state) {
  savedState = state;
  storageFault = false;
  saveToggle.checked = state.enabled;
  const selected = savedSelect.value;
  savedSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.conversations.length ? "Choose a saved conversation" : "No saved conversations";
  savedSelect.append(placeholder);
  const records = [...state.conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  for (const record of records) {
    const option = document.createElement("option");
    option.value = record.id;
    option.textContent = record.title + " (" + record.updatedAt.slice(0, 16).replace("T", " ") + " UTC)";
    savedSelect.append(option);
  }
  savedSelect.value = state.conversations.some((r) => r.id === activeRecord.id)
    ? activeRecord.id : (state.conversations.some((r) => r.id === selected) ? selected : "");
}

function mayDiscardDraft() {
  if (!input.value.trim() && !(unsavedChanges && savedState.enabled)) return true;
  return typeof window.confirm === "function" && window.confirm("Discard the current unsent draft or unsaved changes?");
}

function showRecord(record) {
  activeRecord = conversationData.sanitizeRecord(record);
  savedSelect.value = activeRecord.id;
  activeSaved = true;
  unsavedChanges = false;
  saveBlocked = false;
  chatHistory = activeRecord.messages.map((item) => ({ role: item.role, content: item.content }));
  conversation.replaceChildren(emptyState);
  for (const item of activeRecord.messages) appendMessage(item.role, item.content, false, item.finish_reason);
  input.value = "";
  const overBudget = chatHistory.length > MAX_HISTORY_MESSAGES || contextSizeBytes(chatHistory, "") >= MAX_CONTEXT_BYTES;
  setNotice(overBudget
    ? "This saved conversation exceeds the current context limit. Export it or start a new conversation to continue."
    : "Saved conversation opened. Nothing is sent to the model until you send a message.", "notice-limit");
  setComposerState();
}

async function persistCurrent() {
  if (!savedState.enabled || saveBlocked || !activeRecord.messages.length) return;
  const result = await conversationStore.save(activeRecord, { create: !activeSaved });
  if (!result.ok) {
    if (result.code === "conflict" || result.code === "missing") saveBlocked = true;
    setStorageStatus(storageError(result.code), true);
    return;
  }
  applySavedState(result.state);
  const stored = result.state.conversations.find((item) => item.id === activeRecord.id);
  if (stored) activeRecord.revision = stored.revision;
  activeSaved = true;
  unsavedChanges = false;
  setStorageStatus("Saved on this browser. Export a backup; browser storage can be cleared.");
}

async function historyAction(action) {
  if (chatInFlight || storageBusy || pageUnloading) return false;
  storageBusy = true;
  setComposerState();
  try { return await action(); }
  catch { setStorageStatus("Local history could not be updated. Your current page and draft are still here.", true); return false; }
  finally { storageBusy = false; setComposerState(); }
}

async function initializeHistory() {
  const result = await conversationStore.load();
  storageReady = true;
  if (!result.ok) {
    storageFault = ["corrupt", "unsupported", "too_large", "too_many"].includes(result.code);
    setStorageStatus(storageError(result.code), true);
    setComposerState();
    return;
  }
  applySavedState(result.state);
  if (result.state.enabled && result.state.activeId) {
    const record = result.state.conversations.find((item) => item.id === result.state.activeId);
    if (record) showRecord(record);
  }
  setStorageStatus(result.state.enabled
    ? "Automatic saving is on for this browser. Export a backup."
    : "Page-only mode. Saving is off; existing saved conversations remain until deleted.");
  setComposerState();
}

function exportCurrent(format) {
  if (chatInFlight || pageUnloading || !activeRecord.messages.length) return;
  try {
    const text = format === "json" ? conversationData.exportJson(activeRecord) : conversationData.exportMarkdown(activeRecord);
    const blob = new Blob([text], { type: format === "json" ? "application/json;charset=utf-8" : "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    downloadUrls.add(url);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "oratrice-conversation-" + activeRecord.createdAt.slice(0, 10) + "." + (format === "json" ? "json" : "md");
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => { URL.revokeObjectURL(url); downloadUrls.delete(url); }, 1000);
    setStorageStatus("Export created from successful visible turns. Keep the file as your backup.");
  } catch { setStorageStatus("This conversation could not be exported. Your messages remain on this page.", true); }
}

function resetConversation(options = {}) {
  const preserveDraft = options.preserveDraft === true;
  const force = options.force === true;
  const focus = options.focus !== false;

  if ((chatInFlight || storageBusy) && !force) return false;
  if (!force && !mayDiscardDraft()) return false;
  if (force) {
    chatSequence += 1;
    activeChatController?.abort();
    activeChatController = null;
    chatInFlight = false;
  }

  const clearPage = () => {
    chatHistory = [];
    activeRecord = freshRecord();
    savedSelect.value = "";
    activeSaved = false;
    unsavedChanges = false;
    saveBlocked = false;
    conversation.replaceChildren(emptyState);
    emptyState.hidden = false;
    conversation.setAttribute("aria-busy", "false");
    if (!preserveDraft) input.value = "";
    setNotice("");
    setComposerState();
    if (focus && !pageUnloading) input.focus();
    return true;
  };
  if (storageReady && savedState.enabled) {
    // A normal reset becomes visible only after the reload selection commits.
    // A restored page must discard an interrupted request immediately instead.
    if (force) clearPage();
    const reset = historyAction(async () => {
      const result = await conversationStore.activate(null);
      if (!result.ok) {
        setStorageStatus("Could not update the saved conversation selection; refreshing may reopen the previous conversation. " + storageError(result.code), true);
        return false;
      }
      applySavedState(result.state);
      if (!force) clearPage();
      return true;
    });
    return reset.then((completed) => {
      if (completed && focus && !pageUnloading && !input.disabled) input.focus();
      return completed;
    });
  }
  clearPage();
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

  return {
    content: responseText(payload),
    finishReason: typeof payload?.finish_reason === "string" && payload.finish_reason.length <= 64 ? payload.finish_reason : null,
  };
}

function sendStreamingMessage(message, history, signal, onEvent) {
  const streamClient = globalThis.OratriceStreamClient;
  if (!streamClient || typeof streamClient.streamChat !== "function") {
    const error = new Error("Streamed replies are unavailable in this browser.");
    error.kind = "unsupported";
    return Promise.reject(error);
  }
  const priorMessages = history.map((item) => ({ role: item.role, content: item.content }));
  return streamClient.streamChat(ENDPOINTS.stream, {
    message,
    history: priorMessages,
    max_tokens: MAX_REPLY_TOKENS,
  }, { signal, onEvent, fetch: globalThis.fetch });
}

async function submit(event) {
  event.preventDefault();
  if (chatInFlight || pageUnloading || storageBusy) return false;

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
  const shouldStream = streamToggle.checked;
  let streamedArticle = null;
  let streamedText = "";
  const requestHistory = chatHistory.slice();
  const requestId = ++chatSequence;
  chatInFlight = true;
  streamingActive = shouldStream;
  chatStopRequested = false;
  localChatStatusVersion += 1;
  setStatus("busy", "Busy: request active");
  refreshStatusSoon();
  setComposerState();
  setNotice(
    "Oratrice is thinking. If you leave or reload, the browser wait ends but model work may continue; another request may be busy until it finishes.",
    "notice-busy"
  );

  try {
    let reply;
    if (shouldStream) {
      const controller = new AbortController();
      activeChatController = controller;
      streamedArticle = appendMessage("assistant", "", true);
      const streamedReply = await sendStreamingMessage(message, requestHistory, controller.signal, (event) => {
        if (event.type !== "delta" || requestId !== chatSequence || pageUnloading) return;
        streamedText += event.payload.text;
        streamedArticle._oratriceBody.textContent = streamedText;
        if (streamedText) pendingMessage.classList.remove("message-pending");
      });
      reply = { ...streamedReply, content: streamedText };
    } else {
      reply = await sendMessage(message, requestHistory);
    }
    const answer = reply.content;
    if (requestId !== chatSequence || pageUnloading) return false;
    if (!answer) {
      const emptyResponseError = new Error("The model returned no displayable text.");
      emptyResponseError.kind = reply.finishReason === "length" ? "empty_truncated" : "empty_response";
      throw emptyResponseError;
    }

    pendingMessage.classList.remove("message-pending");
    if (streamedArticle) {
      streamedArticle.classList.remove("message-pending");
      if (reply.finishReason === "length") {
        const status = document.createElement("span");
        status.className = "message-status";
        status.textContent = "Incomplete reply: length limit reached";
        streamedArticle.append(status);
      }
    } else {
      appendMessage("assistant", answer, false, reply.finishReason);
    }
    chatHistory.push(
      { role: "user", content: message },
      { role: "assistant", content: answer }
    );
    activeRecord.messages.push(
      { role: "user", content: message },
      { role: "assistant", content: answer, finish_reason: reply.finishReason }
    );
    if (activeRecord.messages.length === 2) activeRecord.title = Array.from(message.replace(/\s+/g, " ").trim()).slice(0, 50).join("");
    activeRecord.updatedAt = new Date().toISOString();
    unsavedChanges = true;
    input.value = "";
    await persistCurrent();
    if (chatHistory.length > MAX_HISTORY_MESSAGES) {
      setNotice("You have reached the limit of " + MAX_CONVERSATION_PAIRS + " exchanges. Start a new conversation to continue.", "notice-limit");
    } else if (contextSizeBytes(chatHistory, "") >= MAX_CONTEXT_BYTES) {
      setNotice("There is no context space for another message. Start a new conversation to continue.", "notice-limit");
    } else {
      setNotice("");
    }
    if (reply.finishReason === "length") {
      const prior = notice.textContent;
      setNotice("The reply reached its length limit and may be incomplete. Ask to continue if there is conversation space." + (prior ? " " + prior : ""), "notice-limit");
    }
    return true;
  } catch (error) {
    if (requestId !== chatSequence || pageUnloading) return false;
    if (streamedArticle && streamedText.length > 0) {
      pendingMessage.classList.remove("message-pending");
      markPartialMessage(streamedArticle);
    } else {
      pendingMessage.remove();
      streamedArticle?.remove();
      updateEmptyState();
    }
    if (!(error.kind === "cancelled" && (pageUnloading || pagehiddenDuringChat))) {
      setNotice(
        chatStopRequested
          ? "Reply display stopped. The model may continue working, and Oratrice may stay busy until it finishes. Partial text is excluded from future context and exports."
          : error.kind === "empty_truncated"
          ? "The reply reached its length limit without displayable text. Your draft is still here; try a shorter request."
          : error.kind === "empty_response"
          ? "Oratrice returned no displayable text. Your draft is still here; try again."
          : chatErrorMessage(error),
        "notice-error"
      );
    }
    return false;
  } finally {
    if (requestId === chatSequence) {
      chatInFlight = false;
      streamingActive = false;
      chatStopRequested = false;
      if (activeChatController) activeChatController = null;
      setComposerState();
      if (!pageUnloading) {
        if (!input.disabled) input.focus();
        else newConversationButton.focus();
        refreshStatusSoon();
      }
    }
  }
}

function scheduleStatusCheck(delay = statusDelay) {
  if (statusTimer !== null) clearTimeout(statusTimer);
  if (pageUnloading) {
    statusTimer = null;
    return;
  }
  statusTimer = setTimeout(() => {
    statusTimer = null;
    checkStatus();
  }, delay);
}

function validStatusPayload(status) {
  if (!status || typeof status !== "object" || Array.isArray(status)) return false;
  if (status.version !== 1) return false;
  if (!["starting", "ready", "busy", "error"].includes(status.state)) return false;
  if (![null, "chat", "route", "stream"].includes(status.operation)) return false;
  if (![null, "active", "stopped"].includes(status.delivery)) return false;
  if (![null, "operation_failed", "readiness_failed", "readiness_unavailable"].includes(status.error_code)) return false;
  if (typeof status.checked_at !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(status.checked_at)) return false;

  if (status.state === "busy") {
    if (status.operation === null || status.error_code !== null) return false;
    if (status.operation === "stream") {
      if (!["active", "stopped"].includes(status.delivery)) return false;
    } else if (status.delivery !== null) {
      return false;
    }
  } else {
    if (status.operation !== null || status.delivery !== null) return false;
    if (status.state === "ready" && status.error_code !== null) return false;
    if (status.state === "starting" && ![null, "readiness_unavailable"].includes(status.error_code)) return false;
    if (status.state === "error" && !["operation_failed", "readiness_failed", "readiness_unavailable"].includes(status.error_code)) return false;
  }

  const checkedAtMs = Date.parse(status.checked_at);
  if (!Number.isFinite(checkedAtMs)) return false;
  return status.checked_at.slice(0, 19) === new Date(checkedAtMs).toISOString().slice(0, 19);
}

function applyStatus(status) {
  if (status.state === "starting") {
    setStatus("starting", "Starting");
    statusDelay = STATUS_ACTIVE_DELAY_MS;
  } else if (status.state === "ready") {
    setStatus("ready", "Ready");
    statusDelay = STATUS_ACTIVE_DELAY_MS;
  } else if (status.state === "busy") {
    setStatus(
      "busy",
      status.delivery === "stopped"
        ? "Busy: model work continues after Stop"
        : "Busy: model work continues"
    );
    statusDelay = STATUS_ACTIVE_DELAY_MS;
  } else {
    const label = status.error_code === "operation_failed"
      ? "Last request failed"
      : status.error_code === "readiness_unavailable"
      ? "Readiness unavailable"
      : "Service error";
    setStatus("error", label);
    statusDelay = STATUS_ACTIVE_DELAY_MS;
  }
}

function refreshStatusSoon() {
  if (pageUnloading) return;
  if (statusCheckInFlight) {
    statusRefreshRequested = true;
    return;
  }
  scheduleStatusCheck(0);
}

async function checkStatus() {
  if (pageUnloading || statusCheckInFlight) return;
  statusCheckInFlight = true;
  const controller = new AbortController();
  const chatStatusVersion = localChatStatusVersion;
  activeStatusController = controller;

  try {
    let status;
    try {
      status = await requestJson(ENDPOINTS.status, { signal: controller.signal }, STATUS_REQUEST_TIMEOUT_MS);
    } catch (error) {
      if (pageUnloading || error.kind === "cancelled") return;
      if (chatStatusVersion !== localChatStatusVersion) {
        statusRefreshRequested = true;
        return;
      }
      if (error.kind === "network" || error.kind === "timeout") {
        setStatus("offline", "Core unavailable");
        statusDelay = Math.min(statusDelay * 2, STATUS_MAX_DELAY_MS);
      } else {
        setStatus("error", "Status unavailable");
        statusDelay = Math.min(statusDelay * 2, STATUS_MAX_DELAY_MS);
      }
      return;
    }

    if (pageUnloading || controller.signal.aborted) return;
    if (chatStatusVersion !== localChatStatusVersion) {
      statusRefreshRequested = true;
      return;
    }
    if (!validStatusPayload(status)) {
      setStatus("error", "Status unavailable");
      statusDelay = Math.min(statusDelay * 2, STATUS_MAX_DELAY_MS);
      return;
    }
    applyStatus(status);
  } finally {
    if (activeStatusController === controller) {
      activeStatusController = null;
      statusCheckInFlight = false;
      const refreshRequested = statusRefreshRequested;
      statusRefreshRequested = false;
      if (!pageUnloading) scheduleStatusCheck(refreshRequested ? 0 : statusDelay);
    }
  }
}


input.addEventListener("input", setComposerState);
savedSelect.addEventListener("change", setComposerState);
saveToggle.addEventListener("change", () => historyAction(async () => {
  const result = await conversationStore.setEnabled(saveToggle.checked);
  if (!result.ok) { saveToggle.checked = savedState.enabled; setStorageStatus(storageError(result.code), true); return false; }
  applySavedState(result.state);
  if (!activeSaved && activeRecord.revision > 0 && savedState.enabled) { activeRecord.id = freshRecord().id; activeRecord.revision = 0; }
  saveBlocked = false;
  if (savedState.enabled) { await persistCurrent(); if (!activeRecord.messages.length) setStorageStatus("Automatic saving is on. Successful replies will be saved locally."); }
  else setStorageStatus("Saving is off. Existing saved conversations remain until you delete them.");
  return true;
}));
openSavedButton.addEventListener("click", () => historyAction(async () => {
  if (!mayDiscardDraft()) return false;
  const result = await conversationStore.activate(savedSelect.value);
  if (!result.ok) { setStorageStatus(storageError(result.code), true); return false; }
  const record = result.state.conversations.find((item) => item.id === savedSelect.value);
  if (!record) return false;
  applySavedState(result.state);
  showRecord(record);
  return true;
}));
deleteSavedButton.addEventListener("click", () => historyAction(async () => {
  const id = savedSelect.value;
  if (!window.confirm("Delete this saved conversation from this browser? The current page stays available.")) return false;
  const result = await conversationStore.remove(id);
  if (!result.ok) { setStorageStatus(storageError(result.code), true); return false; }
  applySavedState(result.state);
  if (id === activeRecord.id) { activeSaved = false; saveBlocked = true; unsavedChanges = true; }
  setStorageStatus("Saved conversation deleted. The current page was kept; start a new conversation before saving again.");
  return true;
}));
clearSavedButton.addEventListener("click", () => historyAction(async () => {
  if (!window.confirm("Delete all saved conversations and disable saving in this browser? The current page stays available.")) return false;
  const result = await conversationStore.clear();
  if (!result.ok) { setStorageStatus(storageError(result.code), true); return false; }
  applySavedState(result.state);
  activeSaved = false;
  saveBlocked = true;
  unsavedChanges = activeRecord.messages.length > 0;
  setStorageStatus("Saved conversations cleared. Saving is off; your current page was kept.");
  return true;
}));
exportJsonButton.addEventListener("click", () => exportCurrent("json"));
exportMarkdownButton.addEventListener("click", () => exportCurrent("markdown"));
window.addEventListener("storage", async (event) => {
  if (event.key !== null && event.key !== conversationStoreAPI.STORAGE_KEY) return;
  saveBlocked = true;
  const result = await conversationStore.load();
  if (result.ok) {
    applySavedState(result.state);
    if (!result.state.conversations.some((item) => item.id === activeRecord.id)) activeSaved = false;
  } else {
    storageFault = ["corrupt", "unsupported", "too_large", "too_many"].includes(result.code);
  }
  setStorageStatus("Saved data changed in another tab. Saving is paused for this page; export it or reopen the saved version.", true);
  setComposerState();
});
window.addEventListener("beforeunload", (event) => {
  if (storageBusy || input.value.trim() || (savedState.enabled && unsavedChanges)) {
    event.preventDefault?.();
    event.returnValue = "";
  }
});

form.addEventListener("submit", submit);
streamToggle.addEventListener("change", setComposerState);
stopButton.addEventListener("click", () => {
  if (!chatInFlight || !streamingActive || chatStopRequested) return;
  chatStopRequested = true;
  stopButton.disabled = true;
  setNotice("Stopping reply display. The model may continue working, and Oratrice may stay busy until it finishes.", "notice-busy");
  activeChatController?.abort();
  refreshStatusSoon();
});
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
  for (const url of downloadUrls) URL.revokeObjectURL(url);
  downloadUrls.clear();
  if (statusTimer !== null) clearTimeout(statusTimer);
  statusTimer = null;
  activeStatusController?.abort();
  if (chatInFlight) {
    pagehiddenDuringChat = true;
    activeChatController?.abort();
  }
});

window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  pageUnloading = false;
  activeStatusController = null;
  statusCheckInFlight = false;
  if (pagehiddenDuringChat) {
    pagehiddenDuringChat = false;
    resetConversation({ preserveDraft: true, force: true, focus: false });
    setNotice(
      "The browser wait ended when this page was hidden. Model work may continue, and another request may be busy until it finishes.",
      "notice-error"
    );
  }
  setComposerState();
  statusDelay = STATUS_INITIAL_DELAY_MS;
  checkStatus();
});

setComposerState();
setStatus("starting", "Starting");
initializeHistory();
checkStatus();
