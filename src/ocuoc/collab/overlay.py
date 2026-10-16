from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from ctypes import wintypes

from ocuoc.collab.cursor_glyph import blit_rotated, heading_for_velocity
from ocuoc.input.motion import (
    DT,
    MOVE_TIMEOUT,
    PRESS_MS,
    build_move,
    simulate,
    squash_scale,
)
from ocuoc.winapi import (
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BI_RGB,
    BITMAPINFO,
    BLENDFUNCTION,
    DIB_RGB_COLORS,
    ERROR_CLASS_ALREADY_EXISTS,
    HWND_TOPMOST,
    PM_NOREMOVE,
    SIZE,
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    ULW_ALPHA,
    WDA_EXCLUDEFROMCAPTURE,
    WM_APP,
    WM_DESTROY,
    WM_ERASEBKGND,
    WM_NCHITTEST,
    WM_QUIT,
    WM_TIMER,
    WNDCLASSW,
    WNDPROC,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOPMOST,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    WS_POPUP,
    HTTRANSPARENT,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    gdi32,
    kernel32,
    user32,
)

CLASS_NAME = "OcuocCursorOverlay"
WM_OCUOC_MOVE = WM_APP + 1
WM_OCUOC_HIDE = WM_APP + 2
CANVAS = 192
OVERLAY_SIZE = CANVAS
HOTSPOT = (96, 96)
TIMER_ANIM = 1
TIMER_PULSE = 2
TIMER_PRESS = 3   # matches the original's press-hold timer id


def spawn_agent_origin() -> tuple[int, int]:
    vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    return vx + HOTSPOT[0], vy + HOTSPOT[1]


def human_cursor_origin() -> tuple[int, int]:
    pt = wintypes.POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return spawn_agent_origin()


