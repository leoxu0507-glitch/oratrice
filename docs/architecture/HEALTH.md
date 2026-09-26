# Core health contract (M6)

The Core API exposes three deliberately different probes.  They all return a
safe `HealthReport`-compatible JSON envelope (`status`, `healthy`,
`components`, `request_id`, `checked_at`, and `details`), but they do not have
the same failure semantics.

## `GET /live`

`/live` is a pure process liveness signal.  It always returns HTTP 200 with
`status: "live"`, `healthy: true`, empty `components`, and
`details.mode: "liveness"`.  It does not call the facade and therefore does
not construct providers, runtimes, make network requests, or load model
weights.  `checked_at` is an explicit UTC ISO-8601 timestamp.

## `GET /ready`

`/ready` evaluates dependency readiness without starting or constructing a
provider/runtime.  By default it asks the existing facade health port for its
configured report (`include_configured=True`); configured lazy resources are
reported as `unknown`, not instantiated.  Integrations may inject a
`readiness_checker` (or the `readiness_provider` alias) into `create_api` to
provide a precomputed report and explicit `required`/`optional` declarations.

The result is classified as follows:

| Condition | HTTP | `status` | `healthy` |
| --- | ---: | --- | ---: |
| Every required component is healthy and optional components are healthy | 200 | `ready` | `true` |
| Required components are healthy, but an optional component is unknown/unhealthy/missing | 200 | `degraded` | `true` |
| Any required component is unknown/unhealthy/missing, or no components are reported | 503 | `not_ready` | `false` |

When no explicit classification is supplied, every reported component is
treated as required.  Component entries may be grouped under `providers` or
`runtimes`; leaf `required: false`/`optional: true` markers and report/checker
`details.required`/`details.optional` declarations are accepted.  A missing
required declaration is a readiness failure; a missing optional declaration
only produces `degraded`.

This endpoint does not probe sibling processes over HTTP and does not change
launcher ordering or launcher health endpoints.  Cross-process probing is a
later integration concern; the contract here is intentionally in-process and
offline-testable.

## `GET /health`

`/health` keeps the existing compatibility behavior: it always returns HTTP
200, calls the facade with `include_configured=False`, and reports dependency
failures in the JSON body.  An idle graph is mapped to the historical
`healthy`/`details.mode: "liveness"` response.  Consumers that need an HTTP
readiness gate should use `/ready` instead.
