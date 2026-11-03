"""Offline tests for the Windows acceptance evidence helpers."""

import ctypes
import ipaddress
import socket
from ctypes import wintypes

import pytest

from scripts import acceptance_windows as windows


def _set_filetime(pointer, value):
    filetime = ctypes.cast(pointer, ctypes.POINTER(wintypes.FILETIME)).contents
    filetime.dwLowDateTime = value & 0xFFFFFFFF
    filetime.dwHighDateTime = value >> 32


class FakeIdentityKernel32:
    def __init__(self, errors, *, exit_codes=(259,), open_error=None, created=1234):
        self.errors = errors
        self.exit_codes = list(exit_codes)
        self.open_error = open_error
        self.created = created
        self.closed = []
        self.OpenProcess = self.open_process
        self.GetExitCodeProcess = self.get_exit_code
        self.GetProcessTimes = self.get_process_times
        self.CloseHandle = self.close_handle

    def open_process(self, access, inherit, pid):
        if self.open_error is not None:
            self.errors["value"] = self.open_error
            return None
        return 4321

    def get_exit_code(self, handle, output):
        response = self.exit_codes.pop(0)
        if response is None:
            self.errors["value"] = 5
            return 0
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = response
        return 1

    def get_process_times(self, handle, creation, exit_time, kernel_time, user_time):
        _set_filetime(creation, self.created)
        return 1

    def close_handle(self, handle):
        self.closed.append(handle)
        return 1


class FakePsapi:
    def __init__(self, *, working_set=0, private=0):
        self.working_set = working_set
        self.private = private
        self.GetProcessMemoryInfo = self.get_process_memory_info

    def get_process_memory_info(self, handle, counters_pointer, size):
        counters = ctypes.cast(
            counters_pointer, ctypes.POINTER(windows._ProcessMemoryCounters)
        ).contents
        counters.WorkingSetSize = self.working_set
        counters.PrivateUsage = self.private
        return 1


def _install_fake_apis(monkeypatch, kernel32, psapi, errors):
    monkeypatch.setattr(windows, "_windows_api", lambda: (kernel32, psapi))
    monkeypatch.setattr(
        windows.ctypes,
        "set_last_error",
        lambda value: errors.__setitem__("value", value),
        raising=False,
    )
    monkeypatch.setattr(
        windows.ctypes,
        "get_last_error",
        lambda: errors["value"],
        raising=False,
    )


def test_access_denied_open_is_unknown_not_gone(monkeypatch):
    errors = {"value": 0}
    kernel32 = FakeIdentityKernel32(errors, open_error=5)
    _install_fake_apis(monkeypatch, kernel32, FakePsapi(), errors)

    assert windows.process_identity(123) == {"pid": 123, "state": "unknown"}
    assert kernel32.closed == []


@pytest.mark.parametrize("exit_codes", [(None,), (259, None)])
def test_failed_exit_queries_are_unknown_and_close_handle(monkeypatch, exit_codes):
    errors = {"value": 0}
    kernel32 = FakeIdentityKernel32(errors, exit_codes=exit_codes)
    _install_fake_apis(
        monkeypatch,
        kernel32,
        FakePsapi(working_set=8192, private=4096),
        errors,
    )

    assert windows.process_identity(123) == {"pid": 123, "state": "unknown"}
    assert kernel32.closed == [4321]


def test_identity_reports_memory_counters_and_closes_handle(monkeypatch):
    errors = {"value": 0}
    created = 0x1234567812345678
    kernel32 = FakeIdentityKernel32(errors, exit_codes=(259, 259), created=created)
    psapi = FakePsapi(working_set=8192, private=4096)
    _install_fake_apis(monkeypatch, kernel32, psapi, errors)

    assert windows.process_identity(123) == {
        "pid": 123,
        "state": "running",
        "created": created,
        "working_set_bytes": 8192,
        "private_bytes": 4096,
    }
    assert kernel32.closed == [4321]


class FakeToolhelpKernel32:
    def __init__(self, rows, errors):
        self.rows = list(rows)
        self.errors = errors
        self.index = 0
        self.closed = []
        self.CreateToolhelp32Snapshot = self.create_snapshot
        self.Process32FirstW = self.first
        self.Process32NextW = self.next
        self.CloseHandle = self.close_handle

    def create_snapshot(self, flags, pid):
        return 8765

    def _write_entry(self, pointer):
        entry = ctypes.cast(
            pointer, ctypes.POINTER(windows._ProcessEntry32W)
        ).contents
        entry.th32ProcessID, entry.th32ParentProcessID = self.rows[self.index]
        self.index += 1

    def first(self, snapshot, pointer):
        if not self.rows:
            self.errors["value"] = windows._ERROR_NO_MORE_FILES
            return 0
        self.index = 0
        self._write_entry(pointer)
        return 1

    def next(self, snapshot, pointer):
        if self.index >= len(self.rows):
            self.errors["value"] = windows._ERROR_NO_MORE_FILES
            return 0
        self._write_entry(pointer)
        return 1

    def close_handle(self, handle):
        self.closed.append(handle)
        return 1


