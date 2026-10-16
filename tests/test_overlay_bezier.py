"""Motion-model tests for the replicated Codex cursor animation.

Evidence-based expectations from docs/2026-10-16-codex-cursor-animation-re.md.
"""

import math

from ocuoc.collab.overlay import (
    TIMER_ANIM,
    TIMER_PRESS,
    TIMER_PULSE,
    WM_OCUOC_MOVE,
    Overlay,
)
from ocuoc.input.motion import (
    DT,
    MAX_WAYPOINTS,
    SHORT_MAX_PX,
    SIM_CAP_S,
    T_MAX,
    T_MIN,
    T_SHORT,
    ZETA_LONG,
    ZETA_SHORT,
    build_move,
    direction_noise,
    iter_move_frames,
    simulate,
    squash_scale,
)
from ocuoc.winapi import SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW, SW_SHOWNOACTIVATE


def test_short_move_is_single_cubic_with_third_controls():
    plan = build_move((0.0, 0.0), (150.0, 90.0))
    assert len(plan.segments) == 1
    assert plan.T == T_SHORT
    assert plan.zeta == ZETA_SHORT
    seg = plan.segments[0]
    # controls sit at exactly 1/3 and 2/3 of the straight line
    assert seg[1] == (50.0, 30.0)
    assert seg[2] == (100.0, 60.0)
    # short moves carry no waypoint wobble
    assert plan.wobble_at(0.5) == 0.0


def test_below_half_pixel_teleports():
    assert build_move((10.0, 10.0), (10.3, 10.2)).snapped is True
    just_over = build_move((10.0, 10.0), (10.0, 10.6))
    assert just_over.snapped is False
    assert just_over.T == T_SHORT


def test_boundary_at_196px():
    assert build_move((0.0, 0.0), (196.0, 0.0)).zeta == ZETA_SHORT
    assert build_move((0.0, 0.0), (196.1, 0.0)).zeta == ZETA_LONG


def test_long_move_bulges_and_splits():
    plan = build_move((0.0, 0.0), (600.0, 200.0))
    assert plan.zeta == ZETA_LONG
    assert T_MIN <= plan.T <= T_MAX
    assert len(plan.segments) >= 2
    assert 48.0 <= abs(plan.bulge) <= 640.0
    assert plan.arc > plan.chord  # the path bulges away from the chord
    # joints must deviate from the straight start->target line
    sx, sy = plan.start
    tx, ty = plan.target
    dx, dy = tx - sx, ty - sy
    chord = math.hypot(dx, dy)
    for seg in plan.segments[1:]:
        jx, jy = seg[0]
        perp = abs((jx - sx) * dy - (jy - sy) * dx) / chord
        assert perp > 1.0


def test_waypoint_cap_respected():
    plan = build_move((0.0, 0.0), (4000.0, 2500.0))
    joints = len(plan.segments) - 1
    assert joints <= MAX_WAYPOINTS


def test_sampler_endpoints_and_continuity():
    plan = build_move((30.0, 40.0), (700.0, 380.0))
    pos0, _ = plan.sample(0.0)
    pos1, _ = plan.sample(1.0)
    assert pos0 == (30.0, 40.0)
    assert pos1 == (700.0, 380.0)
    prev = None
    for i in range(201):
        pos, _tan = plan.sample(i / 200.0)
        if prev is not None:
            assert math.hypot(pos[0] - prev[0], pos[1] - prev[1]) < 12.0
        prev = pos


def test_spring_settles_on_first_approach():
    # continuous system is underdamped, but the loose |v|<=0.99898 settle
    # check fires on first approach and forces the exact arrival sample —
    # the original never renders a visible overshoot either
    samples = simulate(T_SHORT, ZETA_SHORT)
    raw = [p for _t, p, _v in samples]
    assert max(raw) < 1.001
    assert samples[-1][1] == 1.0
    assert samples[-1][2] == 0.0
    ts = [t for t, _p, _v in samples]
    assert ts == sorted(ts)
    assert ts[-1] <= SIM_CAP_S
    # 0.24s factor still settles in a fraction of a second
    assert ts[-1] < 0.6


def test_spring_respects_cap():
    samples = simulate(T_MAX, ZETA_LONG)
    assert len(samples) <= int(SIM_CAP_S / DT) + 2
    assert samples[-1][1] == 1.0  # arrival is always forced


def test_squash_scales_with_speed():
    assert squash_scale(0.0) == 1.0
    assert abs(squash_scale(3000.0) - 0.4) < 1e-9
    assert squash_scale(-6000.0) == 0.4
    assert squash_scale(1500.0) > squash_scale(3000.0)


