"""Tk status companion and a GUI-independent polling controller."""

from __future__ import annotations

import queue
import threading
import webbrowser
from dataclasses import dataclass
from typing import Callable, Literal

from .client import (
    DEFAULT_BASE_URL,
    OratriceStatusClient,
    StatusClientError,
    StatusContractError,
    StatusHTTPError,
    StatusPayload,
    StatusTransportError,
)

DisplayState = Literal["starting", "ready", "busy", "error", "offline"]

POLL_INTERVAL_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 30.0
RESULT_CHECK_INTERVAL_MS = 100

_STATE_COLORS: dict[DisplayState, str] = {
    "starting": "#e0ad52",
    "ready": "#55b887",
    "busy": "#7196ed",
    "error": "#dd6d72",
    "offline": "#8992a2",
}


@dataclass(frozen=True, slots=True)
class PetDisplayState:
    """Fixed, safe text and color shown by the local pet window."""

    state: DisplayState
    title: str
    detail: str
    color: str


@dataclass(frozen=True, slots=True)
class _PollOutcome:
    display: PetDisplayState
    successful: bool


def display_for_status(payload: StatusPayload) -> PetDisplayState:
    """Map the server contract to fixed user-facing labels."""

    if payload.error_code == "readiness_unavailable":
        title = "Starting"
        detail = "Service readiness is not confirmed."
    elif payload.state == "starting":
        title = "Starting"
        detail = "Oratrice is checking local service readiness."
    elif payload.state == "ready":
        title = "Ready"
        detail = "Oratrice is ready to chat."
    elif payload.state == "busy":
        title = "Working"
        if payload.delivery == "stopped":
            detail = "The model is still working."
        elif payload.operation == "stream" and payload.delivery == "active":
            detail = "Oratrice is streaming a response."
        else:
            detail = "Oratrice is processing a request."
    else:
        title = "Error"
        details = {
            "operation_failed": "The last request failed.",
            "readiness_failed": "A required local service is not ready.",
            "readiness_unavailable": "Service readiness is not confirmed.",
            None: "Oratrice reported an error.",
        }
        detail = details[payload.error_code]

    return PetDisplayState(
        state=payload.state,
        title=title,
        detail=detail,
        color=_STATE_COLORS[payload.state],
    )


def display_for_error(error: BaseException) -> PetDisplayState:
    """Convert failures to bounded messages without exposing exception details."""

    if isinstance(error, StatusTransportError):
        detail = {
            "unreachable": "Oratrice is not running or is not reachable.",
            "timeout": "The status check timed out. Retrying automatically.",
            "transport": "Oratrice is temporarily unreachable. Retrying automatically.",
        }[error.category]
        state: DisplayState = "offline"
        title = "Offline"
    elif isinstance(error, StatusHTTPError):
        status_code = error.status_code
        if status_code == 404:
            detail = "The Oratrice status endpoint was not found."
        elif 100 <= status_code <= 599:
            detail = f"Oratrice returned HTTP {status_code} while checking status."
        else:
            detail = "Oratrice returned an invalid HTTP status."
        state = "error"
        title = "Error"
    elif isinstance(error, StatusContractError):
        detail = "Oratrice returned an invalid status response."
        state = "error"
        title = "Error"
    elif isinstance(error, StatusClientError):
        detail = "Oratrice status could not be read. Retrying automatically."
        state = "error"
        title = "Error"
    else:
        detail = "Oratrice status could not be read. Retrying automatically."
        state = "error"
        title = "Error"

    return PetDisplayState(
        state=state,
        title=title,
        detail=detail,
        color=_STATE_COLORS[state],
    )


