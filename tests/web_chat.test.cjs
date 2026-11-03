"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { TextEncoder } = require("node:util");
const { TextDecoder } = require("node:util");
const { ReadableStream } = require("node:stream/web");

const APP_SOURCE = fs.readFileSync(
  path.join(__dirname, "..", "frontends", "web", "app.js"),
  "utf8"
);
const DATA_SOURCE = fs.readFileSync(path.join(__dirname, "..", "frontends", "web", "conversation-data.js"), "utf8");
const STORE_SOURCE = fs.readFileSync(path.join(__dirname, "..", "frontends", "web", "conversation-store.js"), "utf8");
const STREAM_CLIENT_SOURCE = fs.readFileSync(path.join(__dirname, "..", "frontends", "web", "stream-client.js"), "utf8");
const CHAT_TIMEOUT_MS = 120_000;
const ALLOWED_ENDPOINTS = new Set(["/status", "/chat", "/chat/stream"]);

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.parentNode = null;
    this.focused = false;
    this.classList = {
      add: (...names) => this._changeClasses(names, true),
      remove: (...names) => this._changeClasses(names, false),
      contains: (name) => this.className.split(/\s+/).includes(name),
    };
    Object.defineProperty(this, "innerHTML", {
      get: () => undefined,
      set: () => { throw new Error("UI must render untrusted text with textContent"); },
    });
  }

  _changeClasses(names, adding) {
    const current = new Set(this.className.split(/\s+/).filter(Boolean));
    for (const name of names) {
      if (adding) current.add(name);
      else current.delete(name);
    }
    this.className = [...current].join(" ");
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type, detail = {}) {
    const event = {
      type,
      target: this,
      currentTarget: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...detail,
    };
    const results = (this.listeners.get(type) || []).map((listener) => listener(event));
    return { event, results };
  }

  append(...children) {
    for (const child of children) {
      if (child.parentNode) {
        child.parentNode.children = child.parentNode.children.filter((item) => item !== child);
      }
      child.parentNode = this;
      this.children.push(child);
    }
  }

  replaceChildren(...children) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this.append(...children);
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((item) => item !== this);
    this.parentNode = null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  querySelector(selector) {
    if (selector !== ".message") return null;
    return this.children.find((child) => child.classList.contains("message")) || null;
  }

  requestSubmit() {
    return this.dispatch("submit").results[0];
  }

  click() { return this.dispatch("click").results[0]; }

  focus() {
    this.focused = true;
  }

  scrollIntoView() {}
}

function makeResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

function statusPayload(state = "ready", overrides = {}) {
  return {
    version: 1,
    state,
    operation: null,
    delivery: null,
    error_code: null,
    checked_at: "2026-11-03T00:00:00Z",
    ...overrides,
  };
}

