from __future__ import annotations

import ctypes
import math
import time
from collections.abc import Callable
from ctypes import wintypes

from ocuoc.collab.inject import OCUOC_EXTRA, begin_send, end_send
from ocuoc.input.motion import (
    DT,
    MOVE_TIMEOUT,
    PRESS_MS,
    iter_move_frames,
)
from ocuoc.keys import modifier_vk, parse_hotkey, vk_name
from ocuoc.winapi import (
    INPUT,
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_VIRTUALDESK,
    MOUSEEVENTF_WHEEL,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    WHEEL_DELTA,
    dwmapi,
    user32,
)

BUTTONS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def _send(inputs: list[INPUT]) -> None:
    for inp in inputs:
        if inp.type == INPUT_MOUSE:
            inp.mi.dwExtraInfo = OCUOC_EXTRA
        elif inp.type == INPUT_KEYBOARD:
            inp.ki.dwExtraInfo = OCUOC_EXTRA
    arr = (INPUT * len(inputs))(*inputs)
    begin_send()
    try:
        sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    finally:
        end_send()
    if sent != len(inputs):
        raise OSError("SendInput failed")


def _abs(x: int, y: int) -> tuple[int, int]:
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) - 1, 1)
    vh = max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) - 1, 1)
    ax = int(round((x - vx) * 65535 / vw))
    ay = int(round((y - vy) * 65535 / vh))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(pt)):
        return 0, 0
    return int(pt.x), int(pt.y)


def _dwm_flush() -> None:
    try:
        dwmapi.DwmFlush()
    except Exception:
        pass


def _move_now(x: int, y: int) -> None:
    ax, ay = _abs(x, y)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dx = ax
    inp.mi.dy = ay
    inp.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _send([inp])
    _dwm_flush()


def _glide(x: int, y: int, proceed: Callable[[], bool] | None = None) -> None:
    """Glide the real cursor along the replicated Codex motion:
    same decision tree, bulged/subdivided path and 60Hz spring timing."""
    x0, y0 = cursor_pos()
    frames = iter_move_frames((float(x0), float(y0)), (float(x), float(y)))
    if len(frames) <= 1:
        _move_now(x, y)
        return
    start = time.perf_counter()
    n = 0
    for px, py in frames[:-1]:
        if proceed is not None and not proceed():
            return
        if time.perf_counter() - start > MOVE_TIMEOUT:
            break
        _move_now(int(round(px)), int(round(py)))
        n += 1
        remain = start + n * DT - time.perf_counter()
        if remain > 0:
            time.sleep(remain)
    _move_now(x, y)


def _travel(x: int, y: int, animate: bool, proceed: Callable[[], bool] | None = None) -> None:
    if animate:
        _glide(x, y, proceed=proceed)
    else:
        _move_now(x, y)


def move_abs(
    x: int,
    y: int,
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    _travel(x, y, animate, proceed=proceed)


def click_abs(
    x: int,
    y: int,
    button: str = "left",
    count: int = 1,
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    if button not in BUTTONS:
        raise ValueError(f"unknown button: {button}")
    down, up = BUTTONS[button]
    _travel(x, y, animate, proceed=proceed)
    hold = PRESS_MS / 1000.0
    for _ in range(max(1, count)):
        if proceed is not None and not proceed():
            return
        a = INPUT()
        a.type = INPUT_MOUSE
        a.mi.dwFlags = down
        _send([a])
        time.sleep(hold)
        b = INPUT()
        b.type = INPUT_MOUSE
        b.mi.dwFlags = up
        _send([b])
        time.sleep(0.05)


def mouse_down(
    x: int,
    y: int,
    button: str = "left",
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    if button not in BUTTONS:
        raise ValueError(f"unknown button: {button}")
    down, _up = BUTTONS[button]
    _travel(x, y, animate, proceed=proceed)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dwFlags = down
    _send([inp])


def mouse_up(
    x: int,
    y: int,
    button: str = "left",
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    if button not in BUTTONS:
        raise ValueError(f"unknown button: {button}")
    _down, up = BUTTONS[button]
    _travel(x, y, animate, proceed=proceed)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi.dwFlags = up
    _send([inp])


def drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    steps: int = 12,
    button: str = "left",
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    _ = steps
    if button not in BUTTONS:
        raise ValueError(f"unknown button: {button}")
    down, up = BUTTONS[button]
    _travel(x1, y1, animate, proceed=proceed)
    press = INPUT()
    press.type = INPUT_MOUSE
    press.mi.dwFlags = down
    _send([press])
    time.sleep(PRESS_MS / 1000.0)
    _travel(x2, y2, animate, proceed=proceed)
    release = INPUT()
    release.type = INPUT_MOUSE
    release.mi.dwFlags = up
    _send([release])


def hold_key(spec: str, action: str) -> None:
    action = action.lower().strip()
    if action not in {"down", "up"}:
        raise ValueError("action must be down or up")
    mods, key = parse_hotkey(spec)
    vk = vk_name(key)
    if action == "down":
        seq: list[INPUT] = [_vk(modifier_vk(m)) for m in mods]
        seq.append(_vk(vk))
    else:
        seq = [_vk(vk, up=True)]
        seq.extend(_vk(modifier_vk(m), up=True) for m in reversed(mods))
    _send(seq)
    time.sleep(0.02)


def scroll(
    x: int,
    y: int,
    dy: int = 0,
    dx: int = 0,
    proceed: Callable[[], bool] | None = None,
    animate: bool = True,
) -> None:
    _travel(x, y, animate, proceed=proceed)
    if dy:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi.mouseData = int(dy) * WHEEL_DELTA
        inp.mi.dwFlags = MOUSEEVENTF_WHEEL
        _send([inp])
    if dx:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi.mouseData = int(dx) * WHEEL_DELTA
        inp.mi.dwFlags = 0x1000  # MOUSEEVENTF_HWHEEL
        _send([inp])


def _vk(vk: int, up: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    return inp


def _unicode(ch: str, up: bool = False) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0
    inp.ki.wScan = ord(ch)
    flags = KEYEVENTF_UNICODE
    if up:
        flags |= KEYEVENTF_KEYUP
    inp.ki.dwFlags = flags
    return inp


def type_text(text: str, proceed=None) -> int:
    written = 0
    for ch in text:
        if proceed is not None and not proceed():
            break
        if ch == "\r":
            continue
        if ch == "\n":
            _send([_vk(0x0D), _vk(0x0D, up=True)])
        elif ch == "\t":
            _send([_vk(0x09), _vk(0x09, up=True)])
        else:
            if ord(ch) > 0xFFFF:
                continue
            _send([_unicode(ch), _unicode(ch, up=True)])
        written += 1
        time.sleep(0.008)
    return written


def key_combo(spec: str) -> None:
    mods, key = parse_hotkey(spec)
    vk = vk_name(key)
    seq: list[INPUT] = [_vk(modifier_vk(m)) for m in mods]
    seq.append(_vk(vk))
    seq.append(_vk(vk, up=True))
    seq.extend(_vk(modifier_vk(m), up=True) for m in reversed(mods))
    _send(seq)
    time.sleep(0.03)
