"""Offline tests for the status pet's bounded Oratrice API client."""

from __future__ import annotations

import errno
import json
import urllib.error
import urllib.request

import pytest

from frontends.pet import client as client_module
from frontends.pet.client import (
    DEFAULT_BASE_URL,
    MAX_STATUS_BYTES,
    OratriceStatusClient,
    StatusContractError,
    StatusHTTPError,
    StatusPayload,
    StatusTransportError,
    _NoRedirectHandler,
    parse_status_payload,
    validate_loopback_origin,
)


def status_data(**updates):
    value = {
        "version": 1,
        "state": "ready",
        "operation": None,
        "delivery": None,
        "error_code": None,
        "checked_at": "2026-11-03T09:30:00Z",
    }
    value.update(updates)
    return value


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.read_limits = []
        self.position = 0
        self.closed = False

    def getcode(self):
        return self.status

    def read1(self, limit: int) -> bytes:
        self.read_limits.append(limit)
        chunk = self.body[self.position : self.position + limit]
        self.position += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://127.255.255.255:8000/", "http://127.255.255.255:8000"),
        ("https://LOCALHOST:9443", "https://localhost:9443"),
        ("http://[::1]:8000/", "http://[::1]:8000"),
    ],
)
def test_accepts_only_normalized_loopback_origins(base_url, expected):
    assert validate_loopback_origin(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "https://example.com",
        "http://oratrice.local:8000",
        "http://192.168.1.20:8000",
        "http://[2001:db8::1]:8000",
        "http://user@localhost:8000",
        "http://:secret@localhost:8000",
        "http://localhost:8000/path",
        "http://localhost:8000?",
        "http://localhost:8000#",
        "ftp://localhost:8000",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost\\@example.com",
        "http://localhost%2eexample.com",
        "http://[::1%25eth0]:8000",
    ],
)
def test_rejects_external_or_non_origin_base_urls(base_url):
    with pytest.raises(ValueError):
        validate_loopback_origin(base_url)


def test_default_urls_use_fixed_same_origin_paths_and_get():
    body = json.dumps(status_data()).encode("utf-8")
    response = FakeResponse(body)
    opener = FakeOpener(response=response)
    client = OratriceStatusClient(opener=opener)

    result = client.fetch_status()

    assert client.base_url == DEFAULT_BASE_URL
    assert client.status_url == "http://127.0.0.1:8000/status"
    assert client.ui_url == "http://127.0.0.1:8000/ui/"
    assert isinstance(result, StatusPayload)
    request, timeout = opener.calls[0]
    assert request.full_url == client.status_url
    assert request.get_method() == "GET"
    assert timeout == 2.0
    assert request.get_header("Accept") == "application/json"
    assert response.read_limits
    assert max(response.read_limits) <= 4096
    assert response.closed


def test_default_opener_disables_environment_proxies(monkeypatch):
    handlers = []

    def build_opener(*items):
        handlers.extend(items)
        return FakeOpener(response=FakeResponse(b"{}"))

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    OratriceStatusClient()

    proxy_handlers = [
        item for item in handlers if isinstance(item, urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert any(isinstance(item, _NoRedirectHandler) for item in handlers)


@pytest.mark.parametrize(
    ("updates", "expected_state"),
    [
        ({"state": "starting", "error_code": "readiness_unavailable"}, "starting"),
        ({"state": "busy", "operation": "chat"}, "busy"),
        (
            {"state": "busy", "operation": "stream", "delivery": "active"},
            "busy",
        ),
        (
            {"state": "busy", "operation": "stream", "delivery": "stopped"},
            "busy",
        ),
        ({"state": "error", "error_code": "operation_failed"}, "error"),
    ],
)
def test_accepts_semantically_consistent_statuses(updates, expected_state):
    payload = parse_status_payload(json.dumps(status_data(**updates)).encode("utf-8"))
    assert payload.state == expected_state


def test_custom_ipv6_origin_is_used_for_status_and_chat():
    client = OratriceStatusClient("https://[::1]:9443")
    assert client.status_url == "https://[::1]:9443/status"
    assert client.ui_url == "https://[::1]:9443/ui/"


def test_read_deadline_stops_a_slowly_dripping_body(monkeypatch):
    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

    class DrippingResponse(FakeResponse):
        def read1(self, limit):
            self.read_limits.append(limit)
            self.position += 1
            clock.now += 1.1
            return b" "

    clock = Clock()
    monkeypatch.setattr(client_module.time, "monotonic", clock.monotonic)
    response = DrippingResponse(b" " * 100)
    client = OratriceStatusClient(
        timeout_seconds=2.0,
        opener=FakeOpener(response=response),
    )

    with pytest.raises(StatusTransportError) as captured:
        client.fetch_status()

    assert captured.value.category == "timeout"
    assert len(response.read_limits) == 2
    assert response.closed


def test_rejects_redirect_response_without_following_location():
    target = "https://untrusted.example/"
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/status",
        302,
        "Found",
        {"Location": target},
        None,
    )
    opener = FakeOpener(error=error)
    client = OratriceStatusClient(opener=opener)

    with pytest.raises(StatusHTTPError) as captured:
        client.fetch_status()

    assert captured.value.status_code == 302
    assert len(opener.calls) == 1
    assert opener.calls[0][0].full_url == "http://127.0.0.1:8000/status"

    handler = _NoRedirectHandler()
    redirected = handler.redirect_request(
        urllib.request.Request("http://127.0.0.1:8000/status"),
        None,
        302,
        "Found",
        {"Location": target},
        target,
    )
    assert redirected is None


def test_http_error_body_is_closed_before_returning_a_safe_failure():
    from io import BytesIO

    body = BytesIO(b"private diagnostic data")
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8000/status", 503, "Unavailable", {}, body,
    )
    client = OratriceStatusClient(opener=FakeOpener(error=error))
    with pytest.raises(StatusHTTPError) as failure:
        client.fetch_status()
    assert body.closed
    assert "private" not in str(failure.value)