const encoder = new TextEncoder();
function sseEvent(name, payload) {
  return encoder.encode(`event: ${name}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`);
}
function streamingResponse(request, events = null, status = 200) {
  const body = new ReadableStream({
    start(controller) {
      request.streamController = controller;
      if (events) {
        for (const [name, payload] of events) controller.enqueue(sseEvent(name, payload));
        controller.close();
      }
      request.signal.addEventListener("abort", () => {
        request.streamCancelled = true;
        try {
          const error = new Error("stream request aborted");
          error.name = "AbortError";
          controller.error(error);
        } catch { /* The stream may already have ended. */ }
      }, { once: true });
    },
    cancel() { request.streamCancelled = true; },
  });
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => status === 200 ? "text/event-stream; charset=utf-8" : "application/json" },
    body,
    async json() { return { error: { code: "chat_busy", message: "busy" } }; },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function makeStorage() {
  const values = new Map();
  return { values, getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}
function makeLocks() {
  let pending = Promise.resolve();
  return { request(name, options, callback) {
    const next = pending.then(() => callback({ name }));
    pending = next.catch(() => {});
    return next;
  } };
}
function makePage(options = {}) {
  const elements = {
    "chat-form": new FakeElement("form"),
    "message-input": new FakeElement("textarea"),
    "send-button": new FakeElement("button"),
    "new-conversation-button": new FakeElement("button"),
    "stop-button": new FakeElement("button"),
    "stream-replies": new FakeElement("input"),
    conversation: new FakeElement("section"),
    "empty-state": new FakeElement("div"),
    notice: new FakeElement("p"),
    "status-dot": new FakeElement("span"),
    "status-label": new FakeElement("span"),
  };
  for (const id of ["context-budget", "save-conversations", "saved-conversations", "open-conversation", "delete-conversation", "clear-conversations", "export-json", "export-markdown", "storage-status"]) {
    elements[id] = new FakeElement(id === "saved-conversations" ? "select" : "div");
  }
  elements.conversation.append(elements["empty-state"]);
  elements["stream-replies"].checked = false;
  elements["stop-button"].hidden = true;
  elements["stop-button"].disabled = true;
  const storage = options.storage || makeStorage();
  const locks = options.locks === null ? null : (options.locks || makeLocks());
  const downloads = [];
  const confirmAnswers = [];

  const windowListeners = new Map();
  const window = {
    localStorage: storage,
    navigator: { locks },
    confirm() { return confirmAnswers.length ? confirmAnswers.shift() : true; },
    addEventListener(type, listener) {
      const listeners = windowListeners.get(type) || [];
      listeners.push(listener);
      windowListeners.set(type, listeners);
    },
    dispatch(type, detail = {}) {
      const event = { type, ...detail };
      return (windowListeners.get(type) || []).map((listener) => listener(event));
    },
  };

  const timers = new Map();
  let nextTimerId = 1;
  const setTimeoutFake = (callback, delay) => {
    const id = nextTimerId++;
    timers.set(id, { callback, delay });
    return id;
  };
  const clearTimeoutFake = (id) => timers.delete(id);
  const chatOutcomes = [];
  const streamOutcomes = [];
  const statusOutcomes = [];
  const requests = [];

  function fetchFake(url, options = {}) {
    const request = {
      url: String(url),
      method: options.method || "GET",
      headers: options.headers || {},
      signal: options.signal,
      body: options.body,
      json: options.body ? JSON.parse(options.body) : undefined,
    };
    requests.push(request);

    if (request.url === "/status") {
      const outcome = statusOutcomes.shift();
      if (typeof outcome === "function") return outcome(request);
      return Promise.resolve(outcome ?? makeResponse(statusPayload()));
    }
    if (request.url === "/chat/stream") {
      const outcome = streamOutcomes.shift();
      return Promise.resolve(typeof outcome === "function" ? outcome(request) : outcome);
    }
    if (request.url !== "/chat") {
      return Promise.reject(new Error(`Unexpected endpoint: ${request.url}`));
    }

    const outcome = chatOutcomes.shift();
    if (typeof outcome === "function") return outcome(request);
    return Promise.resolve(makeResponse(outcome ?? { content: "default reply" }));
  }

  const document = {
    body: new FakeElement("body"),
    getElementById(id) {
      return elements[id] || null;
    },
    createElement(tagName) {
      return new FakeElement(tagName);
    },
  };

  const context = vm.createContext({
    document,
    window,
    fetch: fetchFake,
    AbortController,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    ReadableStream,
    Blob,
    URL: { createObjectURL(blob) { downloads.push(blob); return "blob:oratrice-" + downloads.length; }, revokeObjectURL() {} },
    TypeError,
    setTimeout: setTimeoutFake,
    clearTimeout: clearTimeoutFake,
  });
  vm.runInContext(DATA_SOURCE, context, { filename: "conversation-data.js" });
  vm.runInContext(STORE_SOURCE, context, { filename: "conversation-store.js" });
  vm.runInContext(STREAM_CLIENT_SOURCE, context, { filename: "stream-client.js" });
  vm.runInContext(APP_SOURCE, context, { filename: "frontends/web/app.js" });

  return {
    context,
    storage,
    downloads,
    confirmAnswers,
    elements,
    requests,
    timers,
    chatOutcomes,
    streamOutcomes,
    window,
    enqueue(outcome) {
      chatOutcomes.push(outcome);
    },
    enqueueStream(outcome) { streamOutcomes.push(outcome); },
    enqueueStatus(outcome) { statusOutcomes.push(outcome); },
    runTimer(delay) {
      const match = [...timers.entries()].find(([, timer]) => timer.delay === delay);
      assert.ok(match, `expected a scheduled timer with delay ${delay}`);
      timers.delete(match[0]);
      match[1].callback();
    },
    chatRequests() {
      return requests.filter((request) => request.url === "/chat");
    },
    streamRequests() {
      return requests.filter((request) => request.url === "/chat/stream");
    },
    statusRequests() {
      return requests.filter((request) => request.url === "/status");
    },
  };
}

async function settle() {
  for (let index = 0; index < 48; index += 1) await Promise.resolve();
}

async function readyPage(options = {}) {
  const page = makePage(options);
  await settle();
  return page;
}

function submitInput(page, message) {
  page.elements["message-input"].value = message;
  return page.elements["chat-form"].dispatch("submit").results[0];
}

function stateHistory(page) {
  return JSON.parse(vm.runInContext("JSON.stringify(chatHistory)", page.context));
}

function contextSize(page, history, currentMessage) {
  const serializedHistory = JSON.stringify(history);
  const serializedCurrent = JSON.stringify(currentMessage);
  return vm.runInContext(
    `contextSizeBytes(${serializedHistory}, ${serializedCurrent})`,
    page.context
  );
}

function messageArticles(page) {
  return page.elements.conversation.children.filter((child) => child.classList.contains("message"));
}

function bodyText(article) {
  return article.children.find((child) => child.classList.contains("message-body")).textContent;
}

test("M15 status polling displays server busy state after delivery is stopped", async () => {
  const page = await readyPage();
  page.enqueueStatus(makeResponse(statusPayload("busy", {
    operation: "stream",
    delivery: "stopped",
  })));

  await vm.runInContext("checkStatus()", page.context);

  assert.equal(page.statusRequests().at(-1).url, "/status");
  assert.equal(page.elements["status-dot"].className, "status-dot status-busy");
  assert.equal(page.elements["status-label"].textContent, "Busy: model work continues after Stop");
  assert.equal(page.elements["message-input"].disabled, false);
});

test("M15 displays Starting separately and keeps active status polling in the two to three second range", async () => {
  const page = await readyPage();
  page.enqueueStatus(makeResponse(statusPayload("starting")));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-dot"].className, "status-dot status-starting");
  assert.equal(page.elements["status-label"].textContent, "Starting");

  page.enqueueStatus(makeResponse(statusPayload("busy", {
    operation: "chat",
    delivery: null,
  })));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-dot"].className, "status-dot status-busy");
  assert.equal(page.elements["status-label"].textContent, "Busy: model work continues");
  assert.ok([...page.timers.values()].some((timer) => timer.delay >= 2_000 && timer.delay <= 3_000));
});

test("M15 distinguishes operation and readiness errors while keeping the composer available", async () => {
  const page = await readyPage();
  page.enqueueStatus(makeResponse(statusPayload("error", { error_code: "operation_failed" })));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-dot"].className, "status-dot status-error");
  assert.equal(page.elements["status-label"].textContent, "Last request failed");

  page.enqueueStatus(makeResponse(statusPayload("error", { error_code: "readiness_failed" })));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-label"].textContent, "Service error");
  assert.equal(page.elements["message-input"].disabled, false);
});

test("M15 status transport loss is Offline and a later valid probe recovers", async () => {
  const page = await readyPage();
  page.enqueueStatus(() => Promise.reject(new TypeError("connection refused")));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-dot"].className, "status-dot status-offline");
  assert.equal(page.elements["status-label"].textContent, "Core unavailable");

  page.enqueueStatus(makeResponse(statusPayload("ready")));
  await vm.runInContext("checkStatus()", page.context);
  assert.equal(page.elements["status-dot"].className, "status-dot status-ready");
  assert.equal(page.elements["status-label"].textContent, "Ready");
});

test("M15 malformed status fails closed instead of claiming readiness", async () => {
  const page = await readyPage();
  const invalidStatuses = [
    { version: 1, state: "ready" },
    statusPayload("busy", { operation: null, delivery: "active" }),
    statusPayload("busy", { operation: "chat", delivery: "stopped" }),
    statusPayload("ready", { operation: "chat" }),
    statusPayload("starting", { error_code: "operation_failed" }),
    statusPayload("error", { error_code: null }),
    statusPayload("ready", { checked_at: "2026-02-31T00:00:00Z" }),
  ];

  for (const payload of invalidStatuses) {
    page.enqueueStatus(makeResponse(payload));
    await vm.runInContext("checkStatus()", page.context);
    assert.equal(page.elements["status-dot"].className, "status-dot status-error");
    assert.equal(page.elements["status-label"].textContent, "Status unavailable");
  }
  assert.equal(page.elements["message-input"].disabled, false);
});

test("M15 status checks are single-flight and pagehide aborts before pageshow resumes polling", async () => {
  const page = await readyPage();
  const pendingStatus = deferred();
  page.enqueueStatus(() => pendingStatus.promise);
  const check = vm.runInContext("checkStatus()", page.context);
  await settle();
  const requestsDuringProbe = page.statusRequests().length;
  await vm.runInContext("checkStatus(); checkStatus()", page.context);
  assert.equal(page.statusRequests().length, requestsDuringProbe);

  const pendingRequest = page.statusRequests().at(-1);
  page.window.dispatch("pagehide");
  assert.equal(pendingRequest.signal.aborted, true);
  const abort = new Error("aborted");
  abort.name = "AbortError";
  pendingStatus.reject(abort);
  await check;

  page.enqueueStatus(makeResponse(statusPayload("ready")));
  page.window.dispatch("pageshow", { persisted: true });
  await settle();
  assert.equal(page.statusRequests().length, requestsDuringProbe + 1);
  assert.equal(page.elements["status-label"].textContent, "Ready");
});

test("M15 status probe timeout is bounded and reported Offline", async () => {
  const page = await readyPage();
  page.enqueueStatus((request) => new Promise((resolve, reject) => {
    request.signal.addEventListener("abort", () => {
      const error = new Error("timed out");
      error.name = "AbortError";
      reject(error);
    }, { once: true });
  }));
  const check = vm.runInContext("checkStatus()", page.context);
  await settle();
  assert.equal(page.statusRequests().at(-1).signal.aborted, false);
  page.runTimer(4_000);
  await check;

  assert.equal(page.statusRequests().at(-1).signal.aborted, true);
  assert.equal(page.elements["status-dot"].className, "status-dot status-offline");
  assert.equal(page.elements["status-label"].textContent, "Core unavailable");
});

test("sends code follow-up with only complete successful pairs and the fixed reply budget", async () => {
  const page = await readyPage();
  const firstMessage = "Explain `add(a, b)`: return a + b";
  const firstAnswer = "The function returns the sum of its two arguments.";
  const followUp = "What does that code return for add(2, 3)?";
  page.enqueue({ content: firstAnswer });
  await submitInput(page, firstMessage);

  const firstRequest = page.chatRequests()[0];
  assert.equal(firstRequest.url, "/chat");
  assert.equal(firstRequest.method, "POST");
  assert.deepEqual(firstRequest.json, {
    message: firstMessage,
    history: [],
    max_tokens: 256,
  });

  page.enqueue({ content: "It returns 5." });
  await submitInput(page, followUp);

  const secondRequest = page.chatRequests()[1];
  assert.deepEqual(secondRequest.json, {
    message: followUp,
    history: [
      { role: "user", content: firstMessage },
      { role: "assistant", content: firstAnswer },
    ],
    max_tokens: 256,
  });
  assert.equal(secondRequest.json.history.some((item) => item.content === followUp), false);
  assert.equal(page.elements["message-input"].value, "");
});

test("failed and empty replies preserve the draft and never enter the next request history", async () => {
  const page = await readyPage();
  const failedDraft = "Explain this after the provider recovers";
  page.enqueue(() => Promise.resolve(makeResponse({ error: { code: "upstream_error" } }, 502)));
  await submitInput(page, failedDraft);

  assert.equal(page.elements["message-input"].value, failedDraft);
  assert.equal(page.elements["message-input"].disabled, false);
  assert.equal(page.elements["send-button"].disabled, false);
  assert.deepEqual(stateHistory(page), []);

  page.enqueue({ content: ["  ", { text: "\n" }] });
  await submitInput(page, failedDraft);
  assert.equal(page.elements["message-input"].value, failedDraft);
  assert.match(page.elements.notice.textContent, /no displayable text/i);
  assert.deepEqual(stateHistory(page), []);

  page.enqueue({ content: "Recovered answer" });
  await submitInput(page, "Try the same question again");
  const requests = page.chatRequests();
  assert.deepEqual(requests[1].json.history, []);
  assert.deepEqual(requests[2].json.history, []);
  assert.deepEqual(stateHistory(page), [
    { role: "user", content: "Try the same question again" },
    { role: "assistant", content: "Recovered answer" },
  ]);
});

test("busy, network, and timeout outcomes have distinct notices and restore controls", async () => {
  const busyPage = await readyPage();
  busyPage.enqueue(() => Promise.resolve(makeResponse({ error: { code: "chat_busy" } }, 503)));
  await submitInput(busyPage, "busy request");
  assert.match(busyPage.elements.notice.textContent, /busy with another request/i);
  assert.equal(busyPage.elements["message-input"].disabled, false);
  assert.equal(busyPage.elements["send-button"].disabled, false);

  const networkPage = await readyPage();
  networkPage.enqueue(() => Promise.reject(new TypeError("Failed to fetch")));
  await submitInput(networkPage, "network request");
  assert.match(networkPage.elements.notice.textContent, /cannot connect to oratrice core/i);
  assert.doesNotMatch(networkPage.elements.notice.textContent, /timed out|busy with another/i);
  assert.equal(networkPage.elements["message-input"].disabled, false);
  assert.equal(networkPage.elements["send-button"].disabled, false);

  const timeoutPage = await readyPage();
  timeoutPage.enqueue((request) => Promise.resolve({
    ok: true,
    status: 200,
    json: () => new Promise((resolve, reject) => {
      request.signal.addEventListener("abort", () => {
        const error = new Error("Body read was aborted");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
    }),
  }));
  const timedRequest = submitInput(timeoutPage, "slow response body");
  await settle();
  assert.equal(timeoutPage.elements["message-input"].disabled, true);
  assert.equal(timeoutPage.elements["send-button"].disabled, true);
  assert.match(timeoutPage.elements.notice.textContent, /thinking/i);
  timeoutPage.runTimer(CHAT_TIMEOUT_MS);
  await timedRequest;
  assert.match(timeoutPage.elements.notice.textContent, /timed out/i);
  assert.doesNotMatch(timeoutPage.elements.notice.textContent, /no displayable text/i);
  assert.equal(timeoutPage.elements["message-input"].disabled, false);
  assert.equal(timeoutPage.elements["send-button"].disabled, false);
});

test("a TypeError while reading the response body is reported as a connection failure", async () => {
  const page = await readyPage();
  page.enqueue(() => Promise.resolve({
    ok: true,
    status: 200,
    json: async () => { throw new TypeError("Connection dropped while reading JSON"); },
  }));
  await submitInput(page, "body read network error");

  assert.match(page.elements.notice.textContent, /cannot connect to oratrice core/i);
  assert.equal(page.elements["message-input"].disabled, false);
  assert.equal(page.elements["send-button"].disabled, false);
  assert.deepEqual(stateHistory(page), []);
});

test("duplicate submissions are ignored while the UI is busy", async () => {
  const page = await readyPage();
  const response = deferred();
  page.enqueue(() => response.promise);
  const first = submitInput(page, "one request only");

  assert.equal(page.elements["message-input"].disabled, true);
  assert.equal(page.elements["send-button"].disabled, true);
  assert.equal(page.elements["new-conversation-button"].disabled, true);
  assert.equal(page.elements.conversation.getAttribute("aria-busy"), "true");
  assert.match(page.elements.notice.textContent, /thinking/i);

  const duplicate = page.elements["chat-form"].dispatch("submit").results[0];
  await duplicate;
  assert.equal(page.chatRequests().length, 1);
  assert.equal(messageArticles(page).length, 1);

  response.resolve(makeResponse({ content: "single response" }));
  await first;
  assert.equal(page.chatRequests().length, 1);
  assert.equal(page.elements.conversation.getAttribute("aria-busy"), "false");
  assert.equal(page.elements["message-input"].disabled, false);
});

test("new conversation and a fresh page both start with empty context", async () => {
  const page = await readyPage();
  page.enqueue({ content: "first answer" });
  await submitInput(page, "first question");
  page.enqueue({ content: "second answer" });
  await submitInput(page, "second question");
  assert.equal(stateHistory(page).length, 4);

  page.elements["new-conversation-button"].dispatch("click");
  assert.deepEqual(stateHistory(page), []);
  assert.equal(page.elements["empty-state"].hidden, false);
  assert.deepEqual(page.elements.conversation.children, [page.elements["empty-state"]]);

  page.enqueue({ content: "new topic answer" });
  await submitInput(page, "new topic");
  assert.deepEqual(page.chatRequests()[2].json.history, []);

  const reloadedPage = await readyPage();
  assert.deepEqual(stateHistory(reloadedPage), []);
  reloadedPage.enqueue({ content: "fresh page answer" });
  await submitInput(reloadedPage, "fresh page question");
  assert.deepEqual(reloadedPage.chatRequests()[0].json.history, []);
});

test("Enter submits, Shift+Enter inserts a line, and IME composition suppresses Enter", async () => {
  const page = await readyPage();
  page.enqueue({ content: "sent by Enter" });
  const input = page.elements["message-input"];

  input.value = "line one";
  const shifted = input.dispatch("keydown", { key: "Enter", shiftKey: true });
  assert.equal(shifted.event.defaultPrevented, false);
  assert.equal(page.chatRequests().length, 0);

  input.dispatch("compositionstart");
  const composing = input.dispatch("keydown", { key: "Enter", shiftKey: false, keyCode: 229 });
  assert.equal(composing.event.defaultPrevented, false);
  assert.equal(page.chatRequests().length, 0);
  input.dispatch("compositionend");

  const normalEnter = input.dispatch("keydown", { key: "Enter", shiftKey: false });
  assert.equal(normalEnter.event.defaultPrevented, true);
  await settle();
  assert.equal(page.chatRequests().length, 1);
  assert.equal(page.chatRequests()[0].json.message, "line one");
});

test("history stops after twelve prior messages, preserving all pairs until reset", async () => {
  const page = await readyPage();
  for (let turn = 0; turn < 7; turn += 1) {
    page.enqueue({ content: `answer ${turn}` });
    await submitInput(page, `question ${turn}`);
  }

  const requests = page.chatRequests();
  assert.equal(requests.length, 7);
  assert.equal(requests[6].json.message, "question 6");
  assert.equal(requests[6].json.history.length, 12);
  assert.deepEqual(requests[6].json.history.slice(0, 2), [
    { role: "user", content: "question 0" },
    { role: "assistant", content: "answer 0" },
  ]);
  assert.equal(requests[6].json.history.some((item) => item.content === "question 6"), false);
  assert.equal(stateHistory(page).length, 14);
  assert.equal(page.elements["message-input"].disabled, true);
  assert.equal(page.elements["send-button"].disabled, true);
  assert.equal(page.elements["new-conversation-button"].disabled, false);

  await submitInput(page, "blocked eighth turn");
  assert.equal(page.chatRequests().length, 7);
  assert.match(page.elements.notice.textContent, /limit/i);

  page.elements["new-conversation-button"].dispatch("click");
  assert.deepEqual(stateHistory(page), []);
  assert.equal(page.elements["message-input"].disabled, false);
  page.enqueue({ content: "new conversation answer" });
  await submitInput(page, "new conversation question");
  assert.deepEqual(page.chatRequests()[7].json.history, []);
});

test("UTF-8 byte boundaries include framing and a full context locks sending", async () => {
  const exactPage = await readyPage();
  const exactAscii = "a".repeat(1504);
  assert.equal(contextSize(exactPage, [], exactAscii), 1536);
  exactPage.enqueue({ content: "ok" });
  await submitInput(exactPage, exactAscii);
  assert.equal(exactPage.chatRequests().length, 1);
  assert.equal(exactPage.chatRequests()[0].json.message, exactAscii);
  // The empty current message still contributes the framing allowance for a
  // future request, so the history no longer leaves room for another send.
  assert.equal(contextSize(exactPage, stateHistory(exactPage), ""), 1602);
  assert.equal(exactPage.elements["message-input"].disabled, true);
  assert.equal(exactPage.elements["send-button"].disabled, true);
  assert.match(exactPage.elements.notice.textContent, /new conversation/i);

  const overPage = await readyPage();
  const oneByteOver = "a".repeat(1505);
  assert.equal(contextSize(overPage, [], oneByteOver), 1537);
  await submitInput(overPage, oneByteOver);
  assert.equal(overPage.chatRequests().length, 0);
  assert.match(overPage.elements.notice.textContent, /context limit/i);

  const multibytePage = await readyPage();
  const multibyteExact = "\u754c".repeat(501);
  const multibyteOver = "\u754c".repeat(502);
  assert.equal(contextSize(multibytePage, [], multibyteExact), 1535);
  assert.equal(contextSize(multibytePage, [], multibyteOver), 1538);
  multibytePage.enqueue({ content: "ok" });
  await submitInput(multibytePage, multibyteExact);
  assert.equal(multibytePage.chatRequests().length, 1);

  const multibyteOverPage = await readyPage();
  await submitInput(multibyteOverPage, multibyteOver);
  assert.equal(multibyteOverPage.chatRequests().length, 0);
});

test("late response after a persisted-page reset cannot overwrite a newer request", async () => {
  const page = await readyPage();
  const oldResponse = deferred();
  const newResponse = deferred();
  page.enqueue(() => oldResponse.promise);
  const oldSubmission = submitInput(page, "old draft");
  const oldRequest = page.chatRequests()[0];
  assert.equal(page.elements["message-input"].disabled, true);

  page.window.dispatch("pagehide");
  assert.equal(oldRequest.signal.aborted, true);
  page.window.dispatch("pageshow", { persisted: true });
  await settle();
  assert.deepEqual(stateHistory(page), []);
  assert.equal(page.elements["message-input"].value, "old draft");
  assert.equal(page.elements["message-input"].disabled, false);

  page.enqueue(() => newResponse.promise);
  const newSubmission = submitInput(page, "new draft");
  const newRequest = page.chatRequests()[1];
  assert.deepEqual(newRequest.json.history, []);
  await settle();
  assert.equal(page.elements["message-input"].disabled, true);

  oldResponse.resolve(makeResponse({ content: "stale answer" }));
  await oldSubmission;
  assert.equal(page.elements["message-input"].disabled, true);
  assert.equal(page.elements["send-button"].disabled, true);
  assert.match(page.elements.notice.textContent, /thinking/i);
  assert.equal(messageArticles(page).some((article) => bodyText(article) === "stale answer"), false);

  newResponse.resolve(makeResponse({ content: "current answer" }));
  await newSubmission;
  assert.deepEqual(stateHistory(page), [
    { role: "user", content: "new draft" },
    { role: "assistant", content: "current answer" },
  ]);
  assert.equal(messageArticles(page).some((article) => bodyText(article) === "old draft"), false);
  assert.equal(messageArticles(page).some((article) => bodyText(article) === "current answer"), true);
});

test("untrusted messages render as text and fetch stays on the three same-origin endpoints", async () => {
  const page = await readyPage();
  const userText = '<img src=x onerror="alert(1)">';
  const assistantText = "<script>not markup</script>";
  page.enqueue({ content: assistantText });
  await submitInput(page, userText);

  const displayed = messageArticles(page).map(bodyText);
  assert.deepEqual(displayed, [userText, assistantText]);
  assert.ok(page.statusRequests().length >= 1);
  assert.equal(page.chatRequests().length, 1);
  assert.ok(page.requests.every((request) => ALLOWED_ENDPOINTS.has(request.url)));
  assert.equal(page.requests.some((request) => request.url === "/route"), false);
});


const STORE_KEY = "oratrice.conversations.v1";
async function toggleSaving(page, enabled) {
  page.elements["save-conversations"].checked = enabled;
  await page.elements["save-conversations"].dispatch("change").results[0];
  await settle();
}

test("M13 budget counter uses UTF-8 and keeps an over-budget draft editable", async () => {
  const page = await readyPage();
  page.elements["message-input"].value = "\u4f60".repeat(502);
  page.elements["message-input"].dispatch("input");
  assert.match(page.elements["context-budget"].textContent, /1538 \/ 1536/);
  assert.equal(page.elements["send-button"].disabled, true);
  assert.equal(page.elements["message-input"].disabled, false);
  assert.equal(page.chatRequests().length, 0);
});

test("M13 marks a truncated reply and exports finish metadata without provider payloads", async () => {
  const page = await readyPage();
  const text = "code\n```python\nprint('\u4f60\u597d')\n```";
  page.enqueue({ content: text, finish_reason: "length", raw: { token: "hidden-value" } });
  await submitInput(page, "Explain this code");
  assert.match(page.elements.notice.textContent, /length limit.*incomplete/i);
  const answer = messageArticles(page).at(-1);
  assert.ok(answer.children.some((x) => /Incomplete reply/.test(x.textContent)));
  page.elements["export-json"].click();
  page.elements["export-markdown"].click();
  assert.equal(page.downloads.length, 2);
  const exported = JSON.parse(await page.downloads[0].text());
  assert.equal(exported.format, "oratrice-conversation");
  assert.equal(exported.messages[1].content, text);
  assert.equal(exported.messages[1].finish_reason, "length");
  assert.doesNotMatch(await page.downloads[0].text(), /hidden-value|raw/);
  assert.match(await page.downloads[1].text(), /incomplete/i);
  assert.equal(page.storage.values.size, 0);
});

test("M13 opt-in survives reload and keeps API history role-content only", async () => {
  const storage = makeStorage();
  const first = await readyPage({ storage });
  first.enqueue({ content: "Remembered locally", finish_reason: "stop" });
  await submitInput(first, "Save this successful pair");
  assert.equal(storage.values.size, 0);
  await toggleSaving(first, true);
  const saved = JSON.parse(storage.getItem(STORE_KEY));
  assert.equal(saved.enabled, true);
  assert.equal(saved.conversations.length, 1);
  const reloaded = await readyPage({ storage });
  assert.equal(messageArticles(reloaded).length, 2);
  assert.equal(reloaded.chatRequests().length, 0);
  reloaded.enqueue({ content: "Continued" });
  await submitInput(reloaded, "Continue");
  assert.deepEqual(reloaded.chatRequests()[0].json.history, [
    { role: "user", content: "Save this successful pair" },
    { role: "assistant", content: "Remembered locally" },
  ]);
  assert.equal(JSON.parse(storage.getItem(STORE_KEY)).conversations[0].messages.length, 4);
});

test("M13 disabling saving retains old records and restores page-memory reload behavior", async () => {
  const storage = makeStorage();
  const page = await readyPage({ storage });
  await toggleSaving(page, true);
  page.enqueue({ content: "Saved" });
  await submitInput(page, "Keep this");
  await toggleSaving(page, false);
  page.enqueue({ content: "Page only" });
  await submitInput(page, "Do not persist this new turn");
  assert.equal(JSON.parse(storage.getItem(STORE_KEY)).conversations[0].messages.length, 2);
  const fresh = await readyPage({ storage });
  assert.equal(messageArticles(fresh).length, 0);
  assert.equal(fresh.elements["save-conversations"].checked, false);
});

test("M13 corrupted storage can be explicitly cleared while chat stays usable", async () => {
  const storage = makeStorage();
  storage.values.set(STORE_KEY, "not-json");
  storage.values.set("unrelated", "keep");
  const page = await readyPage({ storage });
  assert.match(page.elements["storage-status"].textContent, /preserved/i);
  assert.equal(page.elements["clear-conversations"].disabled, false);
  page.enqueue({ content: "Still usable" });
  await submitInput(page, "Hello");
  await page.elements["clear-conversations"].click();
  assert.equal(storage.getItem(STORE_KEY), null);
  assert.equal(storage.getItem("unrelated"), "keep");
  assert.equal(messageArticles(page).length, 2);
});

test("M13 quota and missing locks do not lose drafts or block subsequent chat", async () => {
  const storage = makeStorage();
  const page = await readyPage({ storage });
  await toggleSaving(page, true);
  storage.setItem = () => { throw new Error("quota"); };
  page.enqueue({ content: "Visible despite save failure" });
  await submitInput(page, "Keep visible");
  assert.match(page.elements["storage-status"].textContent, /saving failed/i);
  assert.equal(page.elements["send-button"].disabled, false);
  page.elements["message-input"].value = "unsent draft";
  page.confirmAnswers.push(false);
  page.elements["new-conversation-button"].click();
  assert.equal(page.elements["message-input"].value, "unsent draft");
  assert.equal(messageArticles(page).length, 2);
  const noLocks = await readyPage({ locks: null });
  await toggleSaving(noLocks, true);
  assert.match(noLocks.elements["storage-status"].textContent, /Web Locks/);
  noLocks.enqueue({ content: "Page only is fine" });
  await submitInput(noLocks, "Hello");
  assert.equal(messageArticles(noLocks).length, 2);
});

test("M13 over-budget saved records open without sending or silently trimming", async () => {
  const storage = makeStorage();
  const record = { id: "oversized", title: "Long saved text", revision: 1,
    createdAt: "2026-11-03T00:00:00.000Z", updatedAt: "2026-11-03T00:00:00.000Z",
    messages: [{ role: "user", content: "x".repeat(1400) }, { role: "assistant", content: "y".repeat(200) }] };
  storage.setItem(STORE_KEY, JSON.stringify({ version: 1, enabled: true, activeId: record.id, conversations: [record] }));
  const page = await readyPage({ storage });
  assert.equal(messageArticles(page).length, 2);
  assert.equal(page.chatRequests().length, 0);
  assert.equal(page.elements["send-button"].disabled, true);
  assert.match(page.elements.notice.textContent, /exceeds.*context limit/i);
  assert.equal(stateHistory(page)[0].content.length, 1400);
  assert.equal(page.elements["export-json"].disabled, false);
});

test("M13 deletion retains current page and explicit re-enable saves under a fresh identity", async () => {
  const page = await readyPage();
  await toggleSaving(page, true);
  page.enqueue({ content: "Saved reply" });
  await submitInput(page, "Saved question");
  const original = JSON.parse(page.storage.getItem(STORE_KEY)).conversations[0].id;
  page.elements["saved-conversations"].value = original;
  await page.elements["delete-conversation"].click();
  assert.equal(messageArticles(page).length, 2);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations.length, 0);
  await toggleSaving(page, false);
  await toggleSaving(page, true);
  const records = JSON.parse(page.storage.getItem(STORE_KEY)).conversations;
  assert.equal(records.length, 1);
  assert.notEqual(records[0].id, original);
});


test("M13 opening another saved record protects drafts and selects the displayed record", async () => {
  const page = await readyPage();
  await toggleSaving(page, true);
  page.enqueue({ content: "First answer" });
  await submitInput(page, "First question");
  const first = JSON.parse(page.storage.getItem(STORE_KEY)).activeId;
  page.elements["new-conversation-button"].click();
  await settle();
  page.enqueue({ content: "Second answer" });
  await submitInput(page, "Second question");
  const second = JSON.parse(page.storage.getItem(STORE_KEY)).activeId;
  page.elements["message-input"].value = "keep my draft";
  page.elements["saved-conversations"].value = first;
  page.confirmAnswers.push(false);
  await page.elements["open-conversation"].click();
  assert.equal(page.elements["message-input"].value, "keep my draft");
  assert.equal(stateHistory(page)[0].content, "Second question");
  page.confirmAnswers.push(true);
  await page.elements["open-conversation"].click();
  assert.equal(stateHistory(page)[0].content, "First question");
  assert.equal(page.elements["saved-conversations"].value, first);
  assert.notEqual(first, second);
});

test("M13 cross-tab writes pause saving without replacing the visible conversation", async () => {
  const storage = makeStorage();
  const locks = makeLocks();
  const first = await readyPage({ storage, locks });
  await toggleSaving(first, true);
  first.enqueue({ content: "Original answer" });
  await submitInput(first, "Original question");
  const second = await readyPage({ storage, locks });
  second.enqueue({ content: "Second tab answer" });
  await submitInput(second, "Second tab question");
  await Promise.all(first.window.dispatch("storage", { key: STORE_KEY }));
  assert.equal(stateHistory(first).length, 2);
  assert.match(first.elements["storage-status"].textContent, /another tab.*paused/i);
  first.enqueue({ content: "Page-only answer" });
  await submitInput(first, "First tab unsaved question");
  const record = JSON.parse(storage.getItem(STORE_KEY)).conversations[0];
  assert.equal(record.messages[2].content, "Second tab question");
  assert.equal(record.messages.some((x) => x.content === "First tab unsaved question"), false);
  assert.equal(stateHistory(first)[2].content, "First tab unsaved question");
});

test("M13 bounded lock waiting restores the composer and preserves a typed draft", async () => {
  const locks = { request(name, options) { return new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }); } };
  const page = await readyPage({ locks });
  page.elements["message-input"].value = "draft during save";
  page.elements["save-conversations"].checked = true;
  const pending = page.elements["save-conversations"].dispatch("change").results[0];
  await settle();
  assert.equal(page.elements["message-input"].disabled, true);
  page.runTimer(2000);
  await pending;
  assert.equal(page.elements["message-input"].value, "draft during save");
  assert.equal(page.elements["message-input"].disabled, false);
  assert.equal(page.elements["save-conversations"].checked, false);
  assert.match(page.elements["storage-status"].textContent, /Web Locks/);
});

