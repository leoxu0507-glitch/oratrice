# M1-09 DeepSeek optional cloud capability

Status: **PASS (configuration and local gateway); cloud inference SKIPPED/BLOCKED**.

## Scope

- Add DeepSeek Reasoner behind LiteLLM without importing or calling DeepSeek from
  Core.
- Keep the normal `live` profile local-first and make the cloud route explicit.
- Verify that an unset `DEEPSEEK_API_KEY` does not prevent the local LiteLLM
  gateway from starting.
- No cloud request was made; no credential value was read or recorded.

## Configuration

- `D:\AI\infrastructure\litellm\config.yaml` now declares the alias
  `deepseek_reasoner` with the locally verified LiteLLM model identifier
  `deepseek/deepseek-reasoner` (LiteLLM 1.74.3 model table).
- The only DeepSeek credential reference is LiteLLM's provider syntax:
  `api_key: os.environ/DEEPSEEK_API_KEY`.  No literal key is present.
- `D:\AI\projects\Oratrice\config\profiles\live.yaml` adds
  `provider.litellm_cloud` (`type: litellm_gateway`, `kind: cloud`) over the
  local `127.0.0.1:4000/v1` gateway, authenticated with
  `${ORATRICE_LITELLM_MASTER_KEY}`.  The model, `policy.cloud_opt_in`, and
  `route.deepseek_reasoner` all remain behind this gateway; Core has no
  DeepSeek SDK or endpoint dependency.
- The default Gemma allow-list remains `gpt_oss`, `qwen_vl`, and
  `provider.litellm_gateway`.  A declarative `defaults.router.cloud_candidates`
  entry documents the explicit opt-in merge required before selecting the cloud
  route, so ordinary requests cannot be silently sent to DeepSeek.

## Verification

1. Environment preflight: `DEEPSEEK_API_KEY` **absent** (presence only checked;
   value was never printed).
2. Staged configuration on temporary port `127.0.0.1:4010`, with no DeepSeek
   key and no chat request: LiteLLM health **200**, model list contained
   `deepseek_reasoner`, `gpt_oss`, and `qwen_vl`; owned process and port cleanup
   **PASS**.
3. The same no-key check was repeated against the main `config.yaml`: health
   **200**, all three aliases present, no relevant startup error, and owned
   process/port cleanup **PASS**.
4. Offline tests: `tests/test_deepseek_optional.py` **3 passed**; full suite
   **64 passed**.  Tests cover secret-reference boundaries, gateway-only Core
   wiring, cloud policy/route, local-first default routing, and application
   construction without `DEEPSEEK_API_KEY`.

## Cloud status

Actual DeepSeek inference is **SKIPPED/BLOCKED** because
`DEEPSEEK_API_KEY` is not configured.  Supplying a key and explicitly extending
the router allow-list are required for a future, separately authorized live
check (the existing harness also requires `--allow-cloud`).

