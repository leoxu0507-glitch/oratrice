# Oratrice HTTP API (M8)

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
browser storage. A different frontend may use the public JSON contracts
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

The Uvicorn entry point defaults to `config/profiles/live.yaml`, matching the
services started by the Launcher. Set `ORATRICE_CONFIG` to an absolute or
project-resolvable configuration path for a standalone deployment that needs a
different profile.
