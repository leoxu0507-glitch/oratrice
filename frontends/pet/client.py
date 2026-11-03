"""Bounded, loopback-only client for Oratrice's status API."""

from __future__ import annotations

import errno
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
STATUS_TIMEOUT_SECONDS = 2.0
MAX_STATUS_BYTES = 16 * 1024

State = Literal["starting", "ready", "busy", "error"]
Operation = Literal["chat", "route", "stream"]
Delivery = Literal["active", "stopped"]
ErrorCode = Literal[
    "operation_failed",
    "readiness_failed",
    "readiness_unavailable",
]

_EXPECTED_FIELDS = {
    "version",
    "state",
    "operation",
    "delivery",
    "error_code",
    "checked_at",
}
_STATES = {"starting", "ready", "busy", "error"}
_OPERATIONS = {"chat", "route", "stream"}
_DELIVERIES = {"active", "stopped"}
_ERROR_CODES = {
    "operation_failed",
    "readiness_failed",
    "readiness_unavailable",
}
_UTC_ISO_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


@dataclass(frozen=True, slots=True)
class StatusPayload:
    """A fully validated response from GET /status."""

    version: int
    state: State
    operation: Operation | None
    delivery: Delivery | None
    error_code: ErrorCode | None
    checked_at: str


class StatusClientError(Exception):
    """A safe, non-sensitive description of a local status request failure."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class StatusTransportError(StatusClientError):
    """The local endpoint could not be reached or timed out."""

    def __init__(self, category: Literal["unreachable", "timeout", "transport"]) -> None:
        self.category = category
        messages = {
            "unreachable": "Oratrice is not running or is not reachable.",
            "timeout": "The Oratrice status request timed out.",
            "transport": "The Oratrice status endpoint is not reachable.",
        }
        super().__init__("transport", messages[category])


class StatusHTTPError(StatusClientError):
    """The status endpoint returned a non-200 HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("http", "The Oratrice status endpoint returned an HTTP error.")


class StatusContractError(StatusClientError):
    """The response was oversized, malformed, or outside the M15 contract."""

    def __init__(self) -> None:
        super().__init__("contract", "Oratrice returned an invalid status response.")


def validate_loopback_origin(base_url: str) -> str:
    """Accept only a loopback HTTP(S) origin, with no arbitrary path or query."""

    if (
        not isinstance(base_url, str)
        or not base_url
        or len(base_url) > 2048
        or any(character.isspace() or ord(character) < 0x20 for character in base_url)
        or any(character in base_url for character in ("\\", "?", "#"))
    ):
        raise ValueError("Base URL must be a loopback HTTP(S) origin.")

    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Base URL must be a loopback HTTP(S) origin.") from None

    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "@" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or hostname is None
        or "%" in hostname
    ):
        raise ValueError("Base URL must be a loopback HTTP(S) origin.")

    normalized_host = hostname.lower()
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        if normalized_host != "localhost":
            raise ValueError("Base URL host must be localhost or a loopback IP.") from None
    else:
        if not address.is_loopback:
            raise ValueError("Base URL host must be localhost or a loopback IP.")

    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Base URL port must be between 1 and 65535.")

    if ":" in normalized_host:
        authority = f"[{normalized_host}]"
    else:
        authority = normalized_host
    if port is not None:
        authority = f"{authority}:{port}"

    return f"{scheme}://{authority}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn redirects into HTTP errors instead of following them."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant: {value}")


