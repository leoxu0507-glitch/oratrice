# M2-03 CLI and Windows entry point

Status: **PASS**.

The CLI loads the configured launch plan, keeps its generated gateway key
process-local, supports dry-run and explicit Qwen opt-in, and always stops
owned services on exit. The Windows EXE is a thin Python bootstrap with Job
Object process-tree cleanup and contains no model/provider arguments.

The original M2 plan had three required targets: `gpt_oss`, `gemma_router`, and
`litellm_gateway`. M4 extends the live plan with the required `core_api` target
after LiteLLM; the current dry-run therefore plans all four. When that target
is started or reused, the CLI waits on the API process instead of constructing
a duplicate in-process Core Application.

The delegated worker was stopped after it did not write files. The primary
process completed the bounded task without a third dispatch. Tests and static
EXE validation are limited to three attempts.

Validation:

- CLI tests: `4 passed in 0.26s` on the final effective test run.
- Two preceding invocations did not execute tests because the recorded Python
  environment no longer existed and the LiteLLM environment did not contain
  pytest; they are recorded as environment checks, not repeated code failures.
- `Start-Oratrice.cs` compiled successfully with the Windows .NET Framework C#
  compiler to `D:\AI\projects\Oratrice\Start-Oratrice.exe`.
- Historical M2 `Start-Oratrice.exe --dry-run --no-browser` returned exit code
  0 and planned `gpt_oss`, `gemma_router`, and `litellm_gateway` in that order;
  this was before the M4 API target was added.
- The current M4 profile/plan adds `core_api` as the fourth required target and
  uses `oratrice_api.main:app` on `127.0.0.1:8000` with `/health` readiness.
- No real model process, browser, or external UI was started during this final
  validation.
