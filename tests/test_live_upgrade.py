from pathlib import Path

import pytest

from ocuoc.engine import ComputerUseEngine, ViewResult

STEAM = Path(r"F:\steam\steam.exe")


def _payload(state):
    if isinstance(state, ViewResult):
        return state.payload, state.png
    return state, None


@pytest.mark.live
def test_steam_launch_matches_webhelper_window():
    if not STEAM.is_file():
        pytest.skip("Steam is not installed at F:\\steam\\steam.exe")
    engine = ComputerUseEngine()
    launched = engine.launch_app(str(STEAM), timeout_s=30)
    assert launched["window_id"].startswith("hwnd:")
    exe = (launched.get("exe") or "").lower()
    title = (launched.get("title") or "").lower()
    assert "steam" in exe or "steam" in title


@pytest.mark.live
def test_electron_or_chromium_window_has_webview_probe():
    engine = ComputerUseEngine()
    target = None
    for item in engine.list_windows()["windows"]:
        cls = (item.get("class_name") or "").lower()
        exe = (item.get("exe") or "").lower()
        if "chrome_widgetwin" in cls or "cursor.exe" in exe or "code.exe" in exe:
            target = item
            break
    if target is None:
        pytest.skip("no Chromium/Electron window is open")
    bundle = engine.get_window_state(target["window_id"], include_screenshot=True, include_elements=True)
    state, png = _payload(bundle)
    assert png is not None and png.startswith(b"\x89PNG")
    webview = state.get("webview") or {}
    assert "source" in webview
    if webview.get("kind") in {"electron", "chromium", "webview2"}:
        assert webview.get("source") in {"uia", "cdp", "none"}
        if webview.get("source") == "none":
            assert webview.get("reason")
        else:
            assert len(state.get("elements") or []) >= 1
    else:
        assert webview.get("reason")
