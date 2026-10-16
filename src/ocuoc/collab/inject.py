from __future__ import annotations

import threading
import time

# Stamped onto SendInput extraInfo so LL hooks can recognize our own events
# even when the OS injected bit is missing.
OCUOC_EXTRA = 0x6F63756F

_lock = threading.Lock()
_depth = 0
_grace_until = 0.0


def begin_send() -> None:
    global _depth
    with _lock:
        _depth += 1


def end_send() -> None:
    global _depth, _grace_until
    with _lock:
        _depth = max(0, _depth - 1)
        _grace_until = time.monotonic() + 0.08


def in_flight() -> bool:
    with _lock:
        return _depth > 0 or time.monotonic() < _grace_until


def reset_for_tests() -> None:
    global _depth, _grace_until
    with _lock:
        _depth = 0
        _grace_until = 0.0
