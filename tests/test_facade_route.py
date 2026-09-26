from __future__ import annotations

from core.ai_service import CoreFacade, CoreRoutingError
from router import RouteDecision, RouteNotFoundError, RouterRequest


class RecordingRouter:
    def __init__(self, decision: RouteDecision):
        self.decision = decision
        self.requests: list[RouterRequest] = []

    def route(self, request: RouterRequest) -> RouteDecision:
        self.requests.append(request)
        return self.decision


class RecordingRuntime:
    def __init__(self):
        self.calls: list[str] = []

    def status_model(self, model_id):
        self.calls.append(f"status:{model_id}")
        return "stopped"

    def start_model(self, model_id):
        self.calls.append(f"start:{model_id}")


class RecordingProvider:
    def __init__(self):
        self.calls: list[str] = []

    def chat(self, request):
        self.calls.append("chat")

    def stream(self, request):
        self.calls.append("stream")
        return iter(())


class RecordingLogger:
    def __init__(self):
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def _record(self, level, event, **fields):
        self.events.append((level, event, fields))

    def info(self, event, **fields):
        self._record("info", event, **fields)

    def debug(self, event, **fields):
        self._record("debug", event, **fields)

    def error(self, event, **fields):
        self._record("error", event, **fields)


def test_route_returns_decision_without_runtime_or_provider_calls():
    decision = RouteDecision(
        model="model.local",
        provider="provider.local",
        task_type="general",
        complexity="medium",
        reason="offline route",
    )
    router = RecordingRouter(decision)
    runtime = RecordingRuntime()
    provider = RecordingProvider()
    logger = RecordingLogger()
    facade = CoreFacade(
        router=router,
        manager=runtime,
        provider_instances={"provider.local": provider},
        request_id_factory=lambda: "generated-route-id",
        logger=logger,
        auto_start=True,
    )

    result = facade.route("model.local", "hello", request_id="route-1")

    assert result is decision
    assert router.requests[0].model == "model.local"
    assert router.requests[0].message == "hello"
    assert runtime.calls == []
    assert provider.calls == []
    assert [event[1] for event in logger.events] == [
        "core.request.start",
        "core.request.routed",
        "core.request.completed",
    ]
    assert all(event[2]["request_id"] == "route-1" for event in logger.events)
    assert all(event[2]["operation"] == "route" for event in logger.events)


def test_route_preserves_metadata_allow_cloud_and_generates_request_id():
    decision = RouteDecision("model.cloud", "provider.cloud", reason="opt-in")
    router = RecordingRouter(decision)
    facade = CoreFacade(
        router=router,
        request_id_factory=lambda: "generated-route-id",
        auto_start=False,
    )

    result = facade.route(
        message="solve this",
        metadata={"allow_cloud": True},
    )

    assert result == decision
    assert router.requests[0].metadata == {"allow_cloud": True}


def test_route_error_has_request_id_and_route_operation():
    class BrokenRouter:
        def route(self, request):
            raise RouteNotFoundError("no configured route")

    facade = CoreFacade(
        router=BrokenRouter(),
        request_id_factory=lambda: "generated-route-id",
        auto_start=False,
    )

    try:
        facade.route(message="hello", request_id="route-error")
    except CoreRoutingError as exc:
        assert exc.request_id == "route-error"
        assert exc.operation == "route"
        assert isinstance(exc.cause, RouteNotFoundError)
        assert exc.to_dict()["request_id"] == "route-error"
    else:
        raise AssertionError("route failure should cross the core boundary")
