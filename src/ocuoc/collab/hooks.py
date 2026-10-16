from __future__ import annotations

import ctypes
import threading
from ctypes import POINTER, cast, wintypes

from ocuoc.winapi import (
    HOOKPROC,
    KBDLLHOOKSTRUCT,
    MSLLHOOKSTRUCT,
    PM_NOREMOVE,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    WM_QUIT,
    kernel32,
    user32,
)


class InputHooks:
    def __init__(self, collab) -> None:
        self._collab = collab
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._kbd_hook = None
        self._mouse_hook = None
        self._kbd_proc = None
        self._mouse_proc = None
        self._ready = threading.Event()

    @property
    def alive(self) -> bool:
        return bool(self._kbd_hook or self._mouse_hook)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="ocuoc-llhooks", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._tid = 0

    def _loop(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

        def _kbd(ncode, wparam, lparam):
            swallow = False
            if ncode >= 0 and lparam:
                info = cast(lparam, POINTER(KBDLLHOOKSTRUCT)).contents
                swallow = self._collab.handle_key(
                    int(info.flags),
                    int(info.vkCode),
                    int(wparam),
                    int(info.dwExtraInfo),
                )
            if swallow:
                return 1
            return user32.CallNextHookEx(self._kbd_hook, ncode, wparam, lparam)

        def _mouse(ncode, wparam, lparam):
            if ncode >= 0 and lparam:
                info = cast(lparam, POINTER(MSLLHOOKSTRUCT)).contents
                hit = user32.WindowFromPoint(info.pt)
                pid = wintypes.DWORD(0)
                if hit:
                    user32.GetWindowThreadProcessId(hit, ctypes.byref(pid))
                self._collab.handle_mouse(
                    int(info.flags),
                    int(wparam),
                    int(hit or 0),
                    int(pid.value),
                    int(info.dwExtraInfo),
                )
            return user32.CallNextHookEx(self._mouse_hook, ncode, wparam, lparam)

        self._kbd_proc = HOOKPROC(_kbd)
        self._mouse_proc = HOOKPROC(_mouse)
        self._kbd_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kbd_proc, None, 0)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc, None, 0)
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._kbd_hook:
            user32.UnhookWindowsHookEx(self._kbd_hook)
            self._kbd_hook = None
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