class PetController:
    """Single-worker, bounded status polling; all view calls stay on the UI thread."""

    def __init__(
        self,
        root,
        view,
        client: OratriceStatusClient,
        *,
        browser_open: Callable[[str], bool] | None = None,
        thread_factory=None,
    ) -> None:
        self._root = root
        self._view = view
        self._client = client
        self._browser_open = browser_open or webbrowser.open
        self._thread_factory = thread_factory or threading.Thread
        self._results: queue.Queue[_PollOutcome] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._started = False
        self._closed = False
        self._worker_active = False
        self._poll_after_id = None
        self._drain_after_id = None
        self._consecutive_failures = 0
        self._next_poll_delay_seconds = POLL_INTERVAL_SECONDS

    @property
    def worker_active(self) -> bool:
        with self._lock:
            return self._worker_active

    @property
    def next_poll_delay_seconds(self) -> float:
        return self._next_poll_delay_seconds

    def start(self) -> None:
        """Show a startup state and schedule one immediate status request."""

        if self._started or self._closed:
            return
        self._started = True
        self._view.update_status(
            PetDisplayState(
                state="starting",
                title="Connecting",
                detail="Checking the local Oratrice service.",
                color=_STATE_COLORS["starting"],
            )
        )
        self._schedule_poll(0.0)

    def open_chat(self) -> None:
        """Open the fixed same-origin UI URL only after a user activates the button."""

        if self._closed:
            return
        try:
            opened = self._browser_open(self._client.ui_url)
        except Exception:
            opened = False
        message = (
            "Oratrice chat opened in your browser."
            if opened
            else "The browser could not open Oratrice chat."
        )
        self._view.set_message(message)

    def close(self) -> None:
        """Stop this window's timers; never stop or signal the Oratrice service."""

        with self._lock:
            if self._closed:
                return
            self._closed = True

        for timer_id in (self._poll_after_id, self._drain_after_id):
            if timer_id is not None:
                try:
                    self._root.after_cancel(timer_id)
                except Exception:
                    pass
        self._poll_after_id = None
        self._drain_after_id = None

        try:
            self._results.get_nowait()
        except queue.Empty:
            pass
        self._root.destroy()

    def _schedule_poll(self, delay_seconds: float) -> None:
        if self._closed:
            return
        if self._poll_after_id is not None:
            try:
                self._root.after_cancel(self._poll_after_id)
            except Exception:
                pass
        self._next_poll_delay_seconds = max(0.0, delay_seconds)
        delay_ms = int(round(self._next_poll_delay_seconds * 1000))
        self._poll_after_id = self._root.after(delay_ms, self._poll_once)

    def _schedule_drain(self) -> None:
        if self._closed or self._drain_after_id is not None:
            return
        self._drain_after_id = self._root.after(
            RESULT_CHECK_INTERVAL_MS,
            self._drain_result,
        )

    def _poll_once(self) -> None:
        self._poll_after_id = None
        with self._lock:
            if self._closed or self._worker_active:
                return
            self._worker_active = True

        try:
            worker = self._thread_factory(target=self._poll_worker, daemon=True)
            worker.start()
        except Exception:
            with self._lock:
                self._worker_active = False
            self._publish(
                _PollOutcome(
                    display_for_error(StatusClientError("worker", "worker error")),
                    successful=False,
                )
            )
        self._schedule_drain()

    def _poll_worker(self) -> None:
        outcome = _PollOutcome(
            display_for_error(StatusClientError("worker", "worker error")),
            successful=False,
        )
        try:
            payload = self._client.fetch_status()
            outcome = _PollOutcome(display_for_status(payload), successful=True)
        except Exception as error:
            outcome = _PollOutcome(display_for_error(error), successful=False)
        finally:
            with self._lock:
                self._worker_active = False
                if not self._closed:
                    self._put_latest(outcome)

    def _publish(self, outcome: _PollOutcome) -> None:
        with self._lock:
            if self._closed:
                return
            self._put_latest(outcome)

    def _put_latest(self, outcome: _PollOutcome) -> None:
        try:
            self._results.put_nowait(outcome)
        except queue.Full:
            try:
                self._results.get_nowait()
            except queue.Empty:
                pass
            try:
                self._results.put_nowait(outcome)
            except queue.Full:
                pass

    def _drain_result(self) -> None:
        self._drain_after_id = None
        if self._closed:
            return

        try:
            outcome = self._results.get_nowait()
        except queue.Empty:
            if self.worker_active:
                self._schedule_drain()
            return

        self._view.update_status(outcome.display)
        if outcome.successful:
            self._consecutive_failures = 0
            delay_seconds = POLL_INTERVAL_SECONDS
        else:
            self._consecutive_failures = min(self._consecutive_failures + 1, 5)
            delay_seconds = min(
                POLL_INTERVAL_SECONDS * (2 ** (self._consecutive_failures - 1)),
                MAX_BACKOFF_SECONDS,
            )
        self._schedule_poll(delay_seconds)


