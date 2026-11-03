"""Read-only Windows process and memory snapshots for acceptance evidence.

Windows DLLs are loaded on first function call so this module remains safe to
import on non-Windows systems.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


# Windows process and snapshot constants.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002
_STILL_ACTIVE = 259
_ERROR_INVALID_PARAMETER = 87
_ERROR_NO_MORE_FILES = 18
_MAX_PATH = 260


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * _MAX_PATH),
    ]


_API = None


def _windows_api():
    """Load and configure Windows APIs only when a public function is called."""
    global _API
    if os.name != "nt":
        raise OSError("Windows required")

    if _API is None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE

        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL

        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL

        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

        kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessEntry32W),
        ]
        kernel32.Process32FirstW.restype = wintypes.BOOL

        kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessEntry32W),
        ]
        kernel32.Process32NextW.restype = wintypes.BOOL

        kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
        kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL

        _API = (kernel32, psapi)

    return _API


def _win_error(error_code: int | None = None) -> OSError:
    if error_code is None:
        error_code = ctypes.get_last_error()
    return ctypes.WinError(error_code)


def _gone(pid: int) -> dict:
    return {"pid": pid, "state": "gone"}


def _unknown(pid: int) -> dict:
    return {"pid": pid, "state": "unknown"}


def _handle_is_exited(api, handle) -> bool | None:
    """Return True/False for an exit query, or None when it could not be read."""
    exit_code = wintypes.DWORD()
    if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
        return None
    return exit_code.value != _STILL_ACTIVE


def _has_live_identity(record: dict) -> bool:
    created = record.get("created")
    return (
        record.get("state") == "running"
        and isinstance(created, int)
        and created > 0
    )


def process_identity(pid: int) -> dict:
    """Return a read-only identity and memory snapshot for a process.

    Access denial and query failures are reported as unknown. Only a confirmed
    missing PID or a process with a non-active exit code is gone.
    """
    pid = int(pid)
    kernel32, psapi = _windows_api()

    if pid < 0 or pid > 0xFFFFFFFF:
        return _gone(pid)

    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_INVALID_PARAMETER:
            return _gone(pid)
        return _unknown(pid)

    try:
        exit_state = _handle_is_exited(kernel32, handle)
        if exit_state is None:
            return _unknown(pid)
        if exit_state:
            return _gone(pid)

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            exit_state = _handle_is_exited(kernel32, handle)
            return _gone(pid) if exit_state is True else _unknown(pid)

        created = (int(creation.dwHighDateTime) << 32) | int(
            creation.dwLowDateTime
        )
        if created <= 0:
            return _unknown(pid)

        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            exit_state = _handle_is_exited(kernel32, handle)
            return _gone(pid) if exit_state is True else _unknown(pid)

        exit_state = _handle_is_exited(kernel32, handle)
        if exit_state is None:
            return _unknown(pid)
        if exit_state:
            return _gone(pid)

        return {
            "pid": pid,
            "state": "running",
            "created": created,
            "working_set_bytes": int(counters.WorkingSetSize),
            "private_bytes": int(counters.PrivateUsage),
        }
    finally:
        kernel32.CloseHandle(handle)


def process_tree(root_pid: int) -> list[dict]:
    """Return the root and verified live descendants from a Toolhelp snapshot.

    A child older than its live parent cannot belong to that parent instance,
    so its branch is excluded. If an ancestor identity is gone or unavailable,
    live descendants are retained as unknown rather than claimed as owned.
    Snapshot entries already gone are omitted; their children are still visited
    with unresolved ancestry.
    """
    root_pid = int(root_pid)
    kernel32, _ = _windows_api()

    ctypes.set_last_error(0)
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if not snapshot or snapshot == invalid_handle:
        raise _win_error()

    try:
        rows = []
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)

        ctypes.set_last_error(0)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise _win_error()

        while True:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ctypes.set_last_error(0)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                error_code = ctypes.get_last_error()
                if error_code == _ERROR_NO_MORE_FILES:
                    break
                raise _win_error(error_code)

        children = {}
        for pid, parent_pid in rows:
            children.setdefault(parent_pid, []).append(pid)

        identities = {}

        def identity(pid: int) -> dict:
            if pid not in identities:
                identities[pid] = process_identity(pid)
            return identities[pid]

        root = identity(root_pid)
        result = {root_pid: root}
        seen = {root_pid}
        queue = [(root_pid, _has_live_identity(root))]

        while queue:
            parent_pid, ancestry_verified = queue.pop(0)
            parent = identity(parent_pid)
            parent_verified = ancestry_verified and _has_live_identity(parent)

            for child_pid in children.get(parent_pid, ()):
                if child_pid in seen:
                    continue
                seen.add(child_pid)
                child = identity(child_pid)

                if child.get("state") == "gone":
                    # It may have exited after the snapshot. Any live child below
                    # it must retain an unknown ancestry gap.
                    queue.append((child_pid, False))
                    continue

                if (
                    _has_live_identity(parent)
                    and _has_live_identity(child)
                    and child["created"] < parent["created"]
                ):
                    # This is a different process that reused the parent's PID.
                    continue

                if not parent_verified:
                    result[child_pid] = _unknown(child_pid)
                    queue.append((child_pid, False))
                    continue

                if not _has_live_identity(child):
                    result[child_pid] = _unknown(child_pid)
                    queue.append((child_pid, False))
                    continue

                result[child_pid] = child
                queue.append((child_pid, True))

        return [result[pid] for pid in sorted(result)]
    finally:
        kernel32.CloseHandle(snapshot)


def memory_snapshot() -> dict:
    """Return physical memory and available commit bytes for this host."""
    kernel32, _ = _windows_api()
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)

    ctypes.set_last_error(0)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise _win_error()

    return {
        "available_physical_bytes": int(status.ullAvailPhys),
        "total_physical_bytes": int(status.ullTotalPhys),
        "available_commit_bytes": int(status.ullAvailPageFile),
    }