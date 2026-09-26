# M1-08A — Qwen-VL runtime direct multimodal validation

- Date/time: 2026-08-03 (Asia/Hong_Kong)
- Scope: one local Qwen2.5-VL llama-server only; no Core/router/provider/config changes, no GPT/Gemma/LiteLLM startup, and no external network access.

## Preflight and startup

- `127.0.0.1:8082` was free before launch; no pre-existing llama-server process was terminated.
- Started hidden `D:\AI\runtimes\llama.cpp\llama-server.exe` (PID `13920`) with the live profile's Qwen arguments, including:
  - main: `D:\AI\models\Qwen2.5-VL-3B\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf`
  - mmproj: `D:\AI\models\Qwen2.5-VL-3B\mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf`
  - host/port: `127.0.0.1:8082`
- Startup stderr markers confirm both model and projector load:
  - `loading model '...Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf'`
  - `loaded multimodal model, '...mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf'`
  - `model loaded`; `listening on http://127.0.0.1:8082`

## Direct endpoint checks

- `GET http://127.0.0.1:8082/health` → HTTP 200, `{"status":"ok"}`.
- `GET http://127.0.0.1:8082/v1/models` → HTTP 200; returned the expected Qwen main-model ID and `owned_by: llamacpp`.
- `POST http://127.0.0.1:8082/v1/chat/completions` → HTTP 200 using OpenAI-compatible standard content parts (`text` + `image_url` with a temporary deterministic 1×1 red PNG), `temperature: 0`, `max_tokens: 32`.
  - Response content: `Red` (non-empty; contains `red`).
  - Usage: prompt 50, completion 2, total 52 tokens; finish reason `stop`.
- The image bytes/data URI were used only in-memory for the request and are not included in this report.

## Cleanup

- Stopped only the recorded PID `13920` after verifying it was the expected llama-server executable.
- Temporary PNG was deleted; no temporary image remains.
- PID no longer exists and `127.0.0.1:8082` has no listening socket.

Result: **PASS** — health, models, multimodal chat, mmproj load, and cleanup all verified.

