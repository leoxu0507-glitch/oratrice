# M12 real-use acceptance and v0.2 release

Status: **BLOCKED**. The real restart and sustained-memory criteria are not
accepted; v0.2.0 has not been released.

## Approved scope

- M12.1: cold start, normal chat, contextual follow-up, New conversation,
  failure recovery, shutdown, and restart through the default local path.
- M12.2: 30-60 minutes of real continuous use, recording latency, resource
  changes, crashes/backlog, and the post-exit baseline.
- M12.3: classify remaining defects as release blockers, accepted limitations,
  or future enhancements. Unverified functionality is not marked complete.
- M12.4: English documentation, a new commit/tag/release, exact-commit CI,
  installation verification, source artifact and SHA-256 checksums. Preserve
  the existing v0.1.0 commit, tag, and release.

No new feature scope: persistent history/export, streaming, pet status,
vision, voice, Memory, Tools and Agents remain future work. Optional Qwen-VL
and cloud-provider real chains do not block the default local text path.

## Preparation and interruption recovery

The canonical working tree contains the existing M9-M11 implementation and
has not been discarded. The public repository and existing v0.1.0 release
were inspected. The repository's configured author is Stellamurus; existing
Codex collaborator credits are retained. GitHub authentication was verified
without exposing or persisting credentials.

The first M12 turn was interrupted after source export and before either
installer was invoked. Resume inspection confirmed no candidate virtual
environments, generated configuration, installer process, or model process.
Core and Gateway installation attempt counts therefore remained zero at
resume. The export contained 186 public files and no `.git`, weights, local
credentials, virtual environments, or runtime output.

Resumed preflight: 3611476 KiB free RAM out of 16395004 KiB; NVIDIA RTX 4060
Laptop GPU, 837 MiB used and 7120 MiB free dedicated VRAM. Required service
ports had no listeners. These snapshots do not prove that the models fit;
only actual loading and request evidence can establish the validated path.

The native console acceptance uses a separate owned console and a separate
controller. It checks console membership before Ctrl+C, and verifies a classic
console HWND before sending its close message. Listener closure and exact
process reaping are separate observations. A test controller does not change
the shipping launcher or count as a human double-click observation.

## Gates

Fresh Core installation passed on attempt 2, after a default sandbox-context
PyPI failure; elevated execution reached the official index and installed the
six pinned direct dependencies. Fresh Gateway installation passed on attempt 1
with LiteLLM 1.74.3. Both passed pip/import checks. Strict Doctor returned
6 PASS, 1 expected generated-key WARN, 0 FAIL; dry-run passed. See
[installation evidence](M12-INSTALL.md).

Real-stack attempt 1 reached readiness in 49.10 seconds. Two real requests
returned HTTP 200 and the correct BLUEBIRD marker, including a follow-up that
omitted the marker from its current message (32.370 and 27.904 seconds).
The browser then timed out waiting for Ready, so no soak or normal-console
acceptance was claimed. The finalizer closed the owned test Job Object and
all service listeners closed. An initial survivor count included the exited
launcher process object retained by the controller's Popen handle; the
controller now checks process exit state as well as PID/creation time.

Diagnosis found the Core API launcher target used `/health`, so `/ready`
called the full facade diagnostic after a provider became active. That can
invoke the Gateway's full inference health check, adding model work and
exceeding status-probe deadlines. An in-process regression reproduced the
unwanted provider health call in both local and legacy profiles (2 expected
failures). The minimal fix changes the Core target to `/live`, while readiness
still checks the model and Gateway endpoints. The focused fix gate passed
12 tests on attempt 2. Model/context/GPU settings and the public `/health`
endpoint behavior were not changed.

Real-stack attempt 2 exited with code 2 before loading models: the owner had
introduced incorrect indentation while manually updating the generated
acceptance YAML. This was a test-setup error, not a source-template failure.
The invalid file and original Gateway config were preserved, then the normal
generator recreated both files from the corrected template. Configuration
validation confirmed the only semantic changes from attempt 1 were the two
intended Core health URLs; model/context/GPU settings were unchanged. Doctor
invocation 3 (the final allowed invocation) returned 6 PASS, 1 expected WARN,
0 FAIL. Dry-run invocation 2 passed.

