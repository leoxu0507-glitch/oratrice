"""GUI-free controller tests using fake Tk timers and a fake status client."""

from __future__ import annotations

from frontends.pet.app import (
    MAX_BACKOFF_SECONDS,
    POLL_INTERVAL_SECONDS,
    PetController,
    PetDisplayState,
    display_for_status,
)
from frontends.pet.client import (
    StatusContractError,
    StatusPayload,
    StatusTransportError,
)


class FakeRoot:
    def __init__(self) -> None:
        self.now_ms = 0
        self._next_id = 0
        self._callbacks = {}
        self.destroyed = False

    def after(self, delay_ms, callback):
        self._next_id += 1
        timer_id = f"timer-{self._next_id}"
        self._callbacks[timer_id] = (
            self.now_ms + max(0, int(delay_ms)),
            self._next_id,
            callback,
        )
        return timer_id

    def after_cancel(self, timer_id) -> None:
        self._callbacks.pop(timer_id, None)

    def destroy(self) -> None:
        self.destroyed = True

    @property
    def pending_count(self) -> int:
        return len(self._callbacks)

    @property
    def pending_delays_ms(self) -> list[int]:
        return [
            max(0, due_ms - self.now_ms)
            for due_ms, _sequence, _callback in self._callbacks.values()
        ]

    def run_next(self) -> None:
        if not self._callbacks:
            raise AssertionError("no fake Tk timer is pending")
        timer_id, (due_ms, _sequence, callback) = min(
            self._callbacks.items(),
            key=lambda item: (item[1][0], item[1][1]),
        )
        del self._callbacks[timer_id]
        self.now_ms = due_ms
        callback()


class FakeView:
    def __init__(self) -> None:
        self.states: list[PetDisplayState] = []
        self.message = ""

    def update_status(self, display: PetDisplayState) -> None:
        self.states.append(display)

    def set_message(self, message: str) -> None:
        self.message = message


class FakeClient:
    def __init__(self, responses, ui_url="http://127.0.0.1:8000/ui/") -> None:
        self.responses = list(responses)
        self.ui_url = ui_url
        self.calls = 0
        self.close_calls = 0
        self._last = None

    def fetch_status(self):
        self.calls += 1
        if self.responses:
            self._last = self.responses.pop(0)
        result = self._last
        if isinstance(result, StatusTransportError):
            raise StatusTransportError(result.category)
        if isinstance(result, StatusContractError):
            raise StatusContractError()
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self) -> None:
        self.close_calls += 1


class ImmediateThread:
    def __init__(self, *, target, daemon) -> None:
        assert daemon is True
        self._target = target

    def start(self) -> None:
        self._target()


class DeferredThread:
    def __init__(self, *, target, daemon) -> None:
        assert daemon is True
        self._target = target

    def start(self) -> None:
        pass


def status_payload(
    state="ready",
    operation=None,
    delivery=None,
    error_code=None,
):
    return StatusPayload(
        version=1,
        state=state,
        operation=operation,
        delivery=delivery,
        error_code=error_code,
        checked_at="2026-11-03T09:30:00+00:00",
    )


def run_one_poll(root: FakeRoot) -> None:
    root.run_next()  # poll timer; the fake worker completes immediately
    root.run_next()  # main-thread result drain


def test_starting_then_ready_and_user_command_opens_fixed_ui_url():
    root = FakeRoot()
    view = FakeView()
    client = FakeClient([status_payload()])
    opened = []
    controller = PetController(
        root,
        view,
        client,
        browser_open=lambda url: opened.append(url) or True,
        thread_factory=ImmediateThread,
    )

    controller.start()
    assert view.states[-1].state == "starting"
    assert opened == []

    run_one_poll(root)
    assert view.states[-1].state == "ready"
    assert view.states[-1].detail == "Oratrice is ready to chat."
    assert opened == []

    controller.open_chat()
    assert opened == ["http://127.0.0.1:8000/ui/"]
    assert view.message == "Oratrice chat opened in your browser."
    controller.close()


def test_busy_stream_after_stop_says_model_is_still_working():
    root = FakeRoot()
    view = FakeView()
    client = FakeClient(
        [status_payload(state="busy", operation="stream", delivery="stopped")]
    )
    controller = PetController(
        root,
        view,
        client,
        thread_factory=ImmediateThread,
    )

    controller.start()
    run_one_poll(root)

    assert view.states[-1].state == "busy"
    assert view.states[-1].detail == "The model is still working."
    controller.close()


def test_starting_readiness_unavailable_does_not_claim_models_are_starting():
    display = display_for_status(
        status_payload(
            state="starting",
            error_code="readiness_unavailable",
        )
    )
    assert display.state == "starting"
    assert display.detail == "Service readiness is not confirmed."


def test_invalid_contract_is_error_and_never_fake_ready():
    root = FakeRoot()
    view = FakeView()
    client = FakeClient([StatusContractError()])
    controller = PetController(
        root,
        view,
        client,
        thread_factory=ImmediateThread,
    )

    controller.start()
    run_one_poll(root)

    assert view.states[-1].state == "error"
    assert view.states[-1].title == "Error"
    controller.close()


def test_offline_backoff_saturates_after_one_thousand_failures():
    root = FakeRoot()
    view = FakeView()
    client = FakeClient([StatusTransportError("unreachable")])
    controller = PetController(
        root,
        view,
        client,
        thread_factory=ImmediateThread,
    )
    controller.start()

    for _ in range(1000):
        run_one_poll(root)

    assert client.calls == 1000
    assert controller.next_poll_delay_seconds == MAX_BACKOFF_SECONDS
    assert controller.next_poll_delay_seconds >= POLL_INTERVAL_SECONDS
    assert view.states[-1].state == "offline"
    controller.close()


def test_pending_worker_does_not_queue_more_polls_and_close_is_local_only():
    root = FakeRoot()
    view = FakeView()
    client = FakeClient([status_payload()])
    controller = PetController(
        root,
        view,
        client,
        thread_factory=DeferredThread,
    )
    controller.start()

    root.run_next()
    assert controller.worker_active
    assert client.calls == 0
    assert root.pending_count == 1
    root.run_next()
    assert controller.worker_active
    assert root.pending_count == 1

    controller.close()
    assert root.destroyed
    assert root.pending_count == 0
    assert client.close_calls == 0
