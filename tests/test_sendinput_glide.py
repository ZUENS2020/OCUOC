from ocuoc.input import sendinput
from ocuoc.input.motion import DT, PRESS_MS, iter_move_frames


def test_iter_move_frames_sixty_hz_and_arrives():
    frames = iter_move_frames((0.0, 0.0), (400.0, 150.0))
    assert len(frames) >= 10
    assert frames[-1] == (400.0, 150.0)
    assert abs(DT - 1.0 / 60.0) < 1e-9


def test_glide_sends_a_frame_per_tick(monkeypatch):
    pts: list[tuple[int, int]] = []
    monkeypatch.setattr(sendinput, "cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(sendinput, "_move_now", lambda x, y: pts.append((x, y)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sendinput.time, "perf_counter", lambda: 0.0)
    sendinput.move_abs(90, 0)
    # short move: T=0.24s spring, ~60Hz frames until settle, then the target
    assert len(pts) >= 8
    assert pts[-1] == (90, 0)


def test_glide_long_move_arcs(monkeypatch):
    pts: list[tuple[int, int]] = []
    monkeypatch.setattr(sendinput, "cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(sendinput, "_move_now", lambda x, y: pts.append((x, y)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sendinput.time, "perf_counter", lambda: 0.0)
    sendinput.move_abs(500, 0)
    assert len(pts) >= 15
    assert pts[-1] == (500, 0)
    # >196px: bulged two-segment path leaves the straight line
    assert max(abs(y) for _x, y in pts) > 1


def test_tiny_move_snaps(monkeypatch):
    pts: list[tuple[int, int]] = []
    monkeypatch.setattr(sendinput, "cursor_pos", lambda: (10, 10))
    monkeypatch.setattr(sendinput, "_move_now", lambda x, y: pts.append((x, y)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    sendinput.move_abs(10, 10)
    assert pts == [(10, 10)]


def test_glide_cancel_stops_early(monkeypatch):
    pts: list[tuple[int, int]] = []
    monkeypatch.setattr(sendinput, "cursor_pos", lambda: (0, 0))
    monkeypatch.setattr(sendinput, "_move_now", lambda x, y: pts.append((x, y)))
    monkeypatch.setattr(sendinput.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sendinput.time, "perf_counter", lambda: 0.0)
    sendinput.move_abs(500, 0, proceed=lambda: False)
    assert pts == []


def test_press_hold_is_one_hundred_ms():
    assert PRESS_MS == 100
