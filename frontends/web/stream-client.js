(function attachOratriceStreamClient(root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module !== null && module.exports) module.exports = api;
  else if (root) root.OratriceStreamClient = api;
})(typeof globalThis === "object" ? globalThis : this, function createOratriceStreamClient() {
  "use strict";

  const DEFAULT_LIMITS = Object.freeze({
    timeoutMs: 120_000,
    maxFrameBytes: 16 * 1024,
    maxTextBytes: 64 * 1024,
    maxEvents: 4096,
  });

  class StreamError extends Error {
    constructor(message, options = {}) {
      super(message);
      this.name = "StreamError";
      this.kind = options.kind || "stream";
      this.status = options.status;
      this.code = options.code;
      this.requestId = options.requestId;
      this.workMayContinue = options.workMayContinue === true;
    }
  }

  function byteLength(value, encoder) {
    return encoder.encode(value).byteLength;
  }

  function createParser(onEvent, limits, encoder) {
    let line = "";
    let lineBytes = 0;
    let lineCR = false;
    let frameBytes = 0;
    let eventName = "";
    let dataFields = [];
    let eventCount = 0;
    let textBytes = 0;
    let started = false;
    let terminal = null;

    function dispatch() {
      if (dataFields.length === 0) {
        frameBytes = 0;
        eventName = "";
        return;
      }
      eventCount += 1;
      if (eventCount > limits.maxEvents) throw new StreamError("The streamed response exceeded its event limit.", { kind: "limit" });

      const name = eventName || "message";
      if (!["start", "delta", "complete", "error", "cancelled"].includes(name)) {
        throw new StreamError("The server sent an unknown streaming event.", { kind: "protocol" });
      }
      if (terminal !== null) throw new StreamError("The server sent data after the stream ended.", { kind: "protocol" });

      let payload;
      try { payload = JSON.parse(dataFields.join("\n")); }
      catch { throw new StreamError("The server sent an invalid streaming event.", { kind: "protocol" }); }
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new StreamError("The server sent an invalid streaming event.", { kind: "protocol" });
      }

      if (!started) {
        if (name !== "start" || payload.version !== 1 || typeof payload.request_id !== "string" || !payload.request_id || payload.cancellation !== "stop_wait_only") {
          throw new StreamError("The streaming session did not start correctly.", { kind: "protocol" });
        }
        started = true;
      } else if (name === "start") {
        throw new StreamError("The server started the stream more than once.", { kind: "protocol" });
      }

      if (name === "delta") {
        if (!started || typeof payload.text !== "string") throw new StreamError("The server sent an invalid text update.", { kind: "protocol" });
        textBytes += byteLength(payload.text, encoder);
        if (textBytes > limits.maxTextBytes) throw new StreamError("The streamed reply exceeded its size limit.", { kind: "limit" });
      } else if (name === "complete") {
        if (!started || !(payload.finish_reason === null || typeof payload.finish_reason === "string")
          || (typeof payload.finish_reason === "string" && payload.finish_reason.length > 64)) {
          throw new StreamError("The server sent an invalid completion event.", { kind: "protocol" });
        }
        terminal = name;
      } else if (name === "error") {
        const error = payload.error;
        if (!error || typeof error !== "object" || typeof error.code !== "string" || typeof error.message !== "string") {
          throw new StreamError("The server sent an invalid error event.", { kind: "protocol" });
        }
        terminal = name;
      } else if (name === "cancelled") {
        if (typeof payload.reason !== "string" || payload.work_may_continue !== true) {
          throw new StreamError("The server sent an invalid cancellation event.", { kind: "protocol" });
        }
        terminal = name;
      }

      const event = { type: name, payload };
      dataFields = [];
      eventName = "";
      frameBytes = 0;
      onEvent(event);
    }

    function finishLine(terminatorBytes) {
      frameBytes += lineBytes + terminatorBytes;
      if (frameBytes > limits.maxFrameBytes) throw new StreamError("The streaming frame exceeded its limit.", { kind: "limit" });
      if (line === "") dispatch();
      else if (line[0] !== ":") {
        const separator = line.indexOf(":");
        const field = separator < 0 ? line : line.slice(0, separator);
        let value = separator < 0 ? "" : line.slice(separator + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") eventName = value;
        else if (field === "data") dataFields.push(value);
      }
      line = "";
      lineBytes = 0;
    }

    function push(text) {
      for (const character of text) {
        if (lineCR) {
          lineCR = false;
          if (character === "\n") continue;
        }
        if (character === "\r") {
          // Count CRLF as two bytes before seeing whether the next byte is LF;
          // CR-only event streams remain supported with a conservative bound.
          finishLine(2);
          lineCR = true;
          continue;
        }
        if (character === "\n") {
          finishLine(1);
          continue;
        }
        const size = byteLength(character, encoder);
        lineBytes += size;
        if (frameBytes + lineBytes > limits.maxFrameBytes) throw new StreamError("The streaming frame exceeded its limit.", { kind: "limit" });
        line += character;
      }
    }

    return Object.freeze({
      push,
      finish() {
        if (line.length) finishLine(0);
        if (terminal !== "complete") {
          if (terminal === "error") throw new StreamError("The model could not complete this streamed reply.", { kind: "remote_error" });
          if (terminal === "cancelled") throw new StreamError("The server stopped sending this reply; model work may continue.", { kind: "remote_cancelled", workMayContinue: true });
          throw new StreamError("The stream ended before the reply was complete.", { kind: "incomplete" });
        }
        return true;
      },
      get terminal() { return terminal; },
      get eventCount() { return eventCount; },
      get textBytes() { return textBytes; },
    });
  }

  async function streamChat(url, body, options = {}) {
    const limits = { ...DEFAULT_LIMITS, ...(options.limits || {}) };
    const fetchImpl = options.fetch || globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new StreamError("The streaming request is unavailable.", { kind: "network" });
    if (typeof ReadableStream !== "function" || typeof TextDecoder !== "function" || typeof TextEncoder !== "function") {
      throw new StreamError("This browser does not support streamed replies.", { kind: "unsupported" });
    }
    const encoder = new TextEncoder();

    const controller = new AbortController();
    const callerSignal = options.signal;
    let timeoutHit = false;
    const abortFromCaller = () => controller.abort();
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
    if (callerSignal?.aborted) abortFromCaller();
    const timer = (options.setTimeout || globalThis.setTimeout)(() => {
      timeoutHit = true;
      controller.abort();
    }, limits.timeoutMs);
    const clear = options.clearTimeout || globalThis.clearTimeout;
    let reader = null;
    let completed = false;
    let sourceEnded = false;
    let terminal = null;
    let finishReason = null;
    const emit = typeof options.onEvent === "function" ? options.onEvent : () => {};
    const parser = createParser((event) => {
      if (event.type === "error") {
        const failure = event.payload.error;
        terminal = "error";
        const error = new StreamError(failure.message || "The model could not complete this reply.", {
          kind: "remote_error", code: failure.code, requestId: failure.request_id,
          workMayContinue: event.payload.work_may_continue,
        });
        error.payload = { error: failure };
        emit(event);
        throw error;
      }
      if (event.type === "cancelled") {
        terminal = "cancelled";
        emit(event);
        throw new StreamError("The server stopped sending this reply; model work may continue.", {
          kind: "remote_cancelled", code: event.payload.reason,
          requestId: event.payload.request_id, workMayContinue: true,
        });
      }
      if (event.type === "complete") {
        terminal = "complete";
        finishReason = event.payload.finish_reason;
      }
      emit(event);
    }, limits, encoder);
    const cancelPendingRead = () => {
      if (reader) Promise.resolve(reader.cancel()).catch(() => {});
    };
    controller.signal.addEventListener("abort", cancelPendingRead, { once: true });

    try {
      const response = await fetchImpl(url, {
        method: "POST",
        headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response?.ok) {
        let payload = null;
        try { payload = await response.json(); } catch { payload = null; }
        const error = new StreamError("The streaming request failed.", { kind: "http", status: response?.status, code: payload?.error?.code });
        error.payload = payload;
        throw error;
      }
      const contentType = response.headers?.get?.("content-type") || "";
      if (!contentType.toLowerCase().startsWith("text/event-stream")) {
        throw new StreamError("The server did not return a streaming response.", { kind: "protocol" });
      }
      if (!response.body || typeof response.body.getReader !== "function") {
        throw new StreamError("This browser cannot read streamed replies.", { kind: "unsupported" });
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: true });
      while (true) {
        const { value, done } = await reader.read();
        if (done) { sourceEnded = true; break; }
        if (!(value instanceof Uint8Array)) throw new StreamError("The server sent invalid stream bytes.", { kind: "protocol" });
        let decoded;
        try { decoded = decoder.decode(value, { stream: true }); }
        catch { throw new StreamError("The server sent invalid UTF-8 stream data.", { kind: "protocol" }); }
        parser.push(decoded);
        // A terminal event ends the application response. Parsing the whole
        // received chunk above still catches duplicate or later events in it.
        if (parser.terminal === "complete") break;
      }
      try { parser.push(decoder.decode()); }
      catch { throw new StreamError("The server sent invalid UTF-8 stream data.", { kind: "protocol" }); }
      parser.finish();
      completed = true;
      return Object.freeze({ finishReason, eventCount: parser.eventCount, textBytes: parser.textBytes });
    } catch (error) {
      if ((callerSignal?.aborted || controller.signal.aborted)
        && !(error instanceof StreamError && error.kind === "remote_error")) {
        if (timeoutHit) throw new StreamError("The streamed reply timed out. The model may continue working, and Oratrice may stay busy until it finishes.", { kind: "timeout", workMayContinue: true });
        throw new StreamError("The displayed reply was stopped. The model may continue working, and Oratrice may stay busy until it finishes.", { kind: "cancelled", workMayContinue: true });
      }
      if (error instanceof StreamError) throw error;
      if (error instanceof TypeError) throw new StreamError("Cannot connect to Oratrice Core while streaming.", { kind: "network" });
      if (error instanceof Error && error.name === "AbortError") {
        if (timeoutHit) throw new StreamError("The streamed reply timed out. The model may continue working, and Oratrice may stay busy until it finishes.", { kind: "timeout", workMayContinue: true });
        throw new StreamError("The displayed reply was stopped. The model may continue working, and Oratrice may stay busy until it finishes.", { kind: "cancelled", workMayContinue: true });
      }
      throw new StreamError("The streamed reply could not be read.", { kind: "stream" });
    } finally {
      clear(timer);
      callerSignal?.removeEventListener("abort", abortFromCaller);
      controller.signal.removeEventListener("abort", cancelPendingRead);
      if (!completed) controller.abort();
      if (reader && (!completed || !sourceEnded)) {
        try { Promise.resolve(reader.cancel()).catch(() => {}); }
        catch { /* The transport may already be closed. */ }
      }
      if (reader) {
        try { reader.releaseLock(); } catch { /* The browser may already have released it. */ }
      }
    }
  }

  return Object.freeze({
    DEFAULT_LIMITS,
    StreamError,
    streamChat,
  });
});
