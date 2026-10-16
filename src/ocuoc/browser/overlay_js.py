"""Ship the same content_cursor.js used by the unpacked extension (hash-checked)."""

from __future__ import annotations

import hashlib
from pathlib import Path

_EXT = Path(__file__).resolve().parents[3] / "ext"
_CURSOR = _EXT / "content_cursor.js"


def ext_dir() -> Path:
    return _EXT


def content_cursor_js() -> str:
    return _CURSOR.read_text(encoding="utf-8")


def content_cursor_sha256() -> str:
    return hashlib.sha256(content_cursor_js().encode("utf-8")).hexdigest()
