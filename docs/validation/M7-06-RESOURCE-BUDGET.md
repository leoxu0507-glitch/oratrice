# M7-06 Resource Budget Preflight

Captured 2026-08-21 (+08:00) from the canonical Windows checkout
`D:\AI\projects\Oratrice`.

This is a read-only resource preflight. It does not load a model, start a
server, open a listener, change `config\profiles\live.yaml`, or stop a
process. The project `AGENTS.md`, the `cpp-local-ai` skill instructions,
`config\profiles\live.yaml`, and `docs\validation\M7-00-BASELINE.md` were
read before recording these results.

## Confirmed host and runtime facts

| Item | Observation |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU; driver 610.74 |
| VRAM snapshot | 8,188 MiB total; 10 MiB used; 7,947 MiB free; 0% utilization |
| System RAM snapshot | 16,788,484,096 bytes total (15.635 GiB); 4,465,303,552 bytes available (4.159 GiB); 73% load |
| Target processes | No related `llama-server`, Python/Uvicorn, LiteLLM, Oratrice, or OpenWebUI process found |
| Target listeners | None on 8080 (GPT), 8090 (Gemma), 8082, 4000, 8000, or 3000 |
| llama-server | `D:\AI\runtimes\llama.cpp\llama-server.exe`, 9,216 bytes |
| llama-server identity | SHA-256 `D6D1FF9F134B48D75094769007C811516A369B386F09873D725F745BD439F4CA`; `--version` exited 0: `9843 (86b94708f)`, Clang 20.1.8, Windows x86_64 |

The RAM total/available values came from the read-only Windows native memory
status API. WMI returned `Access Denied` in this environment; the independent
performance-counter snapshot was also low (4,424,626,176 available bytes),
which is consistent with the native snapshot at a different instant.

## Actual configured model sizes

These are file sizes, not measured load requirements. They must not be used as
a claim that a model fits in VRAM or RAM, or as a performance prediction.

| Profile model | Path | Bytes | GiB |
| --- | --- | ---: | ---: |
| Gemma 3n E4B router | `D:\AI\models\Gemma-3n-E4B\gemma-3n-E4B-it-Q5_K_M.gguf` | 4,947,998,304 | 4.608 |
| GPT-OSS 20B | `D:\AI\models\GPT-OSS\openai_gpt-oss-20b-MXFP4.gguf` | 12,109,565,760 | 11.278 |
| Qwen VL main (not in this budget ladder) | `D:\AI\models\Qwen2.5-VL-3B\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | 1,929,901,056 | 1.797 |
| Qwen VL projector (not in this budget ladder) | `D:\AI\models\Qwen2.5-VL-3B\mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf` | 1,338,428,128 | 1.247 |

## Profile facts relevant to the ladder

`runtime.gpt_oss` currently declares `-ngl 999`, `--flash-attn on`, and
`-t 16`, serving port 8080. `runtime.gemma_router` declares the analogous
`-ngl 999`, `--flash-attn on`, and `-t 16` arguments on port 8090.

The default launcher target for Gemma already has the confirmed override:

```yaml
argument_overrides:
  "-ngl": "0"
```

Therefore Gemma is CPU-first in the default launch plan even though its base
runtime argument list contains `-ngl 999`. This document does not change that
override. The declared GPT `-ngl 999` is only a high-offload startup candidate;
the 11.278-GiB file and 7,947-MiB free VRAM snapshot do not establish that it
will fit.

## Proposed startup and fallback gradient

The following are hypotheses for a later, bounded runtime validation. They are
not executed by M7-06. Keep `--mmap` at its default and do not add `--mlock`
under the observed low available-RAM condition. Hold context, batch, and
parallelism constant while changing GPU layers so a failure has a useful
cause.

### Gemma router (CPU first)

1. **G0, current safe baseline:** retain the launcher `-ngl 0` override. If a
   later test needs explicit conservative limits, use `--ctx-size 2048`,
   `--batch-size 128`, `--ubatch-size 64`, `--parallel 1`, `--flash-attn off`,
   and `-t 16` as trial arguments.
2. **G1, measured partial offload:** only after G0 reaches `/health`, replace
   `-ngl 0` with one small, explicitly recorded `-ngl N` trial. Select `N`
   from that trial's load log and VRAM telemetry; do not assume a layer count
   from the model filename or file size.
3. **G2, measured increase:** raise `N` one step at a time only when the prior
   run is healthy and leaves a documented VRAM margin. On any load/OOM/health
   failure, return to G0 and lower context or batch before another offload
   trial.

### GPT-OSS (declared `-ngl 999`, then step down)

1. **P0, declared candidate:** test the existing `-ngl 999`, `--flash-attn on`,
   and `-t 16` only in a later load-gated run. A successful process start must
   still be checked with load logs, `nvidia-smi`, health, and a representative
   request.
2. **P1, step down GPU layers:** if `-ngl 999` fails, reduce `-ngl` to a
   smaller measured value and repeat the same bounded health/telemetry check.
   Continue monotonically downward (`N1 > N2 > ...`) until the highest
   observed healthy value is known; no fixed `N` is asserted here because the
   GGUF layer metadata and runtime load behavior were not measured.
3. **P2, CPU fallback:** use `-ngl 0` with the conservative
   `--ctx-size 2048`, `--batch-size 128`, `--ubatch-size 64`, `--parallel 1`,
   `--flash-attn off`, and `-t 16` trial settings. This remains a hypothesis:
   the 11.278-GiB file and only 4.159 GiB currently available system RAM do
   not prove that CPU-only loading will succeed.
4. Increase context, batch, parallel slots, or Flash Attention only after a
   stable load and request. Change one high-impact setting per attempt.

Because both models may require host memory even when some layers are on the
GPU, do not assume that GPT and Gemma can simultaneously use their most
aggressive settings. If a GPT fallback leaves insufficient host memory for
Gemma, keep only the priority model resident and defer the other model rather
than starting two unverified CPU-heavy loads.

## Cleanup and ownership rules for later runtime tests

- Before each trial, confirm the target port is free and record the exact
  executable path, command line, and owned PID after process creation.
- On timeout, failed health, load error, or OOM, terminate only the process
  created for that trial (and its owned child process tree), after matching PID,
  executable path, and port. Never kill an unrelated PID based only on a name.
- Verify process exit, port release, and a fresh GPU/RAM snapshot before the
  next gradient step. Do not run the next model while a failed trial still
  owns VRAM or a listener.
- Preserve model files, GGUF caches, `live.yaml`, and unrelated logs. Do not
  use deletion or cache purging as a generic memory fix. Keep failure logs as
  evidence unless a later task explicitly scopes their removal.
- If all GPT tiers fail, leave GPT offline and report the failed tier; do not
  silently switch to an untested model. If Gemma's CPU baseline fails, leave
  it offline rather than undoing the declared override automatically.

## Static self-audit

- Intended write: this file only, `docs\validation\M7-06-RESOURCE-BUDGET.md`.
- No model load, server start, listener, network request, process termination,
  configuration edit, or Git mutation was performed.
- The Gemma `-ngl 0` launcher override and GPT `-ngl 999` declaration are
  recorded as profile facts; this task did not change them. The current
  `live.yaml` SHA-256 is `581A49D1345E41B8196D1F2B691E234E779CE0B740F2682171E70AE2713D7CC1`,
  which differs from the M7-00 baseline hash; that pre-existing/concurrent
  difference is intentionally not reconciled here.
- All startup values above are explicitly labelled as later-test hypotheses,
  not measured performance or fit claims.
