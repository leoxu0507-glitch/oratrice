# OpenAI-compatible HTTP design (M6-07)

**Status:** design-only contract; no OpenAI-compatible endpoint is registered
in M6.

This document describes the smallest honest compatibility surface that can be
added after the provider-neutral Core port is extended. It is not evidence
that Oratrice currently implements an OpenAI-compatible server. The existing
API remains the provider-neutral `POST /chat`, `POST /route`, and health
probes described in [`API.md`](API.md).

## Decision and current boundary

The OpenAI Chat Completions operation is `POST /chat/completions` relative to
an OpenAI API base path; a versioned Oratrice route would therefore be
`POST /v1/chat/completions`. Its request contract carries an ordered
`messages` list, not one prompt string. The corresponding model discovery
operation is `GET /v1/models`. These routes are **not registered in M6**.

The current implementation cannot honestly expose the chat route:

1. `core.ai_service.CoreFacade._request_args` accepts the legacy
   `message` argument (text or structured content). A list is passed to
   `normalize_content` as content parts; role/content message objects are not
   parsed as a conversation history.
2. `CoreFacade._chat_request` calls `ChatRequest(..., message=message, ...)`.
   The `message=` convenience form constructs exactly one
   `ChatMessage(role="user", content=message)`.
3. `providers.base.ChatRequest` already has an immutable `messages` tuple and
   can preserve roles when it is constructed directly, but the facade/API
   path above never supplies that port.

Consequently M6 does not register `/v1/chat/completions`, does not advertise
OpenAI compatibility, and does not silently flatten, concatenate, select one
item from, or discard a caller's history. A future endpoint must reject an
unsupported multi-message shape with a safe, explicit error until the Core
port below is available.

## Contract baseline (future endpoint)

The following is the compatibility target, independent of the current M6
registration status.

### `POST /v1/chat/completions` (non-streaming first)

The request must contain:

| Field | Contract |
| --- | --- |
| `model` | A public model ID from the Oratrice allow-list. No provider URL, filesystem path, or secret is accepted here. |
| `messages` | A non-empty, ordered list of role/content message objects. Order, role, name, and content parts are preserved. |
| generation options | Only explicitly supported options are mapped to the Core request; unsupported options are rejected rather than ignored. |
| `stream` | `false` (or omitted) for the first implementation. `true` belongs to the independent SSE contract below and is **DEFERRED**. |

The non-streaming response is an OpenAI-shaped envelope with these required
fields:

```json
{
  "id": "chatcmpl-<opaque-id>",
  "object": "chat.completion",
  "created": 0,
  "model": "<public-model-id>",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ]
}
```

`created` is a UTC Unix-seconds timestamp and `id` is generated at the API
boundary (it is not a provider request ID or raw provider value). `usage` may
be included only when it is already normalized numeric usage. The envelope
never includes raw transport payloads, provider credentials, exception causes,
request prompts, or image URLs.

### `GET /v1/models`

Model discovery is an allow-list view, not a provider enumeration. The future
response has `object: "list"` and a `data` array of model objects. Each public
object minimally contains a stable `id`, `object: "model"`, `created`, and a
non-secret `owned_by` value. The list is derived from explicitly marked,
enabled public model entries in Oratrice configuration; it must not discover
models by probing providers or expose runtime paths, gateway URLs, disabled
IDs, or credentials. A completion request for an ID outside this allow-list
returns a deterministic model-not-found error without revealing the private
registry.

## Smallest Core multi-message port

Before either versioned route is added, extend the provider-neutral Core port
with a request form equivalent to the existing `ChatRequest(messages=...)`:

- accept `messages` as a required, non-empty sequence for the versioned
  endpoint, mutually exclusive with the legacy single `message` argument;
- coerce each role/content mapping to an immutable `ChatMessage`, preserving
  sequence order, role, optional name/metadata, and text or structured content
  parts;
- pass the complete tuple to the selected provider without converting the
  history to one string;
- give the router only redacted text/capability metadata needed for policy
  selection. Prompt and image source values must not enter logs or error
  messages;
- retain the existing single-user `message` compatibility form for `/chat`
  until callers migrate.

This is a Core contract change, not an HTTP adapter workaround. The router,
provider manager, and concrete adapters must continue to depend on the
provider-neutral request type rather than on FastAPI or OpenAI SDK objects.

## Non-streaming mapping and error boundary

The adapter maps a normalized `ChatResponse` to the envelope above: an opaque
completion ID, the resolved public model ID, one assistant choice, the
normalized finish reason, and optional safe usage. It does not forward
`ChatResponse.raw`, `provider`, transport IDs, or arbitrary metadata. Response
fields are allow-listed in the same way as the existing `/chat` serializer.

Errors use a safe OpenAI-style shape and never echo request data:

```json
{"error": {"message": "invalid request", "type": "invalid_request_error", "code": "..."}}
```

The eventual status mapping is:

| Cause | HTTP result | Boundary rule |
| --- | --- | --- |
| missing/invalid `model` or `messages`, unsupported option | `400` (or the API's documented validation status) | Generic validation text; no body or prompt echo. |
| model not in the public allow-list | `404` | Do not reveal configured private IDs or provider details. |
| routing/validation Core error | documented client-error status | Stable code and correlation ID only. |
| provider transport failure | `502` | No URL, response body, key, or exception cause. |
| runtime/configuration failure | `503` | No process command, path, or secret. |
| unexpected failure | `500` | Generic `internal_error` message. |

Credentials remain process-environment/secret-store inputs. `Authorization`
headers, API keys, image sources, prompts, and raw provider payloads are never
logged or serialized. If a deployment exposes the loopback API beyond the
local machine, an explicit authentication/network boundary is required; an
OpenAI-shaped path must not imply authentication that Oratrice has not
implemented.

## Explicitly deferred capabilities

- **STREAM — DEFERRED.** `stream=true` is a separate Server-Sent Events
  (`text/event-stream`) contract. It must not return a non-streaming JSON
  envelope, and it must not be accepted and ignored. Add SSE event framing,
  cancellation, and `[DONE]` semantics only as a separately tested change.
- **TOOLS — DEFERRED.** `tools`, `tool_choice`, function calls, and tool-role
  orchestration are not mapped by this contract. They must be rejected or
  explicitly marked unsupported; never flatten a tool call into assistant
  text.
- **VISION — DEFERRED.** The provider port can represent structured content
  parts, but versioned endpoint support requires multi-message preservation,
  model capability/allow-list checks, and a privacy-tested image boundary.
  Do not drop image parts or claim vision compatibility in M6.

## Registration gate

The implementation order is intentionally narrow:

1. add and test the Core multi-message port;
2. define and test the explicit public model allow-list;
3. implement and test non-streaming response/error mapping;
4. register `POST /v1/chat/completions` (and, if approved, `GET /v1/models`)
   only after the preceding contracts pass;
5. handle STREAM, TOOLS, and VISION as separate, opt-in contracts.

Until that gate is met, the absence of `/v1/chat/completions` is a deliberate
compatibility boundary, not a missing route to be filled by a best-effort
adapter.
