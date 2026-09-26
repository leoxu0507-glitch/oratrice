# M7-00 Baseline

Captured 2026-08-21 19:31:08 +08:00 (Asia/Hong_Kong) from the canonical Windows checkout `D:\AI\projects\Oratrice`.

This is a static baseline only. No Oratrice, llama.cpp, LiteLLM, OpenWebUI, model, or network service was started. Secret values are intentionally omitted.

## Confirmed facts

### Repository and instructions

- `D:\AI\projects\Oratrice\AGENTS.md` was read in full. It identifies this path as the canonical checkout and the live profile as `config\profiles\live.yaml`.
- `Get-ChildItem -Force` shows no `.git` directory. `git status --short --branch` therefore returned `fatal: not a git repository (or any of the parent directories): .git`. No Git repository was initialized and no Git mutation was attempted.
- The only `AGENTS.md` found under the checkout is the root file above.

### Ports and related processes

| Port | Baseline state |
| ---: | --- |
| 8080 | not listening |
| 8090 | not listening |
| 4000 | not listening |
| 8000 | not listening |
| 8082 | not listening |
| 3000 | not listening |

The related-process scan found no `python`, `uvicorn`, `llama-server`, `llama`, `litellm`, `ollama`, `OpenWebUI`, `Start-Oratrice`, Docker, or npm process. The only name match was an unrelated `node` process, PID 24400, at `<USER_PROFILE>\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`.

### GPU

Read-only `nvidia-smi` query: NVIDIA GeForce RTX 4060 Laptop GPU; driver 610.74; total VRAM 8188 MiB; used 10 MiB; utilization 0%.

### Models, llama.cpp, LiteLLM, and launcher inventory

| Component | Path | Exists | Bytes |
| --- | --- | :---: | ---: |
| llama server | `D:\AI\runtimes\llama.cpp\llama-server.exe` | yes | 9,216 |
| Gemma model | `D:\AI\models\Gemma-3n-E4B\gemma-3n-E4B-it-Q5_K_M.gguf` | yes | 4,947,998,304 |
| GPT-OSS model | `D:\AI\models\GPT-OSS\openai_gpt-oss-20b-MXFP4.gguf` | yes | 12,109,565,760 |
| Qwen VL model | `D:\AI\models\Qwen2.5-VL-3B\Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf` | yes | 1,929,901,056 |
| Qwen VL projector | `D:\AI\models\Qwen2.5-VL-3B\mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf` | yes | 1,338,428,128 |
| LiteLLM config | `D:\AI\infrastructure\litellm\config.yaml` | yes | 1,064 |
| LiteLLM launcher | `D:\AI\infrastructure\litellm\start.bat` | yes | 974 |
| LiteLLM executable | `D:\AI\infrastructure\litellm\.venv\Scripts\litellm.exe` | yes | 108,407 |
| Oratrice launcher | `D:\AI\projects\Oratrice\Start-Oratrice.exe` | yes | 8,704 |

The launcher source files `launcher\__init__.py`, `cli.py`, `doctor.py`, `orchestrator.py`, `plan.py`, and `windows\Start-Oratrice.cs` all exist. The llama.cpp directory also contains its CUDA/ggml DLLs and companion CLI/server binaries. An additional unreferenced model inventory item is present at `D:\AI\models\Qwen3.5-9B-Uncensored\Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` (5,627,044,224 bytes) with `Start-Qwen3.5-9B-Uncensored.exe` (173,600 bytes).

### Python and virtual environments

- System Python: `<USER_PROFILE>\AppData\Local\Programs\Python\Python313\python.exe` exists; `D:\AI\infrastructure\litellm\.venv\pyvenv.cfg` records Python 3.13.5 and `include-system-site-packages = false`.
- LiteLLM venv is present with `Scripts\python.exe` (254,800 bytes), `Scripts\pip.exe` (108,410 bytes), `Scripts\litellm.exe`, and `Scripts\uvicorn.exe`. Installed metadata includes LiteLLM 1.74.3, FastAPI 0.115.14, Uvicorn 0.29.0, PyYAML 6.0.3, Requests 2.34.2, and OpenAI 2.52.0.
- `D:\AI\projects\Oratrice\.venv` and `D:\AI\projects\Oratrice\work\oratrice-test-venv` are absent. No test or application process was run.