def test_rejects_oversized_status_body():
    response = FakeResponse(b" " * (MAX_STATUS_BYTES + 1))
    client = OratriceStatusClient(opener=FakeOpener(response=response))

    with pytest.raises(StatusContractError):
        client.fetch_status()

    assert sum(response.read_limits) == MAX_STATUS_BYTES + 1
    assert max(response.read_limits) <= 4096


@pytest.mark.parametrize(
    "updates",
    [
        {"version": True},
        {"state": "offline"},
        {"state": "working"},
        {"operation": "provider"},
        {"delivery": "cancelled"},
        {"state": "busy"},
        {"state": "busy", "operation": "stream"},
        {"state": "busy", "operation": "chat", "delivery": "active"},
        {"state": "ready", "error_code": "readiness_failed"},
        {"state": "starting", "error_code": "operation_failed"},
        {"error_code": "secret"},
        {"checked_at": "2026-11-03T09:30:00"},
        {"checked_at": "2026-11-03T10:30:00+01:00"},
        {"provider": "must not be accepted"},
    ],
)
def test_rejects_values_outside_fixed_status_schema(updates):
    body = json.dumps(status_data(**updates)).encode("utf-8")

    with pytest.raises(StatusContractError):
        parse_status_payload(body)


def test_accepts_readiness_unavailable_as_starting_state():
    payload = parse_status_payload(
        json.dumps(
            status_data(state="starting", error_code="readiness_unavailable")
        ).encode("utf-8")
    )
    assert payload.state == "starting"
    assert payload.error_code == "readiness_unavailable"


def test_rejects_duplicate_keys_and_nonstandard_json_constants():
    with pytest.raises(StatusContractError):
        parse_status_payload(
            b'{"version":1,"version":1,"state":"ready","operation":null,'
            b'"delivery":null,"error_code":null,"checked_at":"2026-11-03T09:30:00Z"}'
        )
    with pytest.raises(StatusContractError):
        parse_status_payload(
            b'{"version":NaN,"state":"ready","operation":null,'
            b'"delivery":null,"error_code":null,"checked_at":"2026-11-03T09:30:00Z"}'
        )


def test_classifies_connection_refused_and_timeout_without_exposing_reason():
    refused = urllib.error.URLError(
        OSError(errno.ECONNREFUSED, "private transport detail")
    )
    client = OratriceStatusClient(opener=FakeOpener(error=refused))
    with pytest.raises(StatusTransportError) as captured:
        client.fetch_status()
    assert captured.value.category == "unreachable"
    assert "private transport detail" not in str(captured.value)

    timeout = urllib.error.URLError(TimeoutError("private timeout detail"))
    client = OratriceStatusClient(opener=FakeOpener(error=timeout))
    with pytest.raises(StatusTransportError) as captured:
        client.fetch_status()
    assert captured.value.category == "timeout"
    assert "private timeout detail" not in str(captured.value)


def test_non_200_response_is_not_treated_as_ready():
    response = FakeResponse(json.dumps(status_data()).encode("utf-8"), status=503)
    client = OratriceStatusClient(opener=FakeOpener(response=response))

    with pytest.raises(StatusHTTPError) as captured:
        client.fetch_status()

    assert captured.value.status_code == 503
    assert response.closed
