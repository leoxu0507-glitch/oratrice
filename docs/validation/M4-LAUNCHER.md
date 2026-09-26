# M4 launcher/API validation

The live profile now starts the Core HTTP API after LiteLLM using the configured
`oratrice_api.main:app` ASGI application. The target binds to `127.0.0.1:8000`,
waits for `/health`, and reuses an already healthy endpoint. The CLI reports
`Oratrice API: READY` and avoids constructing a second in-process Application;
the launcher orchestrator remains responsible for stopping owned processes.

FastAPI, uvicorn, and the HTTP test client are declared in `requirements.txt`.
The API target uses the existing LiteLLM virtual environment's Python
executable as its configured launcher override; no service is started by the
offline tests.

OpenWebUI remains an external, optional UI. The launcher may open its existing
health-checked URL, but does not install or automatically configure OpenWebUI.

## Offline validation

`tests/test_m4_launcher_api.py` validates the profile ordering, API runtime
command, health target, external-service reuse branch, and duplicate
in-process-Application guard without starting model, gateway, API, or browser
processes.

Result: **3 passed in 0.26s** on the final permitted attempt. Two preceding
invocations stopped during Python/test-environment setup and did not start a
service. No fourth run was performed.
