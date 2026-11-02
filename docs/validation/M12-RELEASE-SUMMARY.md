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
