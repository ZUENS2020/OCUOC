from ocuoc.capture.screenshot import CaptureResult
from ocuoc.engine import ComputerUseEngine
from ocuoc.errors import EngineError
from ocuoc.wm.windows import WindowInfo


def _shot(screenshot_id: str) -> CaptureResult:
    return CaptureResult(
        png=b"\x89PNG",
        image_w=100,
        image_h=100,
        src_w=100,
        src_h=100,
        origin_x=0,
        origin_y=0,
        backend="test",
        screenshot_id=screenshot_id,
    )


def test_unknown_screenshot_id_is_rejected():
    engine = ComputerUseEngine()
    engine._shot["hwnd:1"] = _shot("aaaaaaaaaaaaaaaa")
    try:
        engine._require_shot("hwnd:1", "bbbbbbbbbbbbbbbb")
    except EngineError as exc:
        assert exc.code == "unknown_screenshot_id"
        return
    raise AssertionError("expected unknown_screenshot_id")


def test_matching_screenshot_id_returns_cache():
    engine = ComputerUseEngine()
    cached = _shot("aaaaaaaaaaaaaaaa")
    engine._shot["hwnd:1"] = cached
    assert engine._require_shot("hwnd:1", "aaaaaaaaaaaaaaaa") is cached
    assert engine._require_shot("hwnd:1", None) is cached


def test_map_xy_uses_client_origin_and_scale():
    engine = ComputerUseEngine()
    info = WindowInfo(
        hwnd=1,
        title="t",
        pid=1,
        exe="x.exe",
        class_name="c",
        rect=(0, 0, 200, 200),
        client_rect=(8, 31, 192, 192),
    )
    engine._shot["hwnd:1"] = CaptureResult(
        png=b"\x89PNG",
        image_w=184,
        image_h=161,
        src_w=184,
        src_h=161,
        origin_x=8,
        origin_y=31,
        backend="test",
        screenshot_id="aaaaaaaaaaaaaaaa",
    )
    assert engine._map_xy(info, 10, 10, "aaaaaaaaaaaaaaaa") == (18, 41)
