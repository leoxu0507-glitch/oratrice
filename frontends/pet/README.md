# Oratrice status pet

A small standalone desktop companion built with Python's standard-library Tk
interface. It reads Core status and opens the existing Web chat. Start Core
separately; the companion never starts or stops Core, models, or gateways.

## Run on Windows

From the Oratrice checkout, double-click `Start-Oratrice-Pet.cmd`, or run:

```powershell
& .\.venv\Scripts\python.exe -m frontends.pet
& .\.venv\Scripts\python.exe -m frontends.pet --base-url http://127.0.0.1:8000
```

The one-click entry uses the project `.venv` or an existing Python executable
specified by `ORATRICE_PYTHON`. It prefers `pythonw.exe` to avoid a console
window. Python must include Tk; no additional Python package, Node runtime,
cloud account, or model installation is needed for the companion itself.
The validated host uses Windows, Python 3.13.5, and Tk 8.6.

For a companion-only source bundle, create its Python environment with
`py -3.13 -m venv .venv` or set `ORATRICE_PYTHON` to an existing Tk-enabled
Python. Core must already be installed/configured separately. For diagnostics
use the console command above, including `--help`.

## Controls and states

- **Open chat** opens the validated origin's `/ui/` in your browser. It runs
  only on user activation, never as a result of a status change.
- **Close** and the window close button stop the companion's own polling and
  close its window. Core and any active model request continue independently.
- Starting, Ready, Working, Error, and Offline have both text and color cues.
  Working remains visible after Web Stop while model execution is still active.

The companion requests only `GET /status`. A successful response contains no
prompt, chat transcript, model selection, provider URL, or credential. Normal
polling is approximately every two seconds, with one request in flight and
bounded backoff up to 30 seconds after connection failures. Readiness sampling
inside Core is cached separately, so dependency status changes are not instant.
Operation status bypasses the readiness cache while Core is busy.

## Connection boundary

`--base-url` accepts a loopback HTTP(S) origin: `localhost`, a loopback IPv4
address, or `::1`, with an optional port. It rejects external hosts, embedded
credentials, arbitrary paths, queries, and fragments. `/status` and `/ui/` are
derived from that one origin. Redirects are rejected and environment proxies
are bypassed. Responses are limited to 16 KiB and validated against the
[status contract](../../docs/architecture/API.md).

A stopped display is not confirmation that inference stopped. An unreachable
Core is Offline; a malformed/unsupported status response is Error. A prior
model-operation failure can remain Error until a new operation begins.

## OpenPets compatibility

M15 uses this standalone companion following the operator's choice. The
installed OpenPets 3.2.1 plugin host requires HTTPS and public network hosts,
and rejects local HTTP browser links. Its supported SDK cannot consume
Oratrice's loopback API. OpenPets integration remains deferred until a
supported loopback connection is available. Existing OpenPets files and
settings are unchanged. No host sandbox modification or public relay is
required by this companion.
