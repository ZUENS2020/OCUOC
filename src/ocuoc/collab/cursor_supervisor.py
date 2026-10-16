from __future__ import annotations

import ctypes
import os
import subprocess
import sys

from ocuoc.collab.cursor_agent import event_name, reset_cursor_scheme
from ocuoc.winapi import (
    CREATE_BREAKAWAY_FROM_JOB,
    CREATE_NO_WINDOW,
    kernel32,
)


def running_python() -> str:
    """Path of this process image, not a venv trampoline that re-execs python.exe."""
    buf = ctypes.create_unicode_buffer(32768)
    n = int(kernel32.GetModuleFileNameW(None, buf, len(buf)) or 0)
    if n and buf.value:
        return buf.value
    return sys.executable


class CursorSupervisor:
    """Parent side of the cursor-manager child. Parent death restores the scheme."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._handles: dict[str, int] = {}
        self._wanted = False

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        self._ensure_events()
        self._spawn()

    def stop(self) -> None:
        self._wanted = False
        self._signal("restore", wait=True)
        reset_cursor_scheme()
        self._signal("shutdown", wait=False)
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        for handle in self._handles.values():
            kernel32.CloseHandle(handle)
        self._handles.clear()

    def suppress(self, wait: bool = True) -> None:
        self._wanted = True
        if not self.alive:
            self._spawn()
        self._signal("suppress", wait=wait)

    def restore(self, wait: bool = True) -> None:
        self._wanted = False
        self._signal("restore", wait=wait)
        reset_cursor_scheme()

    def ensure_suppressed(self) -> None:
        if not self._wanted:
            return
        if not self.alive:
            self._spawn()
        self._signal("suppress", wait=False)

    def _ensure_events(self) -> None:
        if self._handles:
            return
        pid = os.getpid()
        for suffix in ("ready", "ack", "suppress", "restore", "shutdown"):
            handle = kernel32.CreateEventW(None, False, False, event_name(pid, suffix))
            if not handle:
                raise OSError(f"CreateEventW failed for {suffix}")
            self._handles[suffix] = handle

    def _spawn(self) -> None:
        self._ensure_events()
        if self.alive:
            return
        argv = [sys.executable, "-m", "ocuoc.collab.cursor_agent", "--parent-pid", str(os.getpid())]
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        try:
            self._proc = subprocess.Popen(
                argv,
                creationflags=CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB,
                **kwargs,
            )
        except OSError:
            try:
                self._proc = subprocess.Popen(
                    argv,
                    creationflags=CREATE_NO_WINDOW,
                    **kwargs,
                )
            except OSError:
                self._proc = None
                return
        kernel32.WaitForSingleObject(self._handles["ready"], 5000)

    def _signal(self, suffix: str, wait: bool) -> None:
        handle = self._handles.get(suffix)
        if not handle:
            return
        kernel32.SetEvent(handle)
        if wait:
            ack = self._handles.get("ack")
            if ack:
                kernel32.WaitForSingleObject(ack, 1500)