def run_app(base_url: str = DEFAULT_BASE_URL) -> int:
    """Create the Tk window lazily so imports and --help stay side-effect free."""

    client = OratriceStatusClient(base_url)

    try:
        import tkinter as tk
    except ImportError:
        raise RuntimeError("Tk is required to run the Oratrice status window.") from None

    try:
        root = tk.Tk()
    except tk.TclError:
        raise RuntimeError("The Oratrice status window could not be created.") from None

    background = "#151a23"
    foreground = "#eef2f8"
    muted = "#b8c2d1"

    class TkPetView:
        def __init__(self, window) -> None:
            self._window = window
            window.title("Oratrice Status Pet")
            window.geometry("310x380")
            window.resizable(False, False)
            window.configure(background=background)

            self._canvas = tk.Canvas(
                window,
                width=286,
                height=190,
                background=background,
                highlightthickness=0,
                takefocus=False,
            )
            self._canvas.pack(padx=12, pady=(8, 0))
            self._halo = self._canvas.create_oval(
                54,
                7,
                232,
                185,
                fill=background,
                outline=_STATE_COLORS["starting"],
                width=5,
            )
            self._orb = self._canvas.create_oval(
                79,
                32,
                207,
                160,
                fill=_STATE_COLORS["starting"],
                outline="#f2f5fa",
                width=2,
            )
            self._canvas.create_oval(113, 76, 125, 88, fill="#ffffff", outline="")
            self._canvas.create_oval(161, 76, 173, 88, fill="#ffffff", outline="")
            self._canvas.create_arc(
                119,
                92,
                167,
                129,
                start=205,
                extent=130,
                style=tk.ARC,
                outline="#ffffff",
                width=3,
            )

            self._title = tk.Label(
                window,
                text="Connecting",
                background=background,
                foreground=foreground,
                font=("Segoe UI", 16, "bold"),
            )
            self._title.pack(pady=(2, 0))
            self._detail = tk.Label(
                window,
                text="Checking the local Oratrice service.",
                background=background,
                foreground=muted,
                font=("Segoe UI", 10),
                wraplength=274,
                justify="center",
            )
            self._detail.pack(padx=16, pady=(4, 12))
            buttons = tk.Frame(window, background=background)
            buttons.pack(pady=(0, 8))
            self._open_button = tk.Button(
                buttons,
                text="Open chat",
                underline=0,
                takefocus=True,
                padx=12,
                pady=4,
            )
            self._open_button.pack(side=tk.LEFT, padx=5)
            self._close_button = tk.Button(
                buttons,
                text="Close",
                underline=0,
                takefocus=True,
                padx=12,
                pady=4,
            )
            self._close_button.pack(side=tk.LEFT, padx=5)
            self._message = tk.Label(
                window,
                text="",
                background=background,
                foreground=muted,
                font=("Segoe UI", 9),
                wraplength=274,
                justify="center",
            )
            self._message.pack(padx=16, pady=(0, 8))

        def bind_actions(self, open_chat, close) -> None:
            self._open_button.configure(command=open_chat)
            self._close_button.configure(command=close)

        def update_status(self, display: PetDisplayState) -> None:
            self._title.configure(text=display.title, foreground=display.color)
            self._detail.configure(text=display.detail)
            self._canvas.itemconfigure(self._halo, outline=display.color)
            self._canvas.itemconfigure(self._orb, fill=display.color)

        def set_message(self, message: str) -> None:
            self._message.configure(text=message)

    view = TkPetView(root)
    controller = PetController(client=client, root=root, view=view)
    view.bind_actions(controller.open_chat, controller.close)
    root.protocol("WM_DELETE_WINDOW", controller.close)
    root.bind("<Escape>", lambda _event: controller.close())
    root.bind("<Alt-c>", lambda _event: controller.open_chat())
    controller.start()
    try:
        root.mainloop()
    finally:
        controller.close()
    return 0
