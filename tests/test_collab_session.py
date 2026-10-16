import os

from ocuoc.collab.cursor_agent import event_name
from ocuoc.collab.cursor_supervisor import running_python
from ocuoc.collab.session import Collaboration
from ocuoc.input import sendinput
from ocuoc.policy.guard import Guard


class Rec:
    def __init__(self) -> None:
        self.calls: list = []
        self.alive = True
        self.on_pulse = None

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    def show_at(self, x: int, y: int, press: bool = False) -> None:
        self.calls.append(("show", x, y, press))

    def hide(self) -> None:
        self.calls.append("hide")

    def wait_idle(self, timeout: float = 0.25) -> None:
        self.calls.append(("wait", timeout))

    def suppress(self, wait: bool = True) -> None:
        self.calls.append(("suppress", wait))

    def restore(self, wait: bool = True) -> None:
        self.calls.append(("restore", wait))

    def ensure_suppressed(self) -> None:
        self.calls.append("ensure")


def _collab():
    guard = Guard()
    overlay = Rec()
    cursor = Rec()
    hooks = Rec()
    collab = Collaboration(guard, hooks=hooks, overlay=overlay, cursor=cursor)
    collab.start()
    return guard, collab, overlay, cursor


def test_physical_esc_swallows_and_aborts():
    guard, collab, overlay, cursor = _collab()
    collab.begin(10, 20)
    assert collab.handle_key(0, 0x1B, 0x0100) is True
    assert guard.allow_input() is False
    assert guard.reason() == "esc"
    assert collab.supervising is False
    assert "hide" in overlay.calls
    assert ("restore", False) in cursor.calls


def test_injected_esc_does_not_abort():
    guard, collab, _overlay, _cursor = _collab()
    collab.begin(10, 20)
    assert collab.handle_key(0x10, 0x1B, 0x0100) is False
    assert guard.allow_input() is True
    assert collab.supervising is True


def test_physical_click_same_pid_interrupts_without_swallow():
    guard, collab, overlay, cursor = _collab()
    collab.begin(10, 20)
    assert collab.handle_mouse(0, 0x0201, 99, 20) is False
    assert guard.reason() == "human_click"
    assert collab.supervising is False
    assert "hide" in overlay.calls
    assert ("restore", False) in cursor.calls


def test_injected_click_and_other_pid_do_not_interrupt():
    guard, collab, _overlay, _cursor = _collab()
    collab.begin(10, 20)
    assert collab.handle_mouse(0x01, 0x0201, 99, 20) is False
    assert collab.handle_mouse(0, 0x0201, 99, 999) is False
    assert guard.allow_input() is True
    assert collab.supervising is True


def test_observe_reports_takeover_and_resets_abort():
    guard, collab, _overlay, _cursor = _collab()
    collab.begin(10, 20)
    collab.handle_key(0, 0x1B, 0x0100)
    meta = collab.resume_after_observe()
    assert meta["human_takeover"] is True
    assert meta["takeover_reason"] == "esc"
    assert guard.allow_input() is True
    assert collab.supervising is False


def test_observe_without_abort_parks_overlay():
    guard, collab, overlay, cursor = _collab()
    collab.begin(10, 20)
    collab.point_to(4, 8, press=True)
    meta = collab.resume_after_observe()
    assert meta["human_takeover"] is False
    assert guard.allow_input() is True
    assert collab.supervising is False
    assert ("show", 4, 8, True) in overlay.calls
    assert "hide" not in overlay.calls
    assert ("restore", True) in cursor.calls


def test_begin_after_start_does_not_suppress():
    _guard, collab, overlay, cursor = _collab()
    collab.begin(10, 20)
    assert overlay.alive is True
    assert ("suppress", False) not in cursor.calls


def test_point_to_shows_then_suppresses():
    _guard, collab, overlay, cursor = _collab()
    collab.begin(10, 20)
    collab.point_to(4, 8, press=True)
    assert overlay.calls.index(("show", 4, 8, True)) == 1
    assert cursor.calls[-1] == ("suppress", False)


def test_pulse_ensures_while_supervising():
    _guard, collab, _overlay, cursor = _collab()
    collab._pulse()
    assert "ensure" not in cursor.calls
    collab.begin(10, 20)
    collab._pulse()
    assert "ensure" in cursor.calls


def test_begin_without_start_does_not_touch_cursor():
    guard = Guard()
    cursor = Rec()
    collab = Collaboration(guard, hooks=Rec(), overlay=Rec(), cursor=cursor)
    collab.begin(1, 2)
    assert collab.supervising is True
    assert cursor.calls == []


def test_running_python_is_a_real_image():
    path = running_python()
    assert os.path.isfile(path)
    assert path.lower().endswith(".exe")


def test_cursor_event_names():
    assert event_name(123, "ready") == "Local\\OcuocCursor-123-ready"
    assert event_name(123, "shutdown") == "Local\\OcuocCursor-123-shutdown"


def test_wait_overlay_uses_overlay_move_timeout():
    guard, collab, overlay, _cursor = _collab()
    overlay.move_timeout = 1.5
    collab.wait_overlay()
    assert ("wait", 1.5) in overlay.calls


def test_type_text_stops_when_proceed_false(monkeypatch):
    sent: list[int] = []
    monkeypatch.setattr(sendinput, "_send", lambda inputs: sent.append(len(inputs)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    assert sendinput.type_text("abc", proceed=lambda: False) == 0
    assert sent == []
    assert sendinput.type_text("ab", proceed=lambda: True) == 2
    assert sent == [2, 2]
