"""High-level browser API + sync host wrapping the asyncio bridge."""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import threading
from typing import Any

from ocuoc.browser.bridge import BrowserBridge
from ocuoc.browser.protocol import (
    ARRIVAL_TIMEOUT_MS,
    BADGE_ACTIVE,
    BADGE_DELIVERABLE,
    BADGE_HANDOFF,
    BADGE_SET,
    CDP_RAW,
    CURSOR_SET,
    INPUT_KEY,
    INPUT_MOUSE,
    INPUT_TEXT,
    PAGE_AXTREE,
    PAGE_DIALOG,
    PAGE_DOM,
    PAGE_EVAL,
    PAGE_SCREENSHOT,
    TAB_ACTIVATE,
    TAB_CLOSE,
    TAB_NEW,
    TABS_LIST,
)
from ocuoc.browser.session import snapshot_id
from ocuoc.errors import EngineError
from ocuoc.keys import parse_hotkey

EVAL_ENV = "OCUOC_BROWSER_EVAL"


def parse_browser_chords(keys: list[str]) -> list[dict[str, Any]]:
    """Turn 'ctrl+a' / 'Enter' specs into CDP modifier bits + key name."""
    chords: list[dict[str, Any]] = []
    for spec in keys:
        mods, key = parse_hotkey(spec)
        bits = 0
        names: list[str] = []
        for mod in mods:
            if mod == "ctrl":
                bits |= 2
                names.append("ctrl")
            elif mod == "alt":
                bits |= 1
                names.append("alt")
            elif mod in {"meta", "win"}:
                bits |= 4
                names.append("meta")
            elif mod == "shift":
                bits |= 8
                names.append("shift")
        chords.append({"key": key, "modifiers": bits, "modNames": names})
    return chords


def _quad_center(quad: list[Any]) -> tuple[float, float] | None:
    if not isinstance(quad, (list, tuple)) or len(quad) < 8:
        return None
    xs = [float(quad[i]) for i in range(0, 8, 2)]
    ys = [float(quad[i]) for i in range(1, 8, 2)]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return None
    return (sum(xs) / 4.0, sum(ys) / 4.0)


def _valid_rect(rect: Any) -> bool:
    if not isinstance(rect, dict):
        return False
    try:
        return float(rect.get("width", 0)) > 0 and float(rect.get("height", 0)) > 0
    except (TypeError, ValueError):
        return False


def _ax_value(node: Any, key: str) -> str:
    raw = node.get(key) if isinstance(node, dict) else None
    if isinstance(raw, dict):
        return str(raw.get("value") or "")
    if raw:
        return str(raw)
    return ""


def merge_ax_dom(ax: Any, snapshot: Any) -> list[dict[str, Any]]:
    """Join Accessibility.getFullAXTree with DOMSnapshot layout bounds (CSS px)."""
    if isinstance(ax, dict):
        ax_nodes = ax.get("nodes") or []
    elif isinstance(ax, list):
        ax_nodes = ax
    else:
        ax_nodes = []
    layout_index: dict[int, dict[str, int]] = {}
    documents = (snapshot or {}).get("documents") if isinstance(snapshot, dict) else None
    if isinstance(documents, list) and documents:
        doc = documents[0] or {}
        nodes = doc.get("nodes") or {}
        backend_ids = nodes.get("backendNodeId") or []
        layout = doc.get("layout") or {}
        node_index = layout.get("nodeIndex") or []
        bounds = layout.get("bounds") or []
        for i, ni in enumerate(node_index):
            if not isinstance(ni, int) or ni < 0 or ni >= len(backend_ids) or i >= len(bounds):
                continue
            box = bounds[i]
            if not isinstance(box, (list, tuple)) or len(box) < 4:
                continue
            bid = int(backend_ids[ni])
            layout_index[bid] = {
                "x": int(round(float(box[0]))),
                "y": int(round(float(box[1]))),
                "width": int(round(float(box[2]))),
                "height": int(round(float(box[3]))),
            }
    elements: list[dict[str, Any]] = []
    idx = 0
    skip_roles = {"webarea", "document", "rootwebarea", "iframe", "none", "ignored"}
    for node in ax_nodes:
        if not isinstance(node, dict) or node.get("ignored"):
            continue
        name = _ax_value(node, "name")
        role = _ax_value(node, "role")
        if role.lower() in skip_roles or not name.strip():
            continue
        backend = node.get("backendDOMNodeId")
        rect = layout_index.get(int(backend)) if backend is not None else None
        elements.append(
            {
                "element_index": idx,
                "name": name,
                "control_type": role or "AX",
                "backendDOMNodeId": backend,
                "rect": rect,
                "source": "ax+dom",
            }
        )
        idx += 1
    return elements


