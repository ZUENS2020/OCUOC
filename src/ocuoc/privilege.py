from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from ocuoc.wm.processes import TOKEN_QUERY, TokenElevation, process_token_info
from ocuoc.winapi import kernel32, user32

advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001
DESKTOP_ENUMERATE = 0x0040


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HDESK
user32.GetThreadDesktop.argtypes = [wintypes.DWORD]
user32.GetThreadDesktop.restype = wintypes.HDESK
user32.GetUserObjectInformationW.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
user32.GetUserObjectInformationW.restype = wintypes.BOOL
user32.CloseDesktop.argtypes = [wintypes.HDESK]
user32.CloseDesktop.restype = wintypes.BOOL
user32.GetProcessWindowStation.argtypes = []
user32.GetProcessWindowStation.restype = wintypes.HWINSTA

advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.OpenProcessToken.restype = wintypes.BOOL
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.IsUserAnAdmin.argtypes = []
shell32.IsUserAnAdmin.restype = wintypes.BOOL


def _desktop_name(handle) -> str:
    if not handle:
        return ""
    needed = wintypes.DWORD(0)
    user32.GetUserObjectInformationW(handle, UOI_NAME, None, 0, ctypes.byref(needed))
    size = max(int(needed.value), 2)
    buf = ctypes.create_unicode_buffer(size // 2 + 1)
    if not user32.GetUserObjectInformationW(handle, UOI_NAME, buf, size, ctypes.byref(needed)):
        return ""
    return buf.value


def input_desktop_name() -> str:
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_ENUMERATE)
    if not handle:
        tid = kernel32.GetCurrentThreadId()
        return _desktop_name(user32.GetThreadDesktop(tid))
    try:
        return _desktop_name(handle)
    finally:
        user32.CloseDesktop(handle)


def current_desktop_name() -> str:
    tid = kernel32.GetCurrentThreadId()
    return _desktop_name(user32.GetThreadDesktop(tid))


def is_secure_desktop_name(name: str) -> bool:
    lowered = (name or "").lower()
    return lowered in {"winlogon", "saisecuredesktop"} or "winlogon" in lowered


def consent_running() -> bool:
    from ocuoc.wm.processes import snapshot_toolhelp

    return any(name.lower() == "consent.exe" for _pid, _ppid, name in snapshot_toolhelp())


@dataclass(frozen=True)
class PrivilegeInfo:
    elevated: bool
    integrity: str
    is_admin: bool
    input_desktop: str
    current_desktop: str
    uac_secure_desktop: bool

    def to_dict(self) -> dict:
        warning = None
        if not self.elevated:
            warning = "not elevated; UIPI may block input/capture of high-integrity windows"
        data = {
            "elevated": self.elevated,
            "integrity": self.integrity,
            "is_admin": self.is_admin,
            "input_desktop": self.input_desktop,
            "uac_secure_desktop": self.uac_secure_desktop,
        }
        if warning:
            data["warning"] = warning
        return data


def snapshot() -> PrivilegeInfo:
    try:
        integrity, elevated = process_token_info(int(kernel32.GetCurrentProcessId()))
    except Exception:
        integrity, elevated = "unknown", False
    is_admin = bool(shell32.IsUserAnAdmin())
    # IsUserAnAdmin is true for split-token admins even when not elevated.
    if not elevated:
        handle = kernel32.GetCurrentProcess()
        token = wintypes.HANDLE()
        if advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            try:
                needed = wintypes.DWORD(0)
                elev = TOKEN_ELEVATION()
                if advapi32.GetTokenInformation(
                    token, TokenElevation, ctypes.byref(elev), ctypes.sizeof(elev), ctypes.byref(needed)
                ):
                    elevated = bool(elev.TokenIsElevated)
            finally:
                kernel32.CloseHandle(token)
    incoming = input_desktop_name()
    current = current_desktop_name()
    secure = is_secure_desktop_name(incoming) or (
        consent_running() and incoming.lower() == "default" and not _consent_window_visible()
    )
    return PrivilegeInfo(
        elevated=bool(elevated),
        integrity=integrity,
        is_admin=is_admin,
        input_desktop=incoming or current,
        current_desktop=current,
        uac_secure_desktop=secure,
    )


def _consent_window_visible() -> bool:
    from ocuoc.wm.windows import iter_top_level_hwnds, snapshot

    for hwnd in iter_top_level_hwnds():
        info = snapshot(hwnd)
        if info is None:
            continue
        exe = (info.exe or "").lower()
        title = (info.title or "").lower()
        if exe.endswith("consent.exe") or "user account control" in title or "用户账户控制" in title:
            return True
    return False


# GetCurrentProcessId is used above; bind if missing.
if not hasattr(kernel32, "GetCurrentProcessId"):
    pass
kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = wintypes.DWORD
