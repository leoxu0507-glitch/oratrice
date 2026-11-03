"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  STORAGE_KEY,
  MAX_RECORDS,
  MAX_STORE_BYTES,
  createStore,
} = require("../frontends/web/conversation-store.js");

class FakeStorage {
  constructor(entries = []) {
    this.entries = new Map(entries);
    this.writes = [];
    this.removals = [];
    this.failWrites = false;
  }

  getItem(key) {
    return this.entries.has(key) ? this.entries.get(key) : null;
  }

  setItem(key, value) {
    this.writes.push([key, value]);
    if (this.failWrites) throw new Error("quota exceeded");
    this.entries.set(key, String(value));
  }

  removeItem(key) {
    this.removals.push(key);
    this.entries.delete(key);
  }
}

class SerializedLocks {
  constructor() {
    this.tail = Promise.resolve();
    this.requests = [];
  }

  request(name, options, callback) {
    this.requests.push({ name, mode: options.mode });
    const next = this.tail.then(() => callback({ name, mode: options.mode }));
    this.tail = next.catch(() => undefined);
    return next;
  }
}

function makeRecord(id, revision = 0, text = "question") {
  return {
    id,
    title: id,
    createdAt: "2026-11-03T00:00:00.000Z",
    updatedAt: "2026-11-03T00:00:00.000Z",
    revision,
    messages: [
      { role: "user", content: text },
      { role: "assistant", content: "answer" },
    ],
    ignoredField: "must not persist",
  };
}

function storedState(storage) {
  return JSON.parse(storage.getItem(STORAGE_KEY));
}

test("missing storage is read as disabled without writing or opting in", async () => {
  const storage = new FakeStorage();
  const locks = new SerializedLocks();
  const store = createStore(storage, locks);

  assert.deepEqual(await store.load(), {
    ok: true,
    state: { version: 1, enabled: false, activeId: null, conversations: [] },
  });
  assert.equal(storage.writes.length, 0);
  assert.equal(storage.entries.has(STORAGE_KEY), false);
  assert.equal(locks.requests.length, 0);
});

test("enable persists opt-in; reload reads it and disabling retains records without an active ID", async () => {
  const storage = new FakeStorage();
  const locks = new SerializedLocks();
  const store = createStore(storage, locks);

  const enabled = await store.setEnabled(true);
  assert.equal(enabled.ok, true);
  assert.equal(enabled.state.enabled, true);
  assert.equal(storage.writes.length, 1);
  assert.deepEqual((await createStore(storage, locks).load()).state, enabled.state);

  const created = await store.save(makeRecord("one"), { create: true });
  assert.equal(created.state.conversations[0].revision, 1);
  const disabled = await store.setEnabled(false);
  assert.equal(disabled.ok, true);
  assert.equal(disabled.state.enabled, false);
  assert.equal(disabled.state.activeId, null);
  assert.equal(disabled.state.conversations.length, 1);
  assert.equal((await createStore(storage, locks).load()).state.enabled, false);
});

test("create and update use revisions; stale or deleted records cannot be recreated by update", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, new SerializedLocks());
  await store.setEnabled(true);

  const created = await store.save(makeRecord("one"), { create: true });
  assert.equal(created.ok, true);
  assert.equal(created.state.conversations[0].revision, 1);
  assert.equal(created.state.conversations[0].ignoredField, undefined);

  const updated = await store.save(makeRecord("one", 1, "updated"));
  assert.equal(updated.ok, true);
  assert.equal(updated.state.conversations[0].revision, 2);
  assert.equal((await store.save(makeRecord("one", 1, "stale"))).code, "conflict");

  assert.equal((await store.remove("one")).ok, true);
  assert.equal((await store.save(makeRecord("one", 2, "deleted"))).code, "missing");
  assert.deepEqual((await store.load()).state.conversations, []);
});

