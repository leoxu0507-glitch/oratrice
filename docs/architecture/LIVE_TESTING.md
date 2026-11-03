# Live verification (explicit and opt-in)

The regular contract suite remains fully offline; use the repository `.venv`
and the commands in [TESTING.md](TESTING.md). No test under `tests/live/` is
collected by that suite.

The following commands show the separate endpoint harness. `--live` examples
require explicit operator intent, a configured smoke profile or environment,
and an already-running model server or gateway. They are not installation,
startup, or release-acceptance commands:

```powershell
& .\.venv\Scripts\python.exe scripts/live_verify.py --help
& .\.venv\Scripts\python.exe scripts/live_verify.py --dry-run --component runtime-gpt,core-text
& .\.venv\Scripts\python.exe scripts/live_verify.py --fake --component gateway-gpt
& .\.venv\Scripts\python.exe scripts/live_verify.py --live --component runtime-gpt
& .\.venv\Scripts\python.exe scripts/live_verify.py --live --component deepseek-cloud --allow-cloud
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
| `core-text` | OpenAI-compatible chat (legacy check name) | explicitly configured compatible endpoint, not the Core `/chat` API |
| `qwen-vision` | chat with one image fixture | Qwen-VL-compatible endpoint |
| `deepseek-cloud` | OpenAI-compatible chat | DeepSeek cloud (guarded) |

`--component` can be repeated or comma-separated.  With no component it plans
all six; for a real check, selecting a narrow component set is recommended.

Despite its name, `core-text` uses the same OpenAI-compatible request builder
as the gateway checks. It sends `messages` to `/v1/chat/completions`; Oratrice
currently exposes `POST /chat` with `message` and optional `history`, not that
compatibility endpoint. Pointing this check at the Core API does not validate
the real UI/Core path. See [API.md](API.md) for the supported request contract.
A successful HTTP status alone also does not prove a useful model answer.

## Profile and environment

The optional profile is JSON or YAML.  The first existing path is used:

1. `--profile PATH`
2. `ORATRICE_LIVE_PROFILE` or `ORATRICE_LIVE_PROFILE_PATH`
3. `config/live-profile.yaml`, `config/live_profile.yaml`,
   `config/live-profile.yml`, `config/live.yaml`, `config/live.json`, or
   `.oratrice/live-profile.yaml`

This smoke-profile schema is separate from the generated service profile
`config/profiles/local.yaml` and the legacy `config/profiles/live.yaml`.
Neither service profile is auto-discovered or translated by this harness.
Use a dedicated component map or explicit environment values; inspect the
dry-run before authorizing HTTP. Discover the real endpoint and model alias
from your deployed configuration instead of copying the illustrative values
below unchanged.

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

## M12 acceptance handoff

The endpoint harness does not measure startup, browser interaction, process
ownership, restart, or a sustained-use session. M12-R1 adds a public,
parameterized operator procedure and `scripts/m12_acceptance.py` for read-only
evidence collection. It replaces reliance on the ignored, machine-specific
controller; it does not introduce another launcher or automatically exercise
a model. Phase startup logs come from the existing native launcher, and UI
checks are explicitly recorded as operator observations.
See the [follow-up plan](../PROJECT-OVERVIEW.md#next-work-proposed-sequence)
and preserve the [M12 ledger](../validation/M12-RELEASE-SUMMARY.md).

Real-model revalidation remains paused by the operator. When explicitly
resumed, a validation owner must first record the repaired hypothesis and
remaining attempt allowance. Count setup failures and all helper runs toward
the shared cap of three; do not erase the original ledger or reset the limit
by changing a script name.

Prepare the following before loading models:

- Exact source revision, Core/Gateway environments, runtime build, model
  identities, selected profile, and the resolved launch commands. Check the
  RAM prompt-cache setting in existing local profiles; template changes do
  not overwrite operator files automatically.
- Available RAM/VRAM and an agreed hardware window. Do not stop unrelated
  applications or infer available capacity from a previous measurement.
- A private output directory for phase stdout/stderr, request timings, resource
  samples, and exact owned-process identities. Redact evidence before sharing;
  do not commit logs, local paths, credentials, or conversation transcripts.
- Sampling intervals, request count/rate, maximum duration, cleanup scope, and
  hardware-specific memory/headroom criteria. Private commit and working set
  are different measurements; record both and do not infer a leak from a
  single increase or from HTTP success.

Accept the default local path only after cold start, real contextual chat,
reset/failure recovery, owned-process cleanup, restart, and model-loaded
console close pass, together with a bounded 30-60 minute use session. Inspect
startup failure logs before another attempt. Verify process exit by identity
as well as listener closure, preserve external/reused services, and distinguish
automatic cleanup from later manual cleanup. Surrogate process checks remain
useful offline-adjacent evidence, but cannot close real-model acceptance gaps.

The candidate's CI and clean installation checks must match its source
revision before release. Record remaining optional/deferred paths, publish
checksums for release artifacts, and retain existing release tags. None of
these preparations starts a model or publishes a release by itself.

### Prepare one reproducible evidence record (offline)

Use the project `.venv` and an already generated profile. From the checkout
root, after confirming the attempt allowance and source state:

```powershell
$acceptanceRoot = (Get-Location).Path
$acceptancePython = Join-Path $acceptanceRoot '.venv\Scripts\python.exe'
$acceptanceProfile = (Resolve-Path 'config/profiles/local.yaml').Path
$acceptanceRun = Join-Path $acceptanceRoot ('work\m12-acceptance\' + [guid]::NewGuid().ToString('N'))
$acceptanceRevision = git rev-parse HEAD
& $acceptancePython scripts/m12_acceptance.py prepare `
    --profile $acceptanceProfile --output $acceptanceRun `
    --revision $acceptanceRevision --attempt 1 --kind real --soak-minutes 30 `
    --hypothesis 'Validate the repaired cache budget and capture startup diagnostics.'
if ($LASTEXITCODE -ne 0) { throw 'Evidence preparation failed; stop this attempt.' }
```

`prepare` parses the supplied service profile, resolves required target
endpoints, and hashes the profile and collector. It neither imports Windows
DLLs nor opens a socket, starts a process, contacts a provider, or needs a
cloud key. The generated Gateway-key reference can be resolved with an
in-memory placeholder, which is removed afterward. Other referenced variables
must be configured normally; their values are not included in the record.

The source revision is operator-declared, not independently certified. Record
any uncommitted candidate changes separately and use the accepted committed
source for release. The attempt number records the shared allowance; creating
a new directory does not grant more attempts. Use `--kind surrogate` only for
a separately authorized surrogate-process check; that label is retained and
cannot close a real-model acceptance gap.

Every run must use a new directory below the checkout's ignored `work/` tree.
Existing evidence is never overwritten by `prepare`. `evidence.json` contains
the source declaration, hashes, phase observations, exact PID/creation-time
identities, memory samples, operator checkpoints, and cleanup results. Logs
are separate files. All of these are private operator artifacts; inspect and
redact any extract before publication. Use one operator and sequential
commands per record; concurrent writers are unsupported.

### Run the existing launcher (only after hardware acceptance is resumed)

The following commands are **live operations**, not part of the offline
preparation gate. The collector's `observe` and `cleanup` commands require
`--live`; this flag permits read-only OS and TCP observation, not model
startup, inference, signaling, or termination.

```powershell
& $acceptancePython scripts/m12_acceptance.py observe --live `
    --run $acceptanceRun --phase baseline
if ($LASTEXITCODE -ne 0) { throw 'Ports are occupied or unknown; do not launch.' }
```

A listener observation is not a health/readiness check. If a required endpoint
is already listening, identify its owner and defer the cold-start check;
leave that external service intact. For this owned-process acceptance path,
do not reuse pre-existing services.

For the interactive console-close check, deliberately start a visible native
launcher window. Keep stdout and stderr in phase-specific files. The launcher
path and interpreter are resolved from this checkout, not a maintainer's drive:

```powershell
$acceptancePhase = 'cold-start'  # Use 'restart' only after verified cleanup.
$acceptanceStdout = Join-Path $acceptanceRun ($acceptancePhase + '.stdout.log')
$acceptanceStderr = Join-Path $acceptanceRun ($acceptancePhase + '.stderr.log')
if ((Test-Path -LiteralPath $acceptanceStdout) -or (Test-Path -LiteralPath $acceptanceStderr)) {
    throw 'Phase logs already exist; preserve them and stop.'
}
$env:ORATRICE_PYTHON = $acceptancePython
$acceptanceLauncher = Start-Process `
    -FilePath (Join-Path $acceptanceRoot 'Start-Oratrice.exe') `
    -WorkingDirectory $acceptanceRoot -WindowStyle Normal -PassThru `
    -ArgumentList @('--profile', ('"{0}"' -f $acceptanceProfile), '--no-browser') `
    -RedirectStandardOutput $acceptanceStdout -RedirectStandardError $acceptanceStderr
& $acceptancePython scripts/m12_acceptance.py observe --live `
    --run $acceptanceRun --phase $acceptancePhase --launcher-pid $acceptanceLauncher.Id
```

Record a sample immediately after launch, during loading, after readiness,
and before close; descendants that were never observed cannot be certified
by the collector. `cold-start` and `restart` register the root identity;
`soak` and `before-close` require that same root PID and creation time. Any
unreadable descendant identity is retained as an evidence gap and blocks a
cleanup pass. An exited launcher before the first sample is a failed startup;
preserve its phase logs rather than claiming there were no owned children.

Derive the UI URL and Core origin from `evidence.json` (`ui_url`), and poll
`/live` and `/ready` with a bounded startup deadline appropriate to the
profile's target timeouts. `/live` only proves liveness. Require `/ready` to
return HTTP 200 and `healthy: true` before sending chat. Do not poll Core
`/health` as a substitute: active-provider health work is a different check.
Preserve startup duration and failures in a checkpoint note. The collector
itself does not send HTTP or evaluate a model answer.

### Chat, browser, and sustained-use observations

Use the request shape in [API.md](API.md), including UTF-8 JSON, the current
message, prior complete user/assistant pairs, and the supported reply budget.
Check a unique short marker in the first answer and a history-dependent
follow-up, then a fresh conversation that does not carry that history.
Record each request's elapsed time, status, and whether visible content and
context were correct; an empty HTTP-200 answer fails this check.

In the bundled UI check send/receive, follow-up, New conversation, keyboard
submission, duplicate-send protection, draft retention after failure, refresh,
and recovery. Use an already authorized failure scenario; do not terminate
unrelated services to simulate failure. Report browser checks as operator
observations and state which recovery scenario was actually exercised.

```powershell
& $acceptancePython scripts/m12_acceptance.py checkpoint --run $acceptanceRun `
    --phase chat --result PASS --note 'Record actual statuses, latency and context observations here.'
```

Replace example notes with actual observations. A checkpoint is an assertion
by the operator, never an automated test result. Use `FAIL` or `DEFERRED` when
appropriate; do not fill in an unperformed check as `PASS`.

For the planned 30-60 minute session, take `observe --phase soak
--launcher-pid <the recorded launcher PID> --live` samples at a stated regular
interval while performing bounded, sequential short conversations and
follow-ups. The command captures working set, private commit, available RAM,
and available system commit. It does not sample GPU memory, generate traffic,
sleep for the session duration, or decide whether a plateau is acceptable.
Record start/end times, request timings/counts, GPU measurements when available,
and the agreed resource thresholds in the `soak` checkpoint. A short or
incomplete session stays deferred.

### Shutdown, restart, and disposition

1. Capture `observe --phase before-close --launcher-pid <recorded PID> --live`
   before signaling the launcher. Send Ctrl+C in its owned console and allow
   the documented cleanup deadline to elapse.
2. Run the read-only cleanup check below. It verifies every tracked PID plus
   creation time and checks required listeners separately. Access denied,
   identity gaps, survivors, or unknown/occupied ports block the result.
3. After a clean exit, record another free-port baseline. Repeat the launch
   block with `$acceptancePhase = 'restart'`, wait for readiness, and verify a
   real response. Preserve new logs and record `restart-chat` observations.
4. Capture another before-close sample, close that owned console window, then
   check cleanup again. Record `console-close` separately from Ctrl+C.

```powershell
& $acceptancePython scripts/m12_acceptance.py cleanup --live --run $acceptanceRun
```

If manual intervention was needed, append `--manual-intervention` when
recording cleanup. Even when all resources are now gone, that observation
cannot pass automatic cleanup acceptance. The collector never kills a
survivor. Preserve the exact identities and investigate the failure within
the remaining attempt allowance; do not kill processes by name.

Exit codes are `0` for a successful preparation/record/observation (not release
acceptance), `1` for a blocked baseline or cleanup observation, and `2` for an
invalid command or unavailable input. Console output contains only operation,
status, and safe error type/message. The JSON always retains
`release_disposition: DEFERRED`; M12-R2 through R5 still require the actual
hardware review, scenario acceptance, defect classification, and release
checks. Neither an operator `PASS` checkpoint nor a surrogate cleanup result
changes the release disposition automatically.
