# M2 Oratrice Launcher summary

Status: **PASS (offline orchestration and final EXE dry-run)**.

## Delivered

- Configuration-driven immutable launch plan.
- Ordered startup: GPT-OSS, Gemma Router in CPU mode, then LiteLLM Gateway.
- Explicit optional Qwen-VL startup with `--with-qwen`; it is not part of the
  default path.
- Health-gated startup, external-service reuse, and reverse cleanup of only
  launcher-owned processes.
- Process-local LiteLLM master-key generation with no printing or persistence.
- OpenWebUI is treated as an external UI: the browser opens only when port 3000
  is already healthy.
- CLI options: `--dry-run`, `--with-qwen`, and `--no-browser`.
- Thin Windows `Start-Oratrice.exe` entry point with Job Object process-tree
  cleanup.

## Validation

- M2-01 launch-plan tests: 4 passed.
- M2-02 launch-plan/orchestrator tests: 10 passed.
- M2-03 CLI tests: 4 passed.
- Final compiled EXE dry-run: PASS, exit code 0.

The final validation did not start model processes or OpenWebUI. M1 had already
validated the real GPT-OSS/Gemma/LiteLLM chain, so M2 avoided another expensive
model-load cycle. Qwen-VL gateway visual validation remains deferred by design.

## Boundaries retained

- No Core HTTP API was added or started; that remains a later milestone.
- No Agent, Memory, Tool, voice, or OpenPets behavior was added.
- No OpenWebUI installation or process ownership was introduced.
- A failing validation path is limited to three attempts; environment misses
  and all effective test outcomes are recorded in the per-task reports.