def test_direction_noise_is_deterministic():
    a = direction_noise(120.0, -80.0)
    assert a == direction_noise(120.0, -80.0)
    assert 0.0 <= a < 1.0
    assert direction_noise(120.0, -80.0, salt=5) != a
    # quantization keeps near-identical directions identical
    assert direction_noise(100.0001, 50.0) == direction_noise(100.0002, 50.0)
    assert direction_noise(1.0, 0.0) != direction_noise(-1.0, 0.0)


def test_wobble_stays_in_envelope():
    plan = build_move((0.0, 0.0), (800.0, 300.0))
    for i in range(101):
        w = plan.wobble_at(i / 100.0)
        assert -90.0 <= w <= 90.0


def test_iter_move_frames_arrives_and_arcs():
    frames = iter_move_frames((0.0, 0.0), (500.0, 0.0))
    assert len(frames) >= 10
    assert frames[-1] == (500.0, 0.0)
    # long moves bulge off the chord (44-degree axis displacement)
    assert max(abs(y) for _x, y in frames) > 1.0
    snapped = iter_move_frames((10.0, 10.0), (10.2, 10.1))
    assert snapped == [(10.2, 10.1)]


def test_short_move_frames_run_straight():
    frames = iter_move_frames((0.0, 0.0), (90.0, 0.0))
    assert frames[-1] == (90.0, 0.0)
    # <= 196px: controls on the line, so the glide is straight
    assert max(abs(y) for _x, y in frames) <= 1.0


def test_overlay_timer_ids_match_original():
    assert TIMER_ANIM == 1
    assert TIMER_PULSE == 2
    assert TIMER_PRESS == 3  # original press-hold timer id


def test_pin_at_snaps_idle(monkeypatch):
    ov = Overlay()
    ov.pin_at(200, 300)
    assert ov._visible is True
    assert ov._cx == 200
    assert ov._cy == 300
    assert ov._flying is False
    assert ov._samples == []


def test_show_at_starts_from_human_cursor(monkeypatch):
    ov = Overlay()
    monkeypatch.setattr("ocuoc.collab.overlay.human_cursor_origin", lambda: (40, 50))
    ov.show_at(140, 50)
    assert ov._has_agent is True
    assert ov._flying is True
    assert ov._plan.start == (40.0, 50.0)
    assert ov._plan.target == (140.0, 50.0)
    assert ov._plan.T == T_SHORT


def test_show_at_paints_synchronously(monkeypatch):
    ov = Overlay()
    ov._hwnd = 7
    sent = []
    monkeypatch.setattr(
        "ocuoc.collab.overlay.user32.SendMessageW",
        lambda hwnd, msg, wparam, lparam: sent.append((hwnd, msg, wparam, lparam)) or 0,
    )
    monkeypatch.setattr("ocuoc.collab.overlay.human_cursor_origin", lambda: (1, 2))
    ov.show_at(40, 50, press=True)
    assert sent == [(7, WM_OCUOC_MOVE, 1, 0)]


def test_apply_pos_paints_before_first_show(monkeypatch):
    ov = Overlay()
    ov._visible = True
    order = []
    monkeypatch.setattr("ocuoc.collab.overlay.user32.IsWindowVisible", lambda _hwnd: 0)
    monkeypatch.setattr(
        "ocuoc.collab.overlay.user32.ShowWindow",
        lambda hwnd, cmd: order.append("show"),
    )
    monkeypatch.setattr(
        "ocuoc.collab.overlay.user32.SetWindowPos",
        lambda *args: order.append("pos"),
    )
    ov._paint = lambda hwnd=None: order.append("paint")
    ov._apply_pos(1)
    assert order[:2] == ["paint", "show"]


def test_apply_pos_does_not_reshow_every_frame(monkeypatch):
    ov = Overlay()
    ov._visible = True
    calls = []
    monkeypatch.setattr("ocuoc.collab.overlay.user32.IsWindowVisible", lambda _hwnd: 1)
    monkeypatch.setattr(
        "ocuoc.collab.overlay.user32.ShowWindow",
        lambda hwnd, cmd: calls.append(("show", cmd)),
    )
    monkeypatch.setattr(
        "ocuoc.collab.overlay.user32.SetWindowPos",
        lambda hwnd, after, x, y, cx, cy, flags: calls.append(("pos", flags)),
    )
    ov._apply_pos(1)
    assert ("show", SW_SHOWNOACTIVATE) not in calls
    flags = [c[1] for c in calls if c[0] == "pos"][0]
    assert flags & SWP_SHOWWINDOW == 0
    assert flags & SWP_NOMOVE
    assert flags & SWP_NOSIZE
    assert flags & SWP_NOACTIVATE
