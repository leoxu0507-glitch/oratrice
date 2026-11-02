# M11 daily conversation UI

Date: 2026-11-02 (Asia/Hong_Kong).

Disposition: **M11 functional acceptance PASS with injected providers**.
Overall project status remains **DEGRADED** until the inherited real-model,
hardware, and native-console acceptance is completed.

## Scope and acceptance

The approved milestone adds only recent, in-memory conversation context and
the experience needed for daily text chat. The Web client remains the
conversation surface; a future desktop pet may consume status. Long-term
memory, persistence, vector databases, automatic summaries, agents, tools,
voice, vision, cloud enablement, and streaming are outside this change.

| Task | Implementation | Acceptance |
| --- | --- | --- |
| M11.1 Minimal multi-turn contract | Optional strict text history on `/chat`, canonical role-preserving provider messages, contextual router input, legacy requests retained | In-process HTTP/Core/provider checks |
| M11.2 Context budget | Bounded history, UTF-8/framing budget, bounded reply tokens, pre-parse request-body cap, explicit reset guidance | Boundary, multibyte, count, chunked-body, and recovery checks |
| M11.3 Chat states and errors | New conversation, successful-pair commit, preserved failed draft, duplicate protection, distinct service/busy/timeout errors | Shipped JavaScript behavior checks |
| M11.4 UI/API integration | Refresh/reset, keyboard/IME behavior, same-origin API, English copy | Integration and browser acceptance recorded below |

## Conversation contract

The client sends `message` plus previous complete successful user/assistant
pairs in `history`. It excludes the current draft, failed attempts, empty
responses, and pending turns. The HTTP DTO rejects privileged roles, extra
fields, nontext history, invalid ordering, and invalid UTF-8. The Core
preserves role/content boundaries for the canonical provider port. The
decision-only router receives recent transcript text to interpret follow-ups.
Neither service retains a session store or writes conversation data.

The UI resets on refresh or New conversation. It accepts at most 12 *prior*
messages on a request, so a last successful request may leave 14 visible
messages before reset is required. No earlier turn is silently discarded.
The API applies a 1536-unit budget to history-supplied requests: UTF-8 content
bytes plus 32 units per message. Replies default to and are capped at 256
tokens. The browser uses the same constants and a finite draft length.
Legacy requests without `history` (or with `null`) keep their sampling and
structured single-message behavior. All chat request bodies are capped at
65536 bytes before JSON parsing, including chunked uploads.

The byte/framing budget is deliberately conservative for the small-context
starting profile. It bounds application input; it does not prove the exact
token count for an arbitrary model/template or guarantee hardware stability.
Provider context limits remain authoritative. A long response can use the
remaining input budget and require a new conversation before another turn.

Busy requests are not retried automatically. Timeouts and page navigation
stop the browser wait, not upstream computation. The M9 admission slot remains
held until the actual facade call returns. Failure recovery re-enables the
composer without adding a false successful turn.

## Verification ledger

- DTO/policy worker: attempt 1 stopped during collection because a pytest
  parameter used reserved name `request`; attempt 2 passed 19 tests; after
  adding strict-list/current-message coverage, attempt 3 passed 20 tests.
  No fourth focused attempt.
- HTTP/Core integration: attempt 1 passed 33 tests in 1.34s, including legacy
  facade/API contracts, M9 admission, M5 boundaries, and new M11 body/context
  and history forwarding checks. Fakes were injected; no model was contacted.
- JavaScript VM behavior: attempt 1 passed 10 of 11 tests; the remaining
  assertion omitted the 32-unit framing allowance for the next current message.
  Correcting that test expectation led to attempt 2: **11 passed, 0 failed**.
  The suite executes the shipped script with inert DOM/HTTP/timer fakes and
  covers successful context, duplicate sends, failed drafts, empty replies,
  timeout/network/busy handling, reset, refresh/lifecycle, keyboard/IME, and
  byte/count boundaries. No Node process is added to the Python suite.
  During final English-source review, a raw multibyte test character was
  replaced by its equivalent JavaScript Unicode escape. This representation-only
  edit preserves the test value and was statically reviewed without another run.
- Browser-tool discovery: the optional Playwright import was unusable and its
  CommonJS fallback was absent. No package was installed. Browser acceptance
  uses the existing Edge executable and Node/CDP instead.
- Real Edge/CDP: the first Edge acceptance run passed, after the two earlier
  tooling-discovery failures. No further browser run was performed. It used
  the shipped `/ui/` and the actual API/Core with an injected local provider,
  producing six test chat requests. Multi-turn payloads, failed-draft recovery,
  reset, byte-budget rejection, refresh, actual Enter/Shift+Enter, a synthetic
  composing-Enter event, 390-pixel viewport layout, and absence of runtime
  exceptions passed. Desktop/mobile screenshots were visually inspected.
  This does not test an actual OS input method or a real model's comprehension.
- Final complete Python regression: attempt 1 **211 passed in 3.59s**, using
  the canonical checkout's Python 3.13.5 `.venv`. The JavaScript gate and
  browser harness used installed Node 25.6.0. CI selects Node 22; that remote
  gate was defined but not dispatched. M10's clean-export installation result
  remains separate historical evidence, not this run's environment.
- The sandbox process helper failed before early source-inspection commands
  could start. Reviewed commands subsequently used escalated execution. These
  were environment setup failures, not product test results.

Commands for the successful automated gates, from the repository root:

```powershell
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp work/m11-full-suite-01
node --test tests/web_chat.test.cjs
```

The disposable, untracked browser harness and screenshots remain under
`work/m11-browser-*` for local inspection. It used an ephemeral loopback port,
a new isolated Edge profile, and no production configuration or user browser
profile. Its exact API PID 26452 and browser PID 28400 were reaped; a follow-up
process check also found no Edge process using that test profile. No service
or model was left running by this acceptance run.

## Corrections from owner review

- The UI initially stopped before a request with exactly 12 prior messages,
  while the API accepted that boundary. Both now allow that final request;
  after its successful reply the finite 14-message transcript requires reset.
- A catch around `response.json()` could swallow an abort or connection failure
  after headers arrived, presenting it as an empty reply. It now propagates
  abort/network errors to their specific recovery paths.
- The draft has a finite HTML length cap in addition to the byte budget.
  Completed history that leaves no room for another message immediately
  requests New conversation. Failed and empty responses never become context.

All three implementation/verification `luna_worker` tasks completed. The owner
reviewed their changes, integrated the protected Core/API path, and retained
one shared bounded verification ledger. No test gate exceeded three attempts.

## Remaining release boundary

M9/M10 real-model startup, chat/restart, native user-console cleanup, and
hardware stability are not closed by an injected-provider browser check.
Current preflight observed 4356204 KiB free RAM out of 16395004 KiB, with no
listeners on the configured 4000/8000/8080/8082/8090 ports. This is still
insufficient evidence to assert full-stack stability; the owning task does
not load large models or reclassify the earlier deferred acceptance.

Public GitHub refs/releases are unchanged. Existing M9/M10 local work is
preserved. No production dependency or frontend build is added; Node is a
separate test gate only.
