# M9 lifecycle and request-boundary validation

Date: 2026-11-01 (Asia/Hong_Kong).

## Scope and disposition

Overall M9 disposition: **DEGRADED** (implementation and offline integration
complete; real-model/user-console acceptance pending).

| Work item | Evidence | Status |
| --- | --- | --- |
| M9.1 Lifecycle diagnosis | Current call-path defects identified; historical M8 sole cause not proven | PASS within static scope |
| M9.2 Windows supervision | Real surrogate descendants reaped, restart succeeded, external sibling survived | PASS within surrogate scope |
| M9.3 Startup and failure cleanup | Offline interruption, rollback, retry, and truthful stop regressions | PASS offline |
| M9.4 Request/resource boundary | One admitted chat/route operation per API instance; busy and recovery tests | PASS within documented scope |
| M9.5 User-entry acceptance | Real model chat/restart and normal interactive console still unverified | DEFERRED |

M9 addresses runtime shutdown truthfulness, interrupted startup, failure
rollback, Windows process supervision, and single-worker request admission.
The real model startup/chat/shutdown/restart acceptance remains **DEFERRED**
because the current host has insufficient free physical memory. Do not infer
that this gate passed from offline tests or lightweight process tests.

## Confirmed defects and changes

- `RuntimeManager.stop()` previously reported `STOPPED` and dropped ownership
  even if terminate and kill both failed. It now raises `RuntimeStopError`,
  retains the live process, and allows shutdown to be retried. Bulk shutdown
  proceeds in reverse order and attempts the remaining runtimes after a stop
  failure. Startup readiness cleanup also retains unreaped handles.
- Readiness probes previously swallowed process-control exceptions. Interrupted
  readiness now propagates the interruption after cleaning the owned process.
- Launcher startup previously skipped standalone rollback on `KeyboardInterrupt`.
  Rollback now includes interruption, always restores generated environment
  state, and preserves active ownership when cleanup is incomplete.
- CLI cleanup failures previously disappeared behind a success return. The CLI
  now restores environment state, emits only the cleanup exception type, and
  returns code 2. Target failure output includes its safe exception type.
- `/chat` and `/route` previously allowed concurrent blocking facade calls.
  They now share one non-blocking admission slot per API instance. Overlap
  returns retryable HTTP 503, a safe busy code, and `Retry-After: 1`.

## Resource and timeout boundaries

One Uvicorn worker is required for the default local profile's single-model
admission guarantee. Separate API instances have separate locks. Admission
limits model execution; it does not bound every HTTP/server queue during a
request flood. Health and static UI requests remain independent.

Browser request timeout/disconnection does not cancel upstream computation.
The admission slot is released only when the synchronous facade call returns.
Existing provider transport timeouts remain in place; they are not a newly
verified end-to-end wall-clock deadline or an upstream cancellation protocol.

Host preflight observed 482504 KiB free physical memory out of 16395004 KiB,
and GPU telemetry reported an RTX 4060 Laptop GPU with 995 MiB used and
6962 MiB free. Ports 4000, 8000, 8080, 8082, and 8090 had no listeners.
No user application was stopped to make room for models.

## Validation ledger

- Runtime stop path attempt 1: 7 passed (new stop contracts plus existing
  runtime tests). Attempt 2: 9 passed after adding interrupted-readiness and
  failed-readiness ownership checks. No third focused run was needed.
- Launcher failure path attempt 1: 18 passed. Attempt 2: 18 passed after
  changing CLI cleanup propagation to a safe diagnostic and exit code 2.
- Request admission: 5 focused tests passed; 13 existing API contract/lifecycle
  tests passed. Tests inject facades and do not load models or open listeners.
- Native supervision evidence is recorded separately in [M9-NATIVE.md](M9-NATIVE.md).
  The supervisor was promoted to `Start-Oratrice.exe` by copying the exact
  validated candidate, SHA-256
  `86FD403AF256B2CE03CC1655074582F4D21EC4408EDC06D55E9903FC248D0FAD`.
  Native helper invocations totaled five including two setup/helper failures,
  exceeding the intended shared three-attempt budget. No further native smoke
  was run; this procedural overrun is retained explicitly.
- Consolidated offline suite attempt 1: **163 passed in 3.83s**, using
  `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp
  work/m9-integrated-tmp`. `git diff --check` passed. This is offline evidence;
  it does not replace native-process or real-model acceptance.

## Remaining acceptance

When memory is available, perform one bounded default-profile acceptance:
launch through `Start-Oratrice.exe`, confirm readiness and a text response,
stop the launcher, verify owned process identities have exited, and restart.
Then validate the real user's normal console/window-close interaction. Keep
port closure and process reaping as separate observations. The exhausted M8
handler experiments remain historical evidence and are not rerun unchanged.

M10-M12, optional Qwen vision, cloud inference, and new Agent behavior remain
outside this change. Public release tags are unchanged.
