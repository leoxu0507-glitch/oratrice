# Live verification (explicit and opt-in)

The regular contract suite remains fully offline:

```powershell
python -m pytest -q
```

No test under `tests/live/` is collected by that command.  The release
operator invokes the stand-alone harness only when a model server or gateway
is already running:

```powershell
python scripts/live_verify.py --help
python scripts/live_verify.py --dry-run --component runtime-gpt,core-text
python scripts/live_verify.py --fake --component gateway-gpt
python scripts/live_verify.py --live --component runtime-gpt
python scripts/live_verify.py --live --component deepseek-cloud --allow-cloud
```

`--live` is the sole switch that enables HTTP.  The harness never launches a
runtime, downloads a model, or starts a process.  `--dry-run` (the default
when no mode is selected) prints a plan, while `--fake` exercises deterministic
offline responses.  Both modes are safe on a machine with no credentials or
model files.

## Components

The six selectable checks are:

| Component | Request | Typical target |
| --- | --- | --- |
| `runtime-gpt` | `GET /health` | local GPT runtime already listening |
| `runtime-gemma` | `GET /health` | local Gemma runtime already listening |
| `gateway-gpt` | OpenAI-compatible chat | local/remote LiteLLM gateway |
| `core-text` | OpenAI-compatible chat | facade/gateway text path |
| `qwen-vision` | chat with one image fixture | Qwen-VL-compatible endpoint |
| `deepseek-cloud` | OpenAI-compatible chat | DeepSeek cloud (guarded) |

`--component` can be repeated or comma-separated.  With no component it plans
all six; for a real check, selecting a narrow component set is recommended.

## Profile and environment

The optional profile is JSON or YAML.  The first existing path is used:

1. `--profile PATH`
2. `ORATRICE_LIVE_PROFILE` or `ORATRICE_LIVE_PROFILE_PATH`
3. `config/live-profile.yaml`, `config/live_profile.yaml`,
   `config/live-profile.yml`, `config/live.yaml`, `config/live.json`, or
   `.oratrice/live-profile.yaml`

Both a top-level component map and a `components:`/`targets:` map are
accepted.  A compact example (do not commit credentials) is:

```yaml
defaults:
  timeout: 15
components:
  runtime-gpt:
    endpoint: http://127.0.0.1:8080/v1
    model: gpt-oss
  qwen-vision:
    endpoint: http://127.0.0.1:8081/v1
    model: qwen2.5-vl
    image_path: fixtures/vision.png
  deepseek-cloud:
    endpoint: https://api.deepseek.com/v1
    model: deepseek-chat
    api_key_env: DEEPSEEK_API_KEY
```

Recognised fields include `endpoint`/`base_url`/`url`, `model`, `timeout`,
`api_key_env`, `api_key`, and `image_path` (or their snake/camel-case
variants).  Component-specific environment values override the profile:

```text
ORATRICE_LIVE_RUNTIME_GPT_ENDPOINT
ORATRICE_LIVE_RUNTIME_GPT_MODEL
ORATRICE_LIVE_RUNTIME_GPT_TIMEOUT
ORATRICE_LIVE_RUNTIME_GPT_API_KEY
ORATRICE_LIVE_QWEN_VISION_IMAGE_PATH
```

The generic `ORATRICE_LIVE_ENDPOINT`, `..._MODEL`, `..._TIMEOUT`, and
`..._API_KEY` forms are also accepted.  API keys may be supplied through an
`*_ENV` field or `${ENV_NAME}` reference.  Cloud checks additionally require
`--allow-cloud` so a profile cannot accidentally incur a provider charge.

## Output and safety

Results are grouped by `config`, `preflight`, and `component`, followed by a
`SUMMARY PASS=… FAIL=… SKIP=… exit=…` line.  `--json` emits the same redacted
summary for automation.  Exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | all selected checks passed (including dry-run/fake) |
| `1` | an endpoint/provider check failed |
| `2` | profile, preflight, or command configuration failed |

Credentials are used only to build an in-memory Authorization header and are
never rendered.  Response bodies, exception text, query strings, and image
bytes/data URIs are never printed.  Vision fixtures are read only during an
explicit live request and are size-limited; dry-run/fake do not open the
image.  Endpoint output strips query strings and userinfo.
