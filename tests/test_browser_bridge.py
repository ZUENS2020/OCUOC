"""Fake-extension protocol tests for browser P0–P3 (not live)."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import time

import pytest

from ocuoc.browser.api import BrowserApi, merge_ax_dom
from ocuoc.browser.bridge import BrowserBridge, WSConn
from ocuoc.browser.fake import FakeExtension
from ocuoc.browser.overlay_js import content_cursor_js, content_cursor_sha256
from ocuoc.browser.session import tab_generation
from ocuoc.errors import EngineError
from ocuoc.server import mcp


async def _paired():
    bridge = BrowserBridge()
    host, port = await bridge.serve()
    fake = FakeExtension(f"ws://{host}:{port}", bridge.token)
    task = asyncio.create_task(fake.run())
    api = BrowserApi(bridge)
    for _ in range(50):
        if bridge.connected:
            break
        await asyncio.sleep(0.02)
    assert bridge.connected
    return bridge, api, fake, task


async def _close(bridge, task):
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    await bridge.close_server()


def test_overlay_js_ships_cuoc_idents():
    src = content_cursor_js()
    assert "CUOC_CURSOR_ARRIVED" in src
    assert "CUOC_BADGE_SET" in src
    assert "cuocCursorArrived" in src
    assert len(content_cursor_sha256()) == 64


def test_overlay_js_uses_documented_plugin_plane():
    src = content_cursor_js()
    assert "M3.045 4.453" in src
    assert "translate(-2 -2) scale(2.1)" in src
    assert "rotate(44deg)" in src
    assert "#339cff" in src


def _masked_frame(opcode: int, payload: bytes, *, fin: bool = True, mask: bytes = b"\x01\x02\x03\x04") -> bytes:
    b0 = (0x80 if fin else 0x00) | opcode
    n = len(payload)
    header = bytes([b0])
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return header + mask + masked


class _NullWriter:
    def write(self, _data: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_extra_info(self, _name: str):
        return ("127.0.0.1", 1)


def test_wsconn_reassembles_fragmented_text():
    async def run():
        reader = asyncio.StreamReader()
        conn = WSConn(reader, _NullWriter())  # type: ignore[arg-type]
        body = json.dumps({"ok": True, "blob": "x" * 200})
        mid = len(body) // 2
        reader.feed_data(_masked_frame(0x1, body[:mid].encode(), fin=False))
        reader.feed_data(_masked_frame(0x0, body[mid:].encode(), fin=True))
        got = await asyncio.wait_for(conn.recv(), 1)
        assert json.loads(got) == json.loads(body)

    asyncio.run(run())


def test_tab_generation_is_tab_plus_url():
    a = tab_generation(3, "https://example.com/")
    b = tab_generation(3, "https://example.com/")
    c = tab_generation(3, "https://other.example/")
    assert a == b
    assert a != c
    assert len(a) == 16


def test_merge_ax_dom_assigns_element_index_and_css_rect():
    ax = {
        "nodes": [
            {"ignored": False, "role": {"value": "button"}, "name": {"value": "Go"}, "backendDOMNodeId": 1},
            {"ignored": True, "role": {"value": "none"}, "backendDOMNodeId": 2},
        ]
    }
    dom = {
        "documents": [
            {
                "nodes": {"backendNodeId": [1, 2]},
                "layout": {"nodeIndex": [0], "bounds": [[10.0, 20.0, 80.0, 24.0]]},
            }
        ]
    }
    els = merge_ax_dom(ax, dom)
    assert len(els) == 1
    assert els[0]["element_index"] == 0
    assert els[0]["name"] == "Go"
    assert els[0]["rect"] == {"x": 10, "y": 20, "width": 80, "height": 24}


def test_p0_tabs_and_screenshot():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            tabs = await api.list_tabs()
            assert tabs[0]["tabId"] == 42
            assert tabs[0]["generation"] == tab_generation(42, "https://example.com/")
            opened = await api.new_tab("https://example.org/")
            assert opened["tabId"] == 43
            png, meta = await api.screenshot(42)
            assert png[:8] == b"\x89PNG\r\n\x1a\n"
            assert meta["dpr"] == 2.0
            await api.activate_tab(42)
            await api.close_tab(43)
            assert "tabs.list" in fake.order
            assert "page.screenshot" in fake.order
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p1_click_arrives_before_press():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            t0 = time.monotonic()
            out = await api.click(42, 900, 300, click_count=2)
            dt = (time.monotonic() - t0) * 1000
            assert out["arrived"] is True
            assert 600 <= dt <= 1500
            assert fake.order.index("input.mouse[mouseMoved]") > fake.order.index("cursor.set#1@900,300")
            presses = [o for o in fake.order if o.startswith("input.mouse[mousePressed")]
            assert len(presses) == 2
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p1_inactive_tab_skips_arrival_wait():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            fake.tabs[0]["active"] = False
            t0 = time.monotonic()
            arrived = await api.move_cursor(42, 10, 10, tab_is_active=False)
            dt = time.monotonic() - t0
            assert arrived is False
            assert dt < 0.4
            assert 1 not in fake.seq_arrived
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p1_arrival_timeout_releases():
    async def run():
        bridge, api, fake, task = await _paired()
        fake.simulated_animate_ms = 2500
        try:
            t0 = time.monotonic()
            arrived = await api.move_cursor(42, 50, 50)
            dt = time.monotonic() - t0
            assert arrived is False
            assert 1.4 <= dt <= 2.2
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p1_drag_second_move_does_not_wait():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            await api.drag(42, 10, 10, 80, 80)
            sets = [o for o in fake.order if o.startswith("cursor.set#")]
            assert len(sets) == 2
            assert "input.mouse[mouseMoved+mouseReleased]" in fake.order
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p2_get_state_elements_and_dpr():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            payload, png = await api.get_state(42)
            assert payload["dpr"] == 2.0
            assert payload["generation"] == tab_generation(42, "https://example.com/")
            assert payload["elements"][0]["element_index"] == 0
            assert payload["elements"][0]["rect"]["width"] == 80
            assert png
            clicked = await api.click(42, element_index=0, elements=payload["elements"])
            assert clicked["x"] == 50.0
            assert clicked["y"] == 32.0
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p2_eval_default_off(monkeypatch):
    async def run():
        bridge, api, fake, task = await _paired()
        monkeypatch.delenv("OCUOC_BROWSER_EVAL", raising=False)
        try:
            with pytest.raises(EngineError) as exc:
                await api.eval_js(42, "1+1")
            assert exc.value.code == "eval_disabled"
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p2_eval_when_enabled(monkeypatch):
    async def run():
        bridge, api, fake, task = await _paired()
        monkeypatch.setenv("OCUOC_BROWSER_EVAL", "1")
        try:
            await api.eval_js(42, "1+1")
            assert "page.eval" in fake.order
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_p3_badge_and_dialog_and_esc_abort():
    async def run():
        bridge, api, fake, task = await _paired()
        try:
            await api.set_badge(42, "deliverable")
            await api.set_badge(42, "handoff")
            await api.set_badge(42, "active")
            assert fake.badges[42] == "active"
            await fake.emit_dialog(42, "sure?")
            await asyncio.sleep(0.05)
            dialogs = bridge.tabs.pop_dialogs()
            assert dialogs and dialogs[0]["message"] == "sure?"
            await api.handle_dialog(42, accept=True)
            assert "page.dialog" in fake.order
            waiter = bridge.cursor.register(42, 99)
            api.abort()
            await asyncio.sleep(0.01)
            assert waiter.cancelled()
        finally:
            await _close(bridge, task)

    asyncio.run(run())


def test_mcp_registers_browser_tools():
    names = {t.name for t in mcp._tool_manager.list_tools()}
    for name in (
        "browser_bridge_info",
        "browser_list_tabs",
        "browser_open_tab",
        "browser_close_tab",
        "browser_activate_tab",
        "browser_screenshot",
        "browser_click",
        "browser_double_click",
        "browser_right_click",
        "browser_type_text",
        "browser_press_keys",
        "browser_scroll",
        "browser_drag",
        "browser_get_state",
        "browser_eval",
        "browser_mark_deliverable",
        "browser_mark_handoff",
        "browser_handle_dialog",
    ):
        assert name in names


def test_browser_bridge_info_schema_has_no_token_param():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    blob = str(tools["browser_bridge_info"].parameters).lower()
    assert "token" not in blob
    _ = os.environ