test("M13 an empty length-limited answer is recoverable and never saved", async () => {
  const page = await readyPage();
  await toggleSaving(page, true);
  page.enqueue({ content: "", finish_reason: "length" });
  await submitInput(page, "Keep this draft");
  assert.equal(page.elements["message-input"].value, "Keep this draft");
  assert.match(page.elements.notice.textContent, /length limit.*without displayable text/i);
  assert.deepEqual(stateHistory(page), []);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations.length, 0);
});

test("M13 reset waits for its saved selection commit and preserves the page on lock timeout", async () => {
  const locks = makeLocks();
  const page = await readyPage({ locks });
  await toggleSaving(page, true);
  page.enqueue({ content: "Saved answer" });
  await submitInput(page, "Saved question");
  const active = JSON.parse(page.storage.getItem(STORE_KEY)).activeId;
  const originalRequest = locks.request;
  locks.request = (name, options) => new Promise((resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  });
  const pending = page.elements["new-conversation-button"].click();
  await settle();
  assert.equal(messageArticles(page).length, 2);
  assert.equal(page.elements["message-input"].disabled, true);
  let warned = false;
  page.window.dispatch("beforeunload", { preventDefault() { warned = true; } });
  assert.equal(warned, true);
  page.runTimer(2000);
  await pending;
  assert.equal(messageArticles(page).length, 2);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).activeId, active);
  assert.equal(page.elements["message-input"].disabled, false);
  assert.match(page.elements["storage-status"].textContent, /refreshing may reopen/);
  locks.request = originalRequest;
  await page.elements["new-conversation-button"].click();
  assert.equal(messageArticles(page).length, 0);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).activeId, null);
  const reloaded = await readyPage({ storage: page.storage, locks });
  assert.equal(messageArticles(reloaded).length, 0);
});