_SKIP_DOM_TAGS = {
    "HTML",
    "HEAD",
    "BODY",
    "SCRIPT",
    "STYLE",
    "META",
    "LINK",
    "NOSCRIPT",
    "BR",
    "#comment",
    "#document",
}


def elements_from_dom(snapshot: Any, max_elements: int = 200) -> list[dict[str, Any]]:
    """Layout boxes from DOMSnapshot when the AX tree is missing or timed out."""
    if not isinstance(snapshot, dict):
        return []
    documents = snapshot.get("documents")
    if not isinstance(documents, list) or not documents:
        return []
    doc = documents[0] or {}
    nodes = doc.get("nodes") or {}
    backend_ids = nodes.get("backendNodeId") or []
    node_names = nodes.get("nodeName") or []
    layout = doc.get("layout") or {}
    node_index = layout.get("nodeIndex") or []
    bounds = layout.get("bounds") or []
    elements: list[dict[str, Any]] = []
    idx = 0
    limit = max(1, int(max_elements))
    for i, ni in enumerate(node_index):
        if idx >= limit:
            break
        if not isinstance(ni, int) or ni < 0 or i >= len(bounds):
            continue
        box = bounds[i]
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            continue
        try:
            width = float(box[2])
            height = float(box[3])
        except (TypeError, ValueError):
            continue
        if width < 8 or height < 8:
            continue
        tag = str(node_names[ni]) if ni < len(node_names) else ""
        if tag.upper() in _SKIP_DOM_TAGS:
            continue
        bid = int(backend_ids[ni]) if ni < len(backend_ids) else None
        elements.append(
            {
                "element_index": idx,
                "name": tag,
                "control_type": tag or "DOM",
                "backendDOMNodeId": bid,
                "rect": {
                    "x": int(round(float(box[0]))),
                    "y": int(round(float(box[1]))),
                    "width": int(round(width)),
                    "height": int(round(height)),
                },
                "source": "dom",
            }
        )
        idx += 1
    return elements


