"""Optional Chrome headless driver: inject content_cursor.js over CDP (plan P4)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ocuoc.browser.overlay_js import content_cursor_js
from ocuoc.browser.protocol import ARRIVAL_TIMEOUT_MS
from ocuoc.errors import EngineError
from ocuoc.webview.cdp import _WebSocket, list_targets


def find_chrome() -> str | None:
    env = os.environ.get("CHROME_BIN") or os.environ.get("OCUOC_CHROME")
    if env and Path(env).is_file():
        return env
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return shutil.which("chrome") or shutil.which("chrome.exe")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


class HeadlessCDP:
    """Page.addScriptToEvaluateOnNewDocument + Runtime.bindingCalled arrival."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.ws: _WebSocket | None = None
        self._profile: tempfile.TemporaryDirectory | None = None
        self._arrivals: list[str] = []

    def start(self, url: str = "about:blank", timeout: float = 12.0) -> None:
        chrome = find_chrome()
        if not chrome:
            raise EngineError("chrome_missing", "Chrome not found for headless mode")
        self.port = _free_port()
        self._profile = tempfile.TemporaryDirectory(prefix="ocuoc-chrome-")
        args = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={self._profile.name}",
            f"--remote-debugging-port={self.port}",
            url,
        ]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        ws_url = ""
        last_exc: Exception | None = None
        while time.time() < deadline:
            try:
                targets = list_targets(self.port, timeout=0.4)
            except Exception as exc:
                last_exc = exc
                time.sleep(0.15)
                continue
            for item in targets:
                if item.get("type") == "page" and item.get("webSocketDebuggerUrl"):
                    ws_url = str(item["webSocketDebuggerUrl"])
                    break
            if ws_url:
                break
            time.sleep(0.15)
        if not ws_url:
            self.stop()
            raise EngineError("cdp_unavailable", f"headless Chrome CDP not ready: {last_exc}")
        self.ws = _WebSocket(ws_url, timeout=timeout)
        self._rpc("Runtime.enable")
        self._rpc("Page.enable")
        self._rpc("Runtime.addBinding", {"name": "cuocCursorArrived"})
        self._rpc("Page.addScriptToEvaluateOnNewDocument", {"source": content_cursor_js()})
        self._rpc("Runtime.evaluate", {"expression": content_cursor_js(), "returnByValue": True})

    def _note(self, msg: dict[str, Any]) -> None:
        if msg.get("method") != "Runtime.bindingCalled":
            return
        params = msg.get("params") or {}
        if params.get("name") == "cuocCursorArrived":
            self._arrivals.append(str(params.get("payload")))

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.ws is None:
            raise EngineError("cdp_unavailable", "headless session closed")
        ws = self.ws
        ws._id += 1
        msg_id = ws._id
        payload: dict[str, Any] = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        ws._send(json.dumps(payload, separators=(",", ":")))
        while True:
            raw = ws._recv()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._note(parsed)
            if parsed.get("id") != msg_id:
                continue
            if "error" in parsed:
                raise EngineError("cdp_error", str(parsed["error"]))
            result = parsed.get("result")
            return result if isinstance(result, dict) else {}

    def set_cursor(self, x: float, y: float, seq: int, animate: bool = True) -> None:
        state = json.dumps(
            {"cursor": {"x": x, "y": y, "visible": True, "animate": animate, "seq": seq}, "isVisible": True}
        )
        self._rpc(
            "Runtime.evaluate",
            {"expression": f"window.__cuocSetCursor && window.__cuocSetCursor({state})", "returnByValue": True},
        )

    def wait_arrived(self, seq: int, timeout: float | None = None) -> bool:
        if self.ws is None:
            return False
        needle = str(seq)
        if needle in self._arrivals:
            return True
        limit = ARRIVAL_TIMEOUT_MS / 1000.0 if timeout is None else timeout
        deadline = time.time() + limit
        while time.time() < deadline:
            try:
                self.ws._sock.settimeout(max(0.05, deadline - time.time()))
                raw = self.ws._recv()
            except Exception:
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            self._note(msg)
            if needle in self._arrivals:
                return True
        return False

    def mouse(self, event_type: str, x: float, y: float, button: str = "none") -> None:
        self._rpc("Input.dispatchMouseEvent", {"type": event_type, "x": x, "y": y, "button": button})

    def set_badge(self, kind: str | None) -> None:
        value = "null" if kind is None else json.dumps(kind)
        self._rpc(
            "Runtime.evaluate",
            {"expression": f"window.__cuocSetBadge && window.__cuocSetBadge({value})", "returnByValue": True},
        )

    def stop(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self._profile:
            try:
                self._profile.cleanup()
            except Exception:
                pass
            self._profile = None
