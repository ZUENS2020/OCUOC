"""cuoc.* WebSocket message types, timeouts, and JSON codec."""

from __future__ import annotations

import json
from typing import Any

ARRIVAL_TIMEOUT_MS = 1500.0
HEARTBEAT_MS = 20000
MAX_FRAME = 4 * 1024 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

HELLO = "hello"
DENIED = "denied"
PING = "ping"
PONG = "pong"
CURSOR_ARRIVED = "cursor.arrived"
TAB_EVENT = "tab.event"
DIALOG_EVENT = "dialog.event"

TABS_LIST = "tabs.list"
TAB_NEW = "tab.new"
TAB_ACTIVATE = "tab.activate"
TAB_CLOSE = "tab.close"
CURSOR_SET = "cursor.set"
CURSOR_HIDE = "cursor.hide"
INPUT_MOUSE = "input.mouse"
INPUT_TEXT = "input.text"
INPUT_KEY = "input.key"
PAGE_SCREENSHOT = "page.screenshot"
PAGE_AXTREE = "page.axtree"
PAGE_DOM = "page.dom"
PAGE_EVAL = "page.eval"
PAGE_DIALOG = "page.dialog"
BADGE_SET = "badge.set"
CDP_RAW = "cdp.raw"

BADGE_ACTIVE = "active"
BADGE_DELIVERABLE = "deliverable"
BADGE_HANDOFF = "handoff"


def dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text: str) -> dict[str, Any]:
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def request(mid: int, mtype: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": int(mid), "type": mtype, "data": data or {}}


def ok(mid: int, result: Any = None) -> dict[str, Any]:
    return {"id": int(mid), "ok": True, "result": {} if result is None else result}


def err(mid: int, error: str) -> dict[str, Any]:
    return {"id": int(mid), "ok": False, "error": error}
