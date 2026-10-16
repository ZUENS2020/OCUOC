"""Local RFC6455 subset WebSocket bridge for the OCUOC browser extension."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import struct
from typing import Any

from ocuoc.browser.cursor import CursorController
from ocuoc.browser.protocol import (
    CURSOR_ARRIVED,
    DENIED,
    DIALOG_EVENT,
    HELLO,
    MAX_FRAME,
    PING,
    PONG,
    TAB_EVENT,
    WS_GUID,
    dumps,
    loads,
    request,
)
from ocuoc.browser.session import TabRegistry

log = logging.getLogger("ocuoc.browser.bridge")


class WSConn:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self.open = True

    async def handshake(self) -> bool:
        data = await self.reader.readuntil(b"\r\n\r\n")
        headers: dict[str, str] = {}
        for line in data.decode("latin-1").split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key")
        if not key or headers.get("upgrade", "").lower() != "websocket":
            self.writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await self.writer.drain()
            return False
        peer = self.writer.get_extra_info("peername")
        if peer and peer[0] not in {"127.0.0.1", "::1"}:
            self.writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await self.writer.drain()
            return False
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.writer.write(resp.encode())
        await self.writer.drain()
        return True

    async def recv(self) -> str | None:
        chunks = bytearray()
        while True:
            head = await self.reader.readexactly(2)
            fin = bool(head[0] & 0x80)
            opcode = head[0] & 0x0F
            length = head[1] & 0x7F
            if length == 126:
                length = struct.unpack(">H", await self.reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await self.reader.readexactly(8))[0]
            if length > MAX_FRAME or len(chunks) + length > MAX_FRAME:
                await self.close()
                return None
            mask = await self.reader.readexactly(4) if (head[1] & 0x80) else None
            payload = await self.reader.readexactly(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                await self.close()
                return None
            if opcode == 0x9:
                await self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x0, 0x1, 0x2):
                chunks.extend(payload)
                if not fin:
                    continue
                text = bytes(chunks).decode("utf-8", "replace")
                chunks.clear()
                return text

    async def send(self, text: str) -> None:
        if self.open:
            await self._send_frame(0x1, text.encode())

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([n])
        elif n < 65536:
            header += bytes([126]) + struct.pack(">H", n)
        else:
            header += bytes([127]) + struct.pack(">Q", n)
        self.writer.write(header + payload)
        await self.writer.drain()

    async def close(self) -> None:
        if self.open:
            self.open = False
            try:
                await self._send_frame(0x8, b"")
            except Exception:
                pass
            try:
                self.writer.close()
            except Exception:
                pass


class BrowserBridge:
    """One extension connection: token pairing, request/response, arrival waiters."""

    def __init__(self, token: str | None = None) -> None:
        self.conn: WSConn | None = None
        self.token = token or secrets.token_hex(32)
        self.authed = False
        self.extension_version = ""
        self.host = "127.0.0.1"
        self.port = 0
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._server: asyncio.AbstractServer | None = None
        self.cursor = CursorController()
        self.tabs = TabRegistry()

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def connected(self) -> bool:
        return bool(self.conn and self.authed)

    async def serve(self, host: str = "127.0.0.1", port: int = 0) -> tuple[str, int]:
        self._server = await asyncio.start_server(self._handle, host, port)
        self.host, self.port = self._server.sockets[0].getsockname()[:2]
        return self.host, int(self.port)

    async def close_server(self) -> None:
        self.cursor.abort_all()
        if self.conn:
            await self.conn.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = WSConn(reader, writer)
        try:
            if not await conn.handshake():
                return
            if self.conn and self.authed:
                await conn.send(dumps({"type": DENIED, "error": "busy"}))
                await conn.close()
                return
            first = await conn.recv()
            if not first:
                return
            hello = loads(first)
            data = hello.get("data") if isinstance(hello.get("data"), dict) else {}
            if hello.get("type") != HELLO or data.get("token") != self.token:
                await conn.send(dumps({"type": DENIED}))
                await conn.close()
                return
            self.conn, self.authed = conn, True
            self.extension_version = str(data.get("version") or "")
            log.info("extension connected")
            while True:
                text = await conn.recv()
                if text is None:
                    break
                self._on_frame(loads(text))
        except Exception as exc:
            log.warning("conn error: %s", exc)
        finally:
            if self.conn is conn:
                self.conn, self.authed = None, False
                self.extension_version = ""
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(ConnectionError("bridge closed"))
                self._pending.clear()
                self.cursor.abort_all()
            try:
                writer.close()
            except Exception:
                pass
            log.info("extension disconnected")

    def _on_frame(self, msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == CURSOR_ARRIVED:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            self.cursor.arrived(int(data.get("tabId", -1)), int(data.get("seq", -1)))
            return
        if mtype == TAB_EVENT:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            self.tabs.on_tab_event(data)
            return
        if mtype == DIALOG_EVENT:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            self.tabs.on_dialog(data)
            return
        if mtype == PING:
            if self.conn:
                asyncio.create_task(self.conn.send(dumps({"type": PONG})))
            return
        if mtype == PONG:
            return
        mid = msg.get("id")
        if mid is not None:
            fut = self._pending.pop(int(mid), None)
            if fut and not fut.done():
                if msg.get("ok"):
                    fut.set_result(msg.get("result"))
                else:
                    fut.set_exception(RuntimeError(str(msg.get("error"))))

    async def call(self, mtype: str, data: dict[str, Any] | None = None, timeout: float = 10.0) -> Any:
        if not self.connected:
            raise ConnectionError("extension not connected")
        mid = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        assert self.conn is not None
        await self.conn.send(dumps(request(mid, mtype, data)))
        return await asyncio.wait_for(fut, timeout)
