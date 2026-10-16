from ocuoc.collab.overlay import Overlay
from ocuoc.input import sendinput
from ocuoc.input.motion_browser import ARRIVAL_TIMEOUT_MS, BezierMotion, ScootMotion, iter_move_frames
from ocuoc.input.profile import PROFILE_BROWSER


def test_overlay_browser_timeout_is_1500ms():
    ov = Overlay(profile="browser")
    assert ov.profile == PROFILE_BROWSER
    assert abs(ov.move_timeout - ARRIVAL_TIMEOUT_MS / 1000.0) < 1e-9
    desk = Overlay(profile="desktop")
    assert desk.move_timeout == 3.0


def test_browser_glide_stops_on_arrival(monkeypatch):
    pts: list[tuple[int, int]] = []
    monkeypatch.setenv("OCUOC_CURSOR_PROFILE", PROFILE_BROWSER)
    monkeypatch.setattr(sendinput, "cursor_pos", lambda: (10, 10))
    monkeypatch.setattr(sendinput, "_move_now", lambda x, y: pts.append((x, y)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sendinput.time, "perf_counter", lambda: 0.0)
    monkeypatch.setattr(sendinput, "_virtual_bounds", lambda: (1280.0, 800.0))
    sendinput.move_abs(205, 10)
    assert pts
    assert pts[-1] == (205, 10)
    assert len(pts) >= 3


def test_browser_frames_do_not_require_think_for_sendinput():
    frames = []
    for t, st in iter_move_frames((0.0, 0.0), (80.0, 0.0), (1280.0, 800.0)):
        frames.append((t, st.motion is None, st.point))
        if st.motion is None:
            break
    assert frames
    assert frames[-1][1] is True
    kinds = []
    st0 = None
    for _t, st in iter_move_frames((0.0, 0.0), (80.0, 0.0), (1280.0, 800.0)):
        st0 = st
        kinds.append(type(st.motion).__name__ if st.motion else None)
        if st.motion is None:
            break
    assert st0 is not None
    assert ARRIVAL_TIMEOUT_MS == 1500.0
    assert ScootMotion and BezierMotion
