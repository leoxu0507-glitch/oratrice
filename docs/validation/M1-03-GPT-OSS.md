# M1-03 GPT-OSS live validation

Date: 2026-08-03 (Asia/Hong_Kong)  
Result: **PASS**

## Scope and safety

- Local-only GPT-OSS runtime validation. No source or configuration files were modified.
- Only the owned GPT-OSS `llama-server.exe` process was started and stopped for this check.

## Controlled runtime

- Owned PID: `24440` (`llama-server.exe`).
- Model identified by `GET /v1/models`: `D:\AI\models\GPT-OSS\openai_gpt-oss-20b-MXFP4.gguf`.
- Reported model metadata: `n_params=20914757184`, `n_ctx=4096`.
- Health check: `GET http://127.0.0.1:8080/health` returned `{status:ok}`.

## Direct completion checks

Two direct requests were made against the local OpenAI-compatible endpoint:

1. With `max_tokens=16`, the response produced only `reasoning_content`; `content` was empty and `finish_reason=length`.
2. With `temperature=0`, `max_tokens=64`, and the instruction `Output only ... ORATRICE_OK`, the response returned `content=ORATRICE_OK`, `finish_reason=stop`, and `total_tokens=128`.

The first result is a reasoning-model output-budget lesson: a small `max_tokens` allowance can be consumed by reasoning before any user-visible content is emitted. Use a sufficient completion budget when validating visible output.

## Cleanup

Only owned PID `24440` was stopped. The final process check found no remaining owned process, and port 8080 no longer responded.

Cleanup: **PASS**.
