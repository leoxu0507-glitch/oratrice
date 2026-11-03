"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { streamChat, StreamError } = require("../frontends/web/stream-client.js");

const encoder = new TextEncoder();
const event = (name, value) => `event: ${name}\r\ndata: ${JSON.stringify(value)}\r\n\r\n`;
const start = event("start", { version: 1, request_id: "req-1", cancellation: "stop_wait_only" });
const complete = (finish_reason = "stop") => event("complete", { finish_reason });

function responseFrom(chunks, options = {}) {
  let index = 0;
  const state = { cancelled: false, cancelCalls: 0, released: false, reads: 0 };
  const body = new ReadableStream({
    pull(controller) {
      state.reads += 1;
      if (index < chunks.length) controller.enqueue(chunks[index++]);
      else controller.close();
    },
    cancel() { state.cancelled = true; },
  });
  const getReader = body.getReader.bind(body);
  body.getReader = () => {
    const reader = getReader();
    return {
      read: () => reader.read(),
      cancel() { state.cancelCalls += 1; return reader.cancel(); },
      releaseLock() { state.released = true; reader.releaseLock(); },
    };
  };
  const response = {
    ok: options.status == null || (options.status >= 200 && options.status < 300),
    status: options.status ?? 200,
    headers: { get: () => options.contentType || "text/event-stream; charset=utf-8" },
    body,
    async json() { return options.payload || {}; },
  };
  return { response, state };
}

function fetchFor(chunks, options = {}) {
  const result = responseFrom(chunks, options);
  const fetch = async (url, init) => {
    assert.equal(url, "/chat/stream");
    assert.equal(init.method, "POST");
    assert.equal(init.headers.Accept, "text/event-stream");
    assert.deepEqual(JSON.parse(init.body), { message: "hello" });
    options.onRequest?.(init);
    return result.response;
  };
  return { fetch, ...result };
}

test("parses split UTF-8, CRLF, comments, and renders ordered events through EOF", async () => {
  const text = start + ": heartbeat\r\n" + event("delta", { text: "你好 🌿\n" }) + complete("length");
  const bytes = encoder.encode(text);
  const chunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
  const observed = [];
  const fixture = fetchFor(chunks);
  const result = await streamChat("/chat/stream", { message: "hello" }, {
    fetch: fixture.fetch,
    onEvent: (item) => observed.push(item),
  });

  assert.deepEqual(observed.map((item) => item.type), ["start", "delta", "complete"]);
  assert.equal(observed[1].payload.text, "你好 🌿\n");
  assert.equal(result.finishReason, "length");
  assert.equal(result.textBytes, encoder.encode("你好 🌿\n").length);
  assert.ok(fixture.state.cancelCalls >= 1);
  assert.equal(fixture.state.released, true);
});

test("rejects EOF without completion and preserves an explicit server error", async () => {
  const truncated = fetchFor([encoder.encode(start + event("delta", { text: "partial" }))]);
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, { fetch: truncated.fetch }),
    (error) => error instanceof StreamError && error.kind === "incomplete"
  );
  assert.ok(truncated.state.cancelCalls >= 1);
  assert.equal(truncated.state.released, true);

  const failed = fetchFor([encoder.encode(start + event("error", {
    error: { code: "provider_error", message: "The model failed.", request_id: "req-1" },
    work_may_continue: false,
  }))]);
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, { fetch: failed.fetch }),
    (error) => error.kind === "remote_error" && error.code === "provider_error" && error.message === "The model failed."
  );
  assert.ok(failed.state.cancelCalls >= 1);
  assert.equal(failed.state.released, true);
});

test("rejects duplicate terminals, events after completion, and malformed protocol order", async () => {
  for (const wire of [
    start + complete() + complete(),
    start + complete() + event("delta", { text: "late" }),
    event("delta", { text: "before start" }) + complete(),
  ]) {
    const fixture = fetchFor([encoder.encode(wire)]);
    await assert.rejects(
      streamChat("/chat/stream", { message: "hello" }, { fetch: fixture.fetch }),
      (error) => error instanceof StreamError && error.kind === "protocol"
    );
  }
});

test("enforces per-frame, aggregate-text, and event-count limits", async () => {
  const oversizedFrame = fetchFor([encoder.encode(start + event("delta", { text: "x" }))]);
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, {
      fetch: oversizedFrame.fetch,
      limits: { maxFrameBytes: 12 },
    }),
    (error) => error.kind === "limit"
  );

  const oversizedText = fetchFor([encoder.encode(start + event("delta", { text: "🌿" }) + complete())]);
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, {
      fetch: oversizedText.fetch,
      limits: { maxTextBytes: 3 },
    }),
    (error) => error.kind === "limit"
  );

  const tooMany = fetchFor([encoder.encode(start + event("delta", { text: "a" }) + event("delta", { text: "b" }) + complete())]);
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, {
      fetch: tooMany.fetch,
      limits: { maxEvents: 2 },
    }),
    (error) => error.kind === "limit"
  );
});

