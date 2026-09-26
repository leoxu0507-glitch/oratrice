# M7-05 offline regression

- Date: 2026-08-21 (Asia/Hong_Kong)
- Scope: ordinary offline pytest regression from the canonical checkout
  `D:\AI\projects\Oratrice` after M7-02/M7-04 environment and runtime
  wiring work.
- Result: `DEGRADED`. The M7 runtime-path tests passed. Attempts #2 and #3
  applied only the three authorized BOM/line-wrap gate fixes; the final two
  failures are an additional, out-of-scope BOM in `router/__init__.py`.

## Command and environment

All commands were run from the repository root with the required project
interpreter and bytecode/cache settings. Attempt #1 used:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& "D:\AI\projects\Oratrice\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider
```

Attempt #2 used the requested writable-project temp-root override:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& "D:\AI\projects\Oratrice\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider --basetemp "D:\AI\projects\Oratrice\.pytest-tmp-m7"
```

Attempt #3 used the authorized C: workspace temp-root override:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& "D:\AI\projects\Oratrice\.venv\Scripts\python.exe" -B -m pytest -q -p no:cacheprovider --basetemp "<USER_PROFILE>\Documents\Codex\2026-08-03\oratrice-codex-oratrice-local-first-ai-2\work\m7-pytest-tmp"
```

The ordinary suite used `pytest.ini` discovery (`tests`, excluding `live`). It
did not invoke the live harness, a service, a model, a browser, or a network
request.

## Result counts

| Attempt | Collected | Passed | Failed | Errors | Skipped |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 141 | 126 | 3 | 12 | 0 |
| 2 | 141 | 127 | 2 | 12 | 0 |
| 3 | 141 | 139 | 2 | 0 | 0 |

Attempt #1 exited with code `1` after `4.42s`; attempt #2 exited with code
`1` after `2.43s`; attempt #3 exited with code `1` after `2.41s`.

## Failure classification

### Setup/isolation errors (12 in each attempt)

The following tests failed during `tmp_path` fixture setup, before their test
bodies ran:

- `tests/test_bootstrap.py::test_build_application_wires_facade_without_constructing_provider`
- `tests/test_chat.py::test_compatibility_ai_service_keeps_string_chat_and_stream`
- `tests/test_config_loader.py::test_loader_resolves_relative_paths_and_references`
- `tests/test_config_loader.py::test_literal_secret_is_rejected`
- `tests/test_config_loader.py::test_environment_secret_is_expanded`
- `tests/test_config_loader.py::test_unknown_reference_is_rejected`
- `tests/test_config_loader.py::test_legacy_resources_are_accepted`
- `tests/test_m6_doctor.py::test_doctor_reports_structural_alias_failure`
- `tests/test_m6_doctor.py::test_doctor_reports_parse_failure_without_echoing_profile_values`
- `tests/test_registry.py::test_load_constructs_typed_resources_and_keeps_metadata`
- `tests/test_registry.py::test_duplicate_ids_are_rejected_across_categories`
- `tests/test_registry.py::test_lookup_order_and_unknown_values_are_stable`

Attempt #1 could not scan its host temp root
`<USER_PROFILE>\AppData\Local\Temp\pytest-of-USER` because of
`PermissionError: [WinError 5] Access is denied`. Attempt #2 used the requested
project path `D:\AI\projects\Oratrice\.pytest-tmp-m7`, but that directory was
also denied at creation with the same error. This is an environment
setup/isolation condition, not an M7 path assertion; the twelve fixture tests
remain unverified under a writable temp root.

### Attempt #1 assertion/test failures (3)

- `tests/test_import_boundaries.py::test_router_and_entities_are_side_effect_free_boundaries`
- `tests/test_import_boundaries.py::test_only_adapters_and_runtime_lifecycle_import_transports`

  Both failures occurred while parsing `router/policy.py`, which began with a
  UTF-8 BOM (`U+FEFF`) and was rejected by the test's
  `ast.parse(path.read_text(encoding="utf-8"))` path. Attempt #2 removed only
  that BOM; the file body and behavior were unchanged.

- `tests/test_m6_release_contract.py::test_project_agreements_record_real_commands_and_bounded_evidence`

  The test expected the contiguous text `provider-neutral protection zone`,
  while `AGENTS.md` wrapped those words across a newline. Attempt #2 joined
  only that line; no wording or other guidance changed.

### Attempt #2 remaining assertion/test failures (2)

- `tests/test_import_boundaries.py::test_router_and_entities_are_side_effect_free_boundaries`
- `tests/test_import_boundaries.py::test_only_adapters_and_runtime_lifecycle_import_transports`

  After the authorized `policy.py` fix, both failures moved to the separate
  `router/router.py`, which also begins with a UTF-8 BOM (`U+FEFF`). Fixing it
  would modify a third file and is outside the authorized M7-05 scope, so it
  was not changed.

### Attempt #3 final assertion/test failures (2)

- `tests/test_import_boundaries.py::test_router_and_entities_are_side_effect_free_boundaries`
- `tests/test_import_boundaries.py::test_only_adapters_and_runtime_lifecycle_import_transports`

  After the authorized `router.py` fix, both failures moved to the separate
  `router/__init__.py`, which also begins with a UTF-8 BOM (`U+FEFF`). No more
  file edits are permitted for this bounded three-attempt regression, so it
  was not changed.

## Attempt ledger and side effects

| Attempt | Scope | Result | Side effects |
| ---: | --- | --- | --- |
| 1 | Full ordinary offline suite with the exact project interpreter and `-p no:cacheprovider` | `DEGRADED`: 126 passed, 3 failed, 12 setup errors, 0 skipped | No service, model, browser, network request, or live harness; no bytecode/cache-provider output requested; report write only |
| 2 | Same suite with the two minimal gate fixes and `--basetemp D:\AI\projects\Oratrice\.pytest-tmp-m7` | `DEGRADED`: 127 passed, 2 failed, 12 setup errors, 0 skipped | No service, model, browser, network request, or live harness; project temp directory creation was denied; only the authorized two-file edits and this report were written |
| 3 | Same suite with the final authorized `router.py` BOM fix and `--basetemp <USER_PROFILE>\Documents\Codex\2026-08-03\oratrice-codex-oratrice-local-first-ai-2\work\m7-pytest-tmp` | `DEGRADED`: 139 passed, 2 failed, 0 setup errors, 0 skipped | No service, model, browser, network request, or live harness; twelve pytest temp directories were created under the authorized C: basetemp; only the authorized `router.py` edit and this report were written |

Attempt #4 is not run. The final result is informative and exposes no
remaining M7 path failure eligible for another fix-and-retry path. The
separate `router/__init__.py` BOM was not edited during the bounded attempts.

## Post-limit static maintenance

`post-limit static fix, not rerun`: after the three-attempt pytest limit was
exhausted, the already-located UTF-8 BOM was removed from
`router/__init__.py`. The file body and behavior were not changed. No pytest
command was run after this maintenance fix.