test("M14 streaming is opt-in, sends the same bounded request contract, and commits only after complete", async () => {
  const page = await readyPage();
  assert.equal(page.elements["stream-replies"].checked, false);
  assert.equal(page.elements["stop-button"].hidden, true);
  await toggleSaving(page, true);
  page.elements["stream-replies"].checked = true;
  page.enqueueStream((request) => streamingResponse(request, [
    ["start", { version: 1, request_id: "stream-1", cancellation: "stop_wait_only" }],
    ["delta", { text: "First " }],
    ["delta", { text: "reply 🌿" }],
    ["complete", { finish_reason: "stop" }],
  ]));
  await submitInput(page, "First question");

  assert.deepEqual(page.streamRequests()[0].json, {
    message: "First question", history: [], max_tokens: 256,
  });
  assert.equal(page.chatRequests().length, 0);
  assert.deepEqual(stateHistory(page), [
    { role: "user", content: "First question" },
    { role: "assistant", content: "First reply 🌿" },
  ]);
  assert.equal(messageArticles(page).at(-1)._oratriceBody.textContent, "First reply 🌿");
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations[0].messages[1].content, "First reply 🌿");
  assert.equal(page.elements["message-input"].value, "");
  assert.equal(page.elements["stop-button"].hidden, true);
});

