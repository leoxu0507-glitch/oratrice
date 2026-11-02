"""M9 request admission contracts for one API worker."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from providers import ChatResponse
from oratrice_api import create_api
from router import RouteDecision


class BlockingFacade:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.calls = 0
        self.route_entered = Event()
        self.route_release = Event()
        self.route_calls = 0
        self.fail_next_chat = False

    def chat(self, **kwargs):
        self.calls += 1
        self.entered.set()
        if self.fail_next_chat:
            self.fail_next_chat = False
            raise RuntimeError("offline facade failure")
        self.release.wait(timeout=5)
        return ChatResponse(
            content="offline reply",
            model=kwargs.get("model_id"),
            provider="provider.fake",
            request_id="facade-request",
        )

    def route(self, **kwargs):
        self.route_calls += 1
        self.route_entered.set()
        self.route_release.wait(timeout=5)
        return RouteDecision(
            model="model.fake",
            provider="provider.fake",
            reason="offline",
        )


class Application:
    def __init__(self, facade: BlockingFacade) -> None:
        self.facade = facade

    def close(self) -> None:
        return None


def test_chat_admission_rejects_overlap_without_queueing_and_keeps_live_available():
    facade = BlockingFacade()
    with TestClient(
        create_api(application=Application(facade)), raise_server_exceptions=False
    ) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/chat", json={"message": "first"})
            assert facade.entered.wait(timeout=2)

            busy = client.post("/chat", json={"message": "second"})
            live = client.get("/live")

            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            assert busy.json()["error"]["code"] == "chat_busy"
            assert busy.json()["error"]["retryable"] is True
            assert live.status_code == 200
            assert facade.calls == 1

            facade.release.set()
            completed = first.result(timeout=2)

        assert completed.status_code == 200
        assert completed.json()["content"] == "offline reply"


def test_chat_admission_is_released_after_facade_returns():
    facade = BlockingFacade()
    with TestClient(
        create_api(application=Application(facade)), raise_server_exceptions=False
    ) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(client.post, "/chat", json={"message": "first"})
            assert facade.entered.wait(timeout=2)
            facade.release.set()
            assert first.result(timeout=2).status_code == 200

        facade.entered.clear()
        facade.release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            second = pool.submit(client.post, "/chat", json={"message": "second"})
            assert facade.entered.wait(timeout=2)
            facade.release.set()
            assert second.result(timeout=2).status_code == 200

        assert facade.calls == 2


def test_chat_admission_is_released_after_facade_failure():
    facade = BlockingFacade()
    facade.fail_next_chat = True
    with TestClient(
        create_api(application=Application(facade)), raise_server_exceptions=False
    ) as client:
        failed = client.post("/chat", json={"message": "fails"})

        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "internal_error"

        facade.release.set()
        recovered = client.post("/chat", json={"message": "recovers"})

        assert recovered.status_code == 200
        assert recovered.json()["content"] == "offline reply"
        assert facade.calls == 2


def test_route_and_chat_share_admission_slot():
    facade = BlockingFacade()
    with TestClient(
        create_api(application=Application(facade)), raise_server_exceptions=False
    ) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/route", json={"message": "route"})
            assert facade.route_entered.wait(timeout=2)

            busy = client.post("/chat", json={"message": "chat"})

            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            assert busy.json()["error"]["code"] == "chat_busy"
            assert busy.json()["error"]["retryable"] is True
            assert facade.calls == 0

            facade.route_release.set()
            completed = first.result(timeout=2)

        assert completed.status_code == 200
        assert facade.route_calls == 1


def test_chat_and_route_share_admission_slot_in_reverse_direction():
    facade = BlockingFacade()
    with TestClient(
        create_api(application=Application(facade)), raise_server_exceptions=False
    ) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/chat", json={"message": "chat"})
            assert facade.entered.wait(timeout=2)

            busy = client.post("/route", json={"message": "route"})

            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            assert busy.json()["error"]["code"] == "route_busy"
            assert busy.json()["error"]["retryable"] is True
            assert facade.route_calls == 0

            facade.release.set()
            completed = first.result(timeout=2)

        assert completed.status_code == 200
        assert facade.calls == 1
