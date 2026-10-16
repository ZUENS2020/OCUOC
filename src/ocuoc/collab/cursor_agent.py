"""Child process: hide/restore the system cursor, recover if the parent dies."""

from __future__ import annotations

import argparse
import atexit
import ctypes
import sys
import time

from ocuoc.winapi import (
    EVENT_MODIFY_STATE,
    PROCESS_SYNCHRONIZE,
    SM_CXCURSOR,
    SM_CYCURSOR,
    SPI_SETCURSORS,
    SPIF_SENDCHANGE,
    SYNCHRONIZE,
    WAIT_OBJECT_0,
    kernel32,
    user32,
)

OCR_IDS = (
    32512,
    32513,
    32514,
    32515,
    32516,
    32642,
    32643,
    32644,
    32645,
    32646,
    32648,
    32649,
    32650,
    32651,
)


def event_name(pid: int, suffix: str) -> str:
    return f"Local\\OcuocCursor-{int(pid)}-{suffix}"


def reset_cursor_scheme() -> None:
    """Reload the user's cursor scheme. Safe to call when already restored."""
    user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)


_reset_scheme = reset_cursor_scheme


def _suppress() -> None:
    w = max(int(user32.GetSystemMetrics(SM_CXCURSOR)), 1)
    h = max(int(user32.GetSystemMetrics(SM_CYCURSOR)), 1)
    and_stride = ((w + 31) // 32) * 4
    xor_stride = and_stride
    and_mask = (ctypes.c_ubyte * (and_stride * h))(*([0xFF] * (and_stride * h)))
    xor_mask = (ctypes.c_ubyte * (xor_stride * h))()
    and_ptr = ctypes.cast(and_mask, ctypes.c_void_p)
    xor_ptr = ctypes.cast(xor_mask, ctypes.c_void_p)
    for oid in OCR_IDS:
        handle = user32.CreateCursor(None, 0, 0, w, h, and_ptr, xor_ptr)
        if not handle:
            continue
        if not user32.SetSystemCursor(handle, oid):
            user32.DestroyCursor(handle)


def apply_suppress(_hidden: bool) -> bool:
    """Hide the 14 system cursors. Never SPI_SETCURSORS here — that flashes the arrow."""
    _suppress()
    return True


def apply_restore(_hidden: bool) -> bool:
    """Always reload the scheme. Dual trampoline processes can disagree on hidden."""
    _reset_scheme()
    return False


def run(parent_pid: int) -> int:
    access = EVENT_MODIFY_STATE | SYNCHRONIZE
    handles = {}
    for suffix in ("ready", "ack", "suppress", "restore", "shutdown"):
        handle = kernel32.OpenEventW(access, False, event_name(parent_pid, suffix))
        if not handle:
            return 2
        handles[suffix] = handle
    parent = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, parent_pid)
    if not parent:
        return 3
    atexit.register(reset_cursor_scheme)
    try:
        _reset_scheme()
        kernel32.SetEvent(handles["ready"])
        hidden = False
        while True:
            if kernel32.WaitForSingleObject(handles["shutdown"], 20) == WAIT_OBJECT_0:
                break
            if kernel32.WaitForSingleObject(parent, 0) == WAIT_OBJECT_0:
                break
            if kernel32.WaitForSingleObject(handles["suppress"], 0) == WAIT_OBJECT_0:
                kernel32.ResetEvent(handles["suppress"])
                hidden = apply_suppress(hidden)
                kernel32.SetEvent(handles["ack"])
            if kernel32.WaitForSingleObject(handles["restore"], 0) == WAIT_OBJECT_0:
                kernel32.ResetEvent(handles["restore"])
                hidden = apply_restore(hidden)
                kernel32.SetEvent(handles["ack"])
            time.sleep(0.005)
        return 0
    finally:
        reset_cursor_scheme()
        kernel32.CloseHandle(parent)
        for handle in handles.values():
            kernel32.CloseHandle(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ocuoc-cursor-agent")
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    return run(args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())