test("M14 displays deltas before completion; Stop preserves the draft and excludes partial text", async () => {
  const page = await readyPage();
  await toggleSaving(page, true);
  page.elements["stream-replies"].checked = true;
  page.enqueueStream((request) => streamingResponse(request));
  const pending = submitInput(page, "Question with a stopped answer");
  await settle();
  const request = page.streamRequests()[0];
  assert.equal(page.elements["stop-button"].hidden, false);
  request.streamController.enqueue(sseEvent("start", {
    version: 1, request_id: "stream-2", cancellation: "stop_wait_only",
  }));
  request.streamController.enqueue(sseEvent("delta", { text: "Visible partial" }));
  await settle();

  const partial = messageArticles(page).at(-1);
  assert.equal(partial._oratriceBody.textContent, "Visible partial");
  assert.deepEqual(stateHistory(page), []);
  assert.equal(page.elements["export-json"].disabled, true);
  page.elements["stop-button"].click();
  await pending;

  assert.equal(request.streamCancelled, true);
  assert.equal(page.elements["message-input"].value, "Question with a stopped answer");
  assert.deepEqual(stateHistory(page), []);
  assert.match(partial._oratriceLabel.textContent, /partial/i);
  assert.match(partial.children.at(-1).textContent, /excluded from conversation history and exports/i);
  assert.match(page.elements.notice.textContent, /model may continue working/i);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations.length, 0);

  page.enqueueStream((next) => streamingResponse(next, [
    ["start", { version: 1, request_id: "stream-3", cancellation: "stop_wait_only" }],
    ["delta", { text: "Recovered" }],
    ["complete", { finish_reason: "stop" }],
  ]));
  await submitInput(page, "Retry with complete response");
  assert.deepEqual(page.streamRequests()[1].json.history, []);
  assert.deepEqual(stateHistory(page), [
    { role: "user", content: "Retry with complete response" },
    { role: "assistant", content: "Recovered" },
  ]);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations[0].messages.length, 2);
});

