# M6 release candidate review

**Date:** 2026-08-16  
**Canonical checkout:** `D:\AI\projects\Oratrice`  
**Declared scope:** required local chain (GPT-OSS, Gemma Router, LiteLLM Gateway, and Core API), with M6 offline contracts and the M6-07 compatibility design recorded as supporting evidence.  
**Release disposition:** **BLOCKED**

This is a release-candidate evidence summary, not a claim that the historical
test suite is green.  It separates implemented behavior, offline/static
evidence, and live evidence that is still unavailable.

## Release decision

The candidate is **BLOCKED**, not `PASS` or `DEGRADED`.  M6-06 could not reach
the first required health gate because the configured LiteLLM virtual
environment is not runnable: its `pyvenv.cfg` points to a missing base Python
installation.  The release contract treats a missing required prerequisite as
`BLOCKED`; no required component reached `READY`.

The M6-06 path used all three permitted attempts.  It loaded no model weights,
made no HTTP probes, and left no launcher, Python, llama-server, uvicorn, or
LiteLLM process/listener behind.  Qwen-VL, DeepSeek/cloud, and OpenWebUI were
outside the selected scope and remain deferred.

## M6 milestone ledger

| Milestone | Implemented / documented behavior | Evidence and boundary | Disposition |
| --- | --- | --- | --- |
| M6-01 release contract | `RELEASE-CONTRACT.md` defines required/optional scope, lifecycle states, dispositions, health URLs, and the three-attempt evidence contract. | The release-contract test path reached three setup-blocked attempts. It did not provide a runnable test result. | **BLOCKED (setup)** |
| M6-02 health contract | Core exposes distinct `/live`, `/ready`, and compatibility `/health` semantics with safe health envelopes. | Final offline result: **5 passed across 3 attempts**. The checks were in-process and did not start services or probe sibling processes. | **PASS (offline contract only)** |
| M6-03 offline doctor | Static `doctor` checks profile structure, launcher plan, aliases, configured paths, dependency discoverability, and redacts values; `--probe` remains explicitly non-live. | The pytest path had a setup failure and a later **4 passed / 1 failed** result; static root-cause repair was made afterward, but the path was not rerun because the three-attempt limit was reached. | **DEFERRED / not fully verified** |
| M6-04 portable launcher | The EXE discovers Python from absolute `ORATRICE_PYTHON`, project `.venv`, normalized infrastructure venv, then `PATH`, without hard-coded checkout paths or machine-state mutation. | Pytest setup failed. Separately, `Start-Oratrice.exe --dry-run --no-browser` and static launcher inspection passed; dry-run is planning evidence only and does not prove readiness. | **PASS (static/dry-run only)** |
| M6-05 reproducible environment | `setup_oratrice.ps1` selects Python 3.10+, creates/checks a project `.venv`, installs through that venv with `requirements.txt` and `constraints.txt`, and avoids global state/secrets. | AST/static checks passed twice. Script execution was blocked by execution policy; no `pip` invocation occurred. | **DEFERRED (execution)** |
| M6-06 controlled real chain | The requested required local launch path and health gates were exercised under the bounded three-attempt policy. | All three attempts were **BLOCKED (setup)** by the broken configured LiteLLM venv; no model load, HTTP request, or residual process/listener was observed. | **BLOCKED (setup)** |
| M6-07 OpenAI-compatible design | `OPENAI-COMPAT.md` records a future multi-message Core port, allow-list, non-streaming response/error boundary, and explicit STREAM/TOOLS/VISION deferrals. No `/v1` endpoint is registered in M6. | Static contract review **PASS**. The pytest path was deferred on setup; no compatibility endpoint or live provider path is claimed. | **PASS (static design only)** |

## What is implemented

- The local-first provider-neutral architecture and four-target release scope
  are documented, including the required launcher order and health contracts.
- `/live`, `/ready`, and `/health` have intentionally different liveness and
  readiness semantics, with safe envelopes and no cross-process probing in the
  offline contract.
- The launcher has portable Python discovery and a static offline doctor.
- The project bootstrap has an explicit Python/`.venv` flow and a direct
  dependency constraints baseline.
- OpenAI compatibility is a design-only boundary; the current API remains
  `/chat`, `/route`, and the health probes.

## Verification classification

**Verified by bounded offline/static evidence:** M6-02's final five-test health
result; M6-04 EXE dry-run and static inspection; M6-05 AST checks; and the M6-07
static design contract.  The M6-03 repair is static only because its test path
was not rerun after the attempt limit.

**Not verified:** a runnable M6-01 test environment, executable M6-03 pytest
path after the repair, M6-04 pytest execution, M6-05 script/pip installation,
and any model/gateway/API live readiness.  Historical M1-M5 results remain
historical and are not promoted to current M6 release evidence.

## Sole P0 next step

Rebuild a usable project Python environment at `D:\AI\projects\Oratrice\.venv`
(or another explicitly selected project venv) using an approved Python 3.10+
installation.  Do **not** use the Codex runtime as a product dependency.
After that repair, start one fresh, independently tracked live-path validation
of the required chain and record new bounded evidence; do not convert the
current setup failure into `PASS`.
