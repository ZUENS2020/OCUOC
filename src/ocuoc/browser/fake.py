"""In-process fake extension for protocol tests (no Chrome)."""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
from typing import Any

# 1×1 PNG
_PNG = (
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeExtension:
    """Replay extension behaviour: animate then cursor.arrived, then ack input.mouse."""

    def __init__(self, url: str, token: str) -> None:
        self.url, self.token = url, token
        self.order: list[str] = []
        self.seq_arrived: set[int] = set()
        self.simulated_animate_ms = 700
        self.tabs = [
            {
                "tabId": 42,
                "windowId": 1,
                "index": 0,
                "url": "https://example.com/",
                "title": "Example",
                "active": True,
                "width": 1280,
                "height": 800,
            }
        ]
        self.badges: dict[int, str | None] = {}
        self.eval_calls: list[str] = []
        self.dialogs: list[dict[str, Any]] = []
        self.hang_types: set[str] = set()
        self.ax_name = "Go"
        self.last_key: dict[str, Any] = {}
        self._writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        port = int(self.url.rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self._writer = writer
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        writer.write(
            (
                "GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        await self._send(
            writer,
            {
                "type": "hello",
                "data": {"token": self.token, "role": "extension", "ext": "fake", "version": "0.1.0"},
            },
        )
        while True:
            frame = await self._read(reader)
            if frame is None:
                break
            msg = json.loads(frame)
            if msg.get("type") == "ping":
                await self._send(writer, {"type": "pong"})
                continue
            if msg.get("id") is None:
                continue
            mid, mtype, data = msg["id"], msg.get("type"), msg.get("data") or {}
            if mtype in self.hang_types:
                asyncio.create_task(self._hang_reply(writer, mid, mtype, data))
                continue
            result = await self._handle(writer, mtype, data)
            await self._send(writer, {"id": mid, "ok": True, "result": result})

    async def _hang_reply(self, writer, mid: int, mtype: str, data: dict[str, Any]) -> None:
        await asyncio.sleep(30)
        result = await self._handle(writer, mtype, data)
        await self._send(writer, {"id": mid, "ok": True, "result": result})

    async def _handle(self, writer, mtype: str, data: dict[str, Any]) -> Any:
        if mtype == "cursor.set":
            self.order.append(f"cursor.set#{data['seq']}@{data['x']:.0f},{data['y']:.0f}")
            if data.get("animate", True):
                asyncio.create_task(self._arrive_later(writer, data))
            return {"delivered": True}
        if mtype == "input.mouse":
            kinds = "+".join(a["type"] for a in data.get("actions") or [])
            self.order.append(f"input.mouse[{kinds}]")
            return {"count": len(data.get("actions") or [])}
        if mtype == "tabs.list":
            self.order.append("tabs.list")
            return list(self.tabs)
        if mtype == "tab.new":
            self.order.append("tab.new")
            tab = {
                "tabId": 43,
                "windowId": 1,
                "index": 1,
                "url": data.get("url") or "about:blank",
                "title": "",
                "active": data.get("active", True),
                "width": 1280,
                "height": 800,
            }
            self.tabs.append(tab)
            return tab
        if mtype == "tab.activate":
            self.order.append("tab.activate")
            for tab in self.tabs:
                tab["active"] = tab["tabId"] == int(data["tabId"])
            return {}
        if mtype == "tab.close":
            self.order.append("tab.close")
            self.tabs = [t for t in self.tabs if t["tabId"] != int(data["tabId"])]
            return {}
        if mtype == "page.screenshot":
            self.order.append("page.screenshot")
            return {
                "dataUrl": "data:image/png;base64," + _PNG.decode("ascii"),
                "backend": "cdp",
                "activated": False,
            }
        if mtype == "cdp.raw":
            method = str(data.get("method") or "")
            self.order.append(f"cdp.raw:{method}")
            if method == "DOM.getContentQuads":
                return {"quads": [[10.0, 20.0, 90.0, 20.0, 90.0, 44.0, 10.0, 44.0]]}
            return {}
        if mtype == "page.axtree":
            self.order.append("page.axtree")
            return {
                "nodes": [
                    {
                        "ignored": False,
                        "role": {"value": "button"},
                        "name": {"value": self.ax_name},
                        "backendDOMNodeId": 1,
                    },
                    {"ignored": True, "role": {"value": "none"}, "name": {"value": ""}, "backendDOMNodeId": 2},
                ]
            }
        if mtype == "page.dom":
            self.order.append("page.dom")
            return {
                "documents": [
                    {
                        "nodes": {"backendNodeId": [1, 2], "nodeName": ["BUTTON", "DIV"]},
                        "layout": {"nodeIndex": [0], "bounds": [[10.0, 20.0, 80.0, 24.0]]},
                    }
                ]
            }
        if mtype == "page.eval":
            expr = str(data.get("expression") or "")
            self.eval_calls.append(expr)
            self.order.append("page.eval")
            if "devicePixelRatio" in expr:
                return {"result": {"value": 2.0}}
            return {"result": {"value": None}}
        if mtype == "badge.set":
            kind = data.get("kind")
            self.badges[int(data["tabId"])] = kind
            self.order.append(f"badge.set:{kind}")
            return {"ok": True}
        if mtype == "page.dialog":
            self.dialogs.append(dict(data))
            self.order.append("page.dialog")
            return {"ok": True}
        if mtype == "input.text":
            self.order.append("input.text")
            return {}
        if mtype == "input.key":
            self.last_key = dict(data)
            self.order.append("input.key")
            return {"ok": True, "chords": data.get("chords") or []}
        self.order.append(mtype or "?")
        return {}

    async def _arrive_later(self, writer, data: dict[str, Any]) -> None:
        await asyncio.sleep(self.simulated_animate_ms / 1000)
        await self._send(
            writer,
            {"type": "cursor.arrived", "data": {"tabId": data["tabId"], "seq": data["seq"]}},
        )
        self.seq_arrived.add(int(data["seq"]))

    async def emit_dialog(self, tab_id: int, message: str) -> None:
        if self._writer is None:
            return
        await self._send(
            self._writer,
            {
                "type": "dialog.event",
                "data": {"kind": "opening", "tabId": tab_id, "message": message, "type": "alert"},
            },
        )

    @staticmethod
    async def _send(writer, obj: dict) -> None:
        payload = json.dumps(obj).encode()
        mask = secrets.token_bytes(4)
        header = bytes([0x81])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            header += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        writer.write(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        await writer.drain()

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> str | None:
        try:
            head = await reader.readexactly(2)
            opcode = head[0] & 0x0F
            length = head[1] & 0x7F
            if length == 126:
                length = int.from_bytes(await reader.readexactly(2), "big")
            elif length == 127:
                length = int.from_bytes(await reader.readexactly(8), "big")
            payload = await reader.readexactly(length)
            if opcode == 0x8:
                return None
            return payload.decode()
        except (asyncio.IncompleteReadError, ConnectionError):
            return None