test("M14 rejects premature EOF and keeps stream provider errors out of history", async () => {
  const page = await readyPage();
  page.elements["stream-replies"].checked = true;
  page.enqueueStream((request) => streamingResponse(request, [
    ["start", { version: 1, request_id: "stream-4", cancellation: "stop_wait_only" }],
    ["delta", { text: "Partial before EOF" }],
  ]));
  await submitInput(page, "EOF draft");
  assert.match(messageArticles(page).at(-1)._oratriceLabel.textContent, /partial/i);
  assert.equal(page.elements["message-input"].value, "EOF draft");
  assert.deepEqual(stateHistory(page), []);
  assert.match(page.elements.notice.textContent, /ended before the reply was complete/i);

  page.enqueueStream((request) => streamingResponse(request, [
    ["start", { version: 1, request_id: "stream-5", cancellation: "stop_wait_only" }],
    ["delta", { text: "Provider began" }],
    ["error", {
      error: { code: "provider_error", message: "The model failed.", request_id: "stream-5" },
      work_may_continue: true,
    }],
  ]));
  await submitInput(page, "Retry after provider error");
  assert.deepEqual(page.streamRequests()[1].json.history, []);
  assert.deepEqual(stateHistory(page), []);
  assert.match(messageArticles(page).at(-1)._oratriceLabel.textContent, /partial/i);
  assert.match(page.elements.notice.textContent, /model service failed/i);
});

test("M14 stream length completion is saved with its truncation status", async () => {
  const page = await readyPage();
  await toggleSaving(page, true);
  page.elements["stream-replies"].checked = true;
  page.enqueueStream((request) => streamingResponse(request, [
    ["start", { version: 1, request_id: "stream-6", cancellation: "stop_wait_only" }],
    ["delta", { text: "Short answer" }],
    ["complete", { finish_reason: "length" }],
  ]));
  await submitInput(page, "Question");
  assert.match(messageArticles(page).at(-1).children.at(-1).textContent, /length limit/);
  assert.equal(JSON.parse(page.storage.getItem(STORE_KEY)).conversations[0].messages[1].finish_reason, "length");
  assert.match(page.elements.notice.textContent, /may be incomplete/i);
});
