# M1-04C Gemma router adapter live validation

Date: 2026-08-03 (Asia/Hong_Kong)  
Result: **PASS**

## Scope and preflight

- Profile was read only: `D:\AI\projects\Oratrice\config\profiles\live.yaml`.
- Configured executable: `D:\AI\runtimes\llama.cpp\llama-server.exe`.
- Configured Gemma model resolved from the profile: `D:\AI\models\Gemma-3n-E4B\gemma-3n-E4B-it-Q5_K_M.gguf`.
- Port 8090 was free before launch. No unknown listener or process was terminated.
- The profile's runtime argument strings were used unchanged except for resolving
  the configured model path to its existing absolute path. This is necessary for
  the configured working directory (`D:\AI\runtimes\llama.cpp`): interpreting
  `../../../../models/...` literally from that directory would target
  `D:\models`, while the profile-resolved model is under `D:\AI\models`.

## Controlled runtime

- Owned PID: `11224` (`llama-server.exe`, Gemma model, `--port 8090`).
- Arguments: `--model <profile-resolved Gemma GGUF> --host 127.0.0.1 --port 8090 -ngl 999 --flash-attn on -t 16`.
- Startup log: `docs/validation/M1-04C-gemma_20260803_203520_163_stderr.log`.
- Health wait used the project `LlamaCppProvider.health()` against
  `http://127.0.0.1:8090/v1`; it returned `ProviderHealth.status=ok`.

## Real adapter call

The call used the project classes directly, with no hand-written HTTP route:

- Client: `LlamaCppProvider(base_url="http://127.0.0.1:8090/v1", provider_id="provider.gemma_router", timeout=120s)`.
- Router: `GemmaRouterProvider` with routing model alias `gemma-router`.
- Allow-lists: models `gpt_oss`, `qwen_vl`; provider `provider.litellm_gateway`.
- Input: one fixed pure-text smoke message from the task (not reproduced here).
- Invocation: `router.route(RouterRequest(...))`.

Observed result:

| Check | Result |
| --- | --- |
| Return type | `RouteDecision` |
| `model` | `gpt_oss` (in allow-list) |
| `provider` | `provider.litellm_gateway` (in allow-list) |
| `requires_vision`, `requires_network`, `requires_tools` | all native `bool` values |
| Decision-only contract | PASS; no separate user answer was returned |

The adapter interface does not expose `max_tokens`, so this request did not send
that field; llama.cpp accepted its default and the call completed successfully.
The provider timeout was explicitly set to 120 seconds.

## Cleanup

The PID command line was re-validated as the owned Gemma `llama-server.exe`
using model identity and `--port 8090` before stopping it. PID `11224` exited,
and a final TCP check found no listener on 8090. Only this PID was stopped.

No source or configuration files were modified. GPT-OSS, Qwen-VL, and LiteLLM
were not started during this validation.
