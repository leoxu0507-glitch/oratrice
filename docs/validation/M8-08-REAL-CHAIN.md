# M8-08 controlled Web UI and required-chain validation

- Date: 2026-08-22 (Asia/Hong_Kong)
- Canonical checkout: `D:\AI\projects\Oratrice`
- Scope: bundled `/ui/`, Core `/live`/`/ready`, `/route`, `/chat`, GPT-OSS,
  Gemma Router, and LiteLLM Gateway
- Not selected: Qwen-VL, DeepSeek/cloud, external OpenWebUI, or browser automation
- Required functional-chain result: **PASS**
- V0.1 overall disposition: **DEGRADED**

## Validation boundary

M8 connects only a thin same-origin Web UI to the existing Core API contract.
The UI serves HTML, CSS, and an ES module at `http://127.0.0.1:8000/ui/`.
Status checks use `/live` and `/ready`, while normal messages use `/chat`. The
UI does not call `/route` to answer normal chats and does not implement model
selection, provider transport, memory, tools, agents, voice, vision, cloud, or
streaming.

## Live attempt 1

The required local stack was started with the project `.venv`, M8 live profile,
and launcher. This validation used one real model-chain attempt and did not
start Qwen, DeepSeek, or OpenWebUI.

| Request/check | Result | Evidence |
| --- | ---: | --- |
| `GET /ui/` | 200 | bundled entry page served by Core API |
| `GET /ui/app.js` | 200 | same-origin client asset served |
| `GET /ready` | 200 | four required targets healthy |
| `POST /route` | 200 | `gpt_oss` / `provider.litellm_gateway`; no answer/content field; about 13.7 s |
| `POST /chat` | 200 | public model `gpt_oss`; visible marker `M8_OK` (length 5); no `raw` field; about 24.7 s |

The route and chat requests confirmed the existing chain:

```text
Web UI -> Core API -> Gemma Router -> LiteLLM Gateway -> GPT-OSS -> Core response
```

The console did not contain `RAW RESPONSE`, the user prompt, or the answer
marker. Metadata-level INFO messages remained, so this is evidence of the M8
logging configuration and this smoke run, not a promise that every future
logger integration is silent.

## Cleanup and disposition

In Codex ConPTY, Ctrl+C closed the listeners but did not reap all
launcher-owned processes. The original live attempt therefore required exact
PID termination. The final check then confirmed ports `4000`, `8000`, `8080`,
`8082`, and `8090` were free and GPU usage was `0 used / 7956 free` (the Qwen
port was also checked although Qwen was not selected).

The cleanup investigation reached its three-path limit:

1. Original Codex ConPTY observation: listeners closed, but owned processes
   were not reaped automatically; exact-PID cleanup succeeded.
2. Managed handler harness: **FAIL**; exact-PID cleanup succeeded.
3. Native handler harness: **FAIL**; exact-PID cleanup succeeded.

The two handler variants were unverified and were reverted. The original Job
Object source was restored and the executable was rebuilt at 8704 bytes with
SHA-256
`46E12D87935017AB30CEC3EB7036E00F054D96A5DCADF3F6EDFE1D5F59E29085`;
dry-run passed. No handler change is accepted as automatic cleanup evidence.

Therefore the required functional chain is **PASS**, while the overall M8/V0.1
release remains **DEGRADED** because Codex ConPTY process reaping was not
proven, both bounded handler variants failed, and hardware headroom is very
small. The cleanup path is stopped at the three-attempt limit. The next
milestone should redesign external lifecycle supervision or validate the
original path in a real user console before changing launcher code. This is not
a Qwen or cloud failure.
