from types import SimpleNamespace

from ocuoc.engine import ComputerUseEngine
from ocuoc.input import sendinput
from ocuoc.wm.windows import WindowInfo


class FakeOverlay:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive


class FakeCollab:
    def __init__(self, overlay_alive: bool = True) -> None:
        self.calls: list = []
        self.overlay = FakeOverlay(overlay_alive)

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    def begin(self, hwnd: int, pid: int) -> None:
        self.calls.append(("begin", hwnd, pid))

    def point_to(self, x: int, y: int, press: bool = False) -> None:
        self.calls.append(("point_to", x, y, press))

    def wait_overlay(self, timeout: float = 1.15) -> None:
        self.calls.append(("wait_overlay", timeout))

    def resume_after_observe(self) -> dict:
        return {"human_takeover": False, "takeover_reason": ""}

    def end_session(self, restore: bool = True, wait: bool = True) -> None:
        self.calls.append(("end", restore, wait))


def _info() -> WindowInfo:
    return WindowInfo(
        hwnd=42,
        title="t",
        pid=7,
        exe="x.exe",
        class_name="C",
        rect=(0, 0, 100, 100),
        client_rect=(0, 0, 100, 100),
    )


def _patch_window(monkeypatch, info: WindowInfo) -> None:
    monkeypatch.setattr("ocuoc.engine.wm.get_window", lambda _wid: info)
    monkeypatch.setattr("ocuoc.engine.wm.activate", lambda _info: None)
    monkeypatch.setattr("ocuoc.engine.privilege_snapshot", lambda: SimpleNamespace(elevated=False))


def test_click_points_then_snaps(monkeypatch):
    collab = FakeCollab(overlay_alive=True)
    engine = ComputerUseEngine(collab=collab)
    engine.start()
    _patch_window(monkeypatch, _info())
    sent: list = []
    monkeypatch.setattr(
        sendinput,
        "click_abs",
        lambda x, y, **kw: sent.append((x, y, kw.get("animate"))),
    )
    out = engine.click("hwnd:42", x=10, y=20)
    assert out["screen_x"] == 10
    assert out["screen_y"] == 20
    assert ("begin", 42, 7) in collab.calls
    assert ("point_to", 10, 20, True) in collab.calls
    assert any(isinstance(c, tuple) and c[0] == "wait_overlay" for c in collab.calls)
    assert sent == [(10, 20, False)]
    assert collab.calls[-1] == ("end", True, True)


def test_click_glides_when_overlay_dead(monkeypatch):
    collab = FakeCollab(overlay_alive=False)
    engine = ComputerUseEngine(collab=collab)
    engine.start()
    _patch_window(monkeypatch, _info())
    sent: list = []
    monkeypatch.setattr(
        sendinput,
        "click_abs",
        lambda x, y, **kw: sent.append((x, y, kw.get("animate"))),
    )
    engine.click("hwnd:42", x=10, y=20)
    assert ("point_to", 10, 20, True) in collab.calls
    assert not any(isinstance(c, tuple) and c[0] == "wait_overlay" for c in collab.calls)
    assert sent == [(10, 20, True)]
    assert collab.calls[-1] == ("end", True, True)