class BrowserApi:
    def __init__(self, bridge: BrowserBridge) -> None:
        self.bridge = bridge

    async def list_tabs(self) -> list[dict[str, Any]]:
        raw = await self.bridge.call(TABS_LIST)
        tabs = raw if isinstance(raw, list) else []
        return [self.bridge.tabs.stamp(t) for t in tabs if isinstance(t, dict)]

    async def new_tab(self, url: str | None = None, active: bool = True) -> dict[str, Any]:
        tab = await self.bridge.call(TAB_NEW, {"url": url or "about:blank", "active": active})
        if not isinstance(tab, dict):
            raise EngineError("bridge_error", "tab.new returned no tab")
        return self.bridge.tabs.stamp(tab)

    async def activate_tab(self, tab_id: int, generation: str | None = None) -> Any:
        await self._ensure_tab(tab_id, generation)
        return await self.bridge.call(TAB_ACTIVATE, {"tabId": int(tab_id)})

    async def close_tab(self, tab_id: int, generation: str | None = None) -> Any:
        await self._ensure_tab(tab_id, generation)
        return await self.bridge.call(TAB_CLOSE, {"tabId": int(tab_id)})

    async def device_pixel_ratio(self, tab_id: int) -> float:
        cached = self.bridge.tabs.dpr(tab_id)
        if cached:
            return cached
        try:
            res = await self.bridge.call(
                PAGE_EVAL,
                {"tabId": int(tab_id), "expression": "window.devicePixelRatio || 1", "awaitPromise": False},
            )
            raw = ((res or {}).get("result") or {}).get("value") if isinstance(res, dict) else res
            dpr = float(raw or 1.0) or 1.0
        except Exception:
            return 1.0
        return self.bridge.tabs.remember_dpr(tab_id, dpr)

    async def _ensure_tab(self, tab_id: int, generation: str | None = None) -> dict[str, Any]:
        if self.bridge.tabs.get(tab_id) is None:
            try:
                await self.list_tabs()
            except Exception:
                pass
        return self.bridge.tabs.require(tab_id, generation)

    async def screenshot(self, tab_id: int, generation: str | None = None) -> tuple[bytes, dict[str, Any]]:
        await self._ensure_tab(tab_id, generation)
        res = None
        last_exc: Exception | None = None
        for timeout in (15.0, 20.0):
            try:
                res = await self.bridge.call(PAGE_SCREENSHOT, {"tabId": int(tab_id)}, timeout=timeout)
                break
            except EngineError as exc:
                last_exc = exc
                if exc.code != "bridge_timeout":
                    raise
        if res is None:
            raise last_exc or EngineError("screenshot_failed", "page.screenshot timed out")
        data_url = (res or {}).get("dataUrl") if isinstance(res, dict) else ""
        if not data_url or "," not in str(data_url):
            raise EngineError("screenshot_failed", "page.screenshot returned no image")
        png = base64.b64decode(str(data_url).split(",", 1)[1])
        dpr = await self.device_pixel_ratio(tab_id)
        shot_id = secrets.token_hex(8)
        backend = "cdp"
        activated = False
        if isinstance(res, dict):
            backend = str(res.get("backend") or "cdp")
            activated = bool(res.get("activated"))
        meta = {
            "screenshot_id": shot_id,
            "dpr": dpr,
            "tab_id": int(tab_id),
            "capture_backend": backend,
            "tab_activated": activated,
        }
        return png, meta

    async def get_state(
        self,
        tab_id: int,
        generation: str | None = None,
        include_screenshot: bool = True,
        include_elements: bool = True,
        max_elements: int = 200,
    ) -> tuple[dict[str, Any], bytes | None]:
        info = await self._ensure_tab(tab_id, generation)
        dpr = await self.device_pixel_ratio(tab_id)
        payload: dict[str, Any] = {
            "tab_id": int(tab_id),
            "url": info.get("url") or "",
            "title": info.get("title") or "",
            "generation": info.get("generation") or "",
            "dpr": dpr,
            "active": bool(info.get("active")),
        }
        png = None
        if include_elements:
            ax: Any = {"nodes": []}
            dom: Any = {}
            limit = max(1, int(max_elements))
            ax_res, dom_res = await asyncio.gather(
                self.bridge.call(
                    PAGE_AXTREE,
                    {"tabId": int(tab_id), "depth": 20},
                    timeout=12.0,
                ),
                self.bridge.call(PAGE_DOM, {"tabId": int(tab_id)}, timeout=15.0),
                return_exceptions=True,
            )
            if isinstance(ax_res, Exception):
                payload["ax_error"] = str(ax_res) or ax_res.__class__.__name__
            else:
                ax = ax_res
            if isinstance(dom_res, Exception):
                payload["dom_error"] = str(dom_res) or dom_res.__class__.__name__
            else:
                dom = dom_res
            elements = merge_ax_dom(ax, dom)[:limit]
            if not elements:
                elements = elements_from_dom(dom, max_elements=limit)
            payload["elements"] = elements
            payload["snapshot_id"] = self.bridge.tabs.remember_snapshot(tab_id, snapshot_id(elements))
        if include_screenshot:
            png, meta = await self.screenshot(tab_id, generation=generation)
            payload.update(meta)
        payload["dialogs"] = self.bridge.tabs.pop_dialogs()
        return payload, png

    async def eval_js(self, tab_id: int, expression: str, await_promise: bool = False) -> Any:
        if not os.environ.get(EVAL_ENV):
            raise EngineError("eval_disabled", f"browser_eval is off; set {EVAL_ENV}=1 to enable")
        res = await self.bridge.call(
            PAGE_EVAL,
            {"tabId": int(tab_id), "expression": expression, "awaitPromise": bool(await_promise)},
        )
        if isinstance(res, dict):
            return (res.get("result") or {}).get("value")
        return res

    async def move_cursor(
        self,
        tab_id: int,
        x: float,
        y: float,
        *,
        wait_arrival: bool = True,
        tab_is_active: bool = True,
    ) -> bool:
        enabled = wait_arrival and tab_is_active
        seq = self.bridge.cursor.next_seq()
        waiter = None
        if enabled:
            waiter = self.bridge.cursor.register(tab_id, seq)
        try:
            await self.bridge.call(
                CURSOR_SET,
                {
                    "tabId": int(tab_id),
                    "seq": seq,
                    "x": x,
                    "y": y,
                    "visible": True,
                    "animate": enabled,
                },
            )
            if waiter is not None:
                try:
                    await asyncio.wait_for(waiter, ARRIVAL_TIMEOUT_MS / 1000.0)
                    return True
                except asyncio.TimeoutError:
                    return False
            return False
        finally:
            self.bridge.cursor.forget(tab_id, seq)

    async def _tab_active(self, tab_id: int) -> bool:
        info = self.bridge.tabs.get(tab_id)
        if info is not None and "active" in info:
            return bool(info["active"])
        try:
            tabs = await self.list_tabs()
        except Exception:
            return True
        for tab in tabs:
            if int(tab.get("tabId") or 0) == int(tab_id):
                return bool(tab.get("active"))
        return True

    def _lookup_element(self, elements: list[dict[str, Any]], element_index: int) -> dict[str, Any]:
        for el in elements:
            if int(el.get("element_index", -1)) == int(element_index):
                return el
        raise EngineError("unknown_element", f"element_index {element_index} not in last browser_get_state")

    def _rect_center(self, el: dict[str, Any]) -> tuple[float, float]:
        rect = el.get("rect")
        if not _valid_rect(rect):
            raise EngineError("element_not_interactable", "Element has no valid layout bounds")
        assert isinstance(rect, dict)
        return (
            float(rect.get("x", 0)) + float(rect.get("width", 0)) / 2.0,
            float(rect.get("y", 0)) + float(rect.get("height", 0)) / 2.0,
        )

    def _tab_size(self, tab_id: int) -> tuple[float, float]:
        info = self.bridge.tabs.get(tab_id) or {}
        return float(info.get("width") or 0), float(info.get("height") or 0)

    def _in_viewport(self, tab_id: int, x: float, y: float) -> bool:
        width, height = self._tab_size(tab_id)
        if width <= 0 or height <= 0:
            return True
        return 0 <= x <= width and 0 <= y <= height

    def _is_full_page_rect(self, tab_id: int, rect: dict[str, Any]) -> bool:
        width, height = self._tab_size(tab_id)
        if width <= 0 or height <= 0:
            return False
        try:
            rw = float(rect.get("width") or 0)
            rh = float(rect.get("height") or 0)
        except (TypeError, ValueError):
            return False
        return rw >= 0.9 * width and rh >= 0.85 * height

    async def _resolve_element_point(
        self,
        tab_id: int,
        elements: list[dict[str, Any]],
        element_index: int,
    ) -> tuple[float, float]:
        el = self._lookup_element(elements, element_index)
        rect = el.get("rect")
        if isinstance(rect, dict) and self._is_full_page_rect(tab_id, rect):
            raise EngineError("element_not_interactable", "Element fills the page; pick a child control")
        bid = el.get("backendDOMNodeId")
        if bid is not None:
            try:
                res = await self.bridge.call(
                    CDP_RAW,
                    {
                        "tabId": int(tab_id),
                        "method": "DOM.getContentQuads",
                        "params": {"backendNodeId": int(bid)},
                    },
                )
            except Exception as exc:
                raise EngineError("element_stale", f"DOM node {bid} is gone or not boxed ({exc})") from exc
            quads = (res or {}).get("quads") if isinstance(res, dict) else None
            if not quads:
                raise EngineError("element_stale", f"DOM node {bid} has no content quads")
            center = _quad_center(quads[0])
            if center is None:
                raise EngineError("element_not_interactable", "Element has no valid layout bounds")
            return center
        return self._rect_center(el)

    async def click(
        self,
        tab_id: int,
        x: float | None = None,
        y: float | None = None,
        *,
        button: str = "left",
        click_count: int = 1,
        modifiers: int = 0,
        element_index: int | None = None,
        elements: list[dict[str, Any]] | None = None,
        generation: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tab(tab_id, generation)
        if element_index is not None:
            if snapshot_id is not None:
                latest = self.bridge.tabs.snapshot(tab_id)
                if latest != snapshot_id:
                    raise EngineError(
                        "snapshot_mismatch",
                        f"element snapshot changed (expected {snapshot_id}, now {latest})",
                    )
            if not elements:
                raise EngineError("unknown_element", "call browser_get_state before clicking by element_index")
            x, y = await self._resolve_element_point(tab_id, elements, element_index)
            if not self._in_viewport(tab_id, float(x), float(y)):
                raise EngineError("element_not_in_viewport", f"element {element_index} center {x},{y} is outside the tab viewport")
        if x is None or y is None:
            raise EngineError("bad_coords", "click needs x,y or element_index")
        active = await self._tab_active(tab_id)
        arrived = await self.move_cursor(tab_id, float(x), float(y), tab_is_active=active)
        await self.bridge.call(
            INPUT_MOUSE,
            {"tabId": int(tab_id), "actions": [{"type": "mouseMoved", "x": x, "y": y, "button": "none"}]},
        )
        for i in range(1, max(1, click_count) + 1):
            await self.bridge.call(
                INPUT_MOUSE,
                {
                    "tabId": int(tab_id),
                    "actions": [
                        {
                            "type": "mousePressed",
                            "x": x,
                            "y": y,
                            "button": button,
                            "clickCount": i,
                            "modifiers": modifiers,
                        },
                        {
                            "type": "mouseReleased",
                            "x": x,
                            "y": y,
                            "button": button,
                            "clickCount": i,
                            "modifiers": modifiers,
                        },
                    ],
                },
            )
        return {"arrived": arrived, "x": x, "y": y, "button": button, "count": click_count}

    async def drag(
        self,
        tab_id: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        button: str = "left",
        modifiers: int = 0,
        generation: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tab(tab_id, generation)
        active = await self._tab_active(tab_id)
        await self.move_cursor(tab_id, x1, y1, tab_is_active=active)
        await self.bridge.call(
            INPUT_MOUSE,
            {
                "tabId": int(tab_id),
                "actions": [
                    {"type": "mousePressed", "x": x1, "y": y1, "button": button, "clickCount": 1, "modifiers": modifiers},
                ],
            },
        )
        await self.move_cursor(tab_id, x2, y2, wait_arrival=False)
        dist = ((float(x2) - float(x1)) ** 2 + (float(y2) - float(y1)) ** 2) ** 0.5
        steps = max(2, min(24, int(dist / 24.0) + 1))
        moves: list[dict[str, Any]] = []
        for i in range(1, steps + 1):
            t = i / steps
            moves.append(
                {
                    "type": "mouseMoved",
                    "x": float(x1) + (float(x2) - float(x1)) * t,
                    "y": float(y1) + (float(y2) - float(y1)) * t,
                    "button": button,
                    "modifiers": modifiers,
                }
            )
        moves.append(
            {"type": "mouseReleased", "x": x2, "y": y2, "button": button, "clickCount": 1, "modifiers": modifiers}
        )
        await self.bridge.call(INPUT_MOUSE, {"tabId": int(tab_id), "actions": moves})
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "steps": steps}

    async def type_text(self, tab_id: int, text: str, generation: str | None = None) -> dict[str, Any]:
        await self._ensure_tab(tab_id, generation)
        await self.bridge.call(INPUT_TEXT, {"tabId": int(tab_id), "text": text})
        return {"written": len(text)}

    async def press_keys(self, tab_id: int, keys: list[str], generation: str | None = None) -> dict[str, Any]:
        await self._ensure_tab(tab_id, generation)
        chords = parse_browser_chords([str(k) for k in keys])
        await self.bridge.call(INPUT_KEY, {"tabId": int(tab_id), "keys": keys, "chords": chords})
        return {"keys": keys, "chords": chords}

    async def scroll(
        self,
        tab_id: int,
        dy: int = 0,
        dx: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        generation: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tab(tab_id, generation)
        await self.bridge.call(
            INPUT_MOUSE,
            {
                "tabId": int(tab_id),
                "actions": [
                    {
                        "type": "mouseWheel",
                        "x": x,
                        "y": y,
                        "button": "none",
                        "deltaX": int(dx) * 120,
                        "deltaY": int(dy) * 120,
                    }
                ],
            },
        )
        return {"dx": dx, "dy": dy}

    async def set_badge(self, tab_id: int, kind: str | None) -> dict[str, Any]:
        if kind is not None and kind not in {BADGE_ACTIVE, BADGE_DELIVERABLE, BADGE_HANDOFF}:
            raise EngineError("bad_badge", f"badge kind must be active|deliverable|handoff, got {kind!r}")
        await self.bridge.call(BADGE_SET, {"tabId": int(tab_id), "kind": kind})
        return {"ok": True, "kind": kind}

    async def handle_dialog(self, tab_id: int, accept: bool = True, prompt_text: str = "") -> dict[str, Any]:
        await self.bridge.call(
            PAGE_DIALOG,
            {"tabId": int(tab_id), "accept": bool(accept), "promptText": prompt_text},
        )
        return {"ok": True, "accept": bool(accept)}

    def abort(self) -> None:
        self.bridge.cursor.abort_all()


class BrowserHost:
    """Background asyncio loop + BrowserBridge, called from sync MCP tools."""

    def __init__(self) -> None:
        self.bridge = BrowserBridge()
        self.api = BrowserApi(self.bridge)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._started = False
        self._elements: dict[int, list[dict[str, Any]]] = {}
        self._shots: dict[int, str] = {}
        self._snapshots: dict[int, str] = {}

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, name="ocuoc-browser-bridge", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self.bridge.close_server(), loop)
            try:
                fut.result(timeout=2.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=1.5)
        self._thread = None
        self._loop = None
        self._started = False
        self._ready.clear()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.run_until_complete(self.bridge.serve())
        self._ready.set()
        loop.run_forever()

    def _call(self, coro, timeout: float = 20.0):
        self.start()
        loop = self._loop
        if loop is None:
            raise EngineError("bridge_error", "browser bridge loop is not running")
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
        except TimeoutError as exc:
            raise EngineError("bridge_timeout", f"browser call timed out after {timeout:.1f}s") from exc

    def info(self) -> dict[str, Any]:
        self.start()
        connected = self.bridge.connected
        return {
            "ws_url": self.bridge.ws_url,
            "pairing_secret": self.bridge.token,
            "connected": connected,
            "extension_version": self.bridge.extension_version,
            "hint": None
            if connected
            else (
                "Load ext/ unpacked in Chrome (developer mode). Open the extension options page and "
                "paste ws_url plus pairing_secret from this result. chrome.debugger shows a system banner "
                "while attached; that is expected."
            ),
        }

    def abort(self, _reason: str | None = None) -> None:
        try:
            self.api.abort()
            if self.bridge.connected:
                tabs = list(self.bridge.tabs._tabs.values())
                for tab in tabs:
                    try:
                        self._call(self.api.set_badge(int(tab["tabId"]), None), timeout=2.0)
                    except Exception:
                        pass
        except Exception:
            pass

    def list_tabs(self) -> dict[str, Any]:
        tabs = self._call(self.api.list_tabs())
        return {"tabs": tabs}

    def open_tab(self, url: str | None = None, active: bool = True) -> dict[str, Any]:
        return self._call(self.api.new_tab(url, active=active))

    def close_tab(self, tab_id: int, generation: str | None = None) -> dict[str, Any]:
        self._call(self.api.close_tab(tab_id, generation=generation))
        return {"closed": True, "tab_id": int(tab_id)}

    def activate_tab(self, tab_id: int, generation: str | None = None) -> dict[str, Any]:
        self._call(self.api.activate_tab(tab_id, generation=generation))
        return {"activated": True, "tab_id": int(tab_id)}

    def screenshot(self, tab_id: int, generation: str | None = None) -> tuple[dict[str, Any], bytes]:
        png, meta = self._call(self.api.screenshot(tab_id, generation=generation), timeout=40.0)
        self._shots[int(tab_id)] = str(meta.get("screenshot_id") or "")
        return meta, png

    def get_state(
        self,
        tab_id: int,
        generation: str | None = None,
        include_screenshot: bool = True,
        include_elements: bool = True,
        max_elements: int = 200,
    ) -> tuple[dict[str, Any], bytes | None]:
        payload, png = self._call(
            self.api.get_state(
                tab_id,
                generation=generation,
                include_screenshot=include_screenshot,
                include_elements=include_elements,
                max_elements=max_elements,
            ),
            timeout=55.0,
        )
        self._elements[int(tab_id)] = list(payload.get("elements") or [])
        if payload.get("snapshot_id"):
            self._snapshots[int(tab_id)] = str(payload["snapshot_id"])
        if payload.get("screenshot_id"):
            self._shots[int(tab_id)] = str(payload["screenshot_id"])
        return payload, png

    def click(
        self,
        tab_id: int,
        x: float | None = None,
        y: float | None = None,
        button: str = "left",
        count: int = 1,
        element_index: int | None = None,
        generation: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call(
            self.api.click(
                tab_id,
                x,
                y,
                button=button,
                click_count=count,
                element_index=element_index,
                elements=self._elements.get(int(tab_id)),
                generation=generation,
                snapshot_id=snapshot_id if snapshot_id is not None else self._snapshots.get(int(tab_id)),
            )
        )

    def drag(
        self,
        tab_id: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        button: str = "left",
        generation: str | None = None,
    ) -> dict[str, Any]:
        return self._call(self.api.drag(tab_id, x1, y1, x2, y2, button=button, generation=generation))

    def type_text(self, tab_id: int, text: str, generation: str | None = None) -> dict[str, Any]:
        return self._call(self.api.type_text(tab_id, text, generation=generation))

    def press_keys(self, tab_id: int, keys: list[str] | str, generation: str | None = None) -> dict[str, Any]:
        if isinstance(keys, str):
            keys = [part.strip() for part in keys.split(",") if part.strip()]
        return self._call(self.api.press_keys(tab_id, keys, generation=generation))

    def scroll(
        self,
        tab_id: int,
        dy: int = 0,
        dx: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        generation: str | None = None,
    ) -> dict[str, Any]:
        return self._call(self.api.scroll(tab_id, dy=dy, dx=dx, x=x, y=y, generation=generation))

    def eval_js(self, tab_id: int, expression: str, await_promise: bool = False) -> dict[str, Any]:
        value = self._call(self.api.eval_js(tab_id, expression, await_promise=await_promise))
        return {"value": value}

    def mark_deliverable(self, tab_id: int) -> dict[str, Any]:
        return self._call(self.api.set_badge(tab_id, BADGE_DELIVERABLE))

    def mark_handoff(self, tab_id: int) -> dict[str, Any]:
        return self._call(self.api.set_badge(tab_id, BADGE_HANDOFF))

    def mark_active(self, tab_id: int) -> dict[str, Any]:
        return self._call(self.api.set_badge(tab_id, BADGE_ACTIVE))

    def handle_dialog(self, tab_id: int, accept: bool = True, prompt_text: str = "") -> dict[str, Any]:
        return self._call(self.api.handle_dialog(tab_id, accept=accept, prompt_text=prompt_text))