def parse_status_payload(body: bytes) -> StatusPayload:
    """Decode and strictly validate the fixed, bounded status contract."""

    if len(body) > MAX_STATUS_BYTES:
        raise StatusContractError()

    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_non_json_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise StatusContractError() from None

    if not isinstance(value, dict) or set(value) != _EXPECTED_FIELDS:
        raise StatusContractError()
    if type(value["version"]) is not int or value["version"] != 1:
        raise StatusContractError()

    state = value["state"]
    operation = value["operation"]
    delivery = value["delivery"]
    error_code = value["error_code"]
    checked_at = value["checked_at"]

    if not isinstance(state, str) or state not in _STATES:
        raise StatusContractError()
    if operation is not None and (
        not isinstance(operation, str) or operation not in _OPERATIONS
    ):
        raise StatusContractError()
    if delivery is not None and (
        not isinstance(delivery, str) or delivery not in _DELIVERIES
    ):
        raise StatusContractError()
    if error_code is not None and (
        not isinstance(error_code, str) or error_code not in _ERROR_CODES
    ):
        raise StatusContractError()
    if (
        not isinstance(checked_at, str)
        or not _UTC_ISO_PATTERN.fullmatch(checked_at)
    ):
        raise StatusContractError()

    if state != "busy" and (operation is not None or delivery is not None):
        raise StatusContractError()
    if state == "busy":
        if operation is None or error_code is not None:
            raise StatusContractError()
        if operation == "stream":
            if delivery not in _DELIVERIES:
                raise StatusContractError()
        elif delivery is not None:
            raise StatusContractError()
    elif state == "starting":
        if error_code not in {None, "readiness_unavailable"}:
            raise StatusContractError()
    elif state == "ready":
        if error_code is not None:
            raise StatusContractError()
    elif error_code not in {"operation_failed", "readiness_failed"}:
        raise StatusContractError()

    try:
        timestamp = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        raise StatusContractError() from None
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise StatusContractError()

    return StatusPayload(
        version=1,
        state=state,
        operation=operation,
        delivery=delivery,
        error_code=error_code,
        checked_at=checked_at,
    )


def _transport_category(reason: object) -> Literal[
    "unreachable", "timeout", "transport"
]:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, OSError):
        if reason.errno == errno.ECONNREFUSED:
            return "unreachable"
        if reason.errno == errno.ETIMEDOUT:
            return "timeout"
    return "transport"



def _read_bounded_response(response, deadline: float) -> bytes:
    read1 = getattr(response, "read1", None)
    if not callable(read1):
        raise StatusContractError()

    body = bytearray()
    while len(body) <= MAX_STATUS_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StatusTransportError("timeout")

        stream = getattr(getattr(response, "fp", None), "raw", None)
        connection = getattr(stream, "_sock", None)
        settimeout = getattr(connection, "settimeout", None)
        if callable(settimeout):
            try:
                settimeout(remaining)
            except OSError:
                pass

        chunk = read1(min(4096, MAX_STATUS_BYTES + 1 - len(body)))
        if time.monotonic() >= deadline:
            raise StatusTransportError("timeout")
        if not isinstance(chunk, bytes):
            raise StatusContractError()
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > MAX_STATUS_BYTES:
            raise StatusContractError()
    return bytes(body)
class OratriceStatusClient:
    """GET /status from a validated local origin and derive its fixed /ui URL."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout_seconds: float = STATUS_TIMEOUT_SECONDS,
        opener=None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Status request timeout must be positive.")
        self.base_url = validate_loopback_origin(base_url)
        self.status_url = f"{self.base_url}/status"
        self.ui_url = f"{self.base_url}/ui/"
        self.timeout_seconds = float(timeout_seconds)
        self._opener = (
            opener
            if opener is not None
            else urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                _NoRedirectHandler(),
            )
        )

    def fetch_status(self) -> StatusPayload:
        """Perform one bounded GET; no redirects, writes, credentials, or retries."""

        request = urllib.request.Request(
            self.status_url,
            headers={"Accept": "application/json"},
            method="GET",
        )

        deadline = time.monotonic() + self.timeout_seconds
        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as error:
            try:
                error.close()
            finally:
                raise StatusHTTPError(int(error.code)) from None
        except urllib.error.URLError as error:
            raise StatusTransportError(_transport_category(error.reason)) from None
        except (TimeoutError, socket.timeout):
            raise StatusTransportError("timeout") from None
        except OSError as error:
            raise StatusTransportError(_transport_category(error)) from None

        try:
            try:
                status_code = response.getcode()
            except AttributeError:
                status_code = getattr(response, "status", None)
            if status_code != 200:
                raise StatusHTTPError(
                    status_code if type(status_code) is int else 0
                )
            body = _read_bounded_response(response, deadline)
        except StatusClientError:
            raise
        except urllib.error.HTTPError as error:
            try:
                error.close()
            finally:
                raise StatusHTTPError(int(error.code)) from None
        except urllib.error.URLError as error:
            raise StatusTransportError(_transport_category(error.reason)) from None
        except (TimeoutError, socket.timeout):
            raise StatusTransportError("timeout") from None
        except OSError as error:
            raise StatusTransportError(_transport_category(error)) from None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        return parse_status_payload(body)
