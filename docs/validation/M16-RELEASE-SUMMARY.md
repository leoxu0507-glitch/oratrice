# M16 release acceptance ledger

**Overall status: PENDING.** This ledger is the evidence record for the
v0.3.0 candidate. Historical M12 real-use, M14 local streaming, and M15
injected-provider checks remain separate and do not fill M16 results.

Do not mark an item `PASS` from a planned command. Record exact source commit,
runtime identity, observed result, attempt number, and evidence file or URL.
Count setup failures within the shared three-attempt limit for that validation
path. Protect local model paths and all credential values; publish no raw logs
or private profile files.

## Candidate identity

| Field | Recorded value |
| --- | --- |
| Source branch and commit | PENDING |
| Windows version and Python version | PENDING |
| llama.cpp version/build | PENDING |
| Local model identifiers and file hashes | PENDING |
| Generated local profile and Gateway environment check | PENDING |
| GitHub Actions run for this exact commit | PENDING |
| Release manifest and archive hashes | PENDING |
| GitHub release URL | PENDING |

## Acceptance results

| Task | Required evidence | Status and result |
| --- | --- | --- |
| M16.1 Installation | `scripts/setup_oratrice.ps1 -CheckOnly` for Core and Gateway; generated local profile; exact documented launcher reaches `/ready` and `/ui/`. Record missing tools as prerequisites, not as passing installation. | PENDING |
| M16.2 Cold start and chat | Cold start from the release candidate; local provider identity; ordinary chat, contextual follow-up, New conversation, injected or real failure and recovery as the scenario requires. Record each HTTP/UI outcome and response timing. | PENDING |
| M16.2 Browser data | With saving off and on, refresh, reopen, export Markdown and JSON, and verify that no failed or partial answer enters completed history. | PENDING |
| M16.2 Streaming | Complete a streamed response, Stop a separate response, observe busy status while upstream work drains, then confirm the next request can recover. State explicitly whether inference cancellation was observed; do not infer it from stopped delivery. | PENDING |
| M16.2 Status companion | Start the actual Tk companion, observe starting/ready/busy/error/offline and recovery as applicable; activate Open chat and record the actual browser and URL; close the companion while Core remains available. | PENDING |
| M16.2 Shutdown and restart | Close/restart the actual launcher after model use. Record owned process IDs and creation times, required listener state, and whether each owned process exited before any outer cleanup. Keep unrelated processes intact. | PENDING |
| M16.2 Bounded usage | Record session duration, request count, response latency, errors, and resource samples. Follow the operator's direction to observe available physical RAM; do not abort solely on that counter. Classify sustained growth or backlog from measured evidence. Cite M12 as prior soak evidence; do not silently claim M16 repeated it. | PENDING |
| M16.3 Package | Build from the same committed source tree as the CI and acceptance record. Inspect archive layout, required launcher files, manifest, and SHA-256; confirm local configuration, credentials, weights, environments, caches, and logs are excluded. Extract to a clean path and follow the documented installation with user-supplied prerequisites. | PENDING |
| M16.4 Release | CI succeeds on the exact candidate. Verify release notes, source commit, manifest, archive asset, and checksums agree. Preserve the existing v0.1.0 and v0.2.0 tags and assets. | PENDING |

## Attempt and issue record

| Validation path | Attempt | Result (`PASS`, `DEGRADED`, `DEFERRED`, or `BLOCKED`) | Cause or evidence |
| --- | --- | --- | --- |
| PENDING | PENDING | PENDING | PENDING |

## Final disposition

- Blocking defects: PENDING
- Accepted limitations: PENDING
- Deferred or unverified features: PENDING
- Overall M16 disposition: PENDING
- v0.3.0 release URL and publication time: PENDING
