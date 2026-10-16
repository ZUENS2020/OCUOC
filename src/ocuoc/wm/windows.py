from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from ocuoc.errors import EngineError
from ocuoc.generation import make_generation, make_window_id, parse_window_id
from ocuoc.winapi import (
    DWMWA_CLOAKED,
    GA_ROOT,
    PROCESS_QUERY_LIMITED_INFORMATION,
    SKIP_CLASSES,
    SW_RESTORE,
    WNDENUMPROC,
    WM_CLOSE,
    dwmapi,
    hwnd_int,
    kernel32,
    user32,
)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe: str
    class_name: str
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    user: str = ""
    integrity: str = "unknown"
    elevated: bool = False

    @property
    def window_id(self) -> str:
        return make_window_id(self.hwnd)

    @property
    def generation(self) -> str:
        return make_generation(self.hwnd, self.title, self.rect, self.class_name)

    def to_dict(self) -> dict:
        left, top, right, bottom = self.rect
        cl, ct, cr, cb = self.client_rect
        return {
            "window_id": self.window_id,
            "title": self.title,
            "pid": self.pid,
            "exe": self.exe,
            "class_name": self.class_name,
            "bounds": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": right - left,
                "height": bottom - top,
            },
            "client_bounds": {
                "left": cl,
                "top": ct,
                "right": cr,
                "bottom": cb,
                "width": cr - cl,
                "height": cb - ct,
            },
            "generation": self.generation,
            "user": self.user,
            "integrity": self.integrity,
            "elevated": self.elevated,
        }


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    rc = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return (0, 0, 0, 0)
    return (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))


def _client_rect(hwnd: int) -> tuple[int, int, int, int]:
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return (0, 0, 0, 0)
    top_left = wintypes.POINT(rc.left, rc.top)
    bottom_right = wintypes.POINT(rc.right, rc.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return (0, 0, 0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(bottom_right))
    return (int(top_left.x), int(top_left.y), int(bottom_right.x), int(bottom_right.y))


def _pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _exe(pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
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


def _cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD(0)
    hr = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), 4)
    return hr == 0 and value.value != 0


def _is_top_level(hwnd: int) -> bool:
    root = hwnd_int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    return root == hwnd_int(hwnd)


def iter_top_level_hwnds() -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):  # type: ignore[misc]
        found.append(hwnd_int(hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return found


def snapshot(hwnd: int, identity: tuple[str, str, bool] | None = None) -> WindowInfo | None:
    if not user32.IsWindow(hwnd):
        return None
    title = _title(hwnd)
    class_name = _class_name(hwnd)
    rect = _rect(hwnd)
    client_rect = _client_rect(hwnd)
    pid = _pid(hwnd)
    user, integrity, elevated = identity if identity is not None else ("", "unknown", False)
    return WindowInfo(
        hwnd=hwnd_int(hwnd),
        title=title,
        pid=pid,
        exe=_exe(pid),
        class_name=class_name,
        rect=rect,
        client_rect=client_rect,
        user=user,
        integrity=integrity,
        elevated=elevated,
    )


def child_hwnds(hwnd: int) -> list[int]:
    found: list[int] = []

    @WNDENUMPROC
    def callback(child, _lparam):  # type: ignore[misc]
        found.append(hwnd_int(child))
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return found


def child_class_names(hwnd: int, limit: int = 40) -> list[str]:
    names: list[str] = []
    for child in child_hwnds(hwnd)[:limit]:
        names.append(_class_name(child))
    return names


def _keep_window(info: WindowInfo) -> bool:
    if info.class_name.lower() in SKIP_CLASSES:
        return False
    left, top, right, bottom = info.rect
    if left <= -10000 or top <= -10000:
        return False
    if user32.IsIconic(info.hwnd):
        return False
    width, height = right - left, bottom - top
    title = info.title.strip()
    title_l = title.lower()
    if "steam" in title_l:
        return width >= 24 and height >= 24
    if width < 24 or height < 24:
        return False
    if not title and not info.exe:
        return False
    if not title and (width < 80 or height < 80):
        return False
    return True


def list_windows() -> list[WindowInfo]:
    from ocuoc.wm.processes import identity_for_pid, wts_process_users

    users = wts_process_users()
    ident_cache: dict[int, tuple[str, str, bool]] = {}
    out: list[WindowInfo] = []
    for hwnd in iter_top_level_hwnds():
        if not user32.IsWindowVisible(hwnd):
            continue
        if not _is_top_level(hwnd):
            continue
        if _cloaked(hwnd):
            continue
        pid = _pid(hwnd)
        if pid not in ident_cache:
            try:
                ident_cache[pid] = identity_for_pid(pid, users)
            except Exception:
                ident_cache[pid] = ("", "unknown", False)
        info = snapshot(hwnd, ident_cache[pid])
        if info is None:
            continue
        if not _keep_window(info):
            continue
        out.append(info)
    return _foreground_first(out)


def _foreground_first(windows: list[WindowInfo]) -> list[WindowInfo]:
    fg = user32.GetForegroundWindow()
    if not fg:
        return windows
    root = user32.GetAncestor(fg, GA_ROOT) or fg
    prefer = {hwnd_int(fg), hwnd_int(root)}
    head = [w for w in windows if w.hwnd in prefer]
    tail = [w for w in windows if w.hwnd not in prefer]
    return head + tail


def get_window(window_id: str) -> WindowInfo:
    hwnd = parse_window_id(window_id)
    if not user32.IsWindow(hwnd):
        raise EngineError("window_gone", f"window no longer exists: {window_id}")
    from ocuoc.wm.processes import identity_for_pid

    try:
        ident = identity_for_pid(_pid(hwnd))
    except Exception:
        ident = ("", "unknown", False)
    info = snapshot(hwnd, ident)
    if info is None:
        raise EngineError("window_gone", f"window no longer exists: {window_id}")
    return info


SHELL_HOSTS = {"searchapp", "searchhost", "startmenuexperiencehost"}


def _foreground_stem() -> str:
    fg = user32.GetForegroundWindow()
    if not fg:
        return ""
    return Path(_exe(_pid(int(fg)))).stem.lower()


def activate(info: WindowInfo) -> None:
    if _foreground_stem() in SHELL_HOSTS:
        from ocuoc.input import sendinput

        sendinput.key_combo("esc")
        time.sleep(0.08)
    hwnd = info.hwnd
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    cur_tid = kernel32.GetCurrentThreadId()
    attached = False
    if fg_tid and fg_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def close_window(info: WindowInfo) -> None:
    user32.PostMessageW(info.hwnd, WM_CLOSE, 0, 0)


def find_by_exe_substring(fragment: str, exclude_hwnds: set[int] | None = None) -> WindowInfo | None:
    needle = fragment.lower()
    skip = exclude_hwnds or set()
    for info in list_windows():
        if info.hwnd in skip:
            continue
        if needle in Path(info.exe).name.lower() or needle in info.title.lower():
            return info
    return None
