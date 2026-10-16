from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
from urllib.parse import urlparse
from urllib.request import urlopen

from ocuoc.errors import EngineError


def list_targets(port: int, timeout: float = 0.8) -> list[dict]:
    url = f"http://127.0.0.1:{int(port)}/json/list"
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        raise EngineError("cdp_unavailable", f"cannot list CDP targets on {port}: {exc}") from exc
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def fetch_ax_tree(port: int, timeout: float = 2.0) -> tuple[list[dict], str]:
    targets = list_targets(port, timeout=min(timeout, 0.8))
    page = None
    for item in targets:
        t = (item.get("type") or "").lower()
        if t in {"page", "webview", "other", "background_page"} and item.get("webSocketDebuggerUrl"):
            page = item
            if t in {"page", "webview"}:
                break
    if page is None:
        return [], "no_cdp_page_target"
    ws_url = page["webSocketDebuggerUrl"]
    try:
        nodes = _ax_via_websocket(ws_url, timeout=timeout)
    except Exception as exc:
        return [], f"cdp_ws_failed:{exc}"
    return nodes, "cdp"


def _ax_via_websocket(ws_url: str, timeout: float) -> list[dict]:
    ws = _WebSocket(ws_url, timeout=timeout)
    try:
        ws.call("Accessibility.enable")
        dpr = 1.0
        try:
            ev = ws.call("Runtime.evaluate", {"expression": "window.devicePixelRatio || 1", "returnByValue": True})
            raw = (((ev or {}).get("result") or {}).get("value"))
            dpr = float(raw or 1) or 1.0
        except Exception:
            dpr = 1.0
        tree = ws.call("Accessibility.getFullAXTree")
        ax_nodes = tree.get("nodes") or []
        out: list[dict] = []
        budget = 80
        for node in ax_nodes:
            if node.get("ignored"):
                continue
            name = ""
            role = ""
            if isinstance(node.get("role"), dict):
                role = str(node["role"].get("value") or "")
            elif node.get("role"):
                role = str(node.get("role"))
            if isinstance(node.get("name"), dict):
                name = str(node["name"].get("value") or "")
            elif node.get("name"):
                name = str(node.get("name"))
            backend = node.get("backendDOMNodeId")
            if not name.strip() and role.lower() in {"generic", "none", "ignored", ""}:
                continue
            rect = None
            if backend and budget > 0:
                budget -= 1
                try:
                    box = ws.call("DOM.getBoxModel", {"backendNodeId": int(backend)})
                    model = box.get("model") or {}
                    quad = model.get("border") or model.get("content") or []
                    rect = _quad_rect(quad, dpr)
                except Exception:
                    rect = None
            out.append(
                {
                    "name": name,
                    "control_type": role or "AX",
                    "backendDOMNodeId": backend,
                    "rect": rect,
                    "source": "cdp",
                }
            )
        return out
    finally:
        ws.close()


def _quad_rect(quad: list, dpr: float) -> dict | None:
    if not quad or len(quad) < 8:
        return None
    xs = [float(quad[i]) * dpr for i in range(0, 8, 2)]
    ys = [float(quad[i]) * dpr for i in range(1, 8, 2)]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    width, height = right - left, bottom - top
    if width < 1 or height < 1:
        return None
    return {"x": int(round(left)), "y": int(round(top)), "width": int(round(width)), "height": int(round(height))}


class _WebSocket:
    def __init__(self, url: str, timeout: float) -> None:
        parsed = urlparse(url)
        self._id = 0
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        raw = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "wss":
            ctx = ssl.create_default_context()
            self._sock = ctx.wrap_socket(raw, server_hostname=host)
        else:
            self._sock = raw
        self._sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(req.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise OSError("CDP websocket handshake closed")
            buf += chunk
        header, _, rest = buf.partition(b"\r\n\r\n")
        status = header.split(b"\r\n", 1)[0]
        if b"101" not in status:
            raise OSError(f"CDP websocket handshake failed: {status!r}")
        expected = base64.b64encode(hashlib.sha1(key.encode("ascii") + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        if expected not in header:
            # some CDP endpoints omit verifying client-side; continue if 101
            pass
        self._pending = rest

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        self._send(json.dumps(payload, separators=(",", ":")))
        while True:
            data = self._recv()
            if not data:
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if parsed.get("id") != msg_id:
                continue
            if "error" in parsed:
                raise EngineError("cdp_error", str(parsed["error"]))
            result = parsed.get("result")
            return result if isinstance(result, dict) else {}

    def _send(self, text: str) -> None:
        payload = text.encode("utf-8")
        opcode = 0x81
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray()
        header.append(opcode)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + masked)

    def _recv(self) -> str:
        header = self._read_exact(2)
        opcode = header[0] & 0x0F
        masked = header[1] & 0x80
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self._read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._read_exact(8), "big")
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            return ""
        if opcode == 0x9:
            # ping -> pong
            self._sock.sendall(bytes([0x8A, 0x00]))
            return ""
        return payload.decode("utf-8", errors="replace")

    def _read_exact(self, n: int) -> bytes:
        data = b""
        if self._pending:
            take = min(n, len(self._pending))
            data, self._pending = self._pending[:take], self._pending[take:]
            n -= take
        while n > 0:
            chunk = self._sock.recv(n)
            if not chunk:
                raise OSError("CDP websocket closed")
            data += chunk
            n -= len(chunk)
        return data

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
