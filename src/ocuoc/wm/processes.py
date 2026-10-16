from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from ocuoc.winapi import PROCESS_QUERY_LIMITED_INFORMATION, kernel32

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
TOKEN_QUERY = 0x0008
TokenElevation = 20
TokenIntegrityLevel = 25
ProcessCommandLineInformation = 60
MAX_PATH = 260

SECURITY_MANDATORY_UNTRUSTED_RID = 0x0000
SECURITY_MANDATORY_LOW_RID = 0x1000
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SECURITY_MANDATORY_HIGH_RID = 0x3000
SECURITY_MANDATORY_SYSTEM_RID = 0x4000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class WTS_PROCESS_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("ProcessId", wintypes.DWORD),
        ("pProcessName", wintypes.LPWSTR),
        ("pUserSid", ctypes.c_void_p),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.GetCurrentProcess.argtypes = []
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
advapi32.GetTokenInformation.restype = wintypes.BOOL
advapi32.LookupAccountSidW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(ctypes.c_int),
]
advapi32.LookupAccountSidW.restype = wintypes.BOOL
advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
advapi32.GetSidSubAuthority.restype = ctypes.c_void_p
advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
advapi32.GetSidSubAuthorityCount.restype = ctypes.c_void_p

ntdll.NtQueryInformationProcess.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long

wtsapi32.WTSEnumerateProcessesW.argtypes = [
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
]
wtsapi32.WTSEnumerateProcessesW.restype = wintypes.BOOL
wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
wtsapi32.WTSFreeMemory.restype = None


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    name: str
    exe: str = ""
    session_id: int = 0
    user: str = ""
    integrity: str = "unknown"
    elevated: bool = False
    cmdline: str = ""


def _integrity_name(rid: int) -> str:
    if rid >= SECURITY_MANDATORY_SYSTEM_RID:
        return "system"
    if rid >= SECURITY_MANDATORY_HIGH_RID:
        return "high"
    if rid >= SECURITY_MANDATORY_MEDIUM_RID:
        return "medium"
    if rid >= SECURITY_MANDATORY_LOW_RID:
        return "low"
    return "untrusted"


def _lookup_sid(sid: int | None) -> str:
    if not sid:
        return ""
    name_cch = wintypes.DWORD(256)
    domain_cch = wintypes.DWORD(256)
    name = ctypes.create_unicode_buffer(256)
    domain = ctypes.create_unicode_buffer(256)
    use = ctypes.c_int(0)
    if not advapi32.LookupAccountSidW(
        None, ctypes.c_void_p(sid), name, ctypes.byref(name_cch), domain, ctypes.byref(domain_cch), ctypes.byref(use)
    ):
        return ""
    if domain.value:
        return f"{domain.value}\\{name.value}"
    return name.value


def _open_process(pid: int):
    return kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)


def process_image_path(pid: int) -> str:
    handle = _open_process(pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def process_token_info(pid: int) -> tuple[str, bool]:
    handle = _open_process(pid)
    if not handle:
        return "unknown", False
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return "unknown", False
        integrity = "unknown"
        elevated = False
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TokenElevation, None, 0, ctypes.byref(needed))
        if needed.value:
            elev = TOKEN_ELEVATION()
            if advapi32.GetTokenInformation(
                token, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(needed)
            ):
                elevated = bool(elev.TokenIsElevated)
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TokenIntegrityLevel, None, 0, ctypes.byref(needed))
        if needed.value:
            buf = ctypes.create_string_buffer(needed.value)
            if advapi32.GetTokenInformation(token, TokenIntegrityLevel, buf, needed.value, ctypes.byref(needed)):
                try:
                    label = TOKEN_MANDATORY_LABEL.from_buffer(buf)
                    sid = label.Label.Sid
                    count_addr = advapi32.GetSidSubAuthorityCount(sid)
                    if count_addr:
                        count = ctypes.c_ubyte.from_address(int(count_addr)).value
                        rid_addr = advapi32.GetSidSubAuthority(sid, count - 1)
                        if rid_addr:
                            rid = wintypes.DWORD.from_address(int(rid_addr)).value
                            integrity = _integrity_name(int(rid))
                except Exception:
                    integrity = "unknown"
        return integrity, elevated
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(handle)


def process_command_line(pid: int) -> str:
    handle = _open_process(pid)
    if not handle:
        return ""
    try:
        retlen = wintypes.ULONG(0)
        status = ntdll.NtQueryInformationProcess(handle, ProcessCommandLineInformation, None, 0, ctypes.byref(retlen))
        # STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
        if retlen.value == 0 and status != 0:
            return ""
        size = max(int(retlen.value), 16)
        buf = ctypes.create_string_buffer(size)
        status = ntdll.NtQueryInformationProcess(handle, ProcessCommandLineInformation, buf, size, ctypes.byref(retlen))
        if status != 0:
            return ""
        us = UNICODE_STRING.from_buffer_copy(buf[: ctypes.sizeof(UNICODE_STRING)])
        if us.Length == 0:
            return ""
        nchars = us.Length // 2
        try:
            if us.Buffer:
                return ctypes.wstring_at(us.Buffer, nchars)
        except Exception:
            pass
        offset = ctypes.sizeof(UNICODE_STRING)
        return ctypes.wstring_at(ctypes.addressof(buf) + offset, nchars)
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(handle)


def snapshot_toolhelp() -> list[tuple[int, int, str]]:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        rows: list[tuple[int, int, str]] = []
        while True:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return rows
    finally:
        kernel32.CloseHandle(snap)


def wts_process_users() -> dict[int, tuple[int, str, str]]:
    """pid -> (session_id, process_name, user)."""
    ptr = ctypes.c_void_p()
    count = wintypes.DWORD(0)
    if not wtsapi32.WTSEnumerateProcessesW(None, 0, 1, ctypes.byref(ptr), ctypes.byref(count)):
        return {}
    try:
        arr = ctypes.cast(ptr, ctypes.POINTER(WTS_PROCESS_INFOW))
        out: dict[int, tuple[int, str, str]] = {}
        for i in range(int(count.value)):
            item = arr[i]
            name = item.pProcessName or ""
            out[int(item.ProcessId)] = (int(item.SessionId), name, _lookup_sid(item.pUserSid))
        return out
    finally:
        wtsapi32.WTSFreeMemory(ptr)


def descendant_pids(root_pid: int, rows: list[tuple[int, int, str]] | None = None) -> set[int]:
    rows = rows if rows is not None else snapshot_toolhelp()
    children: dict[int, list[int]] = {}
    for pid, ppid, _name in rows:
        children.setdefault(ppid, []).append(pid)
    found: set[int] = set()
    stack = list(children.get(root_pid, []))
    while stack:
        pid = stack.pop()
        if pid in found or pid == root_pid:
            continue
        found.add(pid)
        stack.extend(children.get(pid, []))
    return found


def identity_for_pid(pid: int, users: dict[int, tuple[int, str, str]] | None = None) -> tuple[str, str, bool]:
    users = users if users is not None else wts_process_users()
    user = users.get(pid, (0, "", ""))[2]
    integrity, elevated = process_token_info(pid)
    return user, integrity, elevated


def exe_stem(path: str) -> str:
    if not path:
        return ""
    return Path(path).stem.lower()
