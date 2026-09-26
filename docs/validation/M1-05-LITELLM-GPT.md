# M1-05 LiteLLM -> GPT-OSS live validation

Date: 2026-08-03 (UTC)

## Scope and safety

- Local-only validation. No Gemma, Qwen, DeepSeek, cloud endpoint, Core, router, or profile changes were made for this check.
- Preflight confirmed that TCP ports `8080` and `4000` had no listeners. The one-time, non-production `ORATRICE_LITELLM_MASTER_KEY` was injected only into the LiteLLM child process environment and is not recorded here.
- The LiteLLM logs were checked for `Authorization`/`Bearer` markers; none were present.

## Gateway setup

- Interpreter: Python 3.13.5 (`<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe`).
- Isolated environment: `D:\AI\infrastructure\litellm\.venv`.
- LiteLLM: 1.74.3, installed from `D:\AI\infrastructure\litellm\requirements-gateway.txt` (`litellm[proxy]==1.74.3`).
- `D:\AI\infrastructure\litellm\config.yaml` contains one local `gpt_oss` route to `http://127.0.0.1:8080/v1` and resolves the gateway key through `os.environ/ORATRICE_LITELLM_MASTER_KEY`.
- `start.bat` now uses the venv entry point and binds LiteLLM to `127.0.0.1:4000`; the M1-02 missing-key guard remains active (exit code 2 when unset).

## Controlled live result

A single try/finally script started the following owned processes, waited for readiness, exercised the gateway, and stopped only those owned PIDs:

- GPT-OSS `llama-server.exe` PID **27200**, model `D:\AI\models\GPT-OSS\openai_gpt-oss-20b-MXFP4.gguf`, port 8080.
- LiteLLM launcher PID **21408**, venv entry point, port 4000.

Results (elapsed **42,253 ms**):

| Check | Result |
| --- | --- |
| GPT health `GET /health` | HTTP 200 |
| LiteLLM health `GET /health/liveliness` | HTTP 200 |
| LiteLLM `GET /v1/models` | `gpt_oss` present |
| LiteLLM `POST /v1/chat/completions` (`model=gpt_oss`, `temperature=0`, `max_tokens=64`) | non-empty content: `ORATRICE_OK` |

Logs (no credentials or Authorization headers):

- `D:\AI\logs\oratrice-m1\m1-05-gpt-20260803T124155877Z.stdout.log`
- `D:\AI\logs\oratrice-m1\m1-05-gpt-20260803T124155877Z.stderr.log`
- `D:\AI\logs\oratrice-m1\m1-05-litellm-20260803T124155877Z.stdout.log`
- `D:\AI\logs\oratrice-m1\m1-05-litellm-20260803T124155877Z.stderr.log`

## Cleanup

The finally block stopped only PIDs 27200 and 21408 (the LiteLLM child exited with its launcher) and then confirmed no listeners remained on ports 8080 or 4000 and no llama/LiteLLM/Python service process remained.

Status: **PASS**.
