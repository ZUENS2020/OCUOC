from __future__ import annotations

import threading
import time

from ocuoc.collab.cursor_supervisor import CursorSupervisor
from ocuoc.collab.hooks import InputHooks
from ocuoc.collab.overlay import Overlay
from ocuoc.input.motion import MOVE_TIMEOUT
from ocuoc.collab.rules import (
    is_key_injected,
    is_mouse_injected,
    same_process,
    should_interrupt_click,
    should_swallow_esc,
)
from ocuoc.policy.guard import Guard


class _Null:
    alive = False

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def show_at(self, x: int, y: int, press: bool = False) -> None:
        return None

    def hide(self) -> None:
        return None

    def wait_idle(self, timeout: float = MOVE_TIMEOUT) -> None:
        return None

    def suppress(self, wait: bool = True) -> None:
        return None

    def restore(self, wait: bool = True) -> None:
        return None

    def ensure_suppressed(self) -> None:
        return None


class Collaboration:
    def __init__(self, guard: Guard, *, hooks=None, overlay=None, cursor=None) -> None:
        self.guard = guard
        self._lock = threading.Lock()
        self._supervising = False
        self._target_hwnd = 0
        self._target_pid = 0
        self._started = False
        self.hooks = hooks if hooks is not None else InputHooks(self)
        self.overlay = overlay if overlay is not None else Overlay()
        self.cursor = cursor if cursor is not None else CursorSupervisor()
        self.on_abort = None
        if hasattr(self.overlay, "on_pulse"):
            self.overlay.on_pulse = self._pulse

    @property
    def supervising(self) -> bool:
        return self._supervising

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            self.overlay.start()
        except Exception:
            self.overlay = _Null()
        try:
            self.cursor.start()
        except Exception:
            self.cursor = _Null()
        try:
            self.hooks.start()
        except Exception:
            self.hooks = _Null()

    def stop(self) -> None:
        self.end_session(restore=True)
        try:
            self.hooks.stop()
        except Exception:
            pass
        try:
            self.overlay.stop()
        except Exception:
            pass
        try:
            self.cursor.stop()
        except Exception:
            pass
        self._started = False

    def begin(self, hwnd: int, pid: int) -> None:
        with self._lock:
            self._supervising = True
            self._target_hwnd = int(hwnd)
            self._target_pid = int(pid)

    def point_to(self, x: int, y: int, press: bool = False) -> None:
        if not self._supervising or not self._started:
            return
        try:
            if not getattr(self.overlay, "alive", False):
                self.overlay.start()
            self.overlay.show_at(int(x), int(y), press=press)
        except Exception:
            pass
        self._suppress_system()

    def wait_overlay(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = float(getattr(self.overlay, "move_timeout", MOVE_TIMEOUT))
        wait = getattr(self.overlay, "wait_idle", None)
        if wait:
            wait(timeout)
        else:
            time.sleep(min(timeout, 0.12))

    def end_session(self, restore: bool = True, wait: bool = True) -> None:
        with self._lock:
            self._supervising = False
            self._target_hwnd = 0
            self._target_pid = 0
        try:
            self.overlay.hide()
        except Exception:
            pass
        if restore:
            try:
                self.cursor.restore(wait=wait)
            except Exception:
                pass

    def park(self) -> None:
        """Stop supervising so the human can take the mouse, but leave the overlay parked."""
        with self._lock:
            self._supervising = False
            self._target_hwnd = 0
            self._target_pid = 0
        try:
            self.cursor.restore(wait=True)
        except Exception:
            pass

    def handle_key(self, flags: int, vk: int, wparam: int, extra: int = 0) -> bool:
        injected = is_key_injected(flags, extra)
        with self._lock:
            supervising = self._supervising
        if should_swallow_esc(supervising=supervising, injected=injected, vk=vk, wparam=wparam):
            self._takeover("esc")
            return True
        return False

    def handle_mouse(self, flags: int, wparam: int, hwnd_hit: int, hit_pid: int, extra: int = 0) -> bool:
        injected = is_mouse_injected(flags, extra)
        with self._lock:
            supervising = self._supervising
            same = same_process(hit_pid, self._target_pid)
        if should_interrupt_click(
            supervising=supervising,
            injected=injected,
            wparam=wparam,
            same_target=same,
        ):
            self._takeover("human_click")
        return False

    def resume_after_observe(self) -> dict:
        takeover = not self.guard.allow_input()
        reason = self.guard.reason()
        if takeover:
            self.end_session(restore=True)
            self.guard.reset()
        else:
            self.park()
        return {
            "human_takeover": takeover,
            "takeover_reason": reason if takeover else "",
        }

    def status(self) -> dict:
        return {
            "supervising": self._supervising,
            "overlay": bool(getattr(self.overlay, "alive", False)),
            "cursor_child": bool(getattr(self.cursor, "alive", False)),
            "hooks": bool(getattr(self.hooks, "alive", False)),
            "target_hwnd": self._target_hwnd,
        }

    def _takeover(self, reason: str) -> None:
        self.guard.abort(reason)
        cb = self.on_abort
        if cb:
            try:
                cb(reason)
            except Exception:
                pass
        self.end_session(restore=True, wait=False)

    def _pulse(self) -> None:
        with self._lock:
            supervising = self._supervising
        if not supervising:
            return
        try:
            self.cursor.ensure_suppressed()
        except Exception:
            pass
        bump = getattr(self.overlay, "bump", None)
        if bump:
            try:
                bump()
            except Exception:
                pass

    def _suppress_system(self) -> None:
        if not getattr(self.overlay, "alive", False):
            return
        try:
            self.cursor.suppress(wait=False)
        except Exception:
            pass
