// OCUOC Browser Bridge — content_cursor.js(参考实现)
// 页面侧 agent 光标 overlay + favicon 徽章。注入方式:background 经
// chrome.scripting.executeScript 动态注入(等价原版做法,标识符全部自有)。
// 运动模型规格: docs/2026-10-16-codex-browser-cursor-overlay-re.md §2-§7
//   240Hz velocity-Verlet 弹簧 / <0.5px 跳变 / ≤196px scoot / >196px 20候选贝塞尔
//   到达 → CUOC_CURSOR_ARRIVED 回执 → 思考摆动(正弦 12.5°, 0.66s, 1.41s 包络)
// 红线:光标造型为独立重绘(黑体白衬箭头,规格见文档 §2),非官方资产。

(() => {
  'use strict';
  if (window.top !== window.self) return;          // 仅顶层框架(对齐原版行为)
  if (window.__cuocCursorLoaded) return;
  window.__cuocCursorLoaded = true;

  // ── 常量(文档 §3.2/§3.3) ──────────────────────────────────────────────
  const H = 1 / 240, FRAME_DT_MIN = 1 / 60;
  const CATCHUP = 1, CATCHUP_KEEP = 1 / 60, SETTLE_EPS = 0.001 * 60;
  const SNAP_PX = 0.5, SHORT_MAX_PX = 196, REST_ROT = -44;
  const ARRIVE_PX = 0.85, ARRIVE_V = 12, ARRIVE_PROGRESS = 0.999, ARRIVE_PROGRESS_V = 0.01;
  const CLICK_ANGLE = -44, START_HANDLE = 0.41960295031576633, END_HANDLE = 0.15;
  const ARC_SIZE = 0.2765523188064277, ARC_FLOW = 0.5783555327868779;
  const BOUNDS_MARGIN = 20, HANDLE_MIN = 48, HANDLE_MAX = 640, HANDLE_DOM = 0.9;
  const ARC_DIST_MIN = 50, ARC_DIST_MAX = 520, ARC_HANDLE_MIN = 38, ARC_HANDLE_MAX = 440;
  const ARC_DIST_SCALES = [0.55, 0.8, 1.05], ARC_HANDLE_SCALES = [0.65, 1, 1.35];
  const SAMPLES = 24;
  const SPEED_REF = 5500, SPEED_MIN = 0.65;        // En():高速压扁
  const SCOOT_STRETCH = 0.15, SCOOT_TILT_MAX = 70; // Rn()/zt
  const THINK_DURATION = 1.41, THINK_PERIOD = 0.66, THINK_AMPLITUDE = 12.5;
  const APPEAR_X = 0.58, APPEAR_Y = 0.55;          // 默认出现位
  const VIS_SCALE_MIN = 0.4, VIS_BLUR_MAX = 5;
  const GLOW_COLOR = '#339cff';                    // 光晕色(规格值,变量名自有)
  const CFG = {
    position:      { response: 0.19, dampingFraction: 0.90 },
    rotation:      { response: 0.12, dampingFraction: 0.90 },
    scootRotation: { response: 0.055, dampingFraction: 0.82 },
    scootStretch:  { response: 0.12, dampingFraction: 0.86 },
    stretch:       { response: 0.20, dampingFraction: 0.85 },
    visibility:    { response: 0.42, dampingFraction: 0.86 },
    progressScoot: { response: 0.19, dampingFraction: 0.94 },
  };

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const normDeg = (d) => { const r = d % 360; return r < 0 ? r + 360 : r; };
  const deltaDeg = (a, b) => { let d = (b - a) % 360; if (d > 180) d -= 360; if (d < -180) d += 360; return d; };
  const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
  const unit = (v) => { const n = Math.hypot(v.x, v.y); return n < 1e-3 ? { x: 1, y: 0 } : { x: v.x / n, y: v.y / n }; };
  const compass = (deg) => { const r = deg * Math.PI / 180; return { x: Math.sin(r), y: -Math.cos(r) }; };

  // ── 弹簧(文档 §3.1:I/An/We/N/v) ───────────────────────────────────────
  class Spring {
    constructor(value, cfg) {
      this.value = value; this.target = value; this.cfg = { ...cfg };
      this.velocity = 0; this.force = 0; this.simTime = 0; this.scriptTime = 0;
    }
    snap(v) { this.value = this.target = v; this.velocity = this.force = 0; this.simTime = this.scriptTime = 0; }
    retargetAngle(deg) { this.target = this.value + deltaDeg(this.value, deg); }
    _settled() {
      if (Math.max(this.velocity ** 2, this.force ** 2) > SETTLE_EPS ** 2) return false;
      const tol = Math.abs(this.target) * 0.01;
      return Math.abs(this.target - this.value) <= tol;
    }
    advance(dt) {
      const resp = Math.max(0.001, this.cfg.response);
      const k = Math.min((2 * Math.PI / resp) ** 2, 1 / (2 * H * H));
      const c = 2 * this.cfg.dampingFraction * Math.sqrt(k);
      this.scriptTime += Math.max(0, dt);
      if (this.scriptTime - this.simTime > CATCHUP) this.simTime = this.scriptTime - CATCHUP_KEEP;
      while (this.simTime < this.scriptTime) { this._step(k, c); this.simTime += H; }
      if (this._settled()) { this.value = this.target; this.velocity = this.force = 0; }
    }
    _step(k, c) {                                    // velocity-Verlet
      const vh = this.velocity + this.force * (H / 2);
      this.value += vh * H;
      this.force = -c * vh + (this.target - this.value) * k;
      this.velocity = vh + this.force * (H / 2);
    }
    get settled() { return this.value === this.target && this._settled(); }
  }

  // ── 贝塞尔候选(文档 §4.2:20 候选 + 指标 + 打分 + 选路) ────────────────
  const cubic = (p0, c1, c2, p1, t) => {
    const s = 1 - t, a = s * s * s, b = 3 * s * s * t, c = 3 * s * t * t, d = t * t * t;
    return { x: p0.x * a + c1.x * b + c2.x * c + p1.x * d, y: p0.y * a + c1.y * b + c2.y * c + p1.y * d };
  };
  const cubicTangent = (p0, c1, c2, p1, t) => {
    const s = 1 - t;
    return { x: 3 * s * s * (c1.x - p0.x) + 6 * s * t * (c2.x - c1.x) + 3 * t * t * (p1.x - c2.x),
             y: 3 * s * s * (c1.y - p0.y) + 6 * s * t * (c2.y - c1.y) + 3 * t * t * (p1.y - c2.y) };
  };
  const inBounds = (p, vp, m) => p.x >= m && p.x <= vp.width - m && p.y >= m && p.y <= vp.height - m;
  const clampHandle = (vp, o, dir, len) => {
    let r = len;
    if (dir.x < 0) r = Math.min(r, o.x / -dir.x); else if (dir.x > 0) r = Math.min(r, (vp.width - o.x) / dir.x);
    if (dir.y < 0) r = Math.min(r, o.y / -dir.y); else if (dir.y > 0) r = Math.min(r, (vp.height - o.y) / dir.y);
    return { x: o.x + dir.x * Math.max(0, r), y: o.y + dir.y * Math.max(0, r) };
  };
  const directionPenalty = (start, end) => {        // Se()
    const t = compass(CLICK_ANGLE), n = unit({ x: end.x - start.x, y: end.y - start.y });
    return clamp((-(n.x * t.x + n.y * t.y) - 0.08) / 0.92, 0, 1);
  };
  function pathMetrics(path, vp) {                  // ve()
    let length = 0, energy = 0, maxAng = 0, turn = 0, stays = true;
    let prev = path.start, lastDir = null, segStart = path.start;
    for (const seg of path.segments) {
      for (let i = 1; i <= SAMPLES; i++) {
        const p = cubic(segStart, seg.c1, seg.c2, seg.end, i / SAMPLES);
        length += dist(prev, p);
        if (!inBounds(p, vp, BOUNDS_MARGIN)) stays = false;
        const sx = p.x - prev.x, sy = p.y - prev.y;
        if (Math.hypot(sx, sy) > 0.01) {
          const ang = Math.atan2(sy, sx);
          if (lastDir !== null) {
            const d = ((ang - lastDir + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
            energy += d * d; maxAng = Math.max(maxAng, Math.abs(d)); turn += Math.abs(d);
          }
          lastDir = ang;
        }
        prev = p;
      }
      segStart = seg.end;
    }
    return { length, energy, maxAng, turn, stays };
  }
  const pathScore = (p, m) => {                     // ut()
    const straight = Math.max(1, dist(p.start, p.end));
    const over = Math.max(0, m.length / straight - 1);
    return m.length + over * 320 + m.energy * 140 + m.maxAng * 180 + m.turn * 18
         + directionPenalty(p.start, p.end) * 90 + (p.arc ? 45 : 0);
  };
  function buildCandidates(start, end, vp) {
    const i = dist(start, end), n = unit({ x: end.x - start.x, y: end.y - start.y });
    const r = compass(CLICK_ANGLE);
    const s = clamp(i * START_HANDLE, HANDLE_MIN, Math.min(HANDLE_MAX, i * HANDLE_DOM));
    const e = clamp(i * END_HANDLE, HANDLE_MIN, Math.min(HANDLE_MAX, i * HANDLE_DOM));
    const back = { x: -r.x, y: -r.y };
    const sc = clampHandle(vp, start, r, s), ec = clampHandle(vp, end, back, e);
    const mid = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
    let perp = { x: -n.y, y: n.x };
    if (perp.x * r.x + perp.y * r.y < 0) perp = { x: -perp.x, y: -perp.y };
    const baseP = clamp(i * ARC_SIZE, ARC_DIST_MIN, ARC_DIST_MAX);
    const baseA = clamp(i * ARC_FLOW, ARC_HANDLE_MIN, ARC_HANDLE_MAX);
    const out = [];
    const addSingle = (a, b) => out.push({ start, end, segments: [{ c1: a, c2: b, end }], arc: null });
    addSingle(sc, ec);
    addSingle(clampHandle(vp, start, r, s * 0.65), clampHandle(vp, end, back, e * 0.65));
    const addArc = (ds, hs, norm) => {
      const y = { x: mid.x + norm.x * baseP * ds + r.x * s * 0.16,
                  y: mid.y + norm.y * baseP * ds + r.y * s * 0.16 };
      const arcIn = { x: y.x - n.x * baseA * hs, y: y.y - n.y * baseA * hs };
      const arcOut = { x: y.x + n.x * baseA * hs, y: y.y + n.y * baseA * hs };
      out.push({ start, end, segments: [{ c1: sc, c2: arcIn, end: y }, { c1: arcOut, c2: ec, end }], arc: y });
    };
    for (const ds of ARC_DIST_SCALES) for (const hs of ARC_HANDLE_SCALES) {
      addArc(ds, hs, perp); addArc(ds, hs, { x: -perp.x, y: -perp.y });
    }
    return out;
  }
  function pickPath(start, end, vp) {               // lt()
    let bestIn = null, bestInScore = Infinity, best = null, bestScore = Infinity;
    for (const p of buildCandidates(start, end, vp)) {
      const m = pathMetrics(p, vp), score = pathScore(p, m);
      if (score < bestScore) { best = p; bestScore = score; }
      if (m.stays && score < bestInScore) { bestIn = p; bestInScore = score; }
    }
    return bestIn || best;
  }
  function pacingResponse(p, m) {                   // dt()
    const straight = Math.max(1, dist(p.start, p.end));
    const over = Math.max(0, m.length / straight - 1);
    const r = clamp((m.length - 180) / 760, 0, 1);
    const i = clamp(over / 0.55, 0, 1), c = clamp(m.turn / (Math.PI * 1.4), 0, 1);
    const a = clamp(m.energy / 1.25, 0, 1);
    const s = clamp(i * 0.42 + c * 0.38 + a * 0.2, 0, 1);
    const d = directionPenalty(p.start, p.end) * 0.28;
    let raw = (0.42 + r * 0.22 + s * 0.12 + d + (p.arc ? 0.04 : 0)) * 0.7;
    if (p.arc) raw *= 0.9;
    return clamp(raw, 0.12, 2.2);
  }
  const followResponse = (pacing) => clamp(pacing * 0.18, 0.035, 0.12);   // In()

  // ── 光标状态机(文档 §4 决策/到达,§5 渲染) ────────────────────────────
  const speedSquash = (v) => clamp(1 - v / SPEED_REF, SPEED_MIN, 1);      // En()
  const scootStretch = (p) => 1 + Math.sin(clamp(p, 0, 1) * Math.PI) * SCOOT_STRETCH; // Rn()
  const project = (p, a, b) => {
    const ab = { x: b.x - a.x, y: b.y - a.y }, ab2 = ab.x * ab.x + ab.y * ab.y;
    return ab2 < 1e-3 ? 1 : clamp(((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / ab2, 0, 1);
  };

  function makeCursor(point, visible) {
    const rot = normDeg(REST_ROT);
    return {
      point: { ...point }, motion: null, thinkStartedAt: null, rotation: rot,
      px: new Spring(point.x, CFG.position), py: new Spring(point.y, CFG.position),
      rot: new Spring(rot, CFG.rotation), scootAxis: new Spring(0, CFG.rotation),
      scootRot: new Spring(0, CFG.scootRotation), scootStr: new Spring(1, CFG.scootStretch),
      str: new Spring(1, CFG.stretch), vis: new Spring(visible ? 1 : 0, CFG.visibility),
    };
  }
  function setTarget(c, target, vp) {
    c.thinkStartedAt = null;
    const d = dist(c.point, target);
    if (d < SNAP_PX) return finish(c, target, normDeg(REST_ROT));
    if (d <= SHORT_MAX_PX) {                        // scoot(§4.1)
      const dv = { x: target.x - c.point.x, y: target.y - c.point.y };
      const axis = Math.hypot(dv.x, dv.y) < 1e-3 ? 0 : Math.atan2(dv.y, dv.x) * 180 / Math.PI;
      const nd = unit(dv);
      const tilt = clamp(nd.x * 0.75 - nd.y * 0.62, -1, 1) * SCOOT_TILT_MAX;
      c.px.cfg = { ...CFG.position }; c.py.cfg = { ...CFG.position };
      c.px.target = target.x; c.py.target = target.y;
      c.rot.retargetAngle(normDeg(REST_ROT)); c.scootAxis.retargetAngle(axis);
      c.motion = { mode: 'scoot', start: { ...c.point }, end: { ...target },
                   axis, tilt, progress: new Spring(0, CFG.progressScoot) };
    } else {                                        // bezier(§4.2)
      const path = pickPath(c.point, target, vp);
      const m = pathMetrics(path, vp);
      const pacing = pacingResponse(path, m);
      const follow = { response: followResponse(pacing), dampingFraction: 0.9 };
      c.px.cfg = { ...follow }; c.py.cfg = { ...follow };
      c.motion = { mode: 'bezier', path, progress: new Spring(0, { response: pacing, dampingFraction: 0.9 }) };
    }
  }
  function advanceCore(c, dt) {                     // He()
    c.px.advance(dt); c.py.advance(dt); c.rot.advance(dt); c.scootAxis.advance(dt);
    const prev = { ...c.point };
    c.point = { x: c.px.value, y: c.py.value };
    c.rotation = c.rot.value;
    return dist(prev, c.point) / Math.max(dt, 1 / 240);
  }
  const arrivedPos = (c, t) => dist(c.point, t) <= ARRIVE_PX
      && Math.abs(c.px.velocity) <= ARRIVE_V && Math.abs(c.py.velocity) <= ARRIVE_V;
  function finish(c, target, rot) {
    c.motion = null; c.px.snap(target.x); c.py.snap(target.y); c.point = { ...target };
    c.rot.snap(rot); c.rotation = rot;
    c.scootAxis.snap(0); c.scootRot.snap(0); c.scootStr.snap(1); c.str.snap(1);
  }
  function step(c, dt, nowS) {
    let arrived = false;
    if (c.motion == null) {
      c.str.target = 1; c.scootStr.target = 1; c.scootRot.target = 0;
    } else {
      c.thinkStartedAt = null;
      arrived = c.motion.mode === 'scoot' ? stepScoot(c, dt, nowS) : stepBezier(c, dt, nowS);
    }
    c.vis.advance(dt); c.str.advance(dt); c.scootStr.advance(dt); c.scootRot.advance(dt);
    return arrived;
  }
  function stepScoot(c, dt, nowS) {
    const m = c.motion;
    m.progress.advance(dt);
    c.px.target = m.end.x; c.py.target = m.end.y;
    c.scootAxis.retargetAngle(m.axis); c.rot.retargetAngle(normDeg(REST_ROT));
    advanceCore(c, dt);
    const p = project(c.point, m.start, m.end);
    c.str.target = 1;
    c.scootStr.target = scootStretch(p);
    c.scootRot.target = m.tilt * Math.sin(Math.min(1, p) * Math.PI);
    if (p >= ARRIVE_PROGRESS && Math.abs(m.progress.velocity) < ARRIVE_PROGRESS_V && arrivedPos(c, m.end)) {
      finish(c, m.end, normDeg(REST_ROT)); c.thinkStartedAt = nowS; return true;
    }
    return false;
  }
  function stepBezier(c, dt, nowS) {
    const m = c.motion;
    c.scootStr.target = 1; c.scootRot.target = 0;
    m.progress.advance(dt);
    const u = clamp(m.progress.value, 0, 1);
    const pt = evalPath(m.path, u), tg = tangentPath(m.path, u);
    c.px.target = pt.point.x; c.py.target = pt.point.y;
    c.rot.retargetAngle(normDeg(Math.atan2(tg.y, tg.x) * 180 / Math.PI));
    c.scootAxis.retargetAngle(0);
    const speed = advanceCore(c, dt);
    c.str.target = speedSquash(speed);
    if (u >= ARRIVE_PROGRESS && Math.abs(m.progress.velocity) < ARRIVE_PROGRESS_V) {
      const end = evalPath(m.path, 1), endT = tangentPath(m.path, 1);
      if (arrivedPos(c, end.point)) {
        finish(c, end.point, normDeg(Math.atan2(endT.y, endT.x) * 180 / Math.PI));
        c.thinkStartedAt = nowS; return true;
      }
    }
    return false;
  }
  function evalPath(path, u) {                      // me()
    const t = clamp(u, 0, 1), n = path.segments.length;
    const idx = t === 1 ? n - 1 : Math.min(n - 1, Math.floor(t * n));
    const seg = path.segments[idx];
    const prevEnd = idx === 0 ? path.start : path.segments[idx - 1].end;
    return { point: cubic(prevEnd, seg.c1, seg.c2, seg.end, t === 1 ? 1 : t * n - idx) };
  }
  function tangentPath(path, u) {                   // me().tangent
    const t = clamp(u, 0, 1), n = path.segments.length;
    const idx = t === 1 ? n - 1 : Math.min(n - 1, Math.floor(t * n));
    const seg = path.segments[idx];
    const prevEnd = idx === 0 ? path.start : path.segments[idx - 1].end;
    return cubicTangent(prevEnd, seg.c1, seg.c2, seg.end, t === 1 ? 1 : t * n - idx);
  }
  function thinkRotation(c, nowS) {                 // xn():渲染时应用
    if (c.thinkStartedAt == null) return c.rotation;
    const t = nowS - c.thinkStartedAt;
    if (t < 0) return c.rotation;
    const env = Math.min(1, t / THINK_DURATION);
    if (env >= 1) { c.thinkStartedAt = null; return c.rotation; }
    return c.rotation + Math.sin(t / THINK_PERIOD * 2 * Math.PI) * Math.sin(env * Math.PI) * THINK_AMPLITUDE;
  }
  function renderStyle(c, nowS) {                   // yn()
    const v = clamp(c.vis.value, 0, 1);
    const s = lerp(VIS_SCALE_MIN, 1, v), blur = lerp(VIS_BLUR_MAX, 0, v);
    const u = Math.max(0, c.scootStr.value), axis = c.scootAxis.value;
    const parts = [`translate3d(${(c.point.x - 12).toFixed(3)}px, ${(c.point.y - 12).toFixed(3)}px, 0)`];
    if (Math.abs(deltaDeg(0, axis)) > 0.001 || Math.abs(u - 1) > 0.001)
      parts.push(`rotate(${axis.toFixed(3)}deg)`, `scale(1, ${u.toFixed(3)})`, `rotate(${(-axis).toFixed(3)}deg)`);
    parts.push(`rotate(${normDeg(thinkRotation(c, nowS) + c.scootRot.value).toFixed(3)}deg)`,
               `scale(${(c.str.value * s).toFixed(3)}, ${s.toFixed(3)})`);
    return { transform: parts.join(' '), opacity: (Math.round(v * 1000) / 1000).toString(),
             filter: `blur(${blur.toFixed(3)}px)` };
  }
  const busy = (c) => c.motion != null || c.thinkStartedAt != null
      || [c.px, c.py, c.rot, c.scootAxis, c.scootRot, c.scootStr, c.str, c.vis].some((sp) => !sp.settled);

  // ── DOM(文档 §2:双层变换 + 热点偏移 + 光晕滤镜;造型独立重绘) ────────
  const HOST_ID = 'cuoc-agent-overlay-root';
  const GLOW_VAR = '--cuoc-cursor-glow-color';
  // 造型:文档 §2/§7 纸飞机(16×16 path 旋到朝上,装进 23×24;2x 为 46×48)。
  // 基准角 0°=指向正上;img 烘焙 rotate(44deg) 与弹簧 −44° 抵消。
  const PLANE_D = 'M3.045 4.453 C2.758 3.603 3.603 2.758 4.453 3.045 L14.183 6.334 ' +
    'C15.164 6.666 15.087 8.080 14.072 8.390 L10.299 9.543 ' +
    'C9.939 9.653 9.653 9.939 9.543 10.299 L8.390 14.072 ' +
    'C8.080 15.087 6.666 15.164 6.334 14.183 L3.045 4.453 Z';
  const CURSOR_SVG = 'data:image/svg+xml,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="46" height="48" viewBox="0 0 23 24">` +
    `<g transform="translate(11.193 14.225) scale(1.4737) rotate(36.878) translate(-8.743 -8.763)">` +
    `<path d="${PLANE_D}" fill="#111111" stroke="#ffffff" stroke-width="0.95" ` +
    `stroke-linejoin="round" paint-order="stroke fill"/></g></svg>`);

  let layer = null, styleEl = null;
  function mount() {
    if (document.getElementById(HOST_ID)?.isConnected) return true;
    const host = document.createElement('div');
    host.id = HOST_ID;
    host.dataset.cuocAgentOverlay = 'true';
    const root = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = '.cuoc-overlay{all:initial;z-index:2147483646;pointer-events:none;' +
      'position:fixed;inset:0}@media print{.cuoc-overlay{display:none}}';
    root.append(style);
    const overlay = document.createElement('div');
    overlay.className = 'cuoc-overlay';
    const clip = document.createElement('div');      // 裁剪层
    Object.assign(clip.style, { inset: '0', overflow: 'hidden', pointerEvents: 'none',
                                position: 'absolute', zIndex: '20' });
    const mover = document.createElement('div');     // 变换目标(24×24)
    Object.assign(mover.style, { height: '24px', width: '24px', left: '0', top: '0',
      position: 'absolute', transformOrigin: '12px 12px', willChange: 'transform' });
    mover.dataset.testid = 'cuoc-cursor';
    const hotspot = document.createElement('div');   // 热点偏移 (12, −2.5)
    hotspot.style.transform = 'translate3d(12px, -2.5px, 0)';
    const img = document.createElement('img');
    img.alt = ''; img.draggable = false; img.width = 23; img.height = 24;
    img.src = CURSOR_SVG; img.style.display = 'block'; img.style.transformOrigin = '0 0';
    img.style.transform = 'rotate(44deg) scale(1)';
    img.style.setProperty(GLOW_VAR, GLOW_COLOR);
    img.style.filter = `drop-shadow(0 0 6px color-mix(in srgb, var(${GLOW_VAR}) 90%, transparent))` +
                       ` drop-shadow(0 0 15px color-mix(in srgb, var(${GLOW_VAR}) 48%, transparent))`;
    hotspot.append(img); mover.append(hotspot); clip.append(mover); overlay.append(clip);
    root.append(overlay);
    (document.documentElement || document).append(host);
    layer = { host, mover, img };
    return true;
  }
  const viewport = () => ({ width: window.visualViewport?.width ?? window.innerWidth,
                            height: window.visualViewport?.height ?? window.innerHeight });

  // ── 控制器(rAF 循环 + 一次性到达回执) ─────────────────────────────────
  let cursor = null, rafId = null, lastT = 0, forceMinDt = false;
  let lastArrivalKey = null, pendingSeq = null;

  function loop(ts) {
    rafId = null;
    if (!cursor) return;
    const dt = forceMinDt ? FRAME_DT_MIN : Math.max(FRAME_DT_MIN, (ts - lastT) / 1000);
    forceMinDt = false; lastT = ts;
    const arrived = step(cursor, dt, ts / 1000);
    applyStyle(ts / 1000);
    if (arrived && pendingSeq != null) {
      const key = String(pendingSeq);
      if (lastArrivalKey !== key) {
        lastArrivalKey = key;
        notifyArrived(pendingSeq);
      }
    }
    if (busy(cursor)) rafId = requestAnimationFrame(loop);
  }
  function applyStyle(nowS) {
    if (!layer || !cursor) return;
    const st = renderStyle(cursor, nowS);
    layer.mover.style.transform = st.transform;
    layer.mover.style.opacity = st.opacity;
    layer.mover.style.filter = st.filter;
  }

  function onState(state) {
    mount();
    const vp = viewport();
    const turnKey = state.turnKey || '';
    const hasCursor = state.cursor != null;
    const pos = hasCursor
      ? { x: clamp(state.cursor.x ?? Math.round(vp.width * APPEAR_X), 0, vp.width),
          y: clamp(state.cursor.y ?? Math.round(vp.height * APPEAR_Y), 0, vp.height) }
      : { x: Math.round(vp.width * APPEAR_X), y: Math.round(vp.height * APPEAR_Y) };
    const visible = state.isVisible !== false && state.cursor?.visible !== false;
    const animate = state.cursor?.animate !== false;
    pendingSeq = state.cursor?.seq ?? null;
    if (cursor == null) cursor = makeCursor(pos, visible);
    cursor.vis.target = visible ? 1 : 0;
    if (!hasCursor) {                               // 无光标:吸附并隐藏
      finish(cursor, pos, normDeg(REST_ROT));
      applyStyle(performance.now() / 1000);
      kickLoop();
      return;
    }
    const d = dist(cursor.point, pos);
    if (!animate || d < SNAP_PX) {                  // 跳变
      finish(cursor, pos, normDeg(REST_ROT));
      if (animate) {
        cursor.thinkStartedAt = performance.now() / 1000;
        if (pendingSeq != null) notifyArrived(pendingSeq);
      }
    } else {
      setTarget(cursor, pos, vp);
    }
    kickLoop();
  }
  function kickLoop() {
    forceMinDt = true;
    if (rafId == null) { lastT = performance.now(); rafId = requestAnimationFrame(loop); }
  }

  // ── favicon 徽章(文档 §7 语义,造型/颜色独立重绘) ─────────────────────
  const BADGE_DATA = 'cuocFaviconBadge';
  function badgeSvg(kind, faviconHref) {
    const esc = (s) => s.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
                        .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    let badge = '';
    if (kind === 'active') {
      // 文档 §7 纸飞机 path + translate(-2,-2) scale(2.1)
      badge = `<path d="${PLANE_D}" fill="#111111" ` +
              `stroke="white" stroke-width="1.5" stroke-linejoin="round" ` +
              `paint-order="stroke fill" transform="translate(-2 -2) scale(2.1)"/>`;
    } else if (kind === 'deliverable') {
      badge = `<circle cx="24" cy="24" r="7" fill="#22c55e"/>`;
    } else if (kind === 'handoff') {
      badge = `<circle cx="24" cy="24" r="7" fill="#facc15"/>`;
    }
    const img = faviconHref ? `<image href="${esc(faviconHref)}" width="32" height="32"${kind === 'active' ? ' opacity="0.3"' : ''}/>` : '';
    return 'data:image/svg+xml,' + encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" data-cuoc-badge="${BADGE_DATA}" width="32" height="32" viewBox="0 0 32 32">${img}${badge}</svg>`);
  }
  function setBadge(kind, faviconDataUrl) {
    const links = [...document.querySelectorAll("link[rel~='icon']")];
    const targets = links.length ? links : (() => {
      const n = document.createElement('link');
      n.rel = 'icon';
      (document.head || document.documentElement).append(n);
      return [n];
    })();
    for (const link of targets) {
      if (kind == null) {                            // 还原
        const orig = link.dataset.cuocOriginalFaviconHref;
        if (orig != null) link.href = orig;
        delete link.dataset.cuocOriginalFaviconHref;
      } else {
        if (link.dataset.cuocOriginalFaviconHref == null)
          link.dataset.cuocOriginalFaviconHref = link.getAttribute('href') || '';
        link.href = badgeSvg(kind, faviconDataUrl || link.dataset.cuocOriginalFaviconHref || '');
      }
    }
  }

  function notifyArrived(seq) {
    try {
      if (typeof window.cuocCursorArrived === 'function') {
        window.cuocCursorArrived(String(seq));
      }
    } catch (_e) {}
    try {
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage) {
        chrome.runtime.sendMessage({ type: 'CUOC_CURSOR_ARRIVED', seq }).catch(() => {});
      }
    } catch (_e) {}
  }

  // ── 消息接入(扩展) + headless 直连挂钩 ────────────────────────────────
  window.__cuocSetCursor = (state) => onState(state || {});
  window.__cuocSetBadge = (kind, faviconDataUrl) => setBadge(kind ?? null, faviconDataUrl);
  if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'CUOC_CURSOR_STATE') { onState(msg.state || {}); reply({ ok: true }); return true; }
      if (msg.type === 'CUOC_BADGE_SET') { setBadge(msg.kind ?? null, msg.faviconDataUrl); reply({ ok: true }); return true; }
    });
  }

  // 简化守卫:周期检查宿主存活(原版用 MutationObserver,这里等价轻量实现)
  setInterval(() => { if (cursor && !document.getElementById(HOST_ID)?.isConnected) { layer = null; mount(); applyStyle(performance.now() / 1000); } }, 2000);
})();