test("aborting an in-flight body cancels and releases the reader", async () => {
  const controller = new AbortController();
  let streamController;
  let cancelled = false;
  let released = false;
  const body = new ReadableStream({
    start(value) {
      streamController = value;
      value.enqueue(encoder.encode(start));
    },
    pull() { return new Promise(() => {}); },
    cancel() { cancelled = true; },
  });
  const fetch = async (_url, init) => {
    init.signal.addEventListener("abort", () => {
      const error = new Error("aborted"); error.name = "AbortError";
      streamController.error(error);
    }, { once: true });
    return {
      ok: true,
      headers: { get: () => "text/event-stream" },
      body: {
        getReader() {
          const reader = body.getReader();
          return {
            read: () => reader.read(),
            cancel: async () => { cancelled = true; await reader.cancel(); },
            releaseLock: () => { released = true; reader.releaseLock(); },
          };
        },
      },
    };
  };
  const pending = streamChat("/chat/stream", { message: "hello" }, { fetch, signal: controller.signal });
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  await assert.rejects(pending, (error) => error.kind === "cancelled" && error.workMayContinue);
  assert.equal(cancelled, true);
  assert.equal(released, true);
});

test("a complete event finishes the reply without waiting for an open body", async () => {
  let cancellationStarted = false;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(start + event("delta", { text: "done" }) + complete("stop")));
    },
    pull() { return new Promise(() => {}); },
    cancel() {
      cancellationStarted = true;
      return new Promise(() => {});
    },
  });
  const pending = streamChat("/chat/stream", { message: "hello" }, {
    fetch: async () => ({
      ok: true,
      headers: { get: () => "text/event-stream" },
      body,
    }),
  });
  const result = await Promise.race([
    pending,
    new Promise((_, reject) => setTimeout(() => reject(new Error("stream awaited EOF or cancellation")), 500)),
  ]);
  assert.equal(result.finishReason, "stop");
  assert.equal(cancellationStarted, true);
});

test("aborting releases the reader when its underlying cancel hook never resolves", async () => {
  const controller = new AbortController();
  let streamController;
  let cancellationStarted = false;
  const body = new ReadableStream({
    start(value) {
      streamController = value;
      value.enqueue(encoder.encode(start));
    },
    pull() { return new Promise(() => {}); },
    cancel() {
      cancellationStarted = true;
      return new Promise(() => {});
    },
  });
  const fetch = async (_url, init) => {
    init.signal.addEventListener("abort", () => {
      const error = new Error("aborted"); error.name = "AbortError";
      try { streamController.error(error); } catch { /* The body may already be cancelled. */ }
    }, { once: true });
    return {
      ok: true,
      headers: { get: () => "text/event-stream" },
      body,
    };
  };
  const pending = streamChat("/chat/stream", { message: "hello" }, { fetch, signal: controller.signal });
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  const result = await Promise.race([
    pending.then((value) => ({ value }), (error) => ({ error })),
    new Promise((_, reject) => setTimeout(() => reject(new Error("stream cleanup awaited a hanging cancel hook")), 500)),
  ]);
  assert.equal(result.error.kind, "cancelled");
  assert.equal(result.error.workMayContinue, true);
  assert.equal(cancellationStarted, true);
});

test("covers response headers with the total deadline and maps non-stream responses", async () => {
  let capturedTimer;
  const controller = new AbortController();
  const waiting = streamChat("/chat/stream", { message: "hello" }, {
    signal: controller.signal,
    fetch: (_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => {
        const error = new Error("aborted"); error.name = "AbortError"; reject(error);
      }, { once: true });
    }),
    setTimeout(callback) { capturedTimer = callback; return 1; },
    clearTimeout() {},
  });
  await new Promise((resolve) => setImmediate(resolve));
  capturedTimer();
  await assert.rejects(waiting, (error) => error.kind === "timeout" && error.workMayContinue);

  const wrongType = fetchFor([], { contentType: "application/json" });
  await assert.rejects(
    streamChat("/chat/stream", { message: "hello" }, { fetch: wrongType.fetch }),
    (error) => error.kind === "protocol"
  );
  assert.equal(wrongType.state.cancelled, false);
});