@pytest.mark.parametrize(
    ("parent_record", "expected"),
    [
        (
            {"pid": 200, "state": "unknown"},
            [
                {"pid": 100, "state": "running", "created": 100},
                {"pid": 200, "state": "unknown"},
                {"pid": 300, "state": "unknown"},
            ],
        ),
        (
            {"pid": 200, "state": "gone"},
            [
                {"pid": 100, "state": "running", "created": 100},
                {"pid": 300, "state": "unknown"},
            ],
        ),
    ],
)
def test_unverifiable_parent_leaves_unknown_descendant_gap(
    monkeypatch, parent_record, expected
):
    errors = {"value": 0}
    kernel32 = FakeToolhelpKernel32([(100, 1), (200, 100), (300, 200)], errors)
    _install_fake_apis(monkeypatch, kernel32, FakePsapi(), errors)
    identities = {
        100: {"pid": 100, "state": "running", "created": 100},
        200: parent_record,
        300: {"pid": 300, "state": "running", "created": 300},
    }
    monkeypatch.setattr(
        windows,
        "process_identity",
        lambda pid: dict(identities.get(pid, {"pid": pid, "state": "gone"})),
    )

    assert windows.process_tree(100) == expected
    assert kernel32.closed == [8765]


def test_parent_pid_reuse_excludes_older_process_and_its_branch(monkeypatch):
    errors = {"value": 0}
    rows = [(100, 1), (200, 100), (210, 200), (300, 100), (400, 300)]
    kernel32 = FakeToolhelpKernel32(rows, errors)
    _install_fake_apis(monkeypatch, kernel32, FakePsapi(), errors)
    identities = {
        100: {"pid": 100, "state": "running", "created": 100},
        200: {"pid": 200, "state": "running", "created": 200},
        210: {"pid": 210, "state": "running", "created": 250},
        # PID 300 predates parent 100 and therefore belongs to another parent instance.
        300: {"pid": 300, "state": "running", "created": 90},
        400: {"pid": 400, "state": "running", "created": 400},
    }
    monkeypatch.setattr(
        windows,
        "process_identity",
        lambda pid: dict(identities.get(pid, {"pid": pid, "state": "gone"})),
    )

    assert windows.process_tree(100) == [
        identities[100],
        identities[200],
        identities[210],
    ]
    assert kernel32.closed == [8765]


def test_memory_snapshot_maps_windows_memory_counters(monkeypatch):
    errors = {"value": 0}

    class MemoryKernel32:
        def __init__(self):
            self.GlobalMemoryStatusEx = self.global_memory_status_ex

        def global_memory_status_ex(self, pointer):
            status = ctypes.cast(
                pointer, ctypes.POINTER(windows._MemoryStatusEx)
            ).contents
            assert status.dwLength == ctypes.sizeof(status)
            status.ullAvailPhys = 1000
            status.ullTotalPhys = 4000
            status.ullAvailPageFile = 2000
            return 1

    kernel32 = MemoryKernel32()
    _install_fake_apis(monkeypatch, kernel32, FakePsapi(), errors)

    assert windows.memory_snapshot() == {
        "available_physical_bytes": 1000,
        "total_physical_bytes": 4000,
        "available_commit_bytes": 2000,
    }


def _tcp_row(row_type, address, port, pid, *, scope_id=0):
    row = row_type()
    row.dwState = windows._TCP_STATE_LISTEN
    packed_address = ipaddress.ip_address(address).packed
    address_field = "dwLocalAddr" if len(packed_address) == 4 else "ucLocalAddr"
    ctypes.memmove(
        ctypes.addressof(row) + getattr(row_type, address_field).offset,
        packed_address,
        len(packed_address),
    )
    if len(packed_address) == 16:
        row.dwLocalScopeId = scope_id
    row.dwLocalPort = socket.htons(port)
    row.dwOwningPid = pid
    return bytes(row)


def _tcp_table(*rows):
    return bytes(windows._DWORD(len(rows))) + b"".join(rows)


