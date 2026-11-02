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

### `GET /ui/`

The repository ships a small dependency-free HTML/CSS/ES-module client under
`frontends/web/`. The API serves it at `/ui/` using the same loopback origin as
the JSON endpoints; `/ui/app.js` and `/ui/styles.css` are static assets. The
mount only registers a route and does not start a process, open a socket, or
construct the Core application.

The UI calls `/live` and `/ready` for status and `/chat` for ordinary
conversation. It intentionally does not call `/route` for a normal chat and
contains no model/provider selection, memory, tools, agents, voice, vision,
cloud, or streaming implementation. The UI does not persist messages in
browser storage. M11 keeps successful pairs in page memory only; refresh and
New conversation clear them. Sending disables duplicate submission and reset.
Failures preserve the draft and do not commit a turn. Empty responses count as
failures. Busy, unavailable, network, timeout, and context-limit states have
separate actionable messages; browser timeout does not cancel model work.
Enter sends, Shift+Enter inserts a newline, and composing Enter is ignored.
A different frontend may use the public JSON contracts
directly.

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
