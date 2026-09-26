# M1-08 multimodal validation status

Date: 2026-08-03 (Asia/Hong_Kong)

## Decision

The M1-08 result is frozen: direct Qwen-VL recognition through llama.cpp is
**PASS**. The LiteLLM-to-Qwen-VL vision path was not accepted and is deferred;
it does not block M1.

Qwen-VL remains an optional local vision companion for GPT-OSS. It is not a
required delivery path for this milestone, and no additional gateway retries
were authorized.

## Verified work

- **M1-08A: PASS.** The Qwen2.5-VL llama.cpp runtime loaded the main model and
  mmproj. `/health`, `/v1/models`, and an OpenAI-compatible multimodal request
  passed. A deterministic test image was identified as red. See
  [M1-08A-QWEN-RUNTIME.md](M1-08A-QWEN-RUNTIME.md).
- **Multimodal contract retained.** The Core/provider text-and-image content
  parts and offline contract tests remain in place. Deferral does not roll back
  this abstraction or add Agent behavior.

## Gateway result

- **M1-08B: not accepted.** Qwen readiness did not return HTTP 200 within the
  controlled window, so LiteLLM was not started and neither the gateway model
  list nor vision request was validated. See
  [M1-08B-LITELLM-QWEN.md](M1-08B-LITELLM-QWEN.md).
- **M1-08E diagnosis.** The harness `HttpClient` readiness wrapper raised and
  suppressed an exception, producing a false negative. An independent local
  probe with the same parameters later observed Qwen `/health=200` and
  `/v1/models=200`, confirming that the model and mmproj loaded. This identifies
  a harness problem, not proof of a product-chain failure. Because the gate did
  not pass, LiteLLM liveliness, models, and chat were not called; the result
  cannot be reported as a LiteLLM-to-Qwen-VL pass. See
  [M1-08E-LITELLM-QWEN-DIAGNOSIS.md](M1-08E-LITELLM-QWEN-DIAGNOSIS.md).

## Delivery handling

- Stop further M1-08 gateway-vision retries and mark the path as deferred.
- Do not change Core, Router, Provider, or multimodal contracts to accommodate
  the failed probe.
- Continue M1 validation on the required local path.

This report contains no credential, image data URI, or raw model response.
