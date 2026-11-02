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