class Overlay:
    """Layered-window replica of the Codex AI pointer.

    Animation model per docs/2026-10-16-codex-cursor-animation-re.md:
    decision-tree path (teleport / short cubic / bulged two-segment +
    subdivision), 60Hz semi-implicit Euler damped spring on progress,
    tangent rotation + coherent-noise wobble, vertical speed squash and a
    press visual held >= 100ms via timer id 3.
    """

    def __init__(self, *, exclude_from_capture: bool = False) -> None:
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hwnd = 0
        self._ready = threading.Event()
        self._wndproc = None
        self._lock = threading.Lock()
        self._tx = 0
        self._ty = 0
        self._cx = 0
        self._cy = 0
        self._visible = False
        self._press = False
        self._plan = None
        self._samples: list = []
        self._si = 0
        self._flying = False
        self._accum = 0.0
        self._last_tick = 0.0
        self._squash = 1.0
        self._angle = 0.0
        self._last_ulw = 0
        self._hdc = None
        self._hbmp = None
        self._old = None
        self._bits = None
        self._bits_ptr = None
        self._canvas = CANVAS
        self._has_agent = False
        self._exclude_from_capture = exclude_from_capture
        self._bold = False
        self.on_pulse = None

    @property
    def alive(self) -> bool:
        return bool(self._hwnd)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, name="ocuoc-overlay", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._tid = 0
        self._hwnd = 0

    def show_at(self, x: int, y: int, press: bool = False) -> None:
        with self._lock:
            if not self._has_agent:
                self._cx, self._cy = human_cursor_origin()
                self._has_agent = True
            self._tx = int(x)
            self._ty = int(y)
            self._press = bool(press)
            self._visible = True
            plan = build_move((float(self._cx), float(self._cy)), (float(self._tx), float(self._ty)))
            if plan.snapped:
                # < 0.5px: apply immediately, no animation (sub_140050030 path)
                self._plan = None
                self._samples = []
                self._si = 0
                self._flying = False
                self._squash = 1.0
                self._cx, self._cy = self._tx, self._ty
            else:
                self._plan = plan
                self._samples = simulate(plan.T, plan.zeta)
                self._si = 0
                self._flying = True
                self._accum = 0.0
                self._squash = 1.0
        if self._hwnd:
            user32.SendMessageW(self._hwnd, WM_OCUOC_MOVE, 1 if press else 0, 0)

    def pin_at(self, x: int, y: int) -> None:
        """Snap the Codex pointer to a screen point and keep it there."""
        x, y = int(x), int(y)
        with self._lock:
            self._cx = self._tx = x
            self._cy = self._ty = y
            self._plan = None
            self._samples = []
            self._si = 0
            self._flying = False
            self._squash = 1.0
            self._press = False
            self._angle = 0.0
            self._visible = True
            self._has_agent = True
        if self._hwnd:
            user32.SendMessageW(self._hwnd, WM_OCUOC_MOVE, 0, 0)

    def wait_idle(self, timeout: float = MOVE_TIMEOUT) -> None:
        """Wait until the spring settles (and the press hold elapses)."""
        deadline = time.monotonic() + timeout
        visible = False
        while time.monotonic() < deadline:
            with self._lock:
                visible = self._visible
                idle = not self._flying and not self._press
            if visible and idle:
                return
            time.sleep(0.005)
        if visible:
            return
        time.sleep(min(PRESS_MS / 1000.0, timeout))

    def bump(self) -> None:
        if self._hwnd:
            self._apply_pos(self._hwnd)

    def hide(self) -> None:
        with self._lock:
            self._visible = False
            self._press = False
            self._plan = None
            self._samples = []
            self._flying = False
            self._squash = 1.0
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_OCUOC_HIDE, 0, 0)

    def _loop(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        try:
            self._run_loop()
        finally:
            self._ready.set()

    def _run_loop(self) -> None:
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._wndproc = WNDPROC(self._wnd_proc)
        self._class_name = ctypes.c_wchar_p(f"{CLASS_NAME}-{os.getpid()}-{id(self)}")
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = self._class_name
        self._wc = wc
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() not in {0, ERROR_CLASS_ALREADY_EXISTS}:
            self._ready.set()
            return
        ex = WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW
        hwnd = user32.CreateWindowExW(
            ex,
            self._class_name,
            "ocuoc-overlay",
            WS_POPUP,
            0,
            0,
            OVERLAY_SIZE,
            OVERLAY_SIZE,
            None,
            None,
            wc.hInstance,
            None,
        )
        if not hwnd:
            self._ready.set()
            return
        self._hwnd = int(hwnd)
        if self._exclude_from_capture:
            user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        self._init_bitmap()
        self._paint(hwnd)
        user32.SetTimer(hwnd, TIMER_ANIM, 16, None)
        user32.SetTimer(hwnd, TIMER_PULSE, 1000, None)
        user32.ShowWindow(hwnd, SW_HIDE)
        self._ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.KillTimer(hwnd, TIMER_ANIM)
        user32.KillTimer(hwnd, TIMER_PULSE)
        user32.KillTimer(hwnd, TIMER_PRESS)
        self._dispose_bitmap()
        user32.DestroyWindow(hwnd)
        self._hwnd = 0

    def _wnd_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_NCHITTEST:
                return HTTRANSPARENT
            if message == WM_ERASEBKGND:
                return 1
            if message == WM_OCUOC_MOVE:
                if wparam:
                    self._press = True
                    user32.SetTimer(hwnd, TIMER_PRESS, PRESS_MS, None)
                self._apply_pos(hwnd)
                return 0
            if message == WM_OCUOC_HIDE:
                user32.ShowWindow(hwnd, SW_HIDE)
                return 0
            if message == WM_TIMER:
                if wparam == TIMER_ANIM:
                    self._tick_anim(hwnd)
                elif wparam == TIMER_PULSE:
                    cb = self.on_pulse
                    if cb:
                        cb()
                elif wparam == TIMER_PRESS:
                    user32.KillTimer(hwnd, TIMER_PRESS)
                    self._press = False
                    self._apply_pos(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _tick_anim(self, hwnd) -> None:
        with self._lock:
            if not self._visible or not self._flying or not self._samples:
                return
            now = time.perf_counter()
            if self._last_tick:
                self._accum += min(0.25, now - self._last_tick)
            self._last_tick = now
            landed = False
            while self._accum >= DT:
                self._accum -= DT
                self._si += 1
                if self._si >= len(self._samples) - 1:
                    self._si = len(self._samples) - 1
                    landed = True
                _t, p, v = self._samples[self._si]
                plan = self._plan
                if landed or plan is None:
                    break
                pos, tan = plan.sample(min(1.0, max(0.0, p)))
                self._cx = int(round(pos[0]))
                self._cy = int(round(pos[1]))
                self._angle = heading_for_velocity(tan[0], tan[1]) + math.radians(
                    plan.wobble_at(p)
                )
                self._squash = squash_scale(abs(v) * plan.arc)
                if landed:
                    break
            if landed or self._si >= len(self._samples) - 1:
                plan = self._plan
                if plan is not None:
                    _, tan = plan.sample(1.0)
                    self._angle = heading_for_velocity(tan[0], tan[1]) + math.radians(
                        plan.wobble_at(1.0)
                    )
                self._cx, self._cy = self._tx, self._ty
                self._flying = False
                self._squash = 1.0
                self._last_tick = 0.0
        self._apply_pos(hwnd)

    def _apply_pos(self, hwnd) -> None:
        with self._lock:
            if not self._visible:
                user32.ShowWindow(hwnd, SW_HIDE)
                return
        first = not bool(user32.IsWindowVisible(hwnd))
        self._paint(hwnd)
        if first:
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(
            hwnd,
            wintypes.HWND(HWND_TOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _init_bitmap(self) -> None:
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(bmi.bmiHeader)
        bmi.bmiHeader.biWidth = self._canvas
        bmi.bmiHeader.biHeight = -self._canvas
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        hdc = gdi32.CreateCompatibleDC(None)
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not hdc or not hbmp or not bits:
            return
        old = gdi32.SelectObject(hdc, hbmp)
        self._hdc = hdc
        self._hbmp = hbmp
        self._old = old
        self._bits_ptr = bits
        self._bits = (ctypes.c_uint32 * (self._canvas * self._canvas)).from_address(bits.value)

    def _dispose_bitmap(self) -> None:
        if self._hdc and self._old:
            gdi32.SelectObject(self._hdc, self._old)
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
        if self._hdc:
            gdi32.DeleteDC(self._hdc)
        self._hdc = None
        self._hbmp = None
        self._old = None
        self._bits = None
        self._bits_ptr = None

    def _paint(self, hwnd=None) -> None:
        if self._bits is None or self._hdc is None:
            return
        px = self._bits
        w = self._canvas
        ptr = self._bits_ptr.value if self._bits_ptr is not None else None
        if ptr:
            ctypes.memset(ptr, 0, w * w * 4)
        else:
            for i in range(len(px)):
                px[i] = 0
        with self._lock:
            press = self._press
            cx, cy = self._cx, self._cy
            angle = self._angle
            squash = self._squash
        scale_x = 1.0
        scale_y = squash
        alpha = 1.0
        if press:
            # press visual (exact form not decoded; dip inferred)
            scale_x = 0.88
            scale_y = min(scale_y, 0.80)
        if self._bold:
            scale_x *= 1.35
            scale_y *= 1.35
        blit_rotated(px, w, HOTSPOT[0], HOTSPOT[1], angle, scale_x, alpha, scale_y)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        src = wintypes.POINT(0, 0)
        size = SIZE(w, w)
        dst = wintypes.POINT(cx - HOTSPOT[0], cy - HOTSPOT[1])
        target = hwnd if hwnd else self._hwnd
        self._last_ulw = int(
            user32.UpdateLayeredWindow(
                target,
                None,
                ctypes.byref(dst),
                ctypes.byref(size),
                self._hdc,
                ctypes.byref(src),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
        )
