from __future__ import annotations

import ctypes
from ctypes import wintypes

from ocuoc.winapi import user32

HMONITOR = ctypes.c_void_p
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
)
MONITORINFOF_PRIMARY = 1


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [HMONITOR, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL


def list_displays() -> list[dict]:
    found: list[int] = []

    @MONITORENUMPROC
    def callback(hmon, _hdc, _lprc, _lp):  # type: ignore[misc]
        found.append(int(hmon) if hmon else 0)
        return True

    user32.EnumDisplayMonitors(None, None, callback, 0)
    displays: list[dict] = []
    for handle in found:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(ctypes.c_void_p(handle), ctypes.byref(info)):
            continue
        mon = info.rcMonitor
        work = info.rcWork
        displays.append(
            {
                "id": handle,
                "device": info.szDevice,
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                "bounds": {
                    "left": int(mon.left),
                    "top": int(mon.top),
                    "right": int(mon.right),
                    "bottom": int(mon.bottom),
                    "width": int(mon.right - mon.left),
                    "height": int(mon.bottom - mon.top),
                },
                "work": {
                    "left": int(work.left),
                    "top": int(work.top),
                    "right": int(work.right),
                    "bottom": int(work.bottom),
                },
            }
        )
    displays.sort(key=lambda d: (not d["primary"], d["bounds"]["left"], d["bounds"]["top"]))
    return displays
