"""Lifecycle management for executable model runtimes.

The original runtime implementation exposed a thin ``Popen`` wrapper.  This
module keeps process control small and dependency-light, while making the
runtime lifecycle observable and testable.  A process runner and a readiness
probe can be injected by callers (the defaults are ``subprocess.Popen`` and a
standard-library HTTP probe).

No runtime is started merely by importing this module.  The compatibility
``RuntimeLauncher`` in :mod:`core.runtime_launcher` delegates to this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import errno
import inspect
import socket
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen


class RuntimeState(str, Enum):
    """States exposed by :class:`RuntimeManager`.

    ``RUNNING`` means the process is alive but no readiness endpoint was
    configured (or readiness waiting was explicitly disabled).  ``READY`` is
    reached after a configured probe succeeds.  Terminal failure states are
    retained in the status record so a caller can diagnose the last attempt.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    READY = "ready"
    STOPPING = "stopping"
    EXITED = "exited"
    FAILED = "failed"
    TIMEOUT = "timeout"
    PORT_CONFLICT = "port_conflict"

    # Friendly aliases used by a few lifecycle integrations.
    HEALTHY = "ready"
    STARTED = "running"
    DEAD = "exited"


@dataclass
class RuntimeStatus:
    """A snapshot of one runtime's lifecycle.

    The object intentionally compares equal to the legacy status strings, so
    code such as ``status == "stopped"`` continues to work while new callers
    can inspect ``state``, ``error``, ``returncode``, and timestamps.
    """

    runtime_id: str
    state: RuntimeState = RuntimeState.STOPPED
    process: Any = field(default=None, repr=False, compare=False)
    pid: int | None = None
    command: tuple[str, ...] = ()
    endpoint: str | None = None
    port: int | str | None = None
    started_at: float | None = None
    ready_at: float | None = None
    stopped_at: float | None = None
    returncode: int | None = None
    error: str | None = None
    attempts: int = 0
    generation: int = 0

    @property
    def value(self) -> str:
        """Return the string state value (``status.value`` convenience)."""

        return self.state.value

    @property
    def is_running(self) -> bool:
        return self.state in {
            RuntimeState.STARTING,
            RuntimeState.RUNNING,
            RuntimeState.READY,
        }

    @property
    def is_ready(self) -> bool:
        return self.state is RuntimeState.READY

    @property
    def ok(self) -> bool:
        return self.state in {RuntimeState.RUNNING, RuntimeState.READY}

    @property
    def message(self) -> str | None:
        """Alias retained for clients that use ``message`` for diagnostics."""

        return self.error

    def __str__(self) -> str:
        return self.state.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.state.value == other
        if isinstance(other, RuntimeState):
            return self.state is other
        if not isinstance(other, RuntimeStatus):
            return NotImplemented
        # ``process`` is deliberately excluded: it is a live implementation
        # detail and can change while the logical status remains unchanged.
        return (
            self.runtime_id,
            self.state,
            self.pid,
            self.command,
            self.endpoint,
            self.port,
            self.started_at,
            self.ready_at,
            self.stopped_at,
            self.returncode,
            self.error,
            self.attempts,
            self.generation,
        ) == (
            other.runtime_id,
            other.state,
            other.pid,
            other.command,
            other.endpoint,
            other.port,
            other.started_at,
            other.ready_at,
            other.stopped_at,
            other.returncode,
            other.error,
            other.attempts,
            other.generation,
        )

    def __hash__(self) -> int:
        return hash((self.runtime_id, self.state, self.generation))

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable diagnostic view of this status."""

        return {
            "runtime_id": self.runtime_id,
            "state": self.state.value,
            "pid": self.pid,
            "command": list(self.command),
            "endpoint": self.endpoint,
            "port": self.port,
            "started_at": self.started_at,
            "ready_at": self.ready_at,
            "stopped_at": self.stopped_at,
            "returncode": self.returncode,
            "error": self.error,
            "attempts": self.attempts,
            "generation": self.generation,
        }


class RuntimeLifecycleError(RuntimeError):
    """Base error for an unsuccessful lifecycle operation."""

    def __init__(
        self,
        message: str,
        *,
        runtime_id: str | None = None,
        status: RuntimeStatus | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(message)
        self.runtime_id = runtime_id
        self.status = status
        self.cause = cause


class RuntimeConfigurationError(RuntimeLifecycleError, ValueError):
    """Raised when a runtime has no executable or has invalid settings."""


class RuntimeStartError(RuntimeLifecycleError, ValueError):
    """Raised when the process cannot be started or exits during startup."""


class RuntimePortConflictError(RuntimeStartError):
    """Raised when startup reports that the configured port is unavailable."""

    def __init__(
        self,
        message: str,
        *,
        runtime_id: str | None = None,
        port: int | str | None = None,
        status: RuntimeStatus | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(
            message, runtime_id=runtime_id, status=status, cause=cause
        )
        self.port = port


class RuntimeTimeoutError(RuntimeLifecycleError, TimeoutError):
    """Raised when readiness is not observed before the configured deadline."""


# Names used by callers that prefer a shorter/HTTP-oriented spelling.
RuntimeReadinessTimeout = RuntimeTimeoutError
RuntimeStartupError = RuntimeStartError


@dataclass
class _RuntimeRecord:
    runtime_id: str
    runtime: Any
    process: Any
    status: RuntimeStatus
    extra_args: tuple[str, ...] = ()
    health_timeout: float | None = None


def _resource_value(resource: Any, key: str, default: Any = None) -> Any:
    """Read a field from a typed resource, mapping, or simple test double."""

    if resource is None:
        return default
    getter = getattr(resource, "get", None)
    if callable(getter):
        try:
            value = getter(key, default)
        except TypeError:
            try:
                value = getter(key)
            except (AttributeError, KeyError, TypeError):
                value = default
        if value is not None:
            return value
    if isinstance(resource, Mapping):
        return resource.get(key, default)
    return getattr(resource, key, default)


def _runtime_id(runtime_or_id: Any) -> str:
    if isinstance(runtime_or_id, str):
        return runtime_or_id
    value = _resource_value(runtime_or_id, "id")
    if value is None:
        value = _resource_value(runtime_or_id, "runtime_id")
    if value is None:
        raise RuntimeConfigurationError("Runtime is missing an id")
    return str(value)


def _as_float(value: Any, default: float | None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result >= 0 else default


def _as_port(value: Any) -> int | str | None:
    if value is None or value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return str(value)
    return result


class RuntimeManager:
    """Manage executable runtimes with explicit lifecycle state.

    Parameters are intentionally injectable.  ``process_runner`` may be a
    callable compatible with ``subprocess.Popen`` or an object exposing
    ``start``/``Popen``; ``http_probe`` may be a callable receiving ``url`` and
    an optional timeout or an object exposing ``probe``.  The clock and sleep
    functions are injectable as well, which keeps timeout tests deterministic.
    """

    def __init__(
        self,
        process_runner: Any = None,
        http_probe: Any = None,
        *,
        runner: Any = None,
        probe: Any = None,
        process_factory: Any = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], Any] | None = None,
        sleep: Callable[[float], Any] | None = None,
        default_timeout: float = 30.0,
        startup_timeout: float | None = None,
        readiness_timeout: float | None = None,
        probe_interval: float = 0.1,
        stop_timeout: float = 5.0,
        max_probe_attempts: int = 1000,
        **aliases: Any,
    ):
        self.process_runner = (
            process_runner
            if process_runner is not None
            else runner
            if runner is not None
            else process_factory
            if process_factory is not None
            else aliases.pop("popen", None)
        )
        self.http_probe = (
            http_probe
            if http_probe is not None
            else probe
            if probe is not None
            else aliases.pop("health_probe", None)
            or aliases.pop("readiness_probe", None)
        )
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or sleep or time.sleep
        self.default_timeout = _as_float(
            readiness_timeout
            if readiness_timeout is not None
            else startup_timeout
            if startup_timeout is not None
            else default_timeout,
            30.0,
        ) or 30.0
        self.probe_interval = max(0.0, float(probe_interval))
        self.stop_timeout = max(0.0, float(stop_timeout))
        self.max_probe_attempts = max(1, int(max_probe_attempts))

        # ``processes`` is a deliberate compatibility surface.  The complete
        # state is in ``_records``/``status_info``; this mapping only contains
        # currently live process handles.
        self.processes: dict[str, Any] = {}
        self._records: dict[str, _RuntimeRecord] = {}
        self._generation: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    def start(
        self,
        runtime: Any,
        extra_args: Sequence[Any] | None = None,
        *,
        timeout: float | None = None,
        readiness_timeout: float | None = None,
        wait_for_ready: bool | None = None,
        readiness: bool | None = None,
        force: bool = False,
    ) -> Any:
        """Start ``runtime`` and return its process handle.

        A running process is reused unless ``force=True``.  If a readiness
        endpoint is configured, startup waits until the probe succeeds or the
        timeout expires.  On failure the process is terminated and a typed
        exception carrying the final :class:`RuntimeStatus` is raised.
        """

        rid = _runtime_id(runtime)
        self._reap_one(rid)
        existing = self._records.get(rid)
        if existing is not None and self._is_process_alive(existing.process):
            if not force:
                # A prior invocation may have disabled readiness; an explicit
                # readiness request can still wait for the existing process.
                if wait_for_ready or readiness:
                    self._wait_until_ready(
                        existing,
                        timeout=self._resolve_timeout(
                            runtime, timeout, readiness_timeout
                        ),
                    )
                return existing.process
            self.stop(rid)

        executable = _resource_value(runtime, "executable")
        if not executable:
            status = self._new_status(rid, runtime)
            status.state = RuntimeState.FAILED
            status.error = f"Runtime executable missing: {rid}"
            self._records[rid] = _RuntimeRecord(rid, runtime, None, status)
            raise RuntimeConfigurationError(
                status.error, runtime_id=rid, status=status
            )

        command = [str(executable)]
        base_args = _resource_value(runtime, "args", ()) or ()
        if isinstance(base_args, (str, bytes)):
            base_args = [base_args]
        try:
            command.extend(str(item) for item in base_args)
        except TypeError as exc:
            raise RuntimeConfigurationError(
                f"Runtime args must be a sequence: {rid}",
                runtime_id=rid,
                cause=exc,
            ) from exc
        extra = tuple(str(item) for item in (extra_args or ()))
        command.extend(extra)
        working_dir = _resource_value(runtime, "working_dir")

        status = self._new_status(rid, runtime)
        status.state = RuntimeState.STARTING
        status.command = tuple(command)
        status.port = self._runtime_port(runtime, command)
        status.endpoint = self._readiness_url(runtime, command)
        status.started_at = self.clock()
        status.generation = self._generation.get(rid, 0) + 1
        self._generation[rid] = status.generation

        try:
            process = self._spawn(command, working_dir, runtime)
        except BaseException as exc:
            self._mark_start_failure(status, exc)
            self._records[rid] = _RuntimeRecord(rid, runtime, None, status, extra)
            raise self._start_exception(status, exc) from exc

        # Some runners return a (process, metadata) pair.  Accepting that form
        # costs nothing and makes tiny test doubles convenient.
        if isinstance(process, tuple) and process:
            process = process[0]
        status.process = process
        status.pid = getattr(process, "pid", None)
        record = _RuntimeRecord(rid, runtime, process, status, extra)
        self._records[rid] = record
        self.processes[rid] = process

        returncode = self._poll(process)
        if returncode is not None:
            self._mark_process_exit(record, returncode)
            exc = self._start_exception_from_exit(record)
            raise exc

        endpoint = status.endpoint
        if wait_for_ready is None:
            wait_for_ready = self._readiness_enabled(runtime, endpoint)
        if readiness is not None:
            wait_for_ready = bool(readiness)

        if wait_for_ready and endpoint:
            self._wait_until_ready(
                record,
                timeout=self._resolve_timeout(runtime, timeout, readiness_timeout),
            )
        elif wait_for_ready:
            # Explicitly asking for readiness without an endpoint is a valid
            # no-op: a live process is the only observable readiness signal.
            status.state = RuntimeState.READY
            status.ready_at = self.clock()
        else:
            status.state = RuntimeState.RUNNING
        return process

    def stop(
        self,
        runtime_or_id: Any,
        *,
        timeout: float | None = None,
        kill_timeout: float | None = None,
    ) -> RuntimeStatus:
        """Stop a runtime, wait for it, and reap its process handle."""

        rid = _runtime_id(runtime_or_id)
        self._reap_one(rid)
        record = self._records.get(rid)
        if record is None or not self._is_process_alive(record.process):
            if record is None:
                status = RuntimeStatus(runtime_id=rid)
                self._records[rid] = _RuntimeRecord(rid, runtime_or_id, None, status)
            else:
                status = record.status
                status.state = RuntimeState.STOPPED
                status.stopped_at = status.stopped_at or self.clock()
            self.processes.pop(rid, None)
            return status

        process = record.process
        status = record.status
        status.state = RuntimeState.STOPPING
        try:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
        except BaseException as exc:
            status.error = f"Failed to terminate runtime {rid}: {exc}"

        wait_limit = self.stop_timeout if timeout is None else max(0.0, float(timeout))
        exited = self._wait_for_exit(process, wait_limit)
        if not exited:
            try:
                kill = getattr(process, "kill", None)
                if callable(kill):
                    kill()
            except BaseException as exc:
                status.error = f"Failed to kill runtime {rid}: {exc}"
            final_limit = (
                self.stop_timeout
                if kill_timeout is None
                else max(0.0, float(kill_timeout))
            )
            self._wait_for_exit(process, final_limit)

        status.returncode = self._poll(process)
        status.state = RuntimeState.STOPPED
        status.stopped_at = self.clock()
        self.processes.pop(rid, None)
        return status

    def restart(
        self,
        runtime: Any,
        extra_args: Sequence[Any] | None = None,
        *,
        timeout: float | None = None,
        readiness_timeout: float | None = None,
        wait_for_ready: bool | None = None,
        readiness: bool | None = None,
    ) -> Any:
        """Stop (if needed) and start a fresh process generation."""

        rid = _runtime_id(runtime)
        self.stop(rid)
        return self.start(
            runtime,
            extra_args=extra_args,
            timeout=timeout,
            readiness_timeout=readiness_timeout,
            wait_for_ready=wait_for_ready,
            readiness=readiness,
        )

    def status(self, runtime_or_id: Any) -> RuntimeStatus:
        """Return a live, detailed status snapshot for a runtime."""

        rid = _runtime_id(runtime_or_id)
        self._reap_one(rid)
        record = self._records.get(rid)
        if record is None:
            status = RuntimeStatus(runtime_id=rid)
            self._records[rid] = _RuntimeRecord(rid, runtime_or_id, None, status)
            return status
        return record.status

    status_info = status
    get_status = status

    def legacy_status(self, runtime_or_id: Any) -> str:
        """Return the historical ``running``/``stopped`` status string."""

        # Call the base implementation explicitly.  ``RuntimeLauncher``
        # overrides ``status`` with the legacy string API, and dispatching via
        # ``self.status`` here would recurse indefinitely.
        status = RuntimeManager.status(self, runtime_or_id)
        return "running" if status.is_running else "stopped"

    def is_running(self, runtime_or_id: Any) -> bool:
        return self.status(runtime_or_id).is_running

    def is_ready(self, runtime_or_id: Any) -> bool:
        return self.status(runtime_or_id).is_ready

    def reap(self, runtime_id: str | None = None) -> RuntimeStatus | dict[str, RuntimeStatus]:
        """Poll live processes and remove exited handles from ``processes``."""

        if runtime_id is not None:
            rid = _runtime_id(runtime_id)
            self._reap_one(rid)
            return self.status(rid)
        for rid in tuple(self._records):
            self._reap_one(rid)
        return {rid: record.status for rid, record in self._records.items()}

    poll = reap

    def stop_all(self, *, timeout: float | None = None) -> dict[str, RuntimeStatus]:
        result: dict[str, RuntimeStatus] = {}
        for rid in tuple(self._records):
            result[rid] = self.stop(rid, timeout=timeout)
        return result

    shutdown = stop_all

    def __enter__(self) -> "RuntimeManager":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop_all()

    # ------------------------------------------------------------------
    # Process, probe, and status internals
    # ------------------------------------------------------------------

    def _new_status(self, rid: str, runtime: Any) -> RuntimeStatus:
        old = self._records.get(rid)
        if old is not None:
            # Keep the latest generation number while clearing stale details.
            status = RuntimeStatus(runtime_id=rid, generation=old.status.generation)
        else:
            status = RuntimeStatus(runtime_id=rid)
        return status

    @staticmethod
    def _is_process_alive(process: Any) -> bool:
        if process is None:
            return False
        poll = getattr(process, "poll", None)
        if not callable(poll):
            # A minimal fake may expose only ``returncode``.
            return getattr(process, "returncode", None) is None
        try:
            return poll() is None
        except BaseException:
            return False

    @staticmethod
    def _poll(process: Any) -> int | None:
        if process is None:
            return None
        poll = getattr(process, "poll", None)
        if callable(poll):
            try:
                value = poll()
                return None if value is None else int(value)
            except (TypeError, ValueError):
                return getattr(process, "returncode", None)
            except BaseException:
                return getattr(process, "returncode", None)
        value = getattr(process, "returncode", None)
        return None if value is None else int(value)

    def _spawn(self, command: list[str], working_dir: Any, runtime: Any) -> Any:
        runner = self.process_runner
        if runner is None:
            runner = subprocess.Popen
        elif hasattr(runner, "Popen") and callable(getattr(runner, "Popen")):
            runner = runner.Popen
        elif hasattr(runner, "start") and callable(getattr(runner, "start")):
            runner = runner.start
        elif hasattr(runner, "run") and callable(getattr(runner, "run")):
            runner = runner.run
        if not callable(runner):
            raise TypeError("process_runner must be callable or expose start/Popen")

        kwargs: dict[str, Any] = {}
        if working_dir is not None:
            kwargs["cwd"] = working_dir
        env = _resource_value(runtime, "env")
        if isinstance(env, Mapping):
            kwargs["env"] = dict(env)

        # Keep the normal Popen call straightforward.  For tiny doubles that
        # do not accept ``cwd``, retry only when the signature clearly rejects
        # that keyword; TypeErrors raised inside a runner are not swallowed.
        if kwargs and not self._accepts_keyword(runner, "cwd"):
            try:
                return runner(command, working_dir=working_dir, **{
                    key: value for key, value in kwargs.items() if key != "cwd"
                })
            except TypeError as exc:
                if "working_dir" not in str(exc) and "unexpected keyword" not in str(exc):
                    raise
                return runner(command)
        return runner(command, **kwargs)

    @staticmethod
    def _accepts_keyword(func: Callable[..., Any], keyword: str) -> bool:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return True
        parameters = signature.parameters.values()
        if any(param.kind is param.VAR_KEYWORD for param in parameters):
            return True
        return keyword in signature.parameters

    def _wait_until_ready(self, record: _RuntimeRecord, *, timeout: float | None) -> RuntimeStatus:
        status = record.status
        endpoint = status.endpoint
        if not endpoint:
            status.state = RuntimeState.READY
            status.ready_at = self.clock()
            return status

        limit = self.default_timeout if timeout is None else max(0.0, float(timeout))
        deadline = self.clock() + limit
        attempts = 0
        last_error: BaseException | None = None
        while True:
            attempts += 1
            status.attempts = attempts
            returncode = self._poll(record.process)
            if returncode is not None:
                self._mark_process_exit(record, returncode)
                raise self._start_exception_from_exit(record, cause=last_error)

            try:
                response = self._probe(endpoint, record.health_timeout)
                if self._probe_succeeded(response):
                    status.state = RuntimeState.READY
                    status.ready_at = self.clock()
                    status.error = None
                    return status
            except BaseException as exc:
                last_error = exc

            now = self.clock()
            if now >= deadline or attempts >= self.max_probe_attempts:
                message = (
                    f"Runtime '{record.runtime_id}' readiness timed out after "
                    f"{limit:g}s at {endpoint}"
                )
                if last_error is not None:
                    message += f" ({last_error})"
                status.state = RuntimeState.TIMEOUT
                status.error = message
                self._terminate_after_failure(record)
                raise RuntimeTimeoutError(
                    message,
                    runtime_id=record.runtime_id,
                    status=status,
                    cause=last_error,
                )

            remaining = max(0.0, deadline - now)
            delay = min(self.probe_interval, remaining)
            if delay > 0:
                self.sleeper(delay)
            elif self.probe_interval == 0 and attempts >= self.max_probe_attempts:
                # Defensive guard for a static injected clock/sleeper.
                continue

    def _probe(self, endpoint: str, timeout: float | None) -> Any:
        probe = self.http_probe
        if probe is None:
            return self._default_http_probe(endpoint, timeout)
        if hasattr(probe, "probe") and callable(getattr(probe, "probe")):
            probe = probe.probe
        elif hasattr(probe, "get") and callable(getattr(probe, "get")) and not callable(probe):
            probe = probe.get
        if not callable(probe):
            raise TypeError("http_probe must be callable or expose probe/get")

        if timeout is None:
            return probe(endpoint)
        if self._accepts_keyword(probe, "timeout"):
            return probe(endpoint, timeout=timeout)
        try:
            return probe(endpoint, timeout)
        except TypeError as exc:
            if "argument" not in str(exc) and "timeout" not in str(exc):
                raise
            return probe(endpoint)

    @staticmethod
    def _default_http_probe(endpoint: str, timeout: float | None) -> Any:
        request = Request(endpoint, method="GET")
        try:
            with urlopen(request, timeout=timeout or 5.0) as response:
                return getattr(response, "status", response.getcode())
        except (URLError, OSError, socket.timeout):
            return False

    @staticmethod
    def _probe_succeeded(response: Any) -> bool:
        if isinstance(response, bool):
            return response
        if response is None:
            return False
        if isinstance(response, (int, float)):
            return 200 <= response < 400
        if isinstance(response, Mapping):
            if "ok" in response:
                return bool(response["ok"])
            code = response.get("status_code", response.get("status"))
            if code is not None:
                try:
                    return 200 <= int(code) < 400
                except (TypeError, ValueError):
                    pass
            # A JSON health body such as {"status": "ok"} is common.
            return str(response.get("status", "")).lower() in {"ok", "ready", "healthy"}
        code = getattr(response, "status_code", getattr(response, "status", None))
        if code is not None:
            try:
                return 200 <= int(code) < 400
            except (TypeError, ValueError):
                pass
        return bool(response)

    def _wait_for_exit(self, process: Any, timeout: float) -> bool:
        if not self._is_process_alive(process):
            return True
        wait = getattr(process, "wait", None)
        if callable(wait):
            try:
                wait(timeout=max(0.0, timeout))
            except TypeError:
                try:
                    wait()
                except BaseException:
                    pass
            except (subprocess.TimeoutExpired, TimeoutError):
                pass
            except BaseException:
                pass
        if not self._is_process_alive(process):
            return True
        # Fakes often update their state only after ``terminate`` and do not
        # implement wait.  A short polling loop handles those without blocking
        # for the full stop timeout.
        deadline = self.clock() + max(0.0, timeout)
        while self._is_process_alive(process):
            if self.clock() >= deadline:
                break
            self.sleeper(min(self.probe_interval or 0.01, max(0.0, deadline - self.clock())))
        return not self._is_process_alive(process)

    def _reap_one(self, rid: str) -> None:
        record = self._records.get(rid)
        if record is None or record.process is None:
            self.processes.pop(rid, None)
            return
        returncode = self._poll(record.process)
        if returncode is None:
            return
        self._mark_process_exit(record, returncode)

    def _mark_process_exit(self, record: _RuntimeRecord, returncode: int | None) -> None:
        status = record.status
        status.returncode = returncode
        status.process = record.process
        status.stopped_at = status.stopped_at or self.clock()
        if status.state in {RuntimeState.STOPPING, RuntimeState.STOPPED}:
            status.state = RuntimeState.STOPPED
        elif status.state in {RuntimeState.STARTING, RuntimeState.RUNNING} and returncode:
            status.state = RuntimeState.FAILED
        else:
            status.state = RuntimeState.EXITED
        self.processes.pop(record.runtime_id, None)

    def _mark_start_failure(self, status: RuntimeStatus, exc: BaseException) -> None:
        status.state = (
            RuntimeState.PORT_CONFLICT
            if self._looks_like_port_conflict(exc)
            else RuntimeState.FAILED
        )
        status.error = f"Failed to start runtime '{status.runtime_id}': {exc}"
        status.stopped_at = self.clock()

    def _start_exception(self, status: RuntimeStatus, cause: BaseException) -> RuntimeLifecycleError:
        if self._looks_like_port_conflict(cause, status.port):
            message = (
                f"Port {status.port} is already in use while starting runtime "
                f"'{status.runtime_id}'"
            )
            status.state = RuntimeState.PORT_CONFLICT
            status.error = message
            return RuntimePortConflictError(
                message,
                runtime_id=status.runtime_id,
                port=status.port,
                status=status,
                cause=cause,
            )
        return RuntimeStartError(
            status.error or f"Failed to start runtime '{status.runtime_id}'",
            runtime_id=status.runtime_id,
            status=status,
            cause=cause,
        )

    def _start_exception_from_exit(
        self, record: _RuntimeRecord, *, cause: BaseException | None = None
    ) -> RuntimeLifecycleError:
        status = record.status
        output = self._process_output(record.process)
        if self._looks_like_port_conflict(output, status.port):
            message = (
                f"Port {status.port} is unavailable for runtime '{record.runtime_id}'"
            )
            status.state = RuntimeState.PORT_CONFLICT
            status.error = message
            return RuntimePortConflictError(
                message,
                runtime_id=record.runtime_id,
                port=status.port,
                status=status,
                cause=cause,
            )
        message = (
            f"Runtime '{record.runtime_id}' exited during startup"
            f" (return code {status.returncode})"
        )
        if output:
            message += f": {output}"
        status.state = RuntimeState.FAILED
        status.error = message
        self.processes.pop(record.runtime_id, None)
        return RuntimeStartError(
            message,
            runtime_id=record.runtime_id,
            status=status,
            cause=cause,
        )

    @staticmethod
    def _process_output(process: Any) -> str:
        chunks: list[str] = []
        for key in ("stderr", "stdout"):
            value = getattr(process, key, None)
            if value is None:
                continue
            if hasattr(value, "getvalue"):
                try:
                    value = value.getvalue()
                except BaseException:
                    continue
            if isinstance(value, bytes):
                value = value.decode(errors="replace")
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
        return " | ".join(chunks)

    def _terminate_after_failure(self, record: _RuntimeRecord) -> None:
        process = record.process
        if process is None:
            self.processes.pop(record.runtime_id, None)
            return
        try:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                terminate()
        except BaseException:
            pass
        self._wait_for_exit(process, self.stop_timeout)
        if self._is_process_alive(process):
            try:
                kill = getattr(process, "kill", None)
                if callable(kill):
                    kill()
            except BaseException:
                pass
            self._wait_for_exit(process, self.stop_timeout)
        record.status.returncode = self._poll(process)
        self.processes.pop(record.runtime_id, None)

    def _resolve_timeout(
        self,
        runtime: Any,
        timeout: float | None,
        readiness_timeout: float | None,
    ) -> float:
        if readiness_timeout is not None:
            return max(0.0, float(readiness_timeout))
        if timeout is not None:
            return max(0.0, float(timeout))
        for key in (
            "readiness_timeout",
            "ready_timeout",
            "startup_timeout",
            "health_timeout",
            "timeout",
        ):
            value = _as_float(_resource_value(runtime, key), None)
            if value is not None:
                return value
        return self.default_timeout

    def _readiness_enabled(self, runtime: Any, endpoint: str | None) -> bool:
        explicit = _resource_value(runtime, "wait_for_ready")
        if explicit is None:
            explicit = _resource_value(runtime, "readiness")
        if isinstance(explicit, str):
            if explicit.strip().lower() in {"false", "off", "0", "no"}:
                return False
            if explicit.strip().lower() in {"true", "on", "1", "yes"}:
                return True
        if explicit is not None:
            return bool(explicit)
        return endpoint is not None

    def _runtime_port(self, runtime: Any, command: Sequence[str]) -> int | str | None:
        for key in ("port", "listen_port", "http_port"):
            value = _resource_value(runtime, key)
            if value is not None:
                return _as_port(value)
        args = list(command[1:])
        for index, item in enumerate(args):
            value = str(item)
            if value.startswith("--port="):
                return _as_port(value.split("=", 1)[1])
            if value in {"--port", "-p"} and index + 1 < len(args):
                return _as_port(args[index + 1])
        return None

    def _readiness_url(self, runtime: Any, command: Sequence[str]) -> str | None:
        for key in (
            "readiness_url",
            "ready_url",
            "health_url",
            "probe_url",
            "health_endpoint",
        ):
            value = _resource_value(runtime, key)
            if value:
                return self._normalise_url(str(value))

        readiness = _resource_value(runtime, "readiness")
        if isinstance(readiness, str) and "://" in readiness:
            return self._normalise_url(readiness)
        endpoint = _resource_value(runtime, "endpoint") or _resource_value(runtime, "base_url")
        if endpoint:
            text = str(endpoint)
            if "://" in text:
                if text.rstrip("/").endswith("/health"):
                    return text.rstrip("/")
                return text.rstrip("/") + "/health"

        port = self._runtime_port(runtime, command)
        if port is None:
            return None
        host = (
            _resource_value(runtime, "host")
            or _resource_value(runtime, "bind_host")
            or _resource_value(runtime, "listen_host")
            or "127.0.0.1"
        )
        path = (
            _resource_value(runtime, "health_path")
            or _resource_value(runtime, "readiness_path")
            or "/health"
        )
        path = "/" + str(path).lstrip("/")
        return self._normalise_url(f"http://{host}:{port}{path}")

    @staticmethod
    def _normalise_url(url: str) -> str:
        if "://" not in url:
            return "http://" + url
        return url

    @staticmethod
    def _looks_like_port_conflict(value: Any, port: int | str | None = None) -> bool:
        if isinstance(value, BaseException):
            if getattr(value, "errno", None) in {errno.EADDRINUSE, 10048}:
                return True
            text = str(value)
        else:
            text = str(value or "")
        lowered = text.lower()
        if any(
            marker in lowered
            for marker in (
                "eaddrinuse",
                "address already in use",
                "only one usage of each socket address",
                "port is already in use",
                "port already in use",
                "bind() failed",
            )
        ):
            return True
        if port is not None and "address" in lowered and "use" in lowered:
            return True
        return False


__all__ = [
    "RuntimeManager",
    "RuntimeState",
    "RuntimeStatus",
    "RuntimeLifecycleError",
    "RuntimeConfigurationError",
    "RuntimeStartError",
    "RuntimeStartupError",
    "RuntimePortConflictError",
    "RuntimeTimeoutError",
    "RuntimeReadinessTimeout",
]
