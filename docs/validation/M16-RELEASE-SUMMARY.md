# M16 release acceptance ledger

**Local acceptance: PASS.** The documented local setup, integrated real-model
workflows, bounded 30-minute session, restart, and shutdown completed on the
recorded Windows host. This ledger reports observed local evidence; it does not
embed final release metadata. The immutable GitHub `v0.3.0` tag and its release
assets are the authority for exact source, CI, archive manifest, and checksums.

No local model paths, API keys, generated profiles, or raw service logs are
published here.

## Environment and source boundaries

| Item | Recorded value |
| --- | --- |
| Host | Windows 11 build 26200, AMD64 |
| Shell and Python | Windows PowerShell 5.1.26100.9711; Python 3.13.5; Tk 8.6 |
| Gateway and model runtime | LiteLLM 1.74.3; llama.cpp b9843 (`86b94708f`) |
| Local model identifiers | GPT-OSS and Gemma-3n-E4B; paths withheld |
| GPT-OSS model SHA-256 | `75acd89545d50126692df2116bc3fdf700408b4be1d74d58e8eed13bca028f17` |
| Gemma-3n-E4B model SHA-256 | `ef5c72473575ce0b162c0289f5f3ef983ca99fc2f2272efd5871f6bccc3fb49a` |
| Runtime baseline for real03 | `1e91caf1699b278c4c2a9b4bd39a3f8945f740b9` |
| Historical candidate CI | [Run 41636332951](https://github.com/leoxu0507-glitch/oratrice/actions/runs/41636332951), 399 Python and 63 JavaScript tests on `fa69ab6bfeeae49a578f4276e706637ffbbcf53e`; this is not the final-source CI record |
| Cloud credentials | All `*_API_KEY` variables were removed during local acceptance; the launcher generated an ephemeral local Gateway key |

A 75-file operational comparison matched the release-candidate Git blobs apart
from normal Git end-of-line normalization. Core, Router, Provider, runtime, and
frontend implementation files used by the real acceptance remained unchanged
from the runtime baseline. Release-preparation changes were limited to setup,
packaging, tests, and documentation.

## Acceptance results

| Area | Result |
| --- | --- |
| Canonical setup | Fresh Core/Gateway setup, local configuration, strict Doctor, and dry-run passed. Cold readiness was 42.239 seconds. |
| Archive installation | The archive was extracted into a path containing spaces. After the setup wrapper fix, PowerShell 5 setup, dependency checks, imports/version checks, local configuration, strict Doctor, and dry-run passed. Gateway used a fresh environment; Core reused the partial environment created by install attempt 1, so attempt 2 was not a zero-state Core environment install. |
| Real Web workflows | Five Edge 156 UI workflows and five UI chat requests passed: ordinary chat/context, save-refresh-export, stream/status, Stop/busy/overlap, and recovery/New conversation. No browser JavaScript errors occurred. First visible text took 15.573 seconds; completion took 18.261 seconds. |
| Native pet browser action | The sixth workflow pressed Open chat in the Tk pet. The Windows browser opener returned true. The exact new system-browser tab was not inspected; the bundled Web page was tested separately through Edge CDP. |
| Sustained local use | 1800.45 seconds; 30 sequential HTTP 200 requests across 15 question/follow-up pairs; 120 resource samples. Median latency was 11.949 seconds; maximum was 20.637 seconds. One separate restart marker request also passed. |
| Resource trend | Core tracked private memory grew 457.6 MiB overall and 8.4 MiB in the final third; the pet grew 1.8 MiB. This met predeclared 512 / 256 / 32 MiB bounds for this run, not a leak-free uptime claim. Available RAM reached 125.7 MiB and was observed without aborting. GPU use ranged 6952–7650 MiB. |
| Restart and shutdown | Restart readiness was 37.724 seconds. The marker reply passed. Closing the pet removed both pet processes while Core remained ready. Ctrl+C shutdowns reaped owned identities and freed required ports before the outer guard. |
| After-exit observation | Available RAM was 10842.0 MiB and GPU use 670 MiB, compared with 6824.9 MiB and 912 MiB at baseline. These are host observations, not guarantees for other systems. |
| Low-budget response | A manually overridden 64-token request returned HTTP 200 with empty text. The documented 256-token default later returned the expected marker. The cause of the low-budget result is unknown. |

The measured session supports the default local path on this host and workload.
It does not establish compatibility with other GPUs, long-context or concurrent
use, or leak-free continuous operation. Stop ends Web delivery; it is not a
claim that model inference was cancelled.

## Extracted-package smoke

The second installation attempt used a copy of the v0.3.0 source archive under
a directory containing spaces. Core dependency setup had partially completed
in attempt 1 before the PowerShell wrapper surfaced a harmless pip stderr
notice as an error. After correcting native stderr capture, attempt 2 completed
the Core checks and configured a fresh Gateway environment. The reused Core
environment is an explicit limitation of this install evidence.

The default launcher was started without `--no-browser`. `/ready` reported the
local stack ready; `/ui/` and all four JavaScript assets returned HTTP 200. A
Chinese user request received the expected `PACKAGE_OK` marker from the local
model, and the streaming request completed with `STREAM_OK`. Closing the Tk pet
reaped both pet processes while Core remained ready. A subsequent classic
console `WM_CLOSE` reaped all 11 owned launcher identities and freed ports
8000, 8080, 8090, and 4000 before the outer guard.

The setup helper's native-command probe passed these cases: exit 0 with stderr,
preserved exit 7, spaced arguments, and restoration of the caller's
`$ErrorActionPreference`. Seven setup contract tests passed on the second
focused run. The first focused run had six passes and one stale assertion,
which was corrected before the passing run.

## Reproducible package command

Run the packager only after committing the exact release source, passing CI on
that commit, and reviewing the real acceptance provenance JSON. The JSON must
describe observed evidence; do not use a synthetic all-PASS fixture.

```powershell
$sourceCommit = '<full 40-character verified source commit>'
$ciRunUrl = '<GitHub Actions run URL for that exact commit>'
$provenanceJson = '<path to reviewed acceptance provenance JSON>'
$releaseOutput = 'dist\v0.3.0'
& .\.venv\Scripts\python.exe .\scripts\package_release.py `
  --commit $sourceCommit `
  --version v0.3.0 `
  --ci-url $ciRunUrl `
  --acceptance-json $provenanceJson `
  --output-dir $releaseOutput
```

The packager emits the source ZIP, `RELEASE-MANIFEST.json`, and
`SHA256SUMS.txt`. Verify the committed source and artifact from the immutable
GitHub release/tag; do not copy a generated commit or checksum into this
self-referential ledger.

## Issue and attempt record

| Validation path | Attempt | Result | Evidence |
| --- | --- | --- | --- |
| Real model startup / local import | 1 | DEGRADED, setup | Initial attempt stopped before model import due to a local import-path setup error; later bounded startup passed. |
| Real browser / streaming workflow | 2 | PASS | Five UI workflows and five requests in Edge CDP; native Tk browser-open workflow recorded separately. |
| Real local sustained session | 3 | PASS | 1800.45 seconds and 120 resource samples; metrics and bounds are above. |
| Package selection gate | 1 | DEGRADED, assertion | Initial filter rejected the public `SECRETS.md` filename. |
| Package selection gate | 2 | PASS | Corrected filter and focused 27-test gate passed. |
| Archive installation | 1 | DEGRADED, setup | Core dependencies completed, then the PowerShell wrapper treated a pip stderr notice as failure. |
| Archive installation | 2 | PASS with environment-reuse caveat | Setup, configuration, Doctor, dry-run, and smoke passed; Gateway was fresh, Core reused attempt 1's partial environment. |
| Native stderr helper probe | 3 | PASS | Exit/stderr handling, exit-code preservation, spaced arguments, and preference restoration passed. |
| Setup contract tests | 1 | DEGRADED, assertion | Six passed; one stale assertion was corrected. |
| Setup contract tests | 2 | PASS | All seven passed. |

## Release evidence and disposition

**Overall M16 local acceptance: PASS.** No blocking defect was observed in the
measured local chat, streaming, pet, or lifecycle path. The 64-token empty
response and the exact system-browser tab remain recorded limitations.

Final source identity, exact-source CI, package manifest/checksums, and
publication are separate release-integrity evidence. Consult the immutable
[GitHub v0.3.0 release and tag](https://github.com/leoxu0507-glitch/oratrice/releases/tag/v0.3.0)
and its `RELEASE-MANIFEST.json` and `SHA256SUMS.txt`; this local ledger does not
infer those results from the earlier candidate CI.

OpenPets integration, Qwen-VL through LiteLLM, cloud inference, voice, model
Memory, Tools, and Agents remain outside v0.3.0 acceptance.