class FakeIphlpapi:
    def __init__(
        self,
        tables,
        *,
        errors=None,
        initial_size_overrides=None,
        growth_retries=None,
    ):
        self.tables = dict(tables)
        self.errors = dict(errors or {})
        self.initial_size_overrides = dict(initial_size_overrides or {})
        self.growth_retries = dict(growth_retries or {})
        self.calls = []
        self.free_calls = []
        self.GetExtendedTcpTable = self.get_extended_tcp_table
        self.FreeMibTable = self.free_mib_table

    def get_extended_tcp_table(
        self, table_pointer, size_pointer, ordered, family, table_class, reserved
    ):
        size = ctypes.cast(
            size_pointer, ctypes.POINTER(windows._DWORD)
        ).contents
        self.calls.append(
            (
                table_pointer is None,
                family,
                int(size.value),
                ordered,
                table_class,
                reserved,
            )
        )
        if family in self.errors:
            return self.errors[family]

        table = self.tables.get(family, _tcp_table())
        if table_pointer is None:
            size.value = self.initial_size_overrides.get(family, len(table))
            return windows._ERROR_INSUFFICIENT_BUFFER

        remaining_growth = self.growth_retries.get(family, 0)
        if remaining_growth:
            self.growth_retries[family] = remaining_growth - 1
            size.value = max(int(size.value) + 1, len(table) + 1)
            return windows._ERROR_INSUFFICIENT_BUFFER

        if size.value < len(table):
            size.value = len(table)
            return windows._ERROR_INSUFFICIENT_BUFFER

        ctypes.memmove(table_pointer, table, len(table))
        size.value = len(table)
        return 0

    def free_mib_table(self, *args):
        self.free_calls.append(args)


def _install_fake_iphlpapi(monkeypatch, api):
    monkeypatch.setattr(windows, "_listener_windows_api", lambda: api)


def test_listener_snapshot_reads_ipv4_and_ipv6_owner_pid_rows(monkeypatch):
    api = FakeIphlpapi(
        {
            windows._AF_INET: _tcp_table(
                _tcp_row(windows._TcpRowOwnerPid, "0.0.0.0", 8000, 41),
                _tcp_row(windows._TcpRowOwnerPid, "127.0.0.1", 8080, 42),
            ),
            windows._AF_INET6: _tcp_table(
                _tcp_row(windows._Tcp6RowOwnerPid, "::1", 8090, 43)
            ),
        }
    )
    _install_fake_iphlpapi(monkeypatch, api)

    assert windows.listener_snapshot() == [
        {"address": "0.0.0.0", "port": 8000, "pid": 41},
        {"address": "127.0.0.1", "port": 8080, "pid": 42},
        {"address": "::1", "port": 8090, "pid": 43},
    ]
    assert [call[1] for call in api.calls if call[0]] == [
        windows._AF_INET,
        windows._AF_INET6,
    ]
    assert all(
        call[3:] == (0, windows._TCP_TABLE_OWNER_PID_LISTENER, 0)
        for call in api.calls
    )
    assert api.free_calls == []


def test_listener_snapshot_raises_on_ip_helper_errors_without_free(monkeypatch):
    api = FakeIphlpapi({}, errors={windows._AF_INET: 5})
    _install_fake_iphlpapi(monkeypatch, api)

    with pytest.raises(OSError) as error:
        windows.listener_snapshot()

    assert error.value.errno == 5
    assert api.free_calls == []


def test_listener_snapshot_retries_buffer_growth(monkeypatch):
    api = FakeIphlpapi(
        {
            windows._AF_INET: _tcp_table(
                _tcp_row(windows._TcpRowOwnerPid, "127.0.0.1", 8000, 51)
            )
        },
        growth_retries={windows._AF_INET: 1},
    )
    _install_fake_iphlpapi(monkeypatch, api)

    assert windows.listener_snapshot() == [
        {"address": "127.0.0.1", "port": 8000, "pid": 51}
    ]
    assert sum(not call[0] and call[1] == windows._AF_INET for call in api.calls) == 2


def test_listener_snapshot_caps_growth_retries_and_buffer_size(monkeypatch):
    growing = FakeIphlpapi(
        {windows._AF_INET: _tcp_table()},
        growth_retries={windows._AF_INET: 10},
    )
    _install_fake_iphlpapi(monkeypatch, growing)

    with pytest.raises(OSError) as retry_error:
        windows.listener_snapshot()

    assert retry_error.value.errno == windows._ERROR_INSUFFICIENT_BUFFER
    assert (
        sum(
            not call[0] and call[1] == windows._AF_INET
            for call in growing.calls
        )
        == 3
    )
    assert growing.free_calls == []

    oversized = FakeIphlpapi(
        {windows._AF_INET: _tcp_table()},
        initial_size_overrides={
            windows._AF_INET: windows._MAX_TCP_TABLE_BYTES + 1
        },
    )
    _install_fake_iphlpapi(monkeypatch, oversized)

    with pytest.raises(OSError) as size_error:
        windows.listener_snapshot()

    assert size_error.value.errno == windows._ERROR_INSUFFICIENT_BUFFER
    assert len(oversized.calls) == 1
    assert oversized.free_calls == []
