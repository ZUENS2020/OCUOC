"""Codex-style AI pointer: 13-vertex cubic teardrop, #0169CC, white stroke."""

from __future__ import annotations

import math
from array import array

GLYPH_PX = 58.5
FOG_RADIUS = 16
FOG_SURFACE = 28
STROKE_UNIT = 0.03
FILL_RGB = (1, 105, 204)
FILL_ALPHA = 0.80
STROKE_RGB = (255, 255, 255)
REST_HEADING = math.atan2(-1.0, -1.0)

# Start + 4 cubics (3 controls each). Unit space; tip/hotspot ≈ (0, 0).
P0 = (0.0060, 0.1586)
CUBICS = (
    ((-0.0236, 0.0646), (0.0617, -0.0247), (0.1516, 0.0063)),
    ((0.8763, 0.2565), (0.9759, 0.2910), (0.9834, 0.4355)),
    ((0.8879, 0.4809), (0.5934, 0.6211), (0.4595, 0.9293)),
    ((0.4161, 1.0293), (0.2780, 1.0215), (0.2451, 0.9172)),
)

_SPRITE: tuple[int, int, int, int, array] | None = None


def cubic3(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    u = 1.0 - t
    uu, tt = u * u, t * t
    w0, w1, w2, w3 = uu * u, 3.0 * uu * t, 3.0 * u * tt, tt * t
    return (
        w0 * p0[0] + w1 * p1[0] + w2 * p2[0] + w3 * p3[0],
        w0 * p0[1] + w1 * p1[1] + w2 * p2[1] + w3 * p3[1],
    )


def sample_outline(steps: int = 32) -> list[tuple[float, float]]:
    pts = [P0]
    cur = P0
    for c1, c2, c3 in CUBICS:
        for i in range(1, steps + 1):
            pts.append(cubic3(cur, c1, c2, c3, i / steps))
        cur = c3
    return pts


def heading_for_velocity(vx: float, vy: float) -> float:
    if vx * vx + vy * vy < 1e-8:
        return 0.0
    return math.atan2(vy, vx) - REST_HEADING


def lerp_angle(current: float, target: float, k: float = 0.4) -> float:
    delta = (target - current + math.pi) % (2.0 * math.pi) - math.pi
    return current + delta * k


def _point_in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            at = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < at:
                inside = not inside
        j = i
    return inside


def _dist_to_seg(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> float:
    vx, vy = x1 - x0, y1 - y0
    l2 = vx * vx + vy * vy
    if l2 < 1e-12:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * vx + (py - y0) * vy) / l2))
    return math.hypot(px - (x0 + t * vx), py - (y0 + t * vy))


def _signed_distance(px: float, py: float, poly: list[tuple[float, float]]) -> float:
    n = len(poly)
    best = 1e9
    j = n - 1
    for i in range(n):
        x0, y0 = poly[j]
        x1, y1 = poly[i]
        d = _dist_to_seg(px, py, x0, y0, x1, y1)
        if d < best:
            best = d
        j = i
    if _point_in_poly(px, py, poly):
        return -best
    return best


def _cover(edge: float, width: float = 1.0) -> float:
    if width <= 0:
        return 1.0 if edge <= 0 else 0.0
    return max(0.0, min(1.0, 0.5 - edge / width))


def _pack(r: int, g: int, b: int, a: float) -> int:
    ai = max(0, min(255, int(round(a * 255.0))))
    if ai <= 0:
        return 0
    return (ai << 24) | ((r * ai // 255) << 16) | ((g * ai // 255) << 8) | (b * ai // 255)


def _shade(sd: float, stroke_px: float) -> int:
    inside = _cover(sd)
    fill_c = inside * FILL_ALPHA
    stroke_c = _cover(sd - stroke_px) * (1.0 - inside)
    a = 1.0 - (1.0 - fill_c) * (1.0 - stroke_c)
    if a <= 0.002:
        return 0
    fr, fg, fb = FILL_RGB
    sr, sg, sb = STROKE_RGB
    r = fr * fill_c + sr * stroke_c * (1.0 - fill_c)
    g = fg * fill_c + sg * stroke_c * (1.0 - fill_c)
    b = fb * fill_c + sb * stroke_c * (1.0 - fill_c)
    return _pack(
        max(0, min(255, int(round(r / a)))),
        max(0, min(255, int(round(g / a)))),
        max(0, min(255, int(round(b / a)))),
        a,
    )


def rasterize_sprite(glyph_px: float | None = None) -> tuple[int, int, int, int, array]:
    """Return (width, height, hotspot_x, hotspot_y, premul BGRA uint32)."""
    gp = GLYPH_PX if glyph_px is None else float(glyph_px)
    stroke_px = STROKE_UNIT * gp  # 1.755px at 58.5
    unit = sample_outline(64)
    xs = [p[0] * gp for p in unit]
    ys = [p[1] * gp for p in unit]
    pad = stroke_px + 2.25
    min_x = min(xs) - pad
    min_y = min(ys) - pad
    max_x = max(xs) + pad
    max_y = max(ys) + pad
    w = int(math.ceil(max_x - min_x))
    h = int(math.ceil(max_y - min_y))
    hx = -min_x
    hy = -min_y
    ss = 2
    outline = [((x - min_x) * ss, (y - min_y) * ss) for x, y in zip(xs, ys)]
    stroke_ss = stroke_px * ss
    sw, sh = w * ss, h * ss
    hi = [0] * (sw * sh)
    for y in range(sh):
        row = y * sw
        py = y + 0.5
        for x in range(sw):
            hi[row + x] = _shade(_signed_distance(x + 0.5, py, outline), stroke_ss)
    pixels = array("I", [0] * (w * h))
    for y in range(h):
        row = y * w
        y0 = y * ss
        for x in range(w):
            x0 = x * ss
            i00 = y0 * sw + x0
            i10 = i00 + 1
            i01 = i00 + sw
            i11 = i01 + 1
            p00, p10, p01, p11 = hi[i00], hi[i10], hi[i01], hi[i11]
            if (p00 | p10 | p01 | p11) == 0:
                continue
            a = (
                ((p00 >> 24) & 255)
                + ((p10 >> 24) & 255)
                + ((p01 >> 24) & 255)
                + ((p11 >> 24) & 255)
                + 2
            ) // 4
            if a <= 0:
                continue
            r = (
                ((p00 >> 16) & 255)
                + ((p10 >> 16) & 255)
                + ((p01 >> 16) & 255)
                + ((p11 >> 16) & 255)
                + 2
            ) // 4
            g = (
                ((p00 >> 8) & 255)
                + ((p10 >> 8) & 255)
                + ((p01 >> 8) & 255)
                + ((p11 >> 8) & 255)
                + 2
            ) // 4
            b = (p00 & 255) + (p10 & 255) + (p01 & 255) + (p11 & 255) + 2
            b //= 4
            pixels[row + x] = (a << 24) | (r << 16) | (g << 8) | b
    return w, h, int(round(hx)), int(round(hy)), pixels


def sprite() -> tuple[int, int, int, int, array]:
    global _SPRITE
    if _SPRITE is None:
        _SPRITE = rasterize_sprite()
    return _SPRITE


# Browser-plugin glyph (overlay-re §2/§7): 23×24 black paper-plane, white
# stroke, baked 44°, hotspot offset (12, −2.5), dual #339cff drop-shadow.
PLUGIN_FILL = (17, 17, 17)
PLUGIN_STROKE_PX = 1.4
GLOW_RGB = (51, 156, 255)
BAKE_DEG = 44.0
PLUGIN_IMG_W = 23
PLUGIN_IMG_H = 24
PLANE_D_NOSE = (4.453, 3.045)
PLANE_CX, PLANE_CY = 8.743, 8.763
PLANE_ROT = math.radians(36.877648497133755)
PLANE_SCALE = 1.4737061655931902
PLANE_TX, PLANE_TY = 11.193, 14.225

_PLUGIN_SPRITE: tuple[int, int, int, int, array] | None = None


def _plane_src_outline() -> list[tuple[float, float]]:
    cur = (3.045, 4.453)
    pts = [cur]
    segs = (
        ((2.758, 3.603), (3.603, 2.758), (4.453, 3.045)),
        ((14.183, 6.334),),
        ((15.164, 6.666), (15.087, 8.080), (14.072, 8.390)),
        ((10.299, 9.543),),
        ((9.939, 9.653), (9.653, 9.939), (9.543, 10.299)),
        ((8.390, 14.072),),
        ((8.080, 15.087), (6.666, 15.164), (6.334, 14.183)),
        ((3.045, 4.453),),
    )
    for seg in segs:
        if len(seg) == 1:
            pts.append(seg[0])
            cur = seg[0]
            continue
        for i in range(1, 17):
            pts.append(cubic3(cur, seg[0], seg[1], seg[2], i / 16.0))
        cur = seg[2]
    return pts


def sample_plugin_outline() -> list[tuple[float, float]]:
    """Paper-plane outline in 23×24 image space, nose pointing up."""
    cr, sr = math.cos(PLANE_ROT), math.sin(PLANE_ROT)
    out: list[tuple[float, float]] = []
    for x, y in _plane_src_outline():
        dx, dy = x - PLANE_CX, y - PLANE_CY
        rx = dx * cr - dy * sr
        ry = dx * sr + dy * cr
        out.append((rx * PLANE_SCALE + PLANE_TX, ry * PLANE_SCALE + PLANE_TY))
    return out


def _shade_plugin(sd: float, stroke_px: float) -> int:
    inside = _cover(sd)
    fill_c = inside
    stroke_c = _cover(sd - stroke_px) * (1.0 - inside)
    a = 1.0 - (1.0 - fill_c) * (1.0 - stroke_c)
    if a <= 0.002:
        return 0
    fr, fg, fb = PLUGIN_FILL
    sr, sg, sb = STROKE_RGB
    r = fr * fill_c + sr * stroke_c * (1.0 - fill_c)
    g = fg * fill_c + sg * stroke_c * (1.0 - fill_c)
    b = fb * fill_c + sb * stroke_c * (1.0 - fill_c)
    return _pack(
        max(0, min(255, int(round(r / a)))),
        max(0, min(255, int(round(g / a)))),
        max(0, min(255, int(round(b / a)))),
        a,
    )


def _raster_outline(outline: list[tuple[float, float]], w: int, h: int, stroke_px: float, ss: int = 2) -> array:
    sw, sh = w * ss, h * ss
    hi = [0] * (sw * sh)
    scaled = [(p[0] * ss, p[1] * ss) for p in outline]
    stroke_ss = stroke_px * ss
    for y in range(sh):
        row = y * sw
        py = y + 0.5
        for x in range(sw):
            hi[row + x] = _shade_plugin(_signed_distance(x + 0.5, py, scaled), stroke_ss)
    pixels = array("I", [0] * (w * h))
    for y in range(h):
        row = y * w
        y0 = y * ss
        for x in range(w):
            x0 = x * ss
            i00 = y0 * sw + x0
            p00, p10, p01, p11 = hi[i00], hi[i00 + 1], hi[i00 + sw], hi[i00 + sw + 1]
            if (p00 | p10 | p01 | p11) == 0:
                continue
            a = (((p00 >> 24) & 255) + ((p10 >> 24) & 255) + ((p01 >> 24) & 255) + ((p11 >> 24) & 255) + 2) // 4
            if a <= 0:
                continue
            r = (((p00 >> 16) & 255) + ((p10 >> 16) & 255) + ((p01 >> 16) & 255) + ((p11 >> 16) & 255) + 2) // 4
            g = (((p00 >> 8) & 255) + ((p10 >> 8) & 255) + ((p01 >> 8) & 255) + ((p11 >> 8) & 255) + 2) // 4
            b = ((p00 & 255) + (p10 & 255) + (p01 & 255) + (p11 & 255) + 2) // 4
            pixels[row + x] = (a << 24) | (r << 16) | (g << 8) | b
    return pixels


def rasterize_plugin_core() -> tuple[int, int, array]:
    outline = sample_plugin_outline()
    w, h = PLUGIN_IMG_W, PLUGIN_IMG_H
    return w, h, _raster_outline(outline, w, h, PLUGIN_STROKE_PX)


def _box_blur_u8(src: list[int], w: int, h: int, radius: int) -> list[int]:
    if radius < 1:
        return list(src)
    tmp = [0] * (w * h)
    out = [0] * (w * h)
    span = radius * 2 + 1
    for y in range(h):
        row = y * w
        acc = src[row] * (radius + 1)
        for x in range(radius):
            acc += src[row + min(w - 1, x)]
        for x in range(w):
            acc += src[row + min(w - 1, x + radius)]
            acc -= src[row + max(0, x - radius - 1)]
            tmp[row + x] = acc // span
    for x in range(w):
        acc = tmp[x] * (radius + 1)
        for y in range(radius):
            acc += tmp[min(h - 1, y) * w + x]
        for y in range(h):
            acc += tmp[min(h - 1, y + radius) * w + x]
            acc -= tmp[max(0, y - radius - 1) * w + x]
            out[y * w + x] = acc // span
    return out


def rasterize_plugin_sprite() -> tuple[int, int, int, int, array]:
    """23×24 up-pointing plane + dual #339cff drop-shadow. Tip is the hotspot.

    CSS still bakes rotate(44deg) on the img; GDI adds the same 44° in
    blit_browser_visual so rest (−44° + 44°) points up.
    """
    cw, ch, core = rasterize_plugin_core()
    pad = 16
    w, h = cw + pad * 2, ch + pad * 2
    hx = PLANE_TX + pad
    hy = 3.69 + pad
    baked = array("I", [0] * (w * h))
    for y in range(ch):
        for x in range(cw):
            baked[(y + pad) * w + (x + pad)] = core[y * cw + x]
    alpha = [(int(baked[i]) >> 24) & 255 for i in range(w * h)]
    glow6 = _box_blur_u8(alpha, w, h, 6)
    glow15 = _box_blur_u8(_box_blur_u8(alpha, w, h, 8), w, h, 7)
    gr, gg, gb = GLOW_RGB
    out = array("I", [0] * (w * h))
    for i in range(w * h):
        a6 = min(255, int(glow6[i] * 0.90))
        a15 = min(255, int(glow15[i] * 0.48))
        a_g = a15 + a6 * (255 - a15) // 255
        if a_g <= 0 and baked[i] == 0:
            continue
        r = gr * a_g // 255
        g = gg * a_g // 255
        b = gb * a_g // 255
        core_p = int(baked[i])
        ca = (core_p >> 24) & 255
        if ca:
            inv = 255 - ca
            a_g = ca + a_g * inv // 255
            r = ((core_p >> 16) & 255) + r * inv // 255
            g = ((core_p >> 8) & 255) + g * inv // 255
            b = (core_p & 255) + b * inv // 255
        out[i] = (min(255, a_g) << 24) | (min(255, r) << 16) | (min(255, g) << 8) | min(255, b)
    return w, h, int(round(hx)), int(round(hy)), out


def plugin_sprite() -> tuple[int, int, int, int, array]:
    global _PLUGIN_SPRITE
    if _PLUGIN_SPRITE is None:
        _PLUGIN_SPRITE = rasterize_plugin_sprite()
    return _PLUGIN_SPRITE


def _rot2(deg: float) -> tuple[tuple[float, float], tuple[float, float]]:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return ((c, -s), (s, c))


def _mul2(a, b):
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def compose_axis_matrix(axis_deg: float, u: float, rot_deg: float, sx: float, sy: float):
    """CSS chain R(axis)·S(1,u)·R(-axis)·R(θ)·S(sx,sy) as a 2×2 matrix."""
    a = _rot2(axis_deg)
    s1 = ((1.0, 0.0), (0.0, max(0.2, u)))
    ai = _rot2(-axis_deg)
    r = _rot2(rot_deg)
    s2 = ((max(0.2, sx), 0.0), (0.0, max(0.2, sy)))
    return _mul2(_mul2(_mul2(a, s1), ai), _mul2(r, s2))


def blit_transformed(
    dest: object,
    canvas: int,
    dx: float,
    dy: float,
    m11: float,
    m12: float,
    m21: float,
    m22: float,
    alpha: float = 1.0,
    src_sprite: tuple[int, int, int, int, array] | None = None,
) -> None:
    sw, sh, hx, hy, src = sprite() if src_sprite is None else src_sprite
    alpha = max(0.0, min(1.0, alpha))
    det = m11 * m22 - m12 * m21
    if abs(det) < 1e-9:
        return
    inv11 = m22 / det
    inv12 = -m12 / det
    inv21 = -m21 / det
    inv22 = m11 / det
    corners = ((-hx, -hy), (sw - hx, -hy), (-hx, sh - hy), (sw - hx, sh - hy))
    xs = []
    ys = []
    for ox, oy in corners:
        xs.append(dx + ox * m11 + oy * m12)
        ys.append(dy + ox * m21 + oy * m22)
    min_x = max(0, int(math.floor(min(xs))) - 1)
    max_x = min(canvas - 1, int(math.ceil(max(xs))) + 1)
    min_y = max(0, int(math.floor(min(ys))) - 1)
    max_y = min(canvas - 1, int(math.ceil(max(ys))) + 1)
    put = dest
    for y in range(min_y, max_y + 1):
        ry = y + 0.5 - dy
        row = y * canvas
        for x in range(min_x, max_x + 1):
            rx = x + 0.5 - dx
            sx = rx * inv11 + ry * inv12 + hx
            sy = rx * inv21 + ry * inv22 + hy
            if sx < 0 or sy < 0 or sx >= sw - 1 or sy >= sh - 1:
                continue
            x0 = int(sx)
            y0 = int(sy)
            fx = sx - x0
            fy = sy - y0
            i00 = y0 * sw + x0
            i10 = i00 + 1
            i01 = i00 + sw
            i11 = i01 + 1
            p00, p10, p01, p11 = src[i00], src[i10], src[i01], src[i11]
            if (p00 | p10 | p01 | p11) == 0:
                continue
            a = (
                ((p00 >> 24) & 255) * (1 - fx) * (1 - fy)
                + ((p10 >> 24) & 255) * fx * (1 - fy)
                + ((p01 >> 24) & 255) * (1 - fx) * fy
                + ((p11 >> 24) & 255) * fx * fy
            ) * alpha
            if a < 1:
                continue
            r = (
                ((p00 >> 16) & 255) * (1 - fx) * (1 - fy)
                + ((p10 >> 16) & 255) * fx * (1 - fy)
                + ((p01 >> 16) & 255) * (1 - fx) * fy
                + ((p11 >> 16) & 255) * fx * fy
            ) * alpha
            g = (
                ((p00 >> 8) & 255) * (1 - fx) * (1 - fy)
                + ((p10 >> 8) & 255) * fx * (1 - fy)
                + ((p01 >> 8) & 255) * (1 - fx) * fy
                + ((p11 >> 8) & 255) * fx * fy
            ) * alpha
            b = (
                (p00 & 255) * (1 - fx) * (1 - fy)
                + (p10 & 255) * fx * (1 - fy)
                + (p01 & 255) * (1 - fx) * fy
                + (p11 & 255) * fx * fy
            ) * alpha
            di = row + x
            d = int(put[di])
            da = (d >> 24) & 255
            inv_a = 255 - int(a)
            oa = int(a) + da * inv_a // 255
            or_ = int(r) + ((d >> 16) & 255) * inv_a // 255
            og = int(g) + ((d >> 8) & 255) * inv_a // 255
            ob = int(b) + (d & 255) * inv_a // 255
            put[di] = (min(255, oa) << 24) | (min(255, or_) << 16) | (min(255, og) << 8) | min(255, ob)


def _blur_premul_sprite(src: tuple[int, int, int, int, array], radius: int) -> tuple[int, int, int, int, array]:
    if radius < 1:
        return src
    w, h, hx, hy, pix = src
    chans = [[0] * (w * h) for _ in range(4)]
    for i, p in enumerate(pix):
        v = int(p)
        chans[0][i] = (v >> 24) & 255
        chans[1][i] = (v >> 16) & 255
        chans[2][i] = (v >> 8) & 255
        chans[3][i] = v & 255
    blurred = [_box_blur_u8(ch, w, h, radius) for ch in chans]
    out = array("I", [0] * (w * h))
    for i in range(w * h):
        a, r, g, b = (min(255, blurred[k][i]) for k in range(4))
        if a:
            out[i] = (a << 24) | (r << 16) | (g << 8) | b
    return w, h, hx, hy, out


def blit_browser_visual(dest: object, canvas: int, dx: float, dy: float, vis: dict, press: bool = False) -> None:
    """Map CursorState.render() onto the plugin 23×24 paper-plane (overlay-re §2/§5)."""
    axis = float(vis["axis"] or 0.0)
    stretch_u = vis["axis_stretch"]
    u = float(stretch_u) if stretch_u is not None else 1.0
    rot = float(vis["rotate"]) + BAKE_DEG
    sx, sy = vis["scale"]
    sx, sy = float(sx), float(sy)
    if press:
        sx *= 0.88
        sy = min(sy, 0.80)
    alpha = max(0.0, min(1.0, float(vis["opacity"])))
    mat = compose_axis_matrix(axis, u, rot, sx, sy)
    src = plugin_sprite()
    blur_px = float(vis.get("blur_px") or 0.0)
    if blur_px >= 0.8:
        src = _blur_premul_sprite(src, int(round(min(5.0, blur_px))))
    blit_transformed(dest, canvas, dx, dy, mat[0][0], mat[0][1], mat[1][0], mat[1][1], alpha, src)


def blit_rotated(
    dest: object,
    canvas: int,
    dx: float,
    dy: float,
    angle: float,
    scale: float,
    alpha: float = 1.0,
    scale_y: float | None = None,
) -> None:
    """Rotate + non-uniform scale blit; wraps blit_transformed."""
    scale = max(0.2, scale)
    sy_scale = scale if scale_y is None else max(0.2, scale_y)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    blit_transformed(
        dest,
        canvas,
        dx,
        dy,
        cos_a * scale,
        -sin_a * sy_scale,
        sin_a * scale,
        cos_a * sy_scale,
        alpha,
    )
