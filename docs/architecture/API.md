# Oratrice HTTP API

`oratrice_api.create_api` is a thin, provider-neutral FastAPI boundary around
the core facade. Constructing the ASGI app only registers routes and the
repository-bundled static UI mount. The composition factory runs during
FastAPI lifespan with `auto_start=False`, so imports and app construction do
not load models, start runtimes, open sockets, or construct providers.

## Endpoints

### `POST /chat`

Accepts a strict JSON DTO (`extra=forbid`) containing `message`, optional
`model`/`provider`, capability flags, metadata, and generation options
(`temperature`, `max_tokens`, `top_p`, `stop`).  The response is the safe
`ChatResponse` view: content, model, finish reason, usage, provider,
correlation ID, and metadata.  Raw transport payloads, causes, and prompt
fields are never serialized.

M11 adds optional `history` for an in-memory conversation. It contains only
previous successful, complete user/assistant pairs, in chronological order;
the current user input remains in `message`:

```json
{
  "message": "Continue explaining that code.",
  "history": [
    {"role": "user", "content": "Explain def add(a, b): return a + b"},
    {"role": "assistant", "content": "The function adds its two inputs."}
  ],
  "max_tokens": 256
}
```

History supports text only, rejects system/tool roles and extra fields, starts
with a user and ends with an assistant. It excludes failed requests and the
current message. The Core passes the role-preserving messages to the selected
provider and a text transcript to the decision-only router. Neither the API
nor the Core retains conversation state. Omit `history` to keep the legacy
single-message contract and its generation-option semantics; explicit `null`
has the same legacy meaning. Structured single-message content remains valid.

When `history` is supplied, even as `[]`, the following limits apply:

- At most 12 prior messages (six complete pairs).
- At most 1536 budget units: the UTF-8 content byte count of all prior messages
  and the current message, plus 32 units per message for framing.
- `max_tokens` defaults to 256 and must be between 1 and 256.

These conservative defaults suit the small-context deployment starting point.
They bound application requests, not exact model tokenization or measured
hardware capacity; a provider may still reject a request for its own context
limit. No transcript is silently trimmed, summarized, or retried. Budget
exhaustion returns HTTP 422 with code `context_limit` and instructions to
shorten the message or start a new conversation. A response that fills the
remaining input budget may be displayed but require a new conversation before
the next request. All `POST /chat` bodies, including legacy requests and
chunked uploads, have a 65536-byte transport limit enforced before JSON parsing;
excess returns HTTP 413 with `request_too_large` and no facade invocation.

M9 admits one model operation at a time per API application instance. Chat
and route share the slot. An overlapping operation receives HTTP 503 with
`chat_busy` or `route_busy`, `retryable: true`, and `Retry-After: 1`.
The slot remains held until the synchronous facade call actually returns,
including on error. A browser timeout or disconnect is not proof that the
upstream model stopped computing. Health and static UI endpoints do not
acquire this slot. Run one Uvicorn worker for the local single-model profile;
multiple workers or API instances have independent admission slots. This
limits model execution, not transport-level request buffering under a flood.

### `POST /chat/stream`

This additive endpoint accepts the same strict DTO as `/chat`. History and
context limits are unchanged; streaming always defaults to 256 reply tokens
and rejects values outside 1-256, including legacy single-message requests.
The request-body limit is 65536 bytes. A malformed, oversized, or busy request
returns the usual JSON error before streaming begins. A facade without a
stream operation returns HTTP 501 with `stream_unsupported`. A selected
provider that cannot stream returns a terminal SSE error; no implicit retry,
provider change, cloud fallback, or second inference occurs.

A successful HTTP response has `Content-Type: text/event-stream`,
`Cache-Control: no-cache, no-transform`, and UTF-8 JSON SSE frames:

| Event | Data | Meaning |
| --- | --- | --- |
| `start` | `version: 1`, opaque `request_id`, `cancellation: "stop_wait_only"` | Delivery began; this is not evidence that model text is ready. |
| `delta` | `text` | Append this text safely in order. |
| `complete` | `finish_reason` (string or null) | Iteration and cleanup ended successfully; commit the assembled nonblank answer. `length` remains visibly incomplete. |
| `error` | Safe `error` envelope and `work_may_continue` | Fail the turn; retain any displayed partial text separately from successful history. |
| `cancelled` | `reason`, `work_may_continue: true` | Delivery deadline or bounds ended the response. |