test("mutations read fresh state so disjoint updates from separate store instances are preserved", async () => {
  const storage = new FakeStorage();
  const locks = new SerializedLocks();
  const first = createStore(storage, locks);
  await first.setEnabled(true);
  await first.save(makeRecord("one"), { create: true });
  await first.save(makeRecord("two"), { create: true });

  const staleOne = (await createStore(storage, locks).load()).state.conversations[0];
  const staleTwo = (await createStore(storage, locks).load()).state.conversations[1];
  const storeOne = createStore(storage, locks);
  const storeTwo = createStore(storage, locks);
  assert.equal((await storeOne.save({ ...staleOne, messages: makeRecord("one", 1, "changed one").messages })).ok, true);
  assert.equal((await storeTwo.save({ ...staleTwo, messages: makeRecord("two", 1, "changed two").messages })).ok, true);

  const final = storedState(storage);
  assert.deepEqual(final.conversations.map((record) => [record.id, record.revision]), [["one", 2], ["two", 2]]);
  assert.equal(final.conversations[0].messages[0].content, "changed one");
  assert.equal(final.conversations[1].messages[0].content, "changed two");
});

test("record count and serialized store bounds reject writes without evicting existing records", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, new SerializedLocks());
  await store.setEnabled(true);
  for (let index = 0; index < MAX_RECORDS; index += 1) {
    assert.equal((await store.save(makeRecord(`small-${index}`), { create: true })).ok, true);
  }
  const beforeCountFailure = storage.getItem(STORAGE_KEY);
  assert.equal((await store.save(makeRecord("extra"), { create: true })).code, "too_many");
  assert.equal(storage.getItem(STORAGE_KEY), beforeCountFailure);
  assert.equal(storedState(storage).conversations.length, MAX_RECORDS);

  const largeStorage = new FakeStorage();
  const largeStore = createStore(largeStorage, new SerializedLocks());
  await largeStore.setEnabled(true);
  const half = "x".repeat(49_000);
  const largeRecord = (id) => ({
    ...makeRecord(id),
    messages: [
      { role: "user", content: half },
      { role: "assistant", content: half },
    ],
  });
  for (let index = 0; index < 10; index += 1) {
    assert.equal((await largeStore.save(largeRecord(`large-${index}`), { create: true })).ok, true);
  }
  const beforeSizeFailure = largeStorage.getItem(STORAGE_KEY);
  const rejected = await largeStore.save(largeRecord("large-over-limit"), { create: true });
  assert.equal(rejected.code, "too_large");
  assert.equal(largeStorage.getItem(STORAGE_KEY), beforeSizeFailure);
  assert.ok(Buffer.byteLength(beforeSizeFailure, "utf8") <= MAX_STORE_BYTES);
});

test("storage quota failures leave the previously committed state intact", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, new SerializedLocks());
  await store.setEnabled(true);
  await store.save(makeRecord("one"), { create: true });
  const before = storage.getItem(STORAGE_KEY);
  storage.failWrites = true;

  const failed = await store.save(makeRecord("one", 1, "would exceed quota"));
  assert.deepEqual(failed, { ok: false, code: "storage_error" });
  assert.equal(storage.getItem(STORAGE_KEY), before);
});

test("corrupt and unsupported contents fail closed and are not overwritten", async () => {
  for (const [raw, code] of [
    ["{not json", "corrupt"],
    [JSON.stringify({ version: 2, enabled: false, activeId: null, conversations: [] }), "unsupported"],
  ]) {
    const storage = new FakeStorage([[STORAGE_KEY, raw]]);
    const store = createStore(storage, new SerializedLocks());
    assert.deepEqual(await store.load(), { ok: false, code });
    assert.deepEqual(await store.setEnabled(true), { ok: false, code });
    assert.equal(storage.getItem(STORAGE_KEY), raw);
    assert.equal(storage.writes.length, 0);
  }
});

test("blocked or absent storage returns unavailable", async () => {
  const blockedStorage = { getItem() { throw new Error("blocked"); } };
  assert.deepEqual(await createStore(blockedStorage, new SerializedLocks()).load(), {
    ok: false,
    code: "unavailable",
  });
  assert.deepEqual(await createStore(null, new SerializedLocks()).load(), {
    ok: false,
    code: "unavailable",
  });
  assert.deepEqual(await createStore(null, new SerializedLocks()).setEnabled(true), {
    ok: false,
    code: "unavailable",
  });
});

test("writes require Web Locks and missing locks cause no storage writes", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, null);
  assert.deepEqual(await store.setEnabled(true), { ok: false, code: "lock_unavailable" });
  assert.equal(storage.writes.length, 0);
  assert.equal(storage.entries.has(STORAGE_KEY), false);

  const rejectingLocks = { request() { return Promise.reject(new Error("unavailable")); } };
  assert.deepEqual(await createStore(storage, rejectingLocks).clear(), {
    ok: false,
    code: "lock_unavailable",
  });
  assert.equal(storage.removals.length, 0);
});

test("clear removes only the owned key and returns an empty disabled state", async () => {
  const storage = new FakeStorage([["other.app.data", "preserve"]]);
  const locks = new SerializedLocks();
  const store = createStore(storage, locks);
  await store.setEnabled(true);
  await store.save(makeRecord("one"), { create: true });

  const cleared = await store.clear();
  assert.deepEqual(cleared, {
    ok: true,
    state: { version: 1, enabled: false, activeId: null, conversations: [] },
  });
  assert.equal(storage.entries.has(STORAGE_KEY), false);
  assert.equal(storage.entries.get("other.app.data"), "preserve");
  assert.deepEqual(storage.removals, [STORAGE_KEY]);
});

test("activate validates IDs and disabling storage does not select a conversation", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, new SerializedLocks());
  await store.setEnabled(true);
  await store.save(makeRecord("one"), { create: true });
  await store.setEnabled(false);

  assert.equal((await store.activate("missing")).code, "missing");
  const activated = await store.activate("one");
  assert.equal(activated.ok, true);
  assert.equal(activated.state.enabled, false);
  assert.equal(activated.state.activeId, null);
  assert.equal(storedState(storage).activeId, null);
});

test("activate(null) clears the active selection without deleting stored conversations", async () => {
  const storage = new FakeStorage();
  const store = createStore(storage, new SerializedLocks());
  await store.setEnabled(true);
  await store.save(makeRecord("one"), { create: true });

  const cleared = await store.activate(null);
  assert.equal(cleared.ok, true);
  assert.equal(cleared.state.activeId, null);
  assert.equal(cleared.state.conversations.length, 1);
  assert.equal(storedState(storage).activeId, null);
});
test("a pending Web Lock request is aborted at the bounded acquisition deadline", async () => {
  const storage = new FakeStorage();
  let fireDeadline;
  let delayMs;
  let clearedTimer = false;
  let observedSignal;
  const nativeSetTimeout = globalThis.setTimeout;
  const nativeClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => {
    fireDeadline = callback;
    delayMs = delay;
    return "fake-lock-timeout";
  };
  globalThis.clearTimeout = (timer) => {
    assert.equal(timer, "fake-lock-timeout");
    clearedTimer = true;
  };

  try {
    const locks = {
      request(name, options) {
        assert.equal(name, STORAGE_KEY);
        assert.equal(options.mode, "exclusive");
        observedSignal = options.signal;
        return new Promise((resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            const error = new Error("Lock request aborted");
            error.name = "AbortError";
            reject(error);
          }, { once: true });
          queueMicrotask(() => fireDeadline());
        });
      },
    };
    const result = await createStore(storage, locks).setEnabled(true);
    assert.deepEqual(result, { ok: false, code: "lock_unavailable" });
  } finally {
    globalThis.setTimeout = nativeSetTimeout;
    globalThis.clearTimeout = nativeClearTimeout;
  }

  assert.equal(delayMs, 2000);
  assert.equal(observedSignal.aborted, true);
  assert.equal(clearedTimer, true);
  assert.equal(storage.writes.length, 0);
});

test("clear recovers malformed and unsupported owned data without touching other keys", async () => {
  const unsupported = JSON.stringify({ version: 9, enabled: false, activeId: null, conversations: [] });
  for (const raw of ["{invalid", unsupported]) {
    const storage = new FakeStorage([
      [STORAGE_KEY, raw],
      ["other.app.data", "preserve"],
    ]);
    const store = createStore(storage, new SerializedLocks());

    const cleared = await store.clear();
    assert.equal(cleared.ok, true);
    assert.equal(cleared.state.enabled, false);
    assert.deepEqual(cleared.state.conversations, []);
    assert.equal(storage.entries.has(STORAGE_KEY), false);
    assert.equal(storage.entries.get("other.app.data"), "preserve");
    assert.deepEqual(storage.removals, [STORAGE_KEY]);
  }
});