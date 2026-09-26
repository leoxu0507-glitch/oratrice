# M1-06B Full Live Chain Validation

- Status: **FAIL**
- Timestamp (UTC): 20260803T140448522Z
- Scope: build_application(live.yaml) -> CoreFacade.chat -> real GemmaRouterProvider -> LiteLLMGatewayProvider -> LiteLLM -> GPT-OSS.
- Request: text-only marker assertion; prompt and model answer are intentionally omitted.
- Topology note: GPT-OSS used profile GPU setting -ngl 999; Gemma used -ngl 0 CPU for this acceptance run to avoid VRAM contention. The live profile was not changed.

## Checks
- port_8080_free_before: True
- port_8090_free_before: True
- port_4000_free_before: True
- gpt_health: False
- gemma_health: False
- port_8080_free_after: False
- port_8090_free_after: True
- port_4000_free_after: True

- Core assertion result was unavailable; see redacted harness event summary below.

## Cleanup
- Only PIDs started by this harness were stopped.
- Ports after cleanup: 8080=free False, 8090=free True, 4000=free True.

## Events (secrets and payloads redacted)
- Started GPT-OSS (owned PID 18372; logs redacted paths).
- Started Gemma-router-CPU (owned PID 25140; logs redacted paths).
- GPT /health readiness timed out at 120 seconds.
- Gemma /health readiness timed out at 120 seconds.
- Validation failed at stage runtime-readiness (RuntimeException; details redacted).
- Stopped owned PID 18372.
- Stopped owned PID 25140.
