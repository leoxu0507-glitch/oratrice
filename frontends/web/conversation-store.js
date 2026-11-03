(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./conversation-data.js"));
  } else {
    root.OratriceConversationStore = factory(root.OratriceConversationData);
  }
})(typeof globalThis === "object" ? globalThis : this, function (data) {
  "use strict";

  const STORAGE_KEY = "oratrice.conversations.v1";
  const MAX_RECORDS = 20;
  const MAX_STORE_BYTES = 1024 * 1024;
  const LOCK_NAME = STORAGE_KEY;
  const LOCK_TIMEOUT_MS = 2000;
  const STATE_KEYS = new Set(["version", "enabled", "activeId", "conversations"]);
  const FAILURE = Object.freeze({
    unavailable: "unavailable",
    corrupt: "corrupt",
    unsupported: "unsupported",
    lockUnavailable: "lock_unavailable",
    invalidValue: "invalid_value",
    invalidRecord: "invalid_record",
    disabled: "disabled",
    exists: "exists",
    missing: "missing",
    conflict: "conflict",
    tooMany: "too_many",
    tooLarge: "too_large",
    storageError: "storage_error",
  });

  function success(state) {
    return { ok: true, state };
  }

  function failure(code) {
    return { ok: false, code };
  }

  function emptyState() {
    return {
      version: 1,
      enabled: false,
      activeId: null,
      conversations: [],
    };
  }

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function sanitizeRecord(record) {
    if (!data || typeof data.sanitizeRecord !== "function") return null;
    try {
      const sanitized = data.sanitizeRecord(record);
      return isObject(sanitized) ? sanitized : null;
    } catch (_) {
      return null;
    }
  }

  function serializedSize(serialized) {
    if (!data || typeof data.byteLength !== "function") return NaN;
    try {
      return data.byteLength(serialized);
    } catch (_) {
      return NaN;
    }
  }

  function validSize(size) {
    return Number.isFinite(size) && size >= 0;
  }

  function checkStoreBounds(state) {
    if (state.conversations.length > MAX_RECORDS) return FAILURE.tooMany;
    let serialized;
    try {
      serialized = JSON.stringify(state);
    } catch (_) {
      return FAILURE.invalidRecord;
    }
    const size = serializedSize(serialized);
    if (!validSize(size)) return FAILURE.invalidRecord;
    return size > MAX_STORE_BYTES ? FAILURE.tooLarge : null;
  }

  function validateState(parsed) {
    if (!isObject(parsed)) return failure(FAILURE.corrupt);
    if (!Object.prototype.hasOwnProperty.call(parsed, "version")) return failure(FAILURE.corrupt);
    if (parsed.version !== 1) return failure(FAILURE.unsupported);
    if (Object.keys(parsed).some((key) => !STATE_KEYS.has(key))) return failure(FAILURE.corrupt);
    if (typeof parsed.enabled !== "boolean") return failure(FAILURE.corrupt);
    if (parsed.activeId !== null && (typeof parsed.activeId !== "string" || parsed.activeId.length === 0)) {
      return failure(FAILURE.corrupt);
    }
    if (!Array.isArray(parsed.conversations)) return failure(FAILURE.corrupt);
    if (parsed.conversations.length > MAX_RECORDS) return failure(FAILURE.tooMany);

    const ids = new Set();
    const conversations = [];
    for (const record of parsed.conversations) {
      const sanitized = sanitizeRecord(record);
      if (!sanitized || typeof sanitized.id !== "string" || sanitized.id.length === 0 || ids.has(sanitized.id)) {
        return failure(FAILURE.corrupt);
      }
      ids.add(sanitized.id);
      conversations.push(sanitized);
    }

    if (parsed.activeId !== null && !ids.has(parsed.activeId)) return failure(FAILURE.corrupt);
    if (!parsed.enabled && parsed.activeId !== null) return failure(FAILURE.corrupt);

    const state = {
      version: 1,
      enabled: parsed.enabled,
      activeId: parsed.activeId,
      conversations,
    };
    const boundsError = checkStoreBounds(state);
    return boundsError ? failure(boundsError) : success(state);
  }

  function createStore(storage, lockManager) {
    function readState() {
      if (!storage) return failure(FAILURE.unavailable);
      let raw;
      try {
        const getItem = storage.getItem;
        if (typeof getItem !== "function") return failure(FAILURE.unavailable);
        raw = getItem.call(storage, STORAGE_KEY);
      } catch (_) {
        return failure(FAILURE.unavailable);
      }
      if (raw === null) return success(emptyState());
      if (typeof raw !== "string") return failure(FAILURE.corrupt);
      const rawSize = serializedSize(raw);
      if (!validSize(rawSize)) return failure(FAILURE.corrupt);
      if (rawSize > MAX_STORE_BYTES) return failure(FAILURE.tooLarge);

      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (_) {
        return failure(FAILURE.corrupt);
      }
      return validateState(parsed);
    }

    async function withLock(operation) {
      if (!storage) return failure(FAILURE.unavailable);
      try {
        const request = lockManager && lockManager.request;
        if (typeof request !== "function"
          || typeof AbortController !== "function"
          || typeof setTimeout !== "function"
          || typeof clearTimeout !== "function") {
          return failure(FAILURE.lockUnavailable);
        }

        const controller = new AbortController();
        let acquired = false;
        let timedOut = false;
        const timer = setTimeout(function () {
          if (acquired) return;
          timedOut = true;
          controller.abort();
        }, LOCK_TIMEOUT_MS);

        try {
          const result = await request.call(lockManager, LOCK_NAME, {
            mode: "exclusive",
            signal: controller.signal,
          }, function (lock) {
            if (!lock) return failure(FAILURE.lockUnavailable);
            acquired = true;
            return operation();
          });
          return timedOut && !acquired ? failure(FAILURE.lockUnavailable) : result;
        } catch (_) {
          return failure(FAILURE.lockUnavailable);
        } finally {
          clearTimeout(timer);
        }
      } catch (_) {
        return failure(FAILURE.lockUnavailable);
      }
    }
    function writeState(state) {
      if (!storage) return failure(FAILURE.unavailable);
      const boundsError = checkStoreBounds(state);
      if (boundsError) return failure(boundsError);
      try {
        const setItem = storage.setItem;
        if (typeof setItem !== "function") return failure(FAILURE.unavailable);
        setItem.call(storage, STORAGE_KEY, JSON.stringify(state));
      } catch (_) {
        return failure(FAILURE.storageError);
      }
      return success(state);
    }

    async function load() {
      return readState();
    }

    async function setEnabled(enabled) {
      if (typeof enabled !== "boolean") return failure(FAILURE.invalidValue);
      return withLock(function () {
        const loaded = readState();
        if (!loaded.ok) return loaded;
        const state = loaded.state;
        if (state.enabled === enabled && (enabled || state.activeId === null)) return success(state);
        state.enabled = enabled;
        if (!enabled) state.activeId = null;
        return writeState(state);
      });
    }

    async function save(record, options) {
      const create = Boolean(options && options.create === true);
      const sanitized = sanitizeRecord(record);
      if (!sanitized || typeof sanitized.id !== "string" || sanitized.id.length === 0) {
        return failure(FAILURE.invalidRecord);
      }
      if (!Number.isInteger(sanitized.revision) || sanitized.revision < 0) {
        return failure(FAILURE.invalidRecord);
      }

      return withLock(function () {
        const loaded = readState();
        if (!loaded.ok) return loaded;
        const state = loaded.state;
        if (!state.enabled) return failure(FAILURE.disabled);

        const index = state.conversations.findIndex((item) => item.id === sanitized.id);
        if (create) {
          if (index !== -1) return failure(FAILURE.exists);
          if (sanitized.revision !== 0) return failure(FAILURE.conflict);
          if (state.conversations.length >= MAX_RECORDS) return failure(FAILURE.tooMany);
          sanitized.revision = 1;
          state.conversations.push(sanitized);
        } else {
          if (index === -1) return failure(FAILURE.missing);
          const current = state.conversations[index];
          if (sanitized.revision !== current.revision) return failure(FAILURE.conflict);
          sanitized.revision = current.revision + 1;
          state.conversations[index] = sanitized;
        }

        state.activeId = sanitized.id;
        return writeState(state);
      });
    }

    async function activate(id) {
      if (id !== null && (typeof id !== "string" || id.length === 0)) {
        return failure(FAILURE.invalidValue);
      }
      return withLock(function () {
        const loaded = readState();
        if (!loaded.ok) return loaded;
        const state = loaded.state;
        if (id !== null && !state.conversations.some((item) => item.id === id)) {
          return failure(FAILURE.missing);
        }
        if (!state.enabled || state.activeId === id) return success(state);
        state.activeId = id;
        return writeState(state);
      });
    }

    async function remove(id) {
      if (typeof id !== "string" || id.length === 0) return failure(FAILURE.invalidValue);
      return withLock(function () {
        const loaded = readState();
        if (!loaded.ok) return loaded;
        const state = loaded.state;
        const index = state.conversations.findIndex((item) => item.id === id);
        if (index === -1) return failure(FAILURE.missing);
        state.conversations.splice(index, 1);
        if (state.activeId === id) state.activeId = null;
        return writeState(state);
      });
    }

    async function clear() {
      return withLock(function () {
        if (!storage) return failure(FAILURE.unavailable);
        let getItem;
        let removeItem;
        try {
          getItem = storage.getItem;
          removeItem = storage.removeItem;
          if (typeof getItem !== "function" || typeof removeItem !== "function") {
            return failure(FAILURE.unavailable);
          }
          // Reading while locked also makes clear the recovery path for malformed data.
          getItem.call(storage, STORAGE_KEY);
        } catch (_) {
          return failure(FAILURE.unavailable);
        }
        try {
          removeItem.call(storage, STORAGE_KEY);
          return success(emptyState());
        } catch (_) {
          return failure(FAILURE.storageError);
        }
      });
    }
    return Object.freeze({ load, setEnabled, save, activate, remove, clear });
  }

  return Object.freeze({
    STORAGE_KEY,
    MAX_RECORDS,
    MAX_STORE_BYTES,
    createStore,
  });
});