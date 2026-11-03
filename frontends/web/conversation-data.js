(function attachConversationData(root, createApi) {
  "use strict";

  const api = createApi();
  if (typeof module === "object" && module !== null && module.exports) {
    module.exports = api;
  } else if (root) {
    root.OratriceConversationData = api;
  }
})(globalThis, function createConversationDataApi() {
  "use strict";

  const MAX_RECORD_BYTES = 128 * 1024;
  const MAX_MESSAGES = 200;
  const MAX_TITLE_LENGTH = 100;
  const MAX_FINISH_REASON_LENGTH = 64;
  const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const BACKTICK = String.fromCharCode(96);

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function isWellFormedUnicode(value) {
    for (let index = 0; index < value.length; index += 1) {
      const codeUnit = value.charCodeAt(index);
      if (codeUnit >= 0xD800 && codeUnit <= 0xDBFF) {
        const next = value.charCodeAt(index + 1);
        if (!(next >= 0xDC00 && next <= 0xDFFF)) return false;
        index += 1;
      } else if (codeUnit >= 0xDC00 && codeUnit <= 0xDFFF) {
        return false;
      }
    }
    return true;
  }

  function requireUnicodeString(value, label) {
    if (typeof value !== "string") {
      throw new TypeError(label + " must be a string");
    }
    if (!isWellFormedUnicode(value)) {
      throw new TypeError(label + " must contain valid Unicode");
    }
    return value;
  }

  function validIsoDate(value) {
    if (typeof value !== "string") return false;

    const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})?)?$/.exec(value);
    if (!match || match[0] !== value) return false;

    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (month < 1 || month > 12) return false;

    const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (day < 1 || day > monthDays[month - 1]) return false;

    if (match[4] !== undefined) {
      const hour = Number(match[4]);
      const minute = Number(match[5]);
      const second = match[6] === undefined ? 0 : Number(match[6]);
      if (hour > 23 || minute > 59 || second > 59) return false;
    }

    const zone = match[8];
    if (zone && zone !== "Z") {
      const offsetHour = Number(zone.slice(1, 3));
      const offsetMinute = Number(zone.slice(4, 6));
      if (offsetHour > 23 || offsetMinute > 59) return false;
    }

    return true;
  }

  function requireIsoDate(value, label) {
    if (!validIsoDate(value)) {
      throw new TypeError(label + " must be a valid ISO date string");
    }
    return value;
  }

  function truncateToCodeUnits(value, maxLength) {
    let result = "";
    for (const character of value) {
      if (result.length + character.length > maxLength) break;
      result += character;
    }
    return result;
  }

  function deriveTitle(firstUserMessage) {
    const singleLine = firstUserMessage
      .replace(/[\r\n\u0085\u2028\u2029]+/g, " ")
      .trim();
    const title = truncateToCodeUnits(singleLine, MAX_TITLE_LENGTH);
    if (!title.trim()) {
      throw new TypeError("title must be a nonblank string");
    }
    return title;
  }

  function byteLength(value) {
    if (typeof value !== "string") {
      throw new TypeError("byteLength expects a string");
    }
    if (typeof TextEncoder !== "function") {
      throw new Error("TextEncoder is required to measure UTF-8 bytes");
    }
    return new TextEncoder().encode(value).byteLength;
  }

  function sanitizeRecord(record) {
    if (!isObject(record)) {
      throw new TypeError("record must be an object");
    }

    const idMatch = typeof record.id === "string"
      ? /^[A-Za-z0-9_-]{1,80}$/.exec(record.id)
      : null;
    if (!idMatch || idMatch[0] !== record.id) {
      throw new TypeError("id must be a safe opaque string");
    }

    const createdAt = requireIsoDate(record.createdAt, "createdAt");
    const updatedAt = requireIsoDate(record.updatedAt, "updatedAt");

    const revision = hasOwn(record, "revision") ? record.revision : 0;
    if (!Number.isSafeInteger(revision) || revision < 0) {
      throw new TypeError("revision must be a nonnegative integer");
    }

    if (!Array.isArray(record.messages)
      || record.messages.length === 0
      || record.messages.length > MAX_MESSAGES
      || record.messages.length % 2 !== 0) {
      throw new TypeError("messages must contain 1 to 100 complete pairs");
    }

    const messages = record.messages.map((message, index) => {
      if (!isObject(message) || !hasOwn(message, "role") || !hasOwn(message, "content")) {
        throw new TypeError("each message must have a role and content");
      }

      const expectedRole = index % 2 === 0 ? "user" : "assistant";
      if (message.role !== expectedRole) {
        throw new TypeError("messages must alternate user and assistant roles");
      }

      const content = requireUnicodeString(message.content, "message content");
      if (!content.trim()) {
        throw new TypeError("message content must be nonblank");
      }

      const cleanMessage = { role: expectedRole, content };
      if (expectedRole === "assistant" && hasOwn(message, "finish_reason")) {
        const finishReason = message.finish_reason;
        if (finishReason !== null) {
          requireUnicodeString(finishReason, "finish_reason");
          if (finishReason.length > MAX_FINISH_REASON_LENGTH) {
            throw new RangeError("finish_reason must be at most 64 characters");
          }
        }
        cleanMessage.finish_reason = finishReason;
      }
      return cleanMessage;
    });

    let title;
    if (hasOwn(record, "title")) {
      title = requireUnicodeString(record.title, "title");
      if (title.length > MAX_TITLE_LENGTH) {
        throw new RangeError("title must be at most 100 characters");
      }
      if (!title.trim()) {
        throw new TypeError("title must be a nonblank string");
      }
    } else {
      title = deriveTitle(messages[0].content);
    }

    const cleanRecord = {
      id: record.id,
      title,
      createdAt,
      updatedAt,
      revision,
      messages,
    };
    if (byteLength(JSON.stringify(cleanRecord)) > MAX_RECORD_BYTES) {
      throw new RangeError("conversation record exceeds 128 KiB");
    }

    return cleanRecord;
  }

  function exportJson(record) {
    const cleanRecord = sanitizeRecord(record);
    const exportable = {
      format: "oratrice-conversation",
      version: 1,
      title: cleanRecord.title,
      created_at: cleanRecord.createdAt,
      updated_at: cleanRecord.updatedAt,
      messages: cleanRecord.messages,
    };
    return JSON.stringify(exportable, null, 2) + "\n";
  }

  function escapeMarkdownHeader(value) {
    const singleLine = value.replace(/[\r\n\u0085\u2028\u2029]+/g, " ");
    const punctuation = "!\"#$%&'()*+,-./:;<=>?@[\\]^_" + BACKTICK + "{|}~";
    let escaped = "";
    for (const character of singleLine) {
      if (punctuation.includes(character)) escaped += "\\";
      escaped += character;
    }
    return escaped;
  }

  function markdownFence(content) {
    let maxRun = 0;
    let currentRun = 0;
    for (const character of content) {
      if (character === BACKTICK) {
        currentRun += 1;
        if (currentRun > maxRun) maxRun = currentRun;
      } else {
        currentRun = 0;
      }
    }
    return BACKTICK.repeat(Math.max(3, maxRun + 1));
  }

  function markdownMessage(content) {
    const fence = markdownFence(content);
    const bodyEnd = /[\r\n]$/.test(content) ? "" : "\n";
    return fence + "text\n" + content + bodyEnd + fence;
  }

  function exportMarkdown(record) {
    const cleanRecord = sanitizeRecord(record);
    const sections = ["# " + escapeMarkdownHeader(cleanRecord.title)];

    for (let index = 0; index < cleanRecord.messages.length; index += 2) {
      const userMessage = cleanRecord.messages[index];
      const assistantMessage = cleanRecord.messages[index + 1];
      sections.push("## User\n\n" + markdownMessage(userMessage.content));

      const assistantHeading = assistantMessage.finish_reason === "length"
        ? "## Oratrice (incomplete response)"
        : "## Oratrice";
      sections.push(assistantHeading + "\n\n" + markdownMessage(assistantMessage.content));
    }

    return sections.join("\n\n") + "\n";
  }

  return Object.freeze({
    sanitizeRecord,
    byteLength,
    exportJson,
    exportMarkdown,
  });
});
