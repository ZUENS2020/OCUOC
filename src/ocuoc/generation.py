from __future__ import annotations

import hashlib
import json


def make_window_id(hwnd: int) -> str:
    return f"hwnd:{int(hwnd) & 0xFFFFFFFFFFFFFFFF}"


def parse_window_id(window_id: str) -> int:
    if not isinstance(window_id, str) or not window_id.startswith("hwnd:"):
        raise ValueError(f"invalid window_id: {window_id!r}")
    rest = window_id[5:]
    if not rest.isdigit():
        raise ValueError(f"invalid window_id: {window_id!r}")
    return int(rest)


def _snap(value: int, grid: int = 8) -> int:
    return (int(value) // grid) * grid


def make_generation(
    hwnd: int,
    title: str,
    rect: tuple[int, int, int, int],
    class_name: str = "",
) -> str:
    # Title is excluded: editors change it while loading ("Untitled" / dirty '*').
    # Rect is snapped so 1–2px DWM jitter does not invalidate a fresh screenshot.
    payload = json.dumps(
        {
            "hwnd": int(hwnd),
            "class": class_name,
            "rect": [_snap(x) for x in rect],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