### Configuration key paths and SHA-256

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `config\oratrice.yaml` | 1,157 | `709EFFA6F89B66833F3955E7DFC0A25C94B82D37663A5FC8CA37BDF00FE239EE` |
| `config\resources.yaml` | 1,849 | `8BF9ACC3336A3CFB0BBECB681A4D57DEA8695039D0ECB8FED7D9323FC6DAA667` |
| `config\profiles\live.yaml` | 13,714 | `257D9ED213E1AE1F9331B55659DB4ED81E3DBC2106480735DB1CCD684E501AD5` |
| `config\schema.yaml` | 1,271 | `8CC8C35D60F5B06F823D9F5C38E0D163988F00E4E4773B2170378D6E8ABD0B3F` |
| `config\settings.yaml` | 0 | `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855` |
| `config\secrets.example.env` | 392 | `FF179229389E2E7B3655D9326A75223E9B66624A6D20FF1D07F114AAEAB0BD70` |
| `D:\AI\infrastructure\litellm\config.yaml` | 1,064 | `0525DD463BE7B159C8B1682B6272558EFDCECE4387C799095C199C7467E3A139` |
| `D:\AI\infrastructure\litellm\start.bat` | 974 | `0C698B26BC0C6409CD56BA1D65730A86D2CF66AC8D9B33CE96C5FA61852BFC4E` |

The live profile declares local llama.cpp endpoints on 8090 (Gemma), 8080 (GPT-OSS), and 8082 (Qwen VL), LiteLLM on 4000, Core API on 8000, and an optional UI at 3000. Its executable/model paths resolve to the existing `D:\AI\runtimes`, `D:\AI\models`, and `D:\AI\infrastructure\litellm` targets listed above.

### Plaintext-key indicators

- No populated `.env`, credential-named file, or production-shaped secret value was found in the scanned text configuration/source set. The current process has no values set for `ORATRICE_LITELLM_MASTER_KEY`, `DEEPSEEK_API_KEY`, `ORATRICE_API_KEY`, `OPENAI_API_KEY`, or the other checked provider-key names; only presence and character counts were inspected.
- `config\secrets.example.env` contains empty key assignments. `live.yaml` and LiteLLM config use environment-backed references for gateway/cloud credentials. `D:\AI\infrastructure\litellm\config.yaml` has two explicitly documented non-secret local `api_key` markers; they are not authentication credentials.
- Test fixtures contain marker values used to verify literal-secret rejection. They are not runtime credentials. This scan does not prove the absence of secrets in binary model files or outside the scanned roots.

## Risks and boundaries

1. All target services are offline at baseline; no health, routing, startup-order, model-load, or end-to-end claim can be made from this record.
2. The repository-local `.venv` and historical `work\oratrice-test-venv` are absent. Any validation requiring those environments is deferred until an explicit setup step.
3. The legacy `config\resources.yaml` contains relative model paths such as `../../models/...`; under the loader's source-directory semantics these resolve below `D:\AI\projects\models`, which is absent. The canonical live profile uses four-level paths to `D:\AI\models` and is the declared live source.
4. The extra Qwen3.5 model/launcher is present but not referenced by the live profile; ownership, compatibility, and cleanup were not assessed.
5. The no-secret result is a bounded static scan, not a credential rotation or exhaustive binary/filesystem forensic check.

## Recovery boundary

This task performed read-only inspection and one additive write. No service, model, network request, Git initialization, deletion, or modification of existing project/config/model/runtime files was performed. The only intended mutation is this file: `docs\validation\M7-00-BASELINE.md`. If rollback is required, remove only that file after confirming its path; because the checkout has no `.git`, Git restore is unavailable.

## Attempt ledger

| Attempt | Scope | Setup | Result | Side effects |
| ---: | --- | --- | --- | --- |
| 1 | Static M7-00 baseline: instructions, repository state, ports/PIDs, GPU, inventory, config hashes, Python/venv, key indicators | PowerShell from `D:\AI\projects\Oratrice`; no services/models/network started | `DEGRADED` baseline: inventory and configuration evidence captured; runtime services offline and local test venvs absent | Read-only commands plus this single baseline document write; no secret values emitted |

## Static self-audit

- Scope check: only `docs\validation\M7-00-BASELINE.md` was targeted for writing.
- Secret check: this document contains no credential values.
- Evidence check: port states, related PIDs, GPU fields, file sizes, configuration hashes, venv status, risks, recovery boundary, and the single attempt entry are recorded above.
