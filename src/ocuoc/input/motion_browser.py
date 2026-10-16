"""Browser-profile cursor motion (clean-room). Desktop motion.py is untouched."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator

# ---------------------------------------------------------------------------
# 常量(文档 §3.3;来源:逆向测量,已全部归属)
# ---------------------------------------------------------------------------
H = 1.0 / 240.0            # 物理步长 j:240 Hz
FRAME_DT_MIN = 1.0 / 60.0  # 渲染帧 dt 下限 K(渲染节奏 60Hz)
CATCHUP_S = 1.0            # Jt:落后超过 1s 触发追帧
CATCHUP_KEEP = 1.0 / 60.0  # 追帧后保留 1/60
SETTLE_EPS = 0.06          # Ue = 0.001*60:收敛力/速度阈值
SNAP_PX = 0.5              # 距离小于此值直接跳变(与桌面版一致)
SHORT_MAX_PX = 196.0       # scoot/bezier 分界(与桌面版一致)
REST_ROT = -44.0           # 静息转角(img 烘焙 +44° 抵消)
ARRIVE_PX = 0.85           # Kt:到达位置容差
ARRIVE_V = 12.0            # Le:到达速度容差(px/s,速度字段语义见 step)
ARRIVE_PROGRESS = 0.999    # 进度到达阈值
ARRIVE_PROGRESS_V = 0.01   # 进度弹簧速度容差

CLICK_ANGLE_DEG = -44.0        # 出手角(罗盘约定:0°=正上,顺时针为正)
START_HANDLE = 0.41960295031576633
ENDPOINT_HANDLE = 0.15
ARC_SIZE = 0.2765523188064277
ARC_FLOW = 0.5783555327868779
BOUNDS_MARGIN = 20.0
HANDLE_MIN, HANDLE_MAX = 48.0, 640.0
HANDLE_DOMINANCE = 0.9          # 手柄长不得超过 0.9*直线距
ARC_DIST_MIN, ARC_DIST_MAX = 50.0, 520.0
ARC_HANDLE_MIN, ARC_HANDLE_MAX = 38.0, 440.0
ARC_DIST_SCALES = (0.55, 0.8, 1.05)
ARC_HANDLE_SCALES = (0.65, 1.0, 1.35)
BASE_HANDLE_ALT = 0.65          # 第二条基础候选的手柄缩放
ARC_TANGENT_BLEND = 0.16        # 弧点沿出手切向的偏移系数
METRIC_SAMPLES = 24             # 每段采样数(指标计算/打分)
MIN_STEP_PX = 0.01              # 角度统计忽略的微小步长

SCORE_OVERDRAW = 320.0
SCORE_ENERGY = 140.0
SCORE_MAX_ANGLE = 180.0
SCORE_TOTAL_TURN = 18.0
SCORE_DIRECTION = 90.0
SCORE_ARC = 45.0

PACING_BASE = 0.42
PACING_LEN_NUM, PACING_LEN_DEN = 180.0, 760.0
PACING_OVERDRAW_DEN = 0.55
PACING_TURN_DEN = math.pi * 1.4
PACING_ENERGY_DEN = 1.25
PACING_W_OVERDRAW = 0.42
PACING_W_TURN = 0.38
PACING_W_ENERGY = 0.20
PACING_W_DIRECTION = 0.28
PACING_ARC_BONUS = 0.04
PACING_SCALE = 0.7              # ot
PACING_MIN, PACING_MAX = 0.12, 2.2   # nt, tt
PACING_ARC_MULT = 0.9
FOLLOW_RESP_SCALE = 0.18        # In(): 跟随 response = clamp(dt*0.18, ...)
FOLLOW_RESP_MIN, FOLLOW_RESP_MAX = 0.035, 0.12

SPEED_SQUASH_REF = 5500.0       # En(): 速度挤压参考
SPEED_SQUASH_MIN = 0.65
SCOOT_STRETCH_MAX = 0.15        # Rn(): 轴向拉伸增量 Zt
SCOOT_TILT_MAX = 70.0           # zt
SCOOT_TILT_X, SCOOT_TILT_Y = 0.75, 0.62
THINK_DELAY_S = 0.0             # kt
THINK_DURATION_S = 1.41         # $t(包络)
THINK_PERIOD_S = 0.66           # Yt(正弦周期)
THINK_AMPLITUDE_DEG = 12.5      # Wt
APPEAR_POS_X, APPEAR_POS_Y = 0.58, 0.55   # 默认出现位置(视口占比)
VIS_SCALE_MIN = 0.4             # Vt
VIS_BLUR_MAX = 5.0              # Ht(px)

GLYPH_BOX = 24.0                # se:变换盒边长
GLYPH_CENTER = GLYPH_BOX / 2.0  # X
HOTSPOT_DX, HOTSPOT_DY = 12.0, -2.5   # Bt, Ut
ARRIVAL_TIMEOUT_MS = 1500       # Vf(宿主侧等待上限,桌面复刻可沿用)


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def norm_deg(deg: float) -> float:
    d = deg % 360.0
    return d + 360.0 if d < 0 else d


def delta_deg(cur: float, target: float) -> float:
    d = (target - cur) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def compass(deg: float) -> tuple[float, float]:
    """罗盘角 → 单位向量:ye(θ)={x:sinθ, y:-cosθ}(0°=正上,顺时针正)."""
    rad = math.radians(deg)
    return (math.sin(rad), -math.cos(rad))


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def unit(v: tuple[float, float]) -> tuple[float, float]:
    n = math.hypot(*v)
    return v if n < 1e-3 else (v[0] / n, v[1] / n)


# ---------------------------------------------------------------------------
# 弹簧核(文档 §3.1)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SpringCfg:
    response: float
    damping_fraction: float


CFG_POSITION = SpringCfg(0.19, 0.90)        # z
CFG_ROTATION = SpringCfg(0.12, 0.90)        # Fe
CFG_SCOOT_ROT = SpringCfg(0.055, 0.82)      # nn
CFG_SCOOT_STRETCH = SpringCfg(0.12, 0.86)   # on
CFG_STRETCH = SpringCfg(0.20, 0.85)         # Qt
CFG_VISIBILITY = SpringCfg(0.42, 0.86)      # en
CFG_PROGRESS_SCOOT = SpringCfg(0.19, 0.94)  # tn
BEZIER_DAMPING = 0.90                       # et


@dataclass
class Spring:
    """Reanimated 语义弹簧;force 兼作 Verlet 加速度状态."""

    value: float
    target: float
    cfg: SpringCfg
    velocity: float = 0.0
    force: float = 0.0
    sim_time: float = 0.0
    script_time: float = 0.0

    def snap(self, value: float) -> None:
        self.value = self.target = value
        self.velocity = self.force = 0.0
        self.sim_time = self.script_time = 0.0

    def set_cfg(self, cfg: SpringCfg) -> None:
        self.cfg = cfg

    def retarget_shortest_angle(self, target_deg: float) -> None:
        """N():目标 = 当前值 + 最短角差(角度弹簧专用)."""
        self.target = self.value + delta_deg(self.value, target_deg)

    def _settled(self) -> bool:
        if max(self.velocity * self.velocity, self.force * self.force) > SETTLE_EPS**2:
            return False
        tol = abs(self.target) * 0.01
        return abs(self.target - self.value) <= tol

    def advance(self, dt: float) -> None:
        """I():固定 1/240 子步推进;收敛即吸附."""
        resp = max(1e-3, self.cfg.response)
        k = min((2.0 * math.pi / resp) ** 2, 1.0 / (2.0 * H * H))
        c = 2.0 * self.cfg.damping_fraction * math.sqrt(k)
        self.script_time += max(0.0, dt)
        if self.script_time - self.sim_time > CATCHUP_S:
            self.sim_time = self.script_time - CATCHUP_KEEP
        while self.sim_time < self.script_time:
            self._step(k, c)
            self.sim_time += H
        if self._settled():
            self.value = self.target
            self.velocity = 0.0
            self.force = 0.0

    def _step(self, k: float, c: float) -> None:
        """An():velocity-Verlet 半步(leapfrog)."""
        vh = self.velocity + self.force * (H / 2.0)
        self.value += vh * H
        self.force = -c * vh + (self.target - self.value) * k
        self.velocity = vh + self.force * (H / 2.0)

    @property
    def settled(self) -> bool:
        return self.value == self.target and self._settled()


# ---------------------------------------------------------------------------
# 路径:三次贝塞尔 + 20 候选 + 指标 + 打分 + 选路(文档 §4.2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Seg:
    """一段三次贝塞尔:P(t) = cubic(p0, c1, c2, p1, t)."""

    c1: tuple[float, float]
    c2: tuple[float, float]
    p1: tuple[float, float]


@dataclass
class Path:
    start: tuple[float, float]
    end: tuple[float, float]
    segments: list[Seg]
    arc: tuple[float, float] | None = None  # 双段路径的中继弧点(None=单段)

    def point_at(self, u: float) -> tuple[float, float]:
        t = clamp(u, 0.0, 1.0)
        if t == 1.0 or len(self.segments) == 1:
            idx = min(len(self.segments) - 1, int(t * len(self.segments)))
        else:
            pos = t * len(self.segments)
            idx = int(pos)
        seg = self.segments[idx]
        prev_end = self.start if idx == 0 else self.segments[idx - 1].p1
        local = 1.0 if t == 1.0 else (t * len(self.segments) - idx)
        return cubic(prev_end, seg.c1, seg.c2, seg.p1, local)

    def tangent_at(self, u: float) -> tuple[float, float]:
        t = clamp(u, 0.0, 1.0)
        if t == 1.0 or len(self.segments) == 1:
            idx = min(len(self.segments) - 1, int(t * len(self.segments)))
        else:
            pos = t * len(self.segments)
            idx = int(pos)
        seg = self.segments[idx]
        prev_end = self.start if idx == 0 else self.segments[idx - 1].p1
        local = 1.0 if t == 1.0 else (t * len(self.segments) - idx)
        return cubic_tangent(prev_end, seg.c1, seg.c2, seg.p1, local)


def cubic(p0, c1, c2, p1, t):
    s = 1.0 - t
    a, b, cc, d = s * s * s, 3 * s * s * t, 3 * s * t * t, t * t * t
    return (p0[0] * a + c1[0] * b + c2[0] * cc + p1[0] * d,
            p0[1] * a + c1[1] * b + c2[1] * cc + p1[1] * d)


def cubic_tangent(p0, c1, c2, p1, t):
    s = 1.0 - t
    return (3 * s * s * (c1[0] - p0[0]) + 6 * s * t * (c2[0] - c1[0]) + 3 * t * t * (p1[0] - c2[0]),
            3 * s * s * (c1[1] - p0[1]) + 6 * s * t * (c2[1] - c1[1]) + 3 * t * t * (p1[1] - c2[1]))


def clamp_handle(bounds, origin, direction, length):
    """V():把控制点限制在视口内(射线-盒子截断)."""
    w, h = bounds
    r = length
    dx, dy = direction
    if dx < 0:
        r = min(r, origin[0] / -dx)
    elif dx > 0:
        r = min(r, (w - origin[0]) / dx)
    if dy < 0:
        r = min(r, origin[1] / -dy)
    elif dy > 0:
        r = min(r, (h - origin[1]) / dy)
    r = max(0.0, r)
    return (origin[0] + dx * r, origin[1] + dy * r)


def direction_penalty(start, end):
    """Se():与出手角(-44°)反向的惩罚,0..1."""
    t = compass(CLICK_ANGLE_DEG)
    n = unit((end[0] - start[0], end[1] - start[1]))
    return clamp((-(n[0] * t[0] + n[1] * t[1]) - 0.08) / 0.92, 0.0, 1.0)


def in_bounds(p, bounds, margin):
    w, h = bounds
    return margin <= p[0] <= w - margin and margin <= p[1] <= h - margin


@dataclass
class PathMetrics:
    length: float = 0.0
    angle_change_energy: float = 0.0
    max_angle_change: float = 0.0
    total_turn: float = 0.0
    stays_in_bounds: bool = True


def path_metrics(path: Path, bounds) -> PathMetrics:
    """ve():每段 24 采样折线长 + 角度统计 + 视口判定."""
    m = PathMetrics(stays_in_bounds=in_bounds(path.start, bounds, BOUNDS_MARGIN))
    prev_point = path.start
    last_dir: float | None = None
    seg_start = path.start
    for seg in path.segments:
        for i in range(1, METRIC_SAMPLES + 1):
            p = cubic(seg_start, seg.c1, seg.c2, seg.p1, i / METRIC_SAMPLES)
            m.length += dist(prev_point, p)
            if not in_bounds(p, bounds, BOUNDS_MARGIN):
                m.stays_in_bounds = False
            step = (p[0] - prev_point[0], p[1] - prev_point[1])
            if math.hypot(*step) > MIN_STEP_PX:
                ang = math.atan2(step[1], step[0])
                if last_dir is not None:
                    d = (ang - last_dir + math.pi) % (2 * math.pi) - math.pi
                    m.angle_change_energy += d * d
                    m.max_angle_change = max(m.max_angle_change, abs(d))
                    m.total_turn += abs(d)
                last_dir = ang
            prev_point = p
        seg_start = seg.p1
    return m


def path_score(path: Path, m: PathMetrics) -> float:
    """ut():低分优."""
    straight = max(1.0, dist(path.start, path.end))
    overdraw = max(0.0, m.length / straight - 1.0)
    return (m.length + overdraw * SCORE_OVERDRAW
            + m.angle_change_energy * SCORE_ENERGY
            + m.max_angle_change * SCORE_MAX_ANGLE
            + m.total_turn * SCORE_TOTAL_TURN
            + direction_penalty(path.start, path.end) * SCORE_DIRECTION
            + (0.0 if path.arc is None else SCORE_ARC))


def build_candidates(start, end, bounds) -> list[Path]:
    """生成 20 条候选:2 单段(手柄 ×1 / ×0.65)+ 3×3×2 双段弧."""
    i = dist(start, end)
    n = unit((end[0] - start[0], end[1] - start[1]))
    r = compass(CLICK_ANGLE_DEG)
    s = clamp(i * START_HANDLE, HANDLE_MIN, min(HANDLE_MAX, i * HANDLE_DOMINANCE))
    el = clamp(i * ENDPOINT_HANDLE, HANDLE_MIN, min(HANDLE_MAX, i * HANDLE_DOMINANCE))
    back = (-r[0], -r[1])
    sc = clamp_handle(bounds, start, r, s)
    ec = clamp_handle(bounds, end, back, el)
    mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    perp = (-n[1], n[0])
    if perp[0] * r[0] + perp[1] * r[1] < 0:
        perp = (-perp[0], -perp[1])
    base_p = clamp(i * ARC_SIZE, ARC_DIST_MIN, ARC_DIST_MAX)
    base_a = clamp(i * ARC_FLOW, ARC_HANDLE_MIN, ARC_HANDLE_MAX)

    out: list[Path] = []

    def add_single(sc_pt, ec_pt):
        out.append(Path(start, end, [Seg(sc_pt, ec_pt, end)], arc=None))

    add_single(sc, ec)
    add_single(clamp_handle(bounds, start, r, s * BASE_HANDLE_ALT),
               clamp_handle(bounds, end, back, el * BASE_HANDLE_ALT))

    def add_arc(ds: float, hs: float, normal):
        arc_d = base_p * ds
        handle_d = base_a * hs
        y = (mid[0] + normal[0] * arc_d + r[0] * s * ARC_TANGENT_BLEND,
             mid[1] + normal[1] * arc_d + r[1] * s * ARC_TANGENT_BLEND)
        arc_in = (y[0] - n[0] * handle_d, y[1] - n[1] * handle_d)
        arc_out = (y[0] + n[0] * handle_d, y[1] + n[1] * handle_d)
        out.append(Path(start, end,
                        [Seg(sc, arc_in, y), Seg(arc_out, ec, end)], arc=y))

    for ds in ARC_DIST_SCALES:
        for hs in ARC_HANDLE_SCALES:
            add_arc(ds, hs, perp)
            add_arc(ds, hs, (-perp[0], -perp[1]))
    return out


def pick_path(start, end, bounds) -> Path:
    """lt():视口内最低分优先;全体出界取全局最低分."""
    cands = build_candidates(start, end, bounds)
    best_in: Path | None = None
    best_in_score = math.inf
    best_any: Path | None = None
    best_any_score = math.inf
    for p in cands:
        m = path_metrics(p, bounds)
        score = path_score(p, m)
        if score < best_any_score:
            best_any, best_any_score = p, score
        if m.stays_in_bounds and score < best_in_score:
            best_in, best_in_score = p, score
    return best_in if best_in is not None else best_any  # type: ignore[return-value]


def pacing_response(path: Path, m: PathMetrics) -> float:
    """dt():进度弹簧 response ∈ [0.12, 2.2]."""
    straight = max(1.0, dist(path.start, path.end))
    overdraw = max(0.0, m.length / straight - 1.0)
    r = clamp((m.length - PACING_LEN_NUM) / PACING_LEN_DEN, 0.0, 1.0)
    i = clamp(overdraw / PACING_OVERDRAW_DEN, 0.0, 1.0)
    c = clamp(m.total_turn / PACING_TURN_DEN, 0.0, 1.0)
    a = clamp(m.angle_change_energy / PACING_ENERGY_DEN, 0.0, 1.0)
    s = clamp(i * PACING_W_OVERDRAW + c * PACING_W_TURN + a * PACING_W_ENERGY, 0.0, 1.0)
    d = direction_penalty(path.start, path.end) * PACING_W_DIRECTION
    has_arc = path.arc is not None
    raw = (PACING_BASE + r * 0.22 + s * 0.12 + d
           + (PACING_ARC_BONUS if has_arc else 0.0)) * PACING_SCALE
    if has_arc:
        raw *= PACING_ARC_MULT
    return clamp(raw, PACING_MIN, PACING_MAX)


def follow_response(pacing: float) -> float:
    """In():位置跟随 response = clamp(pacing*0.18, 0.035, 0.12)."""
    return clamp(pacing * FOLLOW_RESP_SCALE, FOLLOW_RESP_MIN, FOLLOW_RESP_MAX)


# ---------------------------------------------------------------------------
# 光标状态机(文档 §4 决策 / §4.3 到达 / §5 渲染)
# ---------------------------------------------------------------------------
@dataclass
class ScootMotion:
    end: tuple[float, float]
    start: tuple[float, float]
    axis_rotation: float
    rotation_target: float
    progress: Spring


@dataclass
class BezierMotion:
    path: Path
    progress: Spring


@dataclass
class CursorState:
    point: tuple[float, float]
    px: Spring
    py: Spring
    rotation: float                    # 当前合成角(度,渲染前)
    rotation_spring: Spring
    scoot_axis: Spring
    scoot_rotation: Spring
    scoot_stretch: Spring
    stretch: Spring
    visibility: Spring
    motion: ScootMotion | BezierMotion | None = None
    think_started_at: float | None = None  # 秒(单调钟)

    @classmethod
    def create(cls, point, visible: bool):
        vis = 1.0 if visible else 0.0
        rot = norm_deg(REST_ROT)
        return cls(
            point=point,
            px=Spring(point[0], point[0], CFG_POSITION),
            py=Spring(point[1], point[1], CFG_POSITION),
            rotation=rot,
            rotation_spring=Spring(rot, rot, CFG_ROTATION),
            scoot_axis=Spring(0.0, 0.0, CFG_ROTATION),
            scoot_rotation=Spring(0.0, 0.0, CFG_SCOOT_ROT),
            scoot_stretch=Spring(1.0, 1.0, CFG_SCOOT_STRETCH),
            stretch=Spring(1.0, 1.0, CFG_STRETCH),
            visibility=Spring(vis, vis, CFG_VISIBILITY),
        )

    # -- 决策(§4) --------------------------------------------------------
    def set_target(self, target, bounds) -> None:
        self.think_started_at = None
        d = dist(self.point, target)
        if d < SNAP_PX:
            self._snap(target)
            return
        if d <= SHORT_MAX_PX:
            self._start_scoot(target)
        else:
            self._start_bezier(target, bounds)

    def _snap(self, target) -> None:
        self.motion = None
        self.point = target
        self.px.snap(target[0]); self.py.snap(target[1])
        self.rotation_spring.snap(norm_deg(REST_ROT))
        self.rotation = self.rotation_spring.value
        self.scoot_axis.snap(0.0)
        self.scoot_rotation.snap(0.0)
        self.scoot_stretch.snap(1.0)
        self.stretch.snap(1.0)

    def _start_scoot(self, target) -> None:
        delta = (target[0] - self.point[0], target[1] - self.point[1])
        axis = 0.0 if math.hypot(*delta) < 1e-3 else math.degrees(math.atan2(delta[1], delta[0]))
        nd = unit(delta)
        rot_target = clamp(nd[0] * SCOOT_TILT_X + (-nd[1]) * SCOOT_TILT_Y, -1.0, 1.0) * SCOOT_TILT_MAX
        self.px.set_cfg(CFG_POSITION); self.py.set_cfg(CFG_POSITION)
        self.px.target = target[0]; self.py.target = target[1]
        self.rotation_spring.retarget_shortest_angle(norm_deg(REST_ROT))
        self.scoot_axis.retarget_shortest_angle(axis)
        self.motion = ScootMotion(end=target, start=self.point,
                                  axis_rotation=axis, rotation_target=rot_target,
                                  progress=Spring(0.0, 1.0, CFG_PROGRESS_SCOOT))

    def _start_bezier(self, target, bounds) -> None:
        path = pick_path(self.point, target, bounds)
        m = path_metrics(path, bounds)
        pacing = pacing_response(path, m)
        self.px.set_cfg(SpringCfg(follow_response(pacing), BEZIER_DAMPING))
        self.py.set_cfg(SpringCfg(follow_response(pacing), BEZIER_DAMPING))
        self.motion = BezierMotion(
            path=path,
            progress=Spring(0.0, 1.0, SpringCfg(pacing, BEZIER_DAMPING)))

    # -- 推进(§4.1/§4.2/§4.3) -------------------------------------------
    def step(self, dt: float, now_s: float) -> bool:
        """推进一帧;返回是否『本次移动到达』(触发到达回执,思考摆动开始)."""
        arrived = False
        if self.motion is None:
            self.stretch.target = 1.0
            self.scoot_stretch.target = 1.0
            self.scoot_rotation.target = 0.0
        else:
            self.think_started_at = None
            if isinstance(self.motion, ScootMotion):
                arrived = self._step_scoot(dt, now_s)
            else:
                arrived = self._step_bezier(dt, now_s)
        self.visibility.advance(dt)
        self.stretch.advance(dt)
        self.scoot_stretch.advance(dt)
        self.scoot_rotation.advance(dt)
        return arrived

    def _advance_core(self, dt: float) -> float:
        """He():推进 position/rotation/scootAxis;返回速度(px/s)."""
        prev = self.point
        self.px.advance(dt); self.py.advance(dt)
        self.rotation_spring.advance(dt); self.scoot_axis.advance(dt)
        self.point = (self.px.value, self.py.value)
        self.rotation = self.rotation_spring.value
        return dist(prev, self.point) / max(dt, 1.0 / 240.0)

    def _arrived_position(self, target) -> bool:
        return (dist(self.point, target) <= ARRIVE_PX
                and abs(self.px.velocity) <= ARRIVE_V
                and abs(self.py.velocity) <= ARRIVE_V)

    def _step_scoot(self, dt: float, now_s: float) -> bool:
        m = self.motion
        assert isinstance(m, ScootMotion)
        m.progress.advance(dt)
        self.px.target = m.end[0]; self.py.target = m.end[1]
        self.scoot_axis.retarget_shortest_angle(m.axis_rotation)
        self.rotation_spring.retarget_shortest_angle(norm_deg(REST_ROT))
        self._advance_core(dt)
        p = _project(self.point, m.start, m.end)
        self.stretch.target = 1.0
        self.scoot_stretch.target = scoot_stretch(p)
        self.scoot_rotation.target = m.rotation_target * math.sin(min(1.0, p) * math.pi)
        if (p >= ARRIVE_PROGRESS and abs(m.progress.velocity) < ARRIVE_PROGRESS_V
                and self._arrived_position(m.end)):
            self._finish(m.end, now_s, rest_rot=norm_deg(REST_ROT))
            return True
        return False

    def _step_bezier(self, dt: float, now_s: float) -> bool:
        m = self.motion
        assert isinstance(m, BezierMotion)
        self.scoot_stretch.target = 1.0
        self.scoot_rotation.target = 0.0
        m.progress.advance(dt)
        u = clamp(m.progress.value, 0.0, 1.0)
        pt = m.path.point_at(u)
        tg = m.path.tangent_at(u)
        self.px.target = pt[0]; self.py.target = pt[1]
        self.rotation_spring.retarget_shortest_angle(norm_deg(math.degrees(math.atan2(tg[1], tg[0]))))
        self.scoot_axis.retarget_shortest_angle(0.0)
        speed = self._advance_core(dt)
        self.stretch.target = speed_squash(speed)
        if (u >= ARRIVE_PROGRESS and abs(m.progress.velocity) < ARRIVE_PROGRESS_V
                and self._arrived_position(m.path.point_at(1.0))):
            end_t = m.path.tangent_at(1.0)
            self._finish(m.path.point_at(1.0), now_s,
                         rest_rot=norm_deg(math.degrees(math.atan2(end_t[1], end_t[0]))))
            return True
        return False

    def _finish(self, target, now_s: float, rest_rot: float) -> None:
        self.motion = None
        self.point = target
        self.px.snap(target[0]); self.py.snap(target[1])
        self.rotation_spring.snap(rest_rot)
        self.rotation = rest_rot
        self.scoot_axis.snap(0.0)
        self.scoot_rotation.snap(0.0)
        self.scoot_stretch.snap(1.0)
        self.stretch.snap(1.0)
        self.think_started_at = now_s

    # -- 渲染(§5 + 思考摆动 §4.3) ----------------------------------------
    def think_rotation(self, now_s: float) -> float:
        if self.think_started_at is None:
            return self.rotation
        t = (now_s - self.think_started_at) - THINK_DELAY_S
        if t < 0:
            return self.rotation
        env = min(1.0, t / THINK_DURATION_S)
        wobble = math.sin(t / THINK_PERIOD_S * 2.0 * math.pi) * math.sin(env * math.pi)
        if env >= 1.0:
            self.think_started_at = None
            return self.rotation
        return self.rotation + wobble * THINK_AMPLITUDE_DEG

    def render(self, now_s: float) -> dict[str, float | tuple[float, float]]:
        """yn():产出 CSS transform 链等价物(GDI/Canvas 均可消费)."""
        vis = clamp(self.visibility.value, 0.0, 1.0)
        s = lerp(VIS_SCALE_MIN, 1.0, vis)
        blur = lerp(VIS_BLUR_MAX, 0.0, vis)
        # Rn() peaks at 1.15; clamp-to-1 would kill scoot stretch (doc §4.1 Zt=0.15).
        u = max(0.0, self.scoot_stretch.value)
        axis = self.scoot_axis.value
        use_axis = abs(delta_deg(0.0, axis)) > 0.001 or abs(u - 1.0) > 0.001
        return {
            "translate": (self.point[0] - GLYPH_CENTER, self.point[1] - GLYPH_CENTER),
            "axis": axis if use_axis else None,
            "axis_stretch": u if use_axis else None,
            "rotate": norm_deg(self.think_rotation(now_s) + self.scoot_rotation.value),
            "scale": (self.stretch.value * s, s),
            "blur_px": blur,
            "opacity": round(vis, 3),
        }

    def busy(self) -> bool:
        return (self.motion is not None or self.think_started_at is not None
                or not self.px.settled or not self.py.settled
                or not self.rotation_spring.settled or not self.scoot_axis.settled
                or not self.scoot_rotation.settled or not self.scoot_stretch.settled
                or not self.stretch.settled or not self.visibility.settled)


def _project(p, a, b) -> float:
    ab = (b[0] - a[0], b[1] - a[1])
    ab2 = ab[0] * ab[0] + ab[1] * ab[1]
    if ab2 < 1e-3:
        return 1.0
    return clamp(((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ab2, 0.0, 1.0)


def speed_squash(speed_px_s: float) -> float:
    """En():高速压扁(注意:与桌面版拉伸方向相反)."""
    return clamp(1.0 - speed_px_s / SPEED_SQUASH_REF, SPEED_SQUASH_MIN, 1.0)


def scoot_stretch(progress: float) -> float:
    """Rn():1 + 0.15·sin(π·p),中点最伸."""
    return 1.0 + math.sin(clamp(progress, 0.0, 1.0) * math.pi) * SCOOT_STRETCH_MAX


def default_appear_point(viewport) -> tuple[float, float]:
    """Cn():默认出现位置 = 视口 58% / 55%."""
    w, h = viewport
    return (clamp(round(w * APPEAR_POS_X), 0, w), clamp(round(h * APPEAR_POS_Y), 0, h))


# ---------------------------------------------------------------------------
# 帧迭代器(与 OCUOC 桌面版 iter_move_frames 同形,便于 sendinput/overlay 复用)
# ---------------------------------------------------------------------------
def spring_duration(path: Path, metrics: PathMetrics | None = None) -> float:
    """Estimate move duration from pacing response (seconds)."""
    m = metrics if metrics is not None else path_metrics(path, (1280.0, 800.0))
    return pacing_response(path, m)


def iter_move_frames(start, end, bounds, now_s: float = 0.0,
                     visible: bool = True) -> Iterator[tuple[float, CursorState]]:
    """驱动到到达为止;产出 (t, state)。渲染节奏 60Hz、物理 240Hz 子步。"""
    st = CursorState.create(start, visible)
    t = now_s
    st.set_target(end, bounds)
    first_frame = True
    while True:
        dt = FRAME_DT_MIN if first_frame else FRAME_DT_MIN  # 宿主驱动时可换真实 Δt
        first_frame = False
        t += dt
        arrived = st.step(dt, t)
        yield (t, st)
        if arrived or not st.busy():
            # 到达后再产出若干帧让思考摆动/淡入播完(上限 2s)
            deadline = t + THINK_DURATION_S
            while t < deadline and st.busy():
                t += dt
                st.step(dt, t)
                yield (t, st)
            return
