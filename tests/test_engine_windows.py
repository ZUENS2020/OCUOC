from ocuoc.engine import ComputerUseEngine
from ocuoc.errors import EngineError


def test_list_windows_shape():
    engine = ComputerUseEngine()
    windows = engine.list_windows()["windows"]
    assert isinstance(windows, list)
    for item in windows:
        assert item["window_id"].startswith("hwnd:")
        assert "generation" in item
        assert len(item["generation"]) == 16
        assert "bounds" in item
        assert "client_bounds" in item


def test_get_window_roundtrip():
    engine = ComputerUseEngine()
    windows = engine.list_windows()["windows"]
    if not windows:
        return
    found = engine.get_window(windows[0]["window_id"])
    assert found["window_id"] == windows[0]["window_id"]
    assert found["generation"] == windows[0]["generation"]


def test_stale_generation_rejects_click():
    engine = ComputerUseEngine()
    windows = engine.list_windows()["windows"]
    if not windows:
        return
    target = windows[0]
    try:
        engine.click(target["window_id"], generation="0000000000000000", x=8, y=8)
    except EngineError as exc:
        assert exc.code == "generation_mismatch"
        return
    raise AssertionError("expected generation_mismatch")
