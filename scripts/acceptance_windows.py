"""Read-only Windows process and memory snapshots for acceptance evidence.

Windows DLLs are loaded on first function call so this module remains safe to
import on non-Windows systems.
"""
from __future__ import annotations

import ctypes
import ipaddress
import os
import socket
from ctypes import wintypes


# Windows process and snapshot constants.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002
_STILL_ACTIVE = 259
_ERROR_INVALID_PARAMETER = 87
_ERROR_NO_MORE_FILES = 18
_MAX_PATH = 260

# IP Helper TCP table constants and bounds. The family values are Windows
# AF_* values, not the platform-dependent values exposed by socket.
_AF_INET = 2
_AF_INET6 = 23
_TCP_TABLE_OWNER_PID_LISTENER = 3
_TCP_STATE_LISTEN = 2
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_INVALID_DATA = 13
_MAX_TCP_TABLE_BYTES = 16 * 1024 * 1024
_MAX_TCP_TABLE_ATTEMPTS = 3
_DWORD = ctypes.c_uint32


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


class _TcpRowOwnerPid(ctypes.Structure):
    """MIB_TCPROW_OWNER_PID, with Windows DWORD-sized fields."""

    _fields_ = [
        ("dwState", _DWORD),
        ("dwLocalAddr", _DWORD),
        ("dwLocalPort", _DWORD),
        ("dwRemoteAddr", _DWORD),
        ("dwRemotePort", _DWORD),
        ("dwOwningPid", _DWORD),
    ]


class _Tcp6RowOwnerPid(ctypes.Structure):
    """MIB_TCP6ROW_OWNER_PID, in the order declared by iphlpapi.h."""

    _fields_ = [
        ("ucLocalAddr", ctypes.c_ubyte * 16),
        ("dwLocalScopeId", _DWORD),
        ("dwLocalPort", _DWORD),
        ("ucRemoteAddr", ctypes.c_ubyte * 16),
        ("dwRemoteScopeId", _DWORD),
        ("dwRemotePort", _DWORD),
        ("dwState", _DWORD),
        ("dwOwningPid", _DWORD),
    ]


_API = None
_LISTENER_API = None


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


def _listener_windows_api():
    """Load IP Helper only when a listener snapshot is requested."""
    global _LISTENER_API
    if os.name != "nt":
        raise OSError("Windows required")

    if _LISTENER_API is None:
        iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
        get_table = iphlpapi.GetExtendedTcpTable
        get_table.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_DWORD),
            ctypes.c_int32,
            _DWORD,
            ctypes.c_int32,
            _DWORD,
        ]
        get_table.restype = _DWORD
        _LISTENER_API = iphlpapi

    return _LISTENER_API


def _tcp_table_error(error_code: int, message: str) -> OSError:
    return OSError(int(error_code), message)


def _checked_tcp_table_size(size: int) -> int:
    if size < ctypes.sizeof(_DWORD):
        raise _tcp_table_error(
            _ERROR_INVALID_DATA, "GetExtendedTcpTable returned an invalid size"
        )
    if size > _MAX_TCP_TABLE_BYTES:
        raise _tcp_table_error(
            _ERROR_INSUFFICIENT_BUFFER,
            "GetExtendedTcpTable table exceeds the 16 MiB safety limit",
        )
    return size


def _read_tcp_listener_table(
    api, family: int, row_type
) -> list[dict[str, str | int]]:
    """Read one owner-PID listener table, retrying bounded table growth."""
    required_size = _DWORD(0)
    result = api.GetExtendedTcpTable(
        None,
        ctypes.byref(required_size),
        0,
        family,
        _TCP_TABLE_OWNER_PID_LISTENER,
        0,
    )
    if result == 0 and required_size.value == 0:
        return []
    if result not in (0, _ERROR_INSUFFICIENT_BUFFER):
        raise _tcp_table_error(
            result, "GetExtendedTcpTable size query failed"
        )

    allocation_size = _checked_tcp_table_size(int(required_size.value))
    row_size = ctypes.sizeof(row_type)
    header_size = ctypes.sizeof(_DWORD)

    for _ in range(_MAX_TCP_TABLE_ATTEMPTS):
        buffer = ctypes.create_string_buffer(allocation_size)
        buffer_size = _DWORD(allocation_size)
        result = api.GetExtendedTcpTable(
            buffer,
            ctypes.byref(buffer_size),
            0,
            family,
            _TCP_TABLE_OWNER_PID_LISTENER,
            0,
        )
        if result == 0:
            returned_size = int(buffer_size.value)
            if returned_size > allocation_size:
                raise _tcp_table_error(
                    _ERROR_INVALID_DATA,
                    "GetExtendedTcpTable returned a size larger than its buffer",
                )
            readable_size = returned_size or allocation_size
            if readable_size < header_size:
                raise _tcp_table_error(
                    _ERROR_INVALID_DATA,
                    "GetExtendedTcpTable returned a truncated table header",
                )

            entry_count = int(_DWORD.from_buffer(buffer).value)
            table_size = header_size + entry_count * row_size
            if table_size > readable_size:
                raise _tcp_table_error(
                    _ERROR_INVALID_DATA,
                    "GetExtendedTcpTable returned a truncated row table",
                )

            listeners = []
            for index in range(entry_count):
                offset = header_size + index * row_size
                row = row_type.from_buffer(buffer, offset)
                if int(row.dwState) != _TCP_STATE_LISTEN:
                    continue

                if family == _AF_INET:
                    address_bytes = ctypes.string_at(
                        ctypes.addressof(row) + row_type.dwLocalAddr.offset, 4
                    )
                    address = str(ipaddress.IPv4Address(address_bytes))
                else:
                    address_bytes = bytes(row.ucLocalAddr)
                    address = str(ipaddress.IPv6Address(address_bytes))
                    scope_id = int(row.dwLocalScopeId)
                    if scope_id:
                        address = f"{address}%{scope_id}"

                listeners.append(
                    {
                        "address": address,
                        "port": socket.ntohs(int(row.dwLocalPort) & 0xFFFF),
                        "pid": int(row.dwOwningPid),
                    }
                )
            return listeners

        if result != _ERROR_INSUFFICIENT_BUFFER:
            raise _tcp_table_error(
                result, "GetExtendedTcpTable listener query failed"
            )
        allocation_size = _checked_tcp_table_size(int(buffer_size.value))

    raise _tcp_table_error(
        _ERROR_INSUFFICIENT_BUFFER,
        "TCP listener table kept changing after three buffer attempts",
    )


def listener_snapshot() -> list[dict[str, str | int]]:
    """Return IPv4 and IPv6 TCP listeners as address, port, and owning PID."""
    api = _listener_windows_api()
    return _read_tcp_listener_table(
        api, _AF_INET, _TcpRowOwnerPid
    ) + _read_tcp_listener_table(api, _AF_INET6, _Tcp6RowOwnerPid)