Real-stack attempt 3 was the final allowed whole-chain invocation. It reached
readiness in 54.39 seconds and again passed both real BLUEBIRD requests
(29.951 and 35.766 seconds). Real Edge UI acceptance then passed six UI chat
requests plus one separate model-slot holder: normal response, contextual
follow-up, New conversation, actual HTTP 503 busy rejection with retained
draft, successful retry, and refresh reset. Successful browser replies took
18.680-29.105 seconds; busy rejection returned in 0.106 seconds. The screenshot
was visually inspected; no runtime JavaScript exceptions were observed.
The sustained-use run lasted 1801.5 seconds and completed 15 conversation pairs
(30 requests), all HTTP 200. Across the first and last sustained-use samples,
the tracked process private commit increased from 13805.7 MiB to 14402.4 MiB
(+596.7 MiB). Both llama-server processes contributed approximately 200 MiB
each within the first 10 measured pairs, with continued subsequent growth.
Available RAM varied from 388 to 870 MiB in later samples and GPU use remained
around 7.3-7.8 GiB. A cache-versus-leak cause is not established. Because the
memory trend did not clearly stabilize, the no-obvious-growth criterion is
not accepted. The serial workload did not accumulate concurrent requests.

Ctrl+C returned from the console controller successfully. All recorded owned
processes and required listeners disappeared. The native supervisor exit code
was 3221225786 (Windows Ctrl+C); this does not prove that Python's graceful
cleanup completed before the Job Object reaped descendants. After Ctrl+C,
available RAM was 9329.5 MiB and GPU use was 509 MiB.

The required restart did not reach readiness: the launcher exited 1. Periodic
process snapshots showed only one llama-server alongside the launcher and its
Python processes; the second model, Gateway, and API were not observed during
the restart. The failing process's console output was not captured, so the
underlying failure cannot yet be classified as a timeout, model crash, or
resource error. The finalizer reported zero recorded owned-process survivors,
all required ports free, 9626.2 MiB available RAM, and 503 MiB GPU use.
Classic-console window-close acceptance was not reached. No fourth real-stack
attempt was performed.

The remaining blockers are: (1) reproduce and diagnose the restart failure
with actionable launcher/model diagnostics in a separately authorized future
validation; (2) establish whether the observed per-model private-memory
growth reaches a bounded plateau; and (3) complete window-close/restart
acceptance. Optional vision, cloud, persistence, and streaming remain deferred
and do not block the default local text path.

Installation and the cold-start/real-chat/browser/Ctrl+C portions passed in
their stated scope. Restart and the sustained-memory criterion remain blocked;
therefore no stable v0.2 tag or release is created from these results. Final
offline regression and candidate CI are independent checks, not substitutes
for the blocked real-use criteria.

The final Python offline suite initially reported 210 passed and 3 failed:
the failures were stale expectations for the changed Core liveness endpoint,
including a fake that incorrectly treated the UI as already healthy before the
Core process started. After correcting the expectations and release contract,
the second full run passed **213 tests in 2.97 seconds**. The JavaScript gate
passed **11 tests** on its third and final invocation across M11-M12.


## Repair follow-up (2026-11-02)

Disposition: **BLOCKED for release; local code and surrogate checks PASS**.
The operator requested repairs, then explicitly deferred real-model acceptance
while another application occupied most of the host's RAM and GPU memory.
No additional real-model launch, restart, or sustained-use run was performed.
The original three whole-chain attempts and their results above remain intact.

### Findings and changes

- The installed llama.cpp is b9843 (`86b94708f`). Its actual `--help` reports
  an 8192 MiB default RAM-backed prompt cache per server, with `0` disabling
  it. The original profiles did not override that budget. This is a confirmed
  configuration risk, not proof that every observed byte of growth came from
  that cache. See the [versioned upstream argument implementation](https://github.com/ggml-org/llama.cpp/blob/86b94708f/common/arg.cpp).
- Generated profiles now pass `--cache-ram 0` to both required model runtimes.
  The legacy live profile's runtime and service argument lists match this
  default. `--prompt-cache-mib N` allows an explicit finite per-model budget;
  negative, boolean, and non-integer Python values are rejected before writing
  outputs. Existing operator profiles are not overwritten or migrated silently.
  This budget does not bound model-weight, GPU, or all process allocations.
- Per-process analysis of the original soak isolates the growth to the two
  llama-server processes: +286.0 and +309.1 MiB of private commit. The other
  processes were approximately flat. Total working set fell by 1171.1 MiB.
  The measurements establish private-commit growth, not a proven memory leak.
- The launcher previously discarded the typed failure status and exit code.
  It now snapshots only the trusted runtime state and integer return code,
  including zero, before cleanup. The CLI shows this metadata along with the
  failing target and exception type. It does not echo exception text, process
  arguments, or environment values.
- The ignored real-acceptance controller now records a separate
  `<phase>.launcher.log` from stdout/stderr for each cold start and restart.
  Its previous version is preserved locally. This corrects the missing-output
  instrumentation; it does not diagnose the historical model restart failure.
  No verbose token/payload logging was enabled.

### Bounded validation after these changes

All commands below ran from the canonical checkout with its Python 3.13.5
`.venv\Scripts\python.exe`. They used no real models or cloud inference.

| Path | Attempts | Result and scope |
| --- | --- | --- |
| New native console surrogate check: `python -B work/m12-fixes/console_check.py` | 1 | PASS. Actual shipping EXE, hidden classic console, WM_CLOSE, restart, then Ctrl+C. Each cycle reaped the recorded owned process tree and freed its surrogate port before the outer finalizer. An external sibling survived both cycles; the controller then cleaned it separately. Final owned survivors: zero. |
| Native failed-start diagnostic: `python -B work/m12-fixes/failure_check.py` | 1 | PASS. A tiny runtime exited 23; launcher exited 1 and redirected output identified target, `RuntimeStartError`, `runtime_state=failed`, and `returncode=23`. |
| Diagnostic in the acceptance controller's console mode: `python -B work/m12-fixes/failure_console_check.py` | 1 | PASS. The same intentional runtime failure with CREATE_NEW_CONSOLE confirmed that redirected diagnostics remain available in the previously unlogged mode. This changes the console/handle condition and is not an unchanged retry. |
| Focused Python gate | 1 | 27 passed in 3.52 seconds. |
| Full Python offline regression after code changes | 1 | 220 passed in 9.15 seconds. |

The native close/interrupt exit code was 3221225786 (Windows control-event
termination). These observations prove reaping within the surrogate scope,
not that Python graceful cleanup finished or that real-model window close is
accepted. The Job Object safety mechanism was exercised without modifying
the native launcher source or binary.

Focused command:

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=work\m12-fixes\tmp\focused-01 tests\test_m10_local_config.py tests\test_m9_launcher_failures.py tests\test_launcher_cli.py tests\test_launcher_orchestrator.py tests\test_m12_readiness_probe.py
```

Full regression command:

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp=work\m12-fixes\tmp\full-01
```

The Web UI code and JavaScript tests were unchanged; the historical 11-pass
JavaScript result was not rerun. Baseline candidate commit `416a537` has
[successful CI](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41444082603).
At the time of this repair run, the changes were uncommitted and had not been
checked by CI. Subsequent source publication and exact-checkout CI results are
tracked in [PR #1](https://github.com/leoxu0507-glitch/oratrice/pull/1).
No v0.2 tag, archive, checksum set, or release is created from this follow-up.

### Remaining acceptance

The real-model restart cause is still unknown. A subsequent explicitly
scheduled hardware check must use captured launcher/model diagnostics,
verify the generated profile actually contains the new cache budget, and
measure whether private commit plateaus under a fixed bounded workload.
Real-model window close/restart must also be observed. Keep the original
attempt ledger; do not reuse the old unlogged run as successful evidence.
The operator's deferral applies to these checks, so they remain unaccepted.


## Source and documentation synchronization (2026-11-02)

The maintainer authorized publication of the current source and English
project material through the existing candidate PR. README now separates the
current implementation, recorded checks, and release blockers; the project
overview covers M1-M12; Changelog separates additions, fixes, and validation.
The runtime/configuration repairs and their regression tests are included in
the source update. Stellamurus remains first author and Codex the second AI
engineering collaborator. The v0.1.0 tag and published history are preserved.

The PR checks are the authority for CI on the submitted head. Local repair
results above and historical candidate CI do not substitute for those checks.
No real models were started during this documentation/publication task.
Real-model restart, post-repair memory stability, and real-model window close
remain unaccepted, so source synchronization does not authorize a stable v0.2
release or close the M12 acceptance blockers.

## Resumed real-use acceptance follow-up (2026-11-03)

Status remains **BLOCKED**. The original three whole-chain attempts remain intact, and
the resumed repair pass also consumed all three permitted attempts. No fourth run was
made and no attempt budget was reset. This follow-up uses the logical run labels
acceptance-01, acceptance-02, and acceptance-03; private transcripts, environment
captures, and logs are not reproduced here.

### Candidate and clean installation

The candidate source sequence was 76bf0fd (M12-R1), f06bd04 (IPv4/IPv6 TCP-table probe
repair), and ee1c4c5d503a0e2b37d4c490424e2b7c90a3574c (GPT-OSS automatic GPU-layer
default). The fresh isolated source installation used Python 3.13.5, separate Core and
Gateway virtual environments, and LiteLLM 1.74.3. The documented README setup was
executed; pip checks and dependency imports passed. Existing operator profiles were
preserved.

The native C# launcher rebuild compiled successfully. Live acceptance used the tracked
shipping Start-Oratrice.exe, SHA-256
86FD403AF256B2CE03CC1655074582F4D21EC4408EDC06D55E9903FC248D0FAD. Before acceptance-02,
all candidate tracked files matched the source checkout. The generated local profiles
selected a zero-MiB RAM prompt cache for both models, context size 2048, parallelism 1,
16 threads, and zero Gemma GPU layers. GPT-OSS used 999 GPU layers in acceptance-02 and
the automatic default in acceptance-03. The profile remained local-only; no cloud
credential was configured and no cloud request was made.

The Windows host had 16,011 MiB RAM and an RTX 4060 Laptop GPU with 8 GB VRAM. Node.js
25.6.0 was used for JavaScript checks. The recorded runtime identifiers were b9843 and
86b94708f. Read-only process self-identity and native IPv4/IPv6 GetExtendedTcpTable
checks passed. Additional helper unit tests used fakes only.

### Resumed attempts

- **acceptance-01 — 9.6 seconds, BLOCKED before model launch.** The pre-start baseline
  was blocked because the 0.5-second and 2-second socket probes timed out even though
  the operating-system listener table showed no listeners. No model was launched. The
  probe was then changed to use GetExtendedTcpTable for IPv4 and IPv6. The focused
  fake-only suite passed 52 tests. CI for f06bd04 passed 272 Python and 11 JavaScript
  tests in [run
  41567148316](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41567148316).

- **acceptance-02 — 23.9 seconds, stopped by the predeclared resource guard.** At
  baseline, available RAM was 5370.9 MiB and free GPU memory was 7143 MiB. During model
  loading, available RAM fell to 329.1 MiB, free GPU memory to 191 MiB, and tracked
  private commit reached 11603.3 MiB. The guard stopped the attempt; this was not a
  demonstrated out-of-memory crash or process failure. The launch record showed
  common_fit_params explicitly fixing the GPU-layer value at 999, preventing automatic
  selection. The outer owned-job cleanup left zero owned survivors and the required
  ports free. After cleanup, available RAM was 6665.4 MiB and GPU use was 638 MiB.

- **acceptance-03 — 40.0 seconds, stopped by the predeclared resource guard before Core
  readiness.** This used the automatic GPT-OSS GPU-layer default. Baseline available RAM
  was 6476.5 MiB and free GPU memory was 7323 MiB. The individual server logs show
  GPT-OSS loaded and listening on port 8080 about 18.54 seconds after its own process
  launch, and Gemma on port 8090 about 5.81 seconds after its own launch. Before full
  Core readiness, available RAM was 309.3 MiB, below the predeclared 512-MiB floor; free
  GPU memory was 984 MiB and tracked private commit was 7782.1 MiB. No chat, restart,
  soak, or normal console-close check occurred in this resumed run. An emergency
  controller job finalizer left zero owned survivors; the native listener table showed
  ports 4000, 8000, 8080, and 8090 free. This emergency cleanup is not evidence for
  normal Ctrl+C or WM_CLOSE behavior. After cleanup, available RAM was 10525.2 MiB and
  GPU use was 635 MiB, compared with 634 MiB at baseline.

### Predeclared guard and supporting checks

Before model loading, the resource criteria were fixed at available physical RAM of at
least 512 MiB, available commit of at least 4096 MiB, and steady free GPU memory of at
least 128 MiB. The intended soak was 1800 seconds with 45-second pacing; its final 13
samples had to show tail growth no greater than 64 MiB and range no greater than 256
MiB. Cleanup had to return RAM within 1024 MiB and GPU use within 256 MiB of baseline.
The soak was never reached, and these criteria were not lowered after either guarded
stop.

The final local Python regression passed 276 tests with one Starlette/AnyIO deprecation
warning in 3.72 seconds. The local JavaScript gate passed 11 tests with zero failures,
and the focused configuration-generation gate passed 18 tests. Exact-head CI for
ee1c4c5d503a0e2b37d4c490424e2b7c90a3574c passed 276 Python tests with one deprecation
warning in 7.79 seconds and 11 JavaScript tests with zero failures in [run
41567738093](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41567738093).

### Updated M12 disposition

| Task | Disposition | Evidence |
| --- | --- | --- |
| M12-R1: Reproducible acceptance procedure | **PASS** | Read-only Windows identity and TCP-table checks passed; focused fake-only tests passed. |
| M12-R2: Repair configuration and baseline | **PASS** | Clean isolated Core/Gateway installation and generated local configuration passed; existing operator profiles were preserved. |
| M12-R3: Restart and real console close | **BLOCKED** | The predeclared RAM guard stopped model startup before full Core readiness. Restart and normal console-close acceptance were not completed. |
| M12-R4: Bounded sustained use | **DEFERRED** | No post-repair soak began. |
| M12-R5: Release the accepted source | **BLOCKED** | Offline checks and CI passed, but the required real-use criteria remain unaccepted. |

The current window's resource guard blocked the real default path before it became
ready. The earlier restart cause and whether the observed memory growth reflects cache
behavior or sustained process growth remain unestablished. Qwen-VL and cloud-provider
paths remain optional and deferred. Preserve the original and resumed attempt ledgers;
do not authorize another attempt by changing the harness or resetting the budget.

The candidate remains in draft PR #1. No stable v0.2.0 merge, tag, or release is
authorized by this record; preserve the existing v0.1.0 tag and published history.
Source and checksum preparation do not close the release blockers.

## User-requested resource-window verification (2026-11-03)

Disposition: **BLOCKED**. After the previous recorded window was closed, the
operator explicitly requested real acceptance again. A new read-only preflight
measured about 8307 MiB available RAM, materially higher than the 6476.5 MiB
baseline of acceptance-03. One additional controlled experiment was authorized
for this changed window. The original and repair-pass ledgers remain intact;
this was not another three-run allowance or an unchanged automatic retry.

The installed candidate's tracked bytes matched commit `f6cd3c9`. GPT GPU layers
remained `auto`; both models retained `--cache-ram 0`, context 2048, one slot,
and 16 threads. Gemma remained CPU-only and the profile local-only. The private
controller required at least 8000 MiB available RAM before any process launch;
the existing 512-MiB physical-RAM floor and other runtime/cleanup thresholds
were not lowered. Artifacts are retained privately as
`resource-window-20261103-01`; source, controller, and profile identities were
recorded with the run.

The experiment ran for 40.1 seconds. Actual baseline available RAM was
8425.4 MiB and free GPU memory 7238 MiB. Both model servers loaded and listened
on their configured endpoints. Before full Core readiness was confirmed,
available RAM fell to 255.6 MiB; free GPU memory was 871 MiB, available commit
20541.8 MiB, tracked private commit 7842.3 MiB, and summed tracked working set
10489.5 MiB. The predeclared RAM guard stopped the controller. This establishes
a headroom-floor violation, not a proven OOM crash or the cause of the earlier
restart failure.

No chat request, browser session, restart, soak, or normal console-close check
was reached. The emergency Job finalizer reaped all observed owned processes;
the native listener table then confirmed ports 4000, 8000, 8080, and 8090 free.
After cleanup, available RAM was 10760.1 MiB and GPU use was 753 MiB, compared
with 719 MiB at baseline. No user application was terminated. This cleanup
remains emergency-abort evidence, not normal lifecycle acceptance. No second
experiment was made in this window.

The preflight review also found a private automation limitation: an external
Node timeout could bypass the browser driver's JavaScript cleanup and leave
its owned Edge process outside the launcher's Job. The browser phase was not
started here, so that limitation did not affect this run's cleanup result.
Any future automated browser run must close that ownership gap first; the
public manual browser procedure does not launch that private driver.

The shipped application code was unchanged. The existing 276-Python/11-JavaScript
CI result remains offline evidence, not a pass for this experiment. R3 stays
BLOCKED, R4 stays DEFERRED, and stable v0.2 remains unreleased. Further work
must address concurrent-model RAM headroom before another full acceptance plan.

## Final M12 acceptance under revised resource criterion (2026-11-03)

The preceding resource-window attempt remains **BLOCKED under the criterion active for that attempt**. Before this separate run, the operator explicitly revised the decision rule: low available physical RAM is recorded as an observation and does not abort acceptance. This result does not retroactively change earlier dispositions or remove the recorded private-commit growth.

This real run used source commit `3f9257ff18d48a06a568ed95e740a2d3d7bd6625`; no application or Core source changed for the run. GPT-OSS retained automatic GPU-layer selection and cache-RAM 0, the context remained 2048, and Gemma remained CPU-only. The private browser harness waited for the parent kill-on-close Job gate before starting Edge.

The evidence is limited to the recorded host with 16 GB system RAM and an RTX 4060 Laptop GPU with 8 GB VRAM (build `b9843`), one 30-minute run, sequential requests, and short bounded context. It does not establish multi-day stability, long-context behavior, concurrent-load behavior, or Qwen or cloud-provider acceptance.

### Results

- Cold start reached readiness in 40.7 seconds; restart reached readiness in 37.68 seconds.
- The controller completed 51 chat requests with 51 HTTP 200 responses. Median latency was 15.496 seconds and maximum latency was 20.033 seconds.
- The real browser exercise completed 6 UI chat requests plus 1 held request, with all 9 checks passing and no JavaScript runtime errors. It included the expected busy response (503) and successful retry.
- The soak completed 1800.0 seconds, 24 pairs, and 48 requests. Combined tracked private commit moved from 8384.6 to 8440.7 MiB (+56.1 MiB). Across the final 13 samples, growth and range were each 19.4 MiB, below the 64 MiB growth and 256 MiB range limits.
- Available physical RAM reached a minimum of 77.7 MiB; under the revised criterion this was recorded and did not abort the run. Combined tracked working set moved from 10775.2 to 9063.4 MiB (-1711.8 MiB). No crash or request backlog was observed.
- Available RAM was 8356.2 MiB at baseline and 9776.3 MiB after exit. GPU use was 733 MiB at baseline and 721 MiB after exit; free GPU memory was 7224 MiB and 7236 MiB, respectively.
- After each normal Ctrl+C and after model-loaded WM_CLOSE, before outer guard close, the controller observed zero owned survivors and all four required ports free; the controller helper exited 0. The launcher exited with native status 3221225786, so this evidence does not establish that Python `finally` blocks or graceful hooks completed.

### Updated M12 disposition

| Task | Disposition | Evidence |
| --- | --- | --- |
| M12-R1: Reproducible acceptance procedure | **PASS** | Existing read-only preflight and focused harness checks remain valid. |
| M12-R2: Repair configuration and baseline | **PASS** | The isolated local configuration and unchanged candidate source were used for this run. |
| M12-R3: Restart and real console close | **PASS** | Cold readiness, restart, Ctrl+C, and model-loaded WM_CLOSE were observed; the native exit status limits the cleanup claim as recorded above. |
| M12-R4: Bounded sustained use | **PASS** | The 30-minute sequential soak and final 13-sample plateau criteria passed. |
| M12-R5: Release the accepted source | **Publication gate** | Exact release-commit CI and verified published assets are recorded by the v0.2.0 release and its manifest. |

R1-R4 pass for the default local-text path within the host and workload limits stated above. R5 is completed only by matching release-commit CI, preserved tag history, and verified published assets; the release and its manifest are the authority for publication.
