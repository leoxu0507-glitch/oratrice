"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { TextEncoder } = require("node:util");

const APP_SOURCE = fs.readFileSync(
  path.join(__dirname, "..", "frontends", "web", "app.js"),
  "utf8"
);
const CHAT_TIMEOUT_MS = 120_000;
const ALLOWED_ENDPOINTS = new Set(["/live", "/ready", "/chat"]);

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

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function makePage() {
  const elements = {
    "chat-form": new FakeElement("form"),
    "message-input": new FakeElement("textarea"),
    "send-button": new FakeElement("button"),
    "new-conversation-button": new FakeElement("button"),
    conversation: new FakeElement("section"),
    "empty-state": new FakeElement("div"),
    notice: new FakeElement("p"),
    "status-dot": new FakeElement("span"),
    "status-label": new FakeElement("span"),
  };
  elements.conversation.append(elements["empty-state"]);

  const windowListeners = new Map();
  const window = {
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

    if (request.url === "/live") return Promise.resolve(makeResponse({ healthy: true }));
    if (request.url === "/ready") return Promise.resolve(makeResponse({ healthy: true }));
    if (request.url !== "/chat") {
      return Promise.reject(new Error(`Unexpected endpoint: ${request.url}`));
    }

    const outcome = chatOutcomes.shift();
    if (typeof outcome === "function") return outcome(request);
    return Promise.resolve(makeResponse(outcome ?? { content: "default reply" }));
  }

  const document = {
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
    TypeError,
    setTimeout: setTimeoutFake,
    clearTimeout: clearTimeoutFake,
  });
  vm.runInContext(APP_SOURCE, context, { filename: "frontends/web/app.js" });

  return {
    context,
    elements,
    requests,
    timers,
    chatOutcomes,
    window,
    enqueue(outcome) {
      chatOutcomes.push(outcome);
    },
    runTimer(delay) {
      const match = [...timers.entries()].find(([, timer]) => timer.delay === delay);
      assert.ok(match, `expected a scheduled timer with delay ${delay}`);
      timers.delete(match[0]);
      match[1].callback();
    },
    chatRequests() {
      return requests.filter((request) => request.url === "/chat");
    },
  };
}

async function settle() {
  for (let index = 0; index < 16; index += 1) await Promise.resolve();
}

async function readyPage() {
  const page = makePage();
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
  assert.ok(page.requests.length >= 3);
  assert.ok(page.requests.every((request) => ALLOWED_ENDPOINTS.has(request.url)));
  assert.equal(page.requests.some((request) => request.url === "/route"), false);
});
