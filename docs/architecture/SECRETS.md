# Secret handling

Credentials are process-environment inputs, not repository configuration.
`config/secrets.example.env` documents the variable names without values; copy
the names into a local environment or secret manager and populate them there.
Do not commit a filled-in copy.

## Configuration syntax

Oratrice's `ConfigurationLoader` expands `${ENV_VAR}` references and fails
closed when a referenced variable is missing.  A provider entry that needs a
credential therefore uses the following form:

```yaml
api_key: ${SERVICE_API_KEY}
```

The LiteLLM configuration has a different, provider-supported syntax.  Its
gateway key is read from the environment with `os.environ/NAME`:

```yaml
general_settings:
  master_key: os.environ/ORATRICE_LITELLM_MASTER_KEY
```

`ORATRICE_LITELLM_MASTER_KEY` is required by the local `start.bat` launcher;
the launcher checks only whether it is set and never echoes its value.

`DEEPSEEK_API_KEY` is optional and is referenced only by the opt-in
`deepseek_reasoner` LiteLLM model entry (`os.environ/DEEPSEEK_API_KEY`).  The
Oratrice route still talks only to the local LiteLLM gateway and marks the
cloud provider with `policy.cloud_opt_in`; the default Gemma allow-list remains
local-only.  A caller must explicitly extend that allow-list and set the key
before selecting the cloud route.  The guarded live harness likewise requires
`--allow-cloud`; leaving the variable unset keeps local-only workflows offline.

The local `gpt_oss` entry uses `dummy-local-only` as an OpenAI-compatible
protocol marker.  It is intentionally non-secret and must not be reused as a
cloud credential.
