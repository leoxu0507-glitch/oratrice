"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const conversationData = require("../frontends/web/conversation-data.js");

const createdAt = "2026-11-03T10:30:00.000Z";
const updatedAt = "2026-11-03T10:31:00+00:00";

function makeRecord(overrides = {}) {
  return {
    id: "conversation_01",
    title: "A conversation",
    createdAt,
    updatedAt,
    revision: 3,
    messages: [
      { role: "user", content: "Question" },
      { role: "assistant", content: "Answer" },
    ],
    ...overrides,
  };
}

test("exports a frozen API to CommonJS without browser or storage access at import", () => {
  assert.equal(Object.isFrozen(conversationData), true);
  assert.deepEqual(Object.keys(conversationData).sort(), [
    "byteLength",
    "exportJson",
    "exportMarkdown",
    "sanitizeRecord",
  ]);

  const source = fs.readFileSync(
    path.join(__dirname, "..", "frontends", "web", "conversation-data.js"),
    "utf8"
  );
  const browserContext = vm.createContext({});
  vm.runInContext(source, browserContext, { filename: "conversation-data.js" });
  assert.equal(Object.isFrozen(browserContext.OratriceConversationData), true);
});

test("sanitizes to allowlisted fields and derives a single-line title", () => {
  const input = makeRecord({
    title: undefined,
    revision: undefined,
    provider: "private-provider",
    raw: { token: "never export this" },
    apiKey: "secret",
    messages: [
      {
        role: "user",
        content: "  First line\nsecond line  ",
        finish_reason: "ignored for users",
        provider: "private-provider",
        raw: { response: "private" },
      },
      {
        role: "assistant",
        content: "Reply",
        finish_reason: "stop",
        model: "private-model",
        secret: "private",
      },
    ],
  });
  delete input.title;
  delete input.revision;
  const before = JSON.stringify(input);

  const clean = conversationData.sanitizeRecord(input);

  assert.deepEqual(Object.keys(clean), [
    "id",
    "title",
    "createdAt",
    "updatedAt",
    "revision",
    "messages",
  ]);
  assert.equal(clean.title, "First line second line");
  assert.equal(clean.revision, 0);
  assert.deepEqual(clean.messages, [
    { role: "user", content: "  First line\nsecond line  " },
    { role: "assistant", content: "Reply", finish_reason: "stop" },
  ]);
  assert.notEqual(clean, input);
  assert.notEqual(clean.messages, input.messages);
  assert.notEqual(clean.messages[0], input.messages[0]);
  assert.equal(JSON.stringify(input), before);
  assert.equal(JSON.stringify(clean).includes("private"), false);
});

test("JSON export round-trips exact Unicode and code content while omitting internal fields", () => {
  const tick = String.fromCharCode(96);
  const userText = "  const value = " + tick + "界🙂" + tick + ";\r\n"
    + "line two with café and 日本語\n";
  const assistantText = "🙂 Code stays text:\n" + tick.repeat(3) + "js\n"
    + "console.log(" + tick + "café" + tick + ");\n" + tick.repeat(3) + "\n";
  const record = makeRecord({
    title: "Code • Unicode",
    messages: [
      { role: "user", content: userText },
      { role: "assistant", content: assistantText, finish_reason: null },
    ],
    providerRaw: { key: "secret" },
  });

  const payload = JSON.parse(conversationData.exportJson(record));

  assert.equal(payload.format, "oratrice-conversation");
  assert.equal(payload.version, 1);
  assert.equal(payload.title, "Code • Unicode");
  assert.equal(payload.created_at, createdAt);
  assert.equal(payload.updated_at, updatedAt);
  assert.deepEqual(payload.messages, record.messages);
  assert.equal("id" in payload, false);
  assert.equal("revision" in payload, false);
  assert.equal("providerRaw" in payload, false);
  assert.equal(conversationData.byteLength("A界🙂"), 8);
});

test("Markdown uses longer outer fences, preserves message text, and labels truncated replies", () => {
  const tick = String.fromCharCode(96);
  const userText = "Example:\n" + tick.repeat(3) + "js\n"
    + "const sample = 1;\n" + tick.repeat(3) + "\n";
  const assistantText = "Output:\n" + tick.repeat(4) + "\n"
    + "Done 🙂\n" + tick.repeat(4) + "\n";
  const markdown = conversationData.exportMarkdown(makeRecord({
    title: "Safe # heading <tag>",
    messages: [
      { role: "user", content: userText },
      { role: "assistant", content: assistantText, finish_reason: "length" },
    ],
  }));

  assert.ok(markdown.includes("## User\n\n" + tick.repeat(4) + "text\n"));
  assert.ok(markdown.includes(userText));
  assert.ok(markdown.includes("## Oratrice (incomplete response)"));
  assert.ok(markdown.includes(tick.repeat(5) + "text\n" + assistantText));
  assert.match(markdown, /^# Safe \\# heading \\<tag\\>$/m);
  assert.doesNotMatch(markdown, /<tag>/);
});

test("rejects invalid identifiers, dates, titles, revisions, roles, pair shapes, and finish reasons", () => {
  const invalidRecords = [
    makeRecord({ id: "unsafe/id" }),
    makeRecord({ id: "safe_id\n" }),
    makeRecord({ createdAt: "2026-02-30T10:30:00Z" }),
    makeRecord({ createdAt: "2026-11-03T10:30:00Z\n" }),
    makeRecord({ updatedAt: "not a date" }),
    makeRecord({ title: " \n " }),
    makeRecord({ title: "x".repeat(101) }),
    makeRecord({ revision: -1 }),
    makeRecord({ revision: 1.5 }),
    makeRecord({ messages: [{ role: "assistant", content: "wrong first role" }, { role: "user", content: "wrong second role" }] }),
    makeRecord({ messages: [{ role: "user", content: "unpaired" }] }),
    makeRecord({ messages: [{ role: "user", content: "first" }, { role: "assistant", content: "second", finish_reason: "x".repeat(65) }] }),
  ];

  for (const record of invalidRecords) {
    assert.throws(() => conversationData.sanitizeRecord(record));
  }
});

test("rejects malformed Unicode, blank content, excessive rows, and records over 128 KiB", () => {
  const invalidUnicode = String.fromCharCode(0xD800);
  assert.throws(() => conversationData.sanitizeRecord(makeRecord({
    messages: [
      { role: "user", content: invalidUnicode },
      { role: "assistant", content: "reply" },
    ],
  })), /valid Unicode/);

  assert.throws(() => conversationData.sanitizeRecord(makeRecord({
    messages: [
      { role: "user", content: " \t\n " },
      { role: "assistant", content: "reply" },
    ],
  })), /nonblank/);

  const tooManyMessages = Array.from({ length: 202 }, (_, index) => ({
    role: index % 2 === 0 ? "user" : "assistant",
    content: "message " + index,
  }));
  assert.throws(() => conversationData.sanitizeRecord(makeRecord({ messages: tooManyMessages })));

  assert.throws(() => conversationData.sanitizeRecord(makeRecord({
    messages: [
      { role: "user", content: "x".repeat(130 * 1024) },
      { role: "assistant", content: "reply" },
    ],
  })), /128 KiB/);
});
