# M1-08B LiteLLM -> Qwen-VL live validation

Date/time: 2026-08-03 21:11:34 +08:00 (Asia/Hong_Kong)
Result: **FAIL**

## Scope and safety

- Added only the `qwen_vl` local OpenAI-compatible route to LiteLLM `config.yaml`; existing `gpt_oss` and environment-backed `master_key` were preserved.
- No Core/router/profile changes were made. No GPT/Gemma/DeepSeek process or external network endpoint was started.
- Gateway requests used Bearer authorization. The one-time master key and image data URI are not recorded.

## Controlled live checks

- One try/finally harness started Qwen2.5-VL llama-server (main model + mmproj) on `127.0.0.1:8082`, then LiteLLM 1.74.3 on `127.0.0.1:4000`.
- Qwen `/health` did not return HTTP 200 within the readiness window; LiteLLM was not started, so downstream gateway checks were not exercised.
- LiteLLM `/v1/models` and `/v1/chat/completions` were not exercised because Qwen readiness failed.


Checks:
- preflight_8082_free: True
- preflight_4000_free: True
- config_qwen_route: True
- config_gpt_oss_preserved: True
- config_master_env_preserved: True
- qwen_health: False
- cleanup_8082_released: True
- cleanup_4000_released: True
- cleanup_temp_image_deleted: True

## Cleanup and security log

- Finally stopped only the recorded owned Qwen and LiteLLM PIDs, deleted the temporary PNG, and confirmed ports 8082/4000 were released.
- Redacted security log: D:\AI\logs\oratrice-m1\m1-08b-litellm-qwen-20260803T131134056Z.security.log

Result: **FAIL**.
