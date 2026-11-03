"""M15 operational status contracts without real providers or services."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event, Lock, Thread
from types import SimpleNamespace

from fastapi.testclient import TestClient

from oratrice_api import create_api
from oratrice_api.status import OperationStatusTracker, ReadinessCache
from oratrice_api.streaming import StreamSession
from providers import ChatChunk, ChatResponse


_STATUS_KEYS = {
    "version",
    "state",
    "operation",
    "delivery",
    "error_code",
    "checked_at",
}


def _ready_report(status: str = "healthy"):
    return {
        "status": status,
        "components": {"core": {"status": status}},
        "details": {"private_path": "D:/private/provider/config.yaml"},
    }


def _assert_status_shape(payload):
    assert set(payload) == _STATUS_KEYS
    assert payload["version"] == 1
    assert datetime.fromisoformat(payload["checked_at"]).utcoffset() is not None


def test_status_never_falls_back_to_facade_health_and_reports_unavailable():
    class Facade:
        health_calls = 0

        def health(self, **_kwargs):
            self.health_calls += 1
            raise AssertionError("/status must not call facade health")

    facade = Facade()
    client = TestClient(create_api(application=SimpleNamespace(facade=facade)))
    with client:
        response = client.get("/status")

    payload = response.json()
    _assert_status_shape(payload)
    assert response.status_code == 200
    assert payload["state"] == "starting"
    assert payload["error_code"] == "readiness_unavailable"
    assert facade.health_calls == 0


def test_status_explicit_readiness_is_safe_and_metadata_is_stripped():
    def checker():
        return _ready_report()

    api = create_api(
        application=SimpleNamespace(facade=object()),
        readiness_checker=checker,
    )
    client = TestClient(api)
    with client:
        response = client.get("/status")

    payload = response.json()
    _assert_status_shape(payload)
    assert payload["state"] == "ready"
    assert payload["error_code"] is None
    assert "private_path" not in str(payload)
    assert "provider" not in str(payload)


def test_status_checker_exception_uses_safe_readiness_error_enum():
    def checker():
        raise RuntimeError("private endpoint and credential details")

    client = TestClient(create_api(
        application=SimpleNamespace(facade=object()),
        readiness_checker=checker,
    ))
    with client:
        response = client.get("/status")

    payload = response.json()
    _assert_status_shape(payload)
    assert response.status_code == 200
    assert payload["state"] == "error"
    assert payload["error_code"] == "readiness_failed"
    assert "private" not in str(payload)
    assert "credential" not in str(payload)


def test_status_uses_explicit_application_readiness_provider_attribute():
    class Facade:
        def health(self, **_kwargs):
            raise AssertionError("/status must not fall back to facade health")

    application = SimpleNamespace(
        facade=Facade(),
        readiness_provider=_ready_report(),
    )
    client = TestClient(create_api(application=application))
    with client:
        payload = client.get("/status").json()

    _assert_status_shape(payload)
    assert payload["state"] == "ready"
    assert payload["error_code"] is None


def test_readiness_loss_and_recovery_follow_prior_ready_state():
    cache = ReadinessCache(ttl_seconds=0)
    provider = object()
    assert cache.sample(provider, lambda: False) == "starting"
    assert cache.sample(provider, lambda: True) == "ready"
    assert cache.sample(provider, lambda: False) == "error"
    assert cache.sample(provider, lambda: True) == "ready"


def test_readiness_checker_failures_are_safe_and_singleflight_is_cached():
    clock = [0.0]
    cache = ReadinessCache(
        ttl_seconds=5,
        max_stale_seconds=15,
        clock=lambda: clock[0],
    )
    provider = object()
    assert cache.sample(provider, lambda: True) == "ready"
    clock[0] = 6.0
    checker_entered = Event()
    checker_release = Event()
    checker_calls = 0
    calls_lock = Lock()
    results = []

    def checker():
        nonlocal checker_calls
        with calls_lock:
            checker_calls += 1
        checker_entered.set()
        assert checker_release.wait(timeout=2)
        return True

    first = Thread(target=lambda: results.append(cache.sample(provider, checker)))
    first.start()
    assert checker_entered.wait(timeout=1)

    # An expired but bounded-stale result is reused; the checker is not called
    # a second time while the refresh is in flight.
    assert cache.sample(provider, checker) == "ready"
    assert checker_calls == 1
    clock[0] = 22.0
    assert cache.sample(provider, checker) == "error"
    assert checker_calls == 1
    checker_release.set()
    first.join(timeout=2)
    assert not first.is_alive()
    assert results == ["ready"]

    # The successful result is reused within the cache window.
    assert cache.sample(provider, lambda: False) == "ready"
    assert checker_calls == 1

    failed_cache = ReadinessCache(ttl_seconds=0)
    assert failed_cache.sample(provider, lambda: (_ for _ in ()).throw(RuntimeError("private error"))) == "error"


def test_bound_method_readiness_source_uses_stable_cache_identity():
    class Checker:
        def check(self):
            return True

    cache = ReadinessCache(ttl_seconds=5)
    checker = Checker()
    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return True

    assert cache.sample(checker.check, probe) == "ready"
    assert cache.sample(checker.check, lambda: False) == "ready"
    assert calls == 1


def test_busy_chat_and_route_are_reported_without_readiness_work():
    for operation in ("chat", "route"):
        entered, release = Event(), Event()
        readiness_calls = 0

        class Facade:
            def chat(self, **_kwargs):
                entered.set()
                assert release.wait(timeout=2)
                return ChatResponse(content="done")

            def route(self, **_kwargs):
                entered.set()
                assert release.wait(timeout=2)
                return SimpleNamespace(model="model.test", provider="provider.test")

        def checker():
            nonlocal readiness_calls
            readiness_calls += 1
            return _ready_report()

        client = TestClient(create_api(
            application=SimpleNamespace(facade=Facade()),
            readiness_checker=checker,
        ))
        with ThreadPoolExecutor(max_workers=1) as pool, client:
            pending = pool.submit(client.post, "/" + operation, json={"message": "hello"})
            assert entered.wait(timeout=1)
            status = client.get("/status")
            payload = status.json()
            _assert_status_shape(payload)
            assert status.status_code == 200
            assert payload["state"] == "busy"
            assert payload["operation"] == operation
            assert payload["delivery"] is None
            assert readiness_calls == 0
            release.set()
            assert pending.result(timeout=2).status_code == 200


def test_failed_operation_is_reported_until_a_new_successful_operation():
    class Facade:
        fail = True

        def chat(self, **_kwargs):
            if self.fail:
                raise RuntimeError("private prompt and provider details")
            return ChatResponse(content="recovered")

    facade = Facade()
    client = TestClient(create_api(application=SimpleNamespace(facade=facade)))
    with client:
        failed = client.post("/chat", json={"message": "private input"})
        failed_status = client.get("/status").json()
        facade.fail = False
        succeeded = client.post("/chat", json={"message": "hello"})
        recovered_status = client.get("/status").json()

    assert failed.status_code == 500
    assert failed_status["state"] == "error"
    assert failed_status["error_code"] == "operation_failed"
    assert succeeded.status_code == 200
    assert recovered_status["state"] == "starting"
    assert recovered_status["error_code"] == "readiness_unavailable"
    assert "private" not in str(failed_status)


def test_stopped_stream_remains_busy_until_provider_cleanup_releases_admission():
    entered, release, closed = Event(), Event(), Event()

    class Facade:
        def stream(self, **_kwargs):
            try:
                entered.set()
                assert release.wait(timeout=2)
                yield ChatChunk(content="discarded after stop")
            finally:
                closed.set()

    api = create_api(application=SimpleNamespace(facade=Facade()))
    admission = api.state.status_tracker
    assert admission.acquire(blocking=False, operation="stream")
    session = StreamSession(Facade(), admission, "private-request-id", None, "hello", {})
    client = TestClient(api)
    with client:
        session.start()
        assert entered.wait(timeout=1)
        session.stop_delivery("disconnect")
        try:
            response = client.get("/status")
            payload = response.json()
        finally:
            release.set()
        _assert_status_shape(payload)
        assert response.status_code == 200
        assert payload["state"] == "busy"
        assert payload["operation"] == "stream"
        assert payload["delivery"] == "stopped"
        assert "private-request-id" not in str(payload)
        assert session._finished.wait(timeout=1)
        assert closed.is_set()
        after_cleanup = client.get("/status").json()
    assert after_cleanup["state"] == "starting"
    assert after_cleanup["operation"] is None


def test_late_stream_callbacks_cannot_change_a_later_admission():
    admission = OperationStatusTracker()
    assert admission.acquire(blocking=False, operation="stream")
    old_token = admission.current_token()
    old_session = StreamSession(
        object(),
        admission,
        "old-session",
        None,
        "old request",
        {},
        status_token=old_token,
    )
    admission.release()

    assert admission.acquire(blocking=False, operation="stream")
    new_token = admission.current_token()
    assert new_token != old_token

    old_session.stop_delivery("late-disconnect")
    old_session._mark_operation_failed()
    snapshot = admission.snapshot()
    assert snapshot.busy
    assert snapshot.operation == "stream"
    assert snapshot.delivery == "active"
    assert not snapshot.operation_failed
    admission.release()