There is one `start`, followed by zero or more deltas and one terminal event
when transport permits. EOF without a terminal success is a failed partial
turn. Error payloads use fixed public messages and omit raw chunks, credentials,
internal provider payloads, and prompts. The event format is Oratrice's API
contract, separate from upstream OpenAI-compatible SSE framing. The existing
transport adapters retain their [LiteLLM streaming interface](https://docs.litellm.ai/docs/completion/stream).

Each API instance has one model-operation slot shared by `/chat`, `/route`,
and `/chat/stream`. Stream setup, routing, iterator reads, and close all run
on one worker. The API buffers at most eight events, each frame is at most
16 KiB, assembled text is at most 64 KiB, and at most 4096 SSE events are
delivered. Delivery has a 120-second deadline. Queue waits and ASGI sends
are bounded at five seconds, with a short best-effort terminal send if the
client is already stalled. Health requests do not acquire the slot.

Stop aborts the browser fetch. Disconnect, timeout, and slow consumption
stop delivery; the worker continues draining and discarding upstream output
until iteration returns or fails, then closes its iterator on the same thread
and releases admission. The API never closes an executing generator from a
different thread. A new operation can receive `chat_busy`/`route_busy` until
that work ends. A disconnected client cannot be promised a final event.
There is no remote-inference cancellation guarantee. An unresponsive provider
can keep its slot occupied beyond the delivery deadline, subject to its own
transport timeout; delivery timeout is not permission to overlap inference.

The bundled UI offers streaming as a page-local opt-in and keeps ordinary
chat as its default. Interrupted or failed text is marked partial and excluded
from future context, browser history, and exports. The draft remains editable
for an explicit retry; no automatic retry is performed.

### `POST /route`

Accepts the routing request fields and calls the injected facade's public
`route(message=..., model_id=..., request_id=<uuid>, ...)` method.  The response
contains only `RouteDecision` fields plus the same top-level `request_id`; it
never contains an answer or provider transport object.

### `GET /health`

Calls `facade.health` and serializes the safe `HealthReport`.  This probe always
returns HTTP 200; dependency failures are represented as `status: unhealthy`
with redacted details.  Lazy configured providers remain lazy and are not
constructed merely to answer health.

### `GET /live` and `GET /ready`

`/live` is a process-liveness probe and returns HTTP 200 without touching the
application graph. `/ready` evaluates the configured required launcher targets
and returns HTTP 200 only when required readiness is satisfied; an optional
degradation remains HTTP 200 with `healthy: true`, while a required failure is
HTTP 503. Neither endpoint returns credentials, prompts, raw transport data, or
exception causes.

The declared Core API launcher target uses `/live`. The external `/ready`
checker already probes the required model and Gateway endpoints; it must not
call the API's full `/health` diagnostic as its own process check. Once a
provider is active, full diagnostics may call an upstream health implementation
that performs inference. Using `/health` here can therefore add model work and
time out the status check after an otherwise successful chat. Existing copied
profiles should change the Core target's `health_endpoint` to `/live`.

### `GET /status`

M15's shared frontend status endpoint returns HTTP 200 while Core is alive:

```json
{
  "version": 1,
  "state": "busy",
  "operation": "stream",
  "delivery": "stopped",
  "error_code": null,
  "checked_at": "2026-11-03T09:00:00+00:00"
}
```

| Field | Contract |
| --- | --- |
| `version` | Integer `1`. |
| `state` | `starting`, `ready`, `busy`, or `error`. Clients derive Offline from transport failure. |
| `operation` | `chat`, `route`, or `stream` only while busy; otherwise null. |
| `delivery` | `active` or `stopped` for a busy stream; otherwise null. |
| `error_code` | Null, `operation_failed`, `readiness_failed`, or `readiness_unavailable`. No exception details. |
| `checked_at` | UTC ISO timestamp for this snapshot. |

Busy comes from the actual shared model-operation slot. It remains busy after
Stop or disconnect while upstream output drains and cleanup runs. Admission
generation tokens prevent an older stream's delayed callback from changing a
newer operation's status. Busy/error/ready are API-instance observations;
the single-worker deployment requirement remains unchanged.

The latest operation failure remains Error until a new operation is admitted.
An overlapping busy rejection or an invalid request does not replace active
operation state. Starting means readiness is not yet confirmed. Missing an
explicit checker is Starting with `readiness_unavailable`; known dependency
loss after a prior ready sample or a checker exception is Error.

Readiness uses only the explicitly supplied `readiness_checker` or
`readiness_provider` (including application/facade attributes or static reports).
There is no fallback to facade/provider health, model construction, routing,
or inference. Supply a read-only, timeout-bounded checker. The default live
composition supplies its existing external endpoint readiness adapter.
Sampling uses a five-second cache and single-flight guard; concurrent polls
use a cached result for at most 15 seconds during a blocked refresh, then
report Error. A busy snapshot bypasses sampling. A successful response
contains no prompts, transcript, model/provider identities, endpoints, or
credentials. `/live`, `/ready`, and `/health` keep their existing contracts.

The Web UI polls at 2.5-second intervals with a four-second wait limit. The
standalone pet polls approximately every two seconds with a two-second
request/body budget. Both use capped backoff up to 30 seconds on connection
failures and one outstanding poll. They report malformed data as Error and
do not claim Ready from a failed status response. Polling does not trigger
inference; dependency observations can lag their configured cache/poll window.

### `GET /ui/`

The repository ships a small dependency-free HTML/CSS/ES-module client under
`frontends/web/`. The API serves it at `/ui/` using the same loopback origin as
the JSON endpoints; `/ui/app.js` and `/ui/styles.css` are static assets. The
mount only registers a route and does not start a process, open a socket, or
construct the Core application.

The UI calls `/status` for shared execution status and `/chat` for ordinary
conversation. It intentionally does not call `/route` for a normal chat and
contains no model/provider selection, tools, agents, voice, vision, or cloud
implementation. It optionally consumes `/chat/stream` for incremental replies.
Conversation history is page-only by default;
refresh clears it unless the user has enabled local saving.

### Bundled UI retention and export

Local saving is an explicit opt-in and is off by default. When enabled, the UI
stores conversations under the `oratrice.conversations.v1` localStorage key
for this origin and browser profile. The data is plaintext browser storage,
not encrypted or stored by the API. Saving requires the browser Web Locks API
and an exclusive lock; waiting to acquire it is limited to two seconds. If
storage or locking is unavailable, page-only chat and export remain available.

The store allows at most 20 conversations, at most 1 MiB of UTF-8 serialized
store data, and at most 128 KiB of UTF-8 serialized data per record. Each
record has at most 200 alternating user/assistant messages (100 complete
pairs). The UI does not silently evict records or trim messages: a save that
exceeds a limit fails and leaves the current page available for export or
manual cleanup. Only successful pairs with displayable assistant text are
saved. An assistant response with `finish_reason: "length"` is retained with
that marker and shown as incomplete; failed and empty responses are not
committed.

Turning saving off stops future automatic writes and clears the stored
active selection, but leaves existing records and the current page available.
New conversation clears the page transcript without deleting saved records.
With saving enabled, it commits the active-selection reset before clearing
the page. If the storage lock times out, the existing transcript stays visible
and can be exported; pending storage operations also trigger an unload warning.
Delete saved removes one record from this key. If it is active, the current
page copy remains; start a new conversation before saving again. Clear saved
explicitly removes this application-owned key, turns saving off, and preserves
the current page; it is also the recovery action for a corrupt or unsupported
value under that key. These actions do not delete files the user has exported.
JSON export uses format `oratrice-conversation`, version 1. Markdown marks
assistant replies with `finish_reason: "length"` as incomplete. Browser
storage is not a backup. JSON contains `title`, `created_at`, `updated_at`, and
ordered `messages` with `role`/`content` and optional assistant `finish_reason`;
internal IDs, revisions, and raw provider payloads are omitted. No import is
implemented. Revisions prevent stale saved-record updates. A change from
another tab pauses this page's automatic saving without replacing its visible
conversation; reopen the saved version or start a new conversation to resume.

Opening a saved conversation that exceeds the request limits above displays
its full history read-only for chat. The user can export it or start a new
conversation; the UI does not trim the archived record to make it fit. Browser
retention does not change the API contract or make Core, Router, or API stateful. Each
`/chat` request still supplies its own history and is subject to the limits
above: at most 12 prior messages, 1536 total budget units (UTF-8 content bytes
across prior and current messages plus 32 framing units per message), and a 256-token reply cap
when history is supplied.

Sending disables duplicate submission and reset. Failures preserve the draft
and do not commit a turn. Empty responses count as failures. Busy, unavailable,
network, timeout, and context-limit states have separate actionable messages;
browser timeout does not cancel model work. Enter sends, Shift+Enter inserts a
newline, and composing Enter is ignored. A different frontend may use the
public JSON contracts directly.

## Errors and ownership

Validation and routing errors map to 422, provider errors to 502, and runtime,
configuration, and health errors to 503.  Unknown failures return a generic
500 envelope.  Error payloads contain stable codes and correlation IDs only;
request bodies, prompt text, stack traces, causes, and credentials are omitted.

An application passed to `create_api(application=...)` is externally owned and
is never closed by the API.  If the API creates the application through its
factory, lifespan shutdown calls `close` (or `shutdown`) exactly once.  Uvicorn
binds/configures the listen address; this module adds no CORS or network
startup behavior.

The Core request handlers are synchronous because the current Core/Provider
ports are synchronous. FastAPI therefore executes them in its worker thread
pool instead of blocking the ASGI event loop during local model or gateway
calls. The liveness/readiness and static UI routes do not invoke those Core
ports for ordinary asset or process checks.

The Uvicorn entry point prefers generated `config/profiles/local.yaml` when
present, otherwise `config/profiles/live.yaml`, matching the Launcher.
Set `ORATRICE_CONFIG` to an absolute or
project-resolvable configuration path for a standalone deployment that needs a
different profile.
