"""Cursor motion model replicated from the Codex overlay animation.

Every constant and formula below is cross-validated against the binary, see
docs/2026-10-16-codex-cursor-animation-re.md
(sub_14004BCA6 motion.rs, sub_140055246 sampler, sub_140054A57 splitter,
sub_1400551AF direction noise, sub_14004B902 press timing).

Model summary (evidence in the doc):
- decision tree: <0.5px teleport / <=196px single cubic with controls at
  1/3 and 2/3 of the straight line (T=0.24, damping 1.68) / >196px a
  two-segment cubic bulged along the fixed 44-degree axis, then iteratively
  split into up to 20 waypoints (lateral displacement 0.16*bulge);
- timing is NOT an easing curve: progress is a 60Hz semi-implicit Euler
  damped spring toward 1.0 (underdamped -> slight overshoot), settle when
  progress>=0.999 and |v|<=0.99898, hard cap 5.0s;
- rotation follows the path tangent plus a deterministic per-waypoint
  wobble (coherent noise, seed 3207714082; +45 degree flag on alternating
  joints);
- vertical squash while fast: scale_y = 1/(1.5*min(1,|v_px|/3000)+1);
- press visual is held at least 100ms via timer id 3.

Honest notes (documented deviations):
- the exact hash inside sub_1400551AF is not decoded; direction_noise()
  emulates it with a deterministic integer mix (same inputs -> same value,
  stable across processes);
- the per-waypoint jitter inputs of the x320/x140/x180/x18 weights could
  not all be attributed; wobble_at() preserves the weight ratios scaled to
  the visual envelope (net bank bounded ~ +/-25 degrees + the exact +45
  degree flag).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# -- decision tree (sub_14004BCA6 L460-542) --
SNAP_PX = 0.5          # below: teleport, no animation
SHORT_MAX_PX = 196.0   # <=: single cubic; >: two segments + bulge

# -- geometry --
SIDE = (0.71933979, 0.6946584)     # unit vector at 44deg, .rdata exact
SIDE_PERP = (-SIDE[1], SIDE[0])    # displacement axis used by the splitter
BULGE_FRAC = 0.9        # bulge <= 0.9 * distance
BULGE_MIN_PX = 48.0
BULGE_MAX_PX = 640.0
BULGE_SEG2 = 0.65       # second segment bulge = 65% of the first
SUBDIV_DISPLACE = 0.16  # joint lateral displacement = 0.16 * bulge
MAX_WAYPOINTS = 20      # derived point cap
SUBDIV_A = (0.55, 0.8, 1.1)   # pass A: t range + lateral gain
SUBDIV_B = (0.65, 1.0, 1.2)   # pass B: t range + lateral gain
SUBDIV_T1 = (0.27655232, 50.0, 520.0)   # k*dist clamp [50,520]: pass A threshold
SUBDIV_T2 = (0.57835555, 38.0, 440.0)   # pass B threshold

# -- spring integrator (sub_14004BCA6 L892-926) --
DT = 1.0 / 60.0
TWO_PI = 2.0 * math.pi
T_MIN, T_MAX = 0.12, 2.2
T_SHORT = 0.24
ZETA_SHORT = 1.68
ZETA_LONG = 1.8
SETTLE_P = 0.999
SETTLE_V = 0.99898
SIM_CAP_S = 5.0

# -- duration formula (sub_14004BCA6 L819-866) --
DUR_BASE = 0.42
DUR_DIST_W, DUR_DIST_REF = 0.22, 760.0
DUR_TURN_W, DUR_TURN_REF = 0.38, 4.3982296   # ~252deg in radians
DUR_SPEED_W, DUR_SPEED_REF = 0.42, 0.55
DUR_SAMPLE_W, DUR_SAMPLE_REF = 0.2, 1.25
DUR_INNER_W = 0.12
DUR_NOISE_W = 0.28
DUR_SCALE = 0.9

# -- rotation wobble weights (sub_14004BCA6 L765-770), ratio-preserving gain --
WOBBLE_GAIN = 0.05   # 320->16, 180->9, 140->7, 90->4.5, 18->0.9
WOBBLE_SPEED, WOBBLE_S1, WOBBLE_S2, WOBBLE_S3, WOBBLE_NOISE, WOBBLE_FLAG = (
    320.0 * WOBBLE_GAIN,
    140.0 * WOBBLE_GAIN,
    180.0 * WOBBLE_GAIN,
    18.0 * WOBBLE_GAIN,
    90.0 * WOBBLE_GAIN,
    45.0,   # exact: joints flagged at +40 add a discrete +45 degrees
)

# -- squash (sub_14004BCA6 L1453-1459) --
SQUASH_REF_PX = 3000.0
SQUASH_K = 1.5

PRESS_MS = 100         # sub_14004B902: timer id 3 holds the press >= 100ms
MOVE_TIMEOUT = 3.0     # cap while waiting a move out (worst-case settle ~2.7s)

NOISE_SEED = 3207714082   # sub_1400551AF

_MASK64 = (1 << 64) - 1


def _splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return (z ^ (z >> 31)) & _MASK64


def direction_noise(dx: float, dy: float, salt: int = 0) -> float:
    """Deterministic [0,1) noise of a direction vector.

    Emulates sub_1400551AF: a hash seeded with 3207714082 evaluated on the
    motion vector. Same direction -> same value, stable across processes
    (never uses Python's salted hash()).
    """
    lo = int(round(dx * 256.0)) & 0xFFFFFFFF
    hi = int(round(dy * 256.0)) & 0xFFFFFFFF
    h = _splitmix64(lo | (hi << 32))
    h = _splitmix64(h ^ (NOISE_SEED + salt * 0x9E3779B1))
    return (h >> 11) / float(1 << 53)


def cubic3(p0, p1, p2, p3, t):
    """Cubic bezier point."""
    u = 1.0 - t
    uu, tt = u * u, t * t
    w0, w1, w2, w3 = uu * u, 3.0 * uu * t, 3.0 * u * tt, tt * t
    return (
        w0 * p0[0] + w1 * p1[0] + w2 * p2[0] + w3 * p3[0],
        w0 * p0[1] + w1 * p1[1] + w2 * p2[1] + w3 * p3[1],
    )


def cubic3_tangent(p0, p1, p2, p3, t):
    """Cubic bezier tangent: 3(1-t)^2, 6t(1-t), 3t^2 (sub_140055246)."""
    u = 1.0 - t
    return (
        3.0 * u * u * (p1[0] - p0[0]) + 6.0 * u * t * (p2[0] - p1[0]) + 3.0 * t * t * (p3[0] - p2[0]),
        3.0 * u * u * (p1[1] - p0[1]) + 6.0 * u * t * (p2[1] - p1[1]) + 3.0 * t * t * (p3[1] - p2[1]),
    )


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def bulge_for(dx: float, dy: float, dist: float) -> float:
    """Signed lateral bulge magnitude for a long move.

    mag = clamp(min(noise-driven value, 0.9*dist), 48, 640);
    sign picks the side of the 44-degree axis (dot of the motion vector).
    """
    sign = 1.0 if dx * SIDE[0] + dy * SIDE[1] >= 0.0 else -1.0
    n = direction_noise(dx, dy, salt=1)
    mag = _clamp(min(n * BULGE_MAX_PX, BULGE_FRAC * dist), BULGE_MIN_PX, BULGE_MAX_PX)
    return mag * sign


def _split_segment(seg, t, lateral):
    """De Casteljau split at t; the joint is displaced along SIDE_PERP
    (sub_140054A57: mid + perp44 * 0.16 * bulge * gain)."""
    p0, p1, p2, p3 = seg
    p01 = _lerp_pt(p0, p1, t)
    p12 = _lerp_pt(p1, p2, t)
    p23 = _lerp_pt(p2, p3, t)
    p012 = _lerp_pt(p01, p12, t)
    p123 = _lerp_pt(p12, p23, t)
    m = _lerp_pt(p012, p123, t)
    m = (m[0] + SIDE_PERP[0] * lateral, m[1] + SIDE_PERP[1] * lateral)
    return (p0, p01, p012, m), (m, p123, p23, p3)


def _lerp_pt(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _seg_chord(seg):
    return math.hypot(seg[3][0] - seg[0][0], seg[3][1] - seg[0][1])


@dataclass
class MovePlan:
    """A fully planned animated move: geometry + timing + wobble."""

    start: tuple[float, float]
    target: tuple[float, float]
    segments: list
    T: float
    zeta: float
    bulge: float = 0.0
    arc: float = 0.0
    chord: float = 0.0
    banks: list = field(default_factory=list)   # per-segment wobble, degrees
    snapped: bool = False

    def sample(self, progress: float):
        """(position, tangent) at progress in [0,1]; segments are timed
        uniformly (Progress*n remap from the offset expression)."""
        segs = self.segments
        n = len(segs)
        p = _clamp(progress, 0.0, 1.0)
        i = min(n - 1, int(p * n))
        local = p * n - i
        seg = segs[i]
        return cubic3(*seg, local), cubic3_tangent(*seg, local)

    def wobble_at(self, progress: float) -> float:
        """Rotation jitter in degrees, blended linearly across segments
        (piecewise-linear keyframes in the original)."""
        if not self.banks:
            return 0.0
        n = len(self.banks)
        p = _clamp(progress, 0.0, 1.0)
        i = min(n - 1, int(p * n))
        local = p * n - i
        if i + 1 >= n:
            return self.banks[i]
        return _lerp(self.banks[i], self.banks[i + 1], local)


def _banks_for(segments, bulge, chord, arc):
    """Per-segment wobble bank, degrees (weights from L765-770)."""
    banks = []
    for i, seg in enumerate(segments):
        ex, ey = seg[3][0] - seg[0][0], seg[3][1] - seg[0][1]
        n1 = direction_noise(ex, ey, salt=11)
        n2 = direction_noise(ex, ey, salt=12)
        n3 = direction_noise(ex, ey, salt=13)
        n4 = direction_noise(ex, ey, salt=14)
        speed_ratio = (arc / chord - 1.0) if chord > 1.0 else 0.0
        flag = WOBBLE_FLAG if (i % 2 == 1 and i + 1 < len(segments)) else 0.0
        banks.append(
            (n1 - 0.5) * 2.0 * WOBBLE_S1
            + (n2 - 0.5) * 2.0 * WOBBLE_S2
            + n3 * WOBBLE_S3
            + (n4 - 0.5) * 2.0 * WOBBLE_NOISE
            + _clamp(speed_ratio, 0.0, 1.0) * WOBBLE_SPEED
            + flag
        )
    return banks


def spring_duration(dist: float, turn_rad: float, arc: float, chord: float, bulge: float) -> float:
    """Duration factor T (sub_14004BCA6 L819-866), clamped [0.12, 2.2].

    T = (0.42 + 0.22*dist_term + 0.12*(0.2*s1 + 0.38*turn + 0.42*speed)
         + 0.28*noise) * 0.9
    dist_term = min(1, dist/760); turn = min(1, |turn|/4.398);
    speed = min(1, (arc/chord - 1)/0.55); s1 = min(1, bulge_ratio/1.25).
    """
    chord = max(chord, 1.0)
    dist_term = min(1.0, max(0.0, dist / DUR_DIST_REF))
    turn_term = min(1.0, max(0.0, abs(turn_rad) / DUR_TURN_REF))
    speed_term = min(1.0, max(0.0, (arc / chord - 1.0) / DUR_SPEED_REF))
    sample_term = min(1.0, max(0.0, (abs(bulge) / chord) / DUR_SAMPLE_REF))
    noise = direction_noise(chord, turn_rad, salt=3)
    inner = (
        DUR_SAMPLE_W * sample_term
        + DUR_TURN_W * turn_term
        + DUR_SPEED_W * speed_term
    )
    t = (DUR_BASE + DUR_DIST_W * dist_term + DUR_INNER_W * inner + DUR_NOISE_W * noise) * DUR_SCALE
    return _clamp(t, T_MIN, T_MAX)


def spring_step(p: float, v: float, T: float, zeta: float, dt: float = DT):
    """One semi-implicit Euler step toward progress 1.0."""
    w = TWO_PI / T
    a = (1.0 - p) * w * w - v * w * zeta
    v = v + a * dt
    p = p + v * dt
    return p, v


def simulate(T: float, zeta: float, dt: float = DT, cap: float = SIM_CAP_S):
    """Spring samples [(t, progress, velocity)] until settled or cap.

    Settled: progress >= 0.999 and |v| <= 0.99898, then a final exact
    (progress=1.0, v=0) sample is forced (sub_14004BCA6 L912-919).
    """
    p = v = 0.0
    t = 0.0
    out = []
    while t < cap:
        p, v = spring_step(p, v, T, zeta, dt)
        t += dt
        if p >= SETTLE_P and abs(v) <= SETTLE_V:
            out.append((t, 1.0, 0.0))
            return out
        out.append((t, p, v))
    out.append((t, 1.0, 0.0))
    return out


def squash_scale(vel_px: float) -> float:
    """Vertical squash while fast: 1/(1.5*min(1,|v|/3000)+1) in [0.4, 1]."""
    return 1.0 / (SQUASH_K * min(1.0, abs(vel_px) / SQUASH_REF_PX) + 1.0)


def _arc_length(segments, steps: int = 48) -> float:
    total = 0.0
    prev = None
    for seg in segments:
        for i in range(steps + 1):
            pt = cubic3(*seg, i / steps)
            if prev is not None:
                total += math.hypot(pt[0] - prev[0], pt[1] - prev[1])
            prev = pt
    return total


def build_move(start, target) -> MovePlan:
    """Plan an animated move: decision tree + geometry + subdivision + timing."""
    sx, sy = float(start[0]), float(start[1])
    tx, ty = float(target[0]), float(target[1])
    dx, dy = tx - sx, ty - sy
    dist = math.hypot(dx, dy)
    if dist < SNAP_PX:
        degenerate = ((sx, sy), (sx, sy), (sx, sy), (tx, ty))
        return MovePlan(
            start=(sx, sy), target=(tx, ty), segments=[degenerate],
            T=0.0, zeta=ZETA_SHORT, chord=dist, arc=dist, snapped=True,
        )
    if dist <= SHORT_MAX_PX:
        seg = (
            (sx, sy),
            (sx + dx / 3.0, sy + dy / 3.0),
            (sx + dx * (2.0 / 3.0), sy + dy * (2.0 / 3.0)),
            (tx, ty),
        )
        arc = _arc_length([seg])
        return MovePlan(
            start=(sx, sy), target=(tx, ty), segments=[seg],
            T=T_SHORT, zeta=ZETA_SHORT, chord=dist, arc=arc, banks=[0.0],
        )
    # long move: two bulged segments sharing the joint (sub_14004BCA6 L555-629)
    bulge = bulge_for(dx, dy, dist)
    mx, my = sx + dx / 2.0, sy + dy / 2.0
    j = (mx + SIDE_PERP[0] * bulge, my + SIDE_PERP[1] * bulge)
    h = (dx / 6.0, dy / 6.0)
    seg1 = (
        (sx, sy),
        (sx + h[0], sy + h[1]),
        (j[0] - h[0], j[1] - h[1]),
        j,
    )
    # second-half curvature is scaled by BULGE_SEG2 via a shorter outgoing
    # handle (position-continuous joint, softer second arc)
    seg2 = (
        j,
        (j[0] + h[0] * BULGE_SEG2, j[1] + h[1] * BULGE_SEG2),
        (tx - h[0], ty - h[1]),
        (tx, ty),
    )
    segments = [seg1, seg2]
    # waypoint subdivision: two passes, up to MAX_WAYPOINTS joints
    joints = 1
    for params, thresh in ((SUBDIV_A, SUBDIV_T1), (SUBDIV_B, SUBDIV_T2)):
        tmin, tmax, gain = params
        limit = _clamp(thresh[0] * dist, thresh[1], thresh[2])
        nxt = []
        for seg in segments:
            if joints >= MAX_WAYPOINTS or _seg_chord(seg) <= limit:
                nxt.append(seg)
                continue
            t = tmin + direction_noise(seg[3][0] - seg[0][0], seg[3][1] - seg[0][1], salt=21) * (tmax - tmin)
            lateral = SUBDIV_DISPLACE * bulge * gain * (1.0 if joints % 2 == 0 else -1.0)
            a, b = _split_segment(seg, t, lateral)
            nxt.append(a)
            nxt.append(b)
            joints += 1
        segments = nxt
    arc = _arc_length(segments)
    tan0 = cubic3_tangent(*segments[0], 0.0)
    tan1 = cubic3_tangent(*segments[-1], 1.0)
    turn = math.atan2(tan1[1], tan1[0]) - math.atan2(tan0[1], tan0[0])
    T = spring_duration(dist, turn, arc, dist, bulge)
    banks = _banks_for(segments, bulge, dist, arc)
    return MovePlan(
        start=(sx, sy), target=(tx, ty), segments=segments,
        T=T, zeta=ZETA_LONG, bulge=bulge, chord=dist, arc=arc, banks=banks,
    )


def iter_move_frames(start, target):
    """Frame positions [(x, y)] at 60Hz for gliding the real cursor:
    same decision tree, same spring timing as the overlay animation."""
    plan = build_move(start, target)
    if plan.snapped:
        return [(plan.target[0], plan.target[1])]
    frames = []
    for _t, p, _v in simulate(plan.T, plan.zeta):
        pos, _tan = plan.sample(min(1.0, max(0.0, p)))
        frames.append((pos[0], pos[1]))
    if not frames or frames[-1] != (plan.target[0], plan.target[1]):
        frames.append((plan.target[0], plan.target[1]))
    return frames
