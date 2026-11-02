# M9 native supervisor validation

- Date: 2026-11-01 (Asia/Hong_Kong)
- Scope: the Windows bootstrap's process-tree supervision boundary only.
- Candidate artifact: `work/m9-native/Start-Oratrice.m9.exe`, compiled from
  `launcher/windows/Start-Oratrice.cs`.
- Integration status: the owning task promoted the exact validated candidate
  to `Start-Oratrice.exe` (10240 bytes) and verified the SHA-256 match below.

## Causal diagnosis

The previous bootstrap started the Python launcher with `Process.Start`, then
assigned the already-running child to a kill-on-close Job Object. That ordering
leaves a race window in which the launcher can create descendants before the
assignment. Assignment failure was also reported as a warning while startup
continued, which made the safety boundary optional. In addition, the old
failure path unconditionally waited for console input, which can block a
redirected or automated invocation.

The historical M8 console results do not prove that this race was the sole
cause of every cleanup observation. They do establish that listener closure
and process-tree reaping must be measured separately.

## Candidate design

The candidate uses a native suspended process creation sequence:

1. create and configure a kill-on-close Job Object;
2. call `CreateProcess` with `CREATE_SUSPENDED`;
3. assign the suspended Python launcher to the Job Object;
4. resume its primary thread only after assignment succeeds;
5. wait for the native process handle and close the Job Object in `finally`.

Assignment and resume failures are fail-closed: the suspended child is
terminated and the bootstrap returns an error. The error path does not wait
for a key when stdin or stdout is redirected.

This follows the Windows process and Job Object contracts:

- [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)

## Bounded smoke setup

The smoke helper is
[scripts/m9_lifecycle_smoke.ps1](../../scripts/m9_lifecycle_smoke.ps1).
It creates an isolated YAML profile and invokes the repository's default
`scripts/launch_oratrice.py` through the candidate. The profile contains one
lightweight PowerShell surrogate target. The surrogate starts a second
PowerShell process, records both exact PIDs, and remains alive; no model,
gateway, browser, network request, or real service is started.

The candidate was compiled without replacing the production executable:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\scripts\build_launcher.ps1
```

Candidate SHA-256:

```text
86FD403AF256B2CE03CC1655074582F4D21EC4408EDC06D55E9903FC248D0FAD
```

## Results

Command:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\scripts\m9_lifecycle_smoke.ps1 `
  -LauncherExe .\work\m9-native\Start-Oratrice.m9.exe
```

Observed result:

```text
forced_parent_exit=PASS candidate=35336 parent=9232 child=15716
external_survivor_after_first=PASS pid=11072
restart_after_cleanup=PASS candidate=31768 parent=35088 child=34760
external_survivor_after_second=PASS pid=11072
profile=D:\AI\projects\Oratrice\work\m9-native-smoke\profile.yaml
observed_pids=35336,9232,15716,31768,35088,34760
all_recorded_pids_absent=PASS
```

The first run proved that terminating the candidate closes its Job Object and
reaps both the recorded surrogate parent and grandchild. The second run proved
that the same isolated profile can start and clean up again after the first
tree is gone. The exact PID scan after the run found none of the six
candidate-tree PIDs or of the external sibling PID. The external sibling was
launched by the smoke
harness outside the candidate and remained alive after both candidate cleanups;
it was then stopped by exact PID in the harness finalizer. The candidate was
staged temporarily at the repository root because its root resolution is based
on the executable directory; the staging file was removed after the run.

Operator diagnostics were also checked through redirected streams:

```text
dryrun_exit=0
stdout_bytes=140
stderr_bytes=0
```

The captured stdout contained the normal `Oratrice launcher: PASS` dry-run
plan. An invalid absolute `ORATRICE_PYTHON` check returned exit code `2`
immediately with the diagnostic on stderr; it did not wait for console input.

## Attempt ledger

| Path | Attempt | Result |
| --- | ---: | --- |
| Initial helper preflight | 1 | **BLOCKED/setup:** Windows PowerShell 5.1 rejected the unsupported `utf8NoBOM` encoding name; no process started. |
| Direct root candidate smoke | 1 | **PASS:** forced-parent cleanup and restart cleanup; no external-sibling assertion. |
| Direct root candidate smoke after hidden-window adjustment | 2 | **PASS:** forced-parent cleanup and restart cleanup; no external-sibling assertion. |
| Staged work candidate with external sibling | 1 | **BLOCKED/helper defect:** the generated surrogate lacked its `$shell` assignment; no surrogate tree became ready, and the external sibling was cleaned. |
| Staged work candidate with external sibling | 2 | **PASS:** both cleanups, external survival after each, exact-PID cleanup, and restart. |

Across the helper as a whole there were five invocations: two setup/helper
failures and three completed process validations. This exceeded the intended
three-invocation budget when counted as one native-validation task. Splitting
the ledger into paths does not erase that overrun. The owning task stopped
further execution; future native validation must use one shared attempt budget.
The final evidence above is from the second staged attempt.

## Limits and follow-up

This is real subtree-reaping evidence for the new native candidate, not a port
closure proxy. It is not evidence for a real model or service restart. The
host was resource-constrained during this validation, so real model startup
and restart remain deferred.

The smoke was launched by PowerShell with redirected streams. A normal
user double-click in an attached interactive console, and Ctrl+C behavior in
that console, remain unverified. Do not claim those paths from this report.
The root-level staging executable is transient and was removed. The validated
candidate remains under `work/m9-native`; the production executable is a
byte-for-byte copy of this candidate. No additional process smoke was executed
after promotion; the owner checked artifact identity rather than spending
another invocation on the exhausted path.
