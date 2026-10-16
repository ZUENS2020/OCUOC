"""Browser motion profile unit matrix (plan §1.5)."""

from ocuoc.input.motion_browser import (
    ARRIVE_PX,
    FRAME_DT_MIN,
    PACING_MAX,
    PACING_MIN,
    SHORT_MAX_PX,
    SNAP_PX,
    THINK_AMPLITUDE_DEG,
    CursorState,
    Spring,
    CFG_POSITION,
    delta_deg,
    dist,
    iter_move_frames,
    path_metrics,
    pacing_response,
    pick_path,
)


BOUNDS = (1280.0, 800.0)


def _last_state(start, end):
    last = None
    n = 0
    t0 = None
    t1 = None
    for t, st in iter_move_frames(start, end, BOUNDS):
        if t0 is None:
            t0 = t
        t1, last = t, st
        n += 1
    return last, n, (t1 - t0 if t0 is not None else 0.0)


def test_spring_step_response_settles_on_target():
    s = Spring(0.0, 10.0, CFG_POSITION)
    t = 0.0
    while t < 2.0 and not s.settled:
        s.advance(FRAME_DT_MIN)
        t += FRAME_DT_MIN
    assert s.settled
    assert abs(s.value - 10.0) < 1e-6
    assert s.velocity == 0.0
    assert s.force == 0.0


def test_three_way_decision_snap_scoot_bezier():
    snap = CursorState.create((400.0, 300.0), True)
    snap.set_target((400.4, 300.0), BOUNDS)
    assert snap.motion is None
    assert dist(snap.point, (400.4, 300.0)) < SNAP_PX

    scoot = CursorState.create((400.0, 300.0), True)
    scoot.set_target((400.0 + 195.0, 300.0), BOUNDS)
    assert type(scoot.motion).__name__ == "ScootMotion"

    bezier = CursorState.create((400.0, 300.0), True)
    bezier.set_target((400.0 + 197.0, 300.0), BOUNDS)
    assert type(bezier.motion).__name__ == "BezierMotion"
    assert 195.0 <= SHORT_MAX_PX < 197.0


def test_pick_path_is_deterministic():
    a = pick_path((100.0, 700.0), (1150.0, 100.0), BOUNDS)
    b = pick_path((100.0, 700.0), (1150.0, 100.0), BOUNDS)
    assert [s for s in a.segments] == [s for s in b.segments]


def test_pacing_bounds_and_reverse_penalty_monotone():
    # Se(e) reverse-direction penalty is documented with -0.08/+0.92 normalisation.
    forward = pick_path((200.0, 200.0), (400.0, 50.0), BOUNDS)
    reverse = pick_path((200.0, 200.0), (50.0, 400.0), BOUNDS)
    pf = pacing_response(forward, path_metrics(forward, BOUNDS))
    pr = pacing_response(reverse, path_metrics(reverse, BOUNDS))
    assert PACING_MIN <= pf <= PACING_MAX
    assert PACING_MIN <= pr <= PACING_MAX
    assert pr >= pf


def test_think_wobble_peaks_then_stops():
    st, _n, _dt = _last_state((100.0, 700.0), (1150.0, 100.0))
    rot0 = st.rotation
    t = 0.0
    max_dev = 0.0
    while st.think_started_at is not None or t < 2.0:
        t += FRAME_DT_MIN
        st.step(FRAME_DT_MIN, t)
        max_dev = max(max_dev, abs(delta_deg(rot0, st.think_rotation(t))))
    assert max_dev <= THINK_AMPLITUDE_DEG + 1e-6
    assert st.think_started_at is None


def test_long_glide_arrives_within_tolerance():
    st, n, dt = _last_state((100.0, 700.0), (1150.0, 100.0))
    assert n > 30
    assert 1.2 <= dt <= 3.5
    assert dist(st.point, (1150.0, 100.0)) <= ARRIVE_PX + 0.5
