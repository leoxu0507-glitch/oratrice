# M1-08E LiteLLM -> Qwen-VL multimodal diagnosis

Date/time: 2026-08-03 21:46:46 +08:00 (Asia/Hong_Kong)

Result: **FAIL (gateway chain not reached)**

## Scope and safety

- This was a read-only live check of the existing LiteLLM configuration. No Core/product source or LiteLLM configuration was changed.
- The harness attempted to start only Qwen2.5-VL on `127.0.0.1:8082`; LiteLLM was gated on Qwen readiness and therefore was not started in this run.
- The Qwen argv safety summary was: `llama-server.exe --model <absolute Qwen main GGUF> --mmproj <absolute Qwen mmproj GGUF> --host 127.0.0.1 --port 8082 -ngl 999 --flash-attn on -t 16`.
- The temporary gateway key, Authorization value, PNG bytes/data URI, and model response were never written to output or this report.

## Controlled run evidence

- Preflight: ports 8082 and 4000 were free.
- Owned Qwen PID: `25704`; no process exit code was captured because the harness stopped this recorded PID during normal `finally` cleanup (no abnormal exit was observed).
- `qwen_health`: `False` after the 120-second readiness deadline. The harness's local `HttpClient` readiness wrapper raised/suppressed a `RuntimeException` (exception details intentionally redacted); this is a harness-probe failure and does not establish that Qwen failed to start.
- No safe stderr error marker was retained for this run; the security log records only the redacted readiness failure and normal owned-PID cleanup.
- Because the readiness gate failed, this run did not call LiteLLM `/health/liveliness`, `/v1/models`, or `/v1/chat/completions`; no LiteLLM-to-Qwen PASS claim is made.

## Independent runtime diagnostic (same Qwen argv, no gateway)

A bounded Qwen-only probe performed during diagnosis (owned PID `8088`, then stopped) used the same absolute model/mmproj and runtime flags. With `curl` against the local endpoint it observed `/health=200` and `/v1/models=200` in 6 seconds. Safe stderr markers were `loaded multimodal model`, `model loaded`, and `listening on http://127.0.0.1:8082`; no error marker was observed. This indicates the Qwen runtime can become ready and narrows the failure to the first harness's HTTP readiness implementation, not to a model/configuration change.

## Cleanup

- Only PIDs started by the harness/probe were stopped.
- Final port checks: `127.0.0.1:8082` free; `127.0.0.1:4000` free.
- Temporary PNG and process logs were deleted.
- Redacted security log: `<USER_PROFILE>\Documents\Codex\2026-08-03\oratrice-codex-oratrice-local-first-ai-2\.m1_live_stage\security\m1-08e-litellm-qwen-20260803T134646446Z.security.log`

Result: **FAIL (rerun required with the proven direct HTTP readiness method before claiming M1-08E complete).**
