# M1-06D Full Live Chain Validation

- Status: **PASS (product chain)**
- Timestamp (UTC): 20260803T142440717Z
- Scope: build_application(live.yaml) -> CoreFacade.chat -> real GemmaRouterProvider -> LiteLLMGatewayProvider -> LiteLLM -> GPT-OSS.
- Request: text-only marker assertion; prompt and model answer are intentionally omitted.
- Topology note: GPT-OSS used profile GPU setting -ngl 999; Gemma used -ngl 0 CPU for this acceptance run to avoid VRAM contention. The live profile was not changed.

## Checks
- port_8080_free_before: True
- port_8090_free_before: True
- port_4000_free_before: True
- gpt_health: True
- gemma_health: True
- gateway_liveliness: True
- gateway_models_http_200: True
- gateway_models_gpt_oss: True
- core_harness_exit_0: False (supervisor observation; non-authoritative)
- core_chain_pass: True
- port_8080_free_after: True
- port_8090_free_after: True
- port_4000_free_after: True

## Core assertion metadata (redacted)
- Router type: GemmaRouterProvider; Gemma router: True; route calls: 1.
- Decision: model=gpt_oss, provider=provider.litellm_gateway, requires_vision=False, requires_network=False, requires_tools=False.
- Response metadata: content_non_empty=True, marker_match=True, provider=provider.litellm_gateway, model_present=True, model_alias_match=False, request_id_present=True, finish_reason=stop.

## Cleanup
- Only PIDs started by this harness were stopped.
- Ports after cleanup: 8080=free True, 8090=free True, 4000=free True.

## Events (secrets and payloads redacted)
- Started GPT-OSS (owned PID 25948; logs redacted paths).
- GPT /health ready (HTTP 200; attempt=130).
- Started Gemma-router-CPU (owned PID 23680; logs redacted paths).
- Gemma /health ready (HTTP 200; attempt=16).
- Started LiteLLM-gateway (owned PID 23892; logs redacted paths).
- LiteLLM /health/liveliness ready (HTTP 200; attempt=5).
- Started Core harness (owned PID 26072; prompt/answer redacted).
- Core harness supervisor exit-code observation was nonzero; JSON assertion status is authoritative (details redacted).
- Stopped owned PID 25948.
- Stopped owned PID 23680.
- Stopped owned PID 23892.
