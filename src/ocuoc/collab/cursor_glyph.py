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
    """Rotate + non-uniform scale blit; scale_y alone gives the original's
    squash Vector3(1, s, 1) (sub_14004BCA6 L1453-1459)."""
    sw, sh, hx, hy, src = sprite()
    scale = max(0.2, scale)
    sy_scale = scale if scale_y is None else max(0.2, scale_y)
    alpha = max(0.0, min(1.0, alpha))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    corners = ((-hx, -hy), (sw - hx, -hy), (-hx, sh - hy), (sw - hx, sh - hy))
    xs = []
    ys = []
    for ox, oy in corners:
        ox *= scale
        oy *= sy_scale
        xs.append(dx + ox * cos_a - oy * sin_a)
        ys.append(dy + ox * sin_a + oy * cos_a)
    min_x = max(0, int(math.floor(min(xs))) - 1)
    max_x = min(canvas - 1, int(math.ceil(max(xs))) + 1)
    min_y = max(0, int(math.floor(min(ys))) - 1)
    max_y = min(canvas - 1, int(math.ceil(max(ys))) + 1)
    inv_x = 1.0 / scale
    inv_y = 1.0 / sy_scale
    put = dest
    for y in range(min_y, max_y + 1):
        ry = y + 0.5 - dy
        row = y * canvas
        for x in range(min_x, max_x + 1):
            rx = x + 0.5 - dx
            sx = (rx * cos_a + ry * sin_a) * inv_x + hx
            sy = (-rx * sin_a + ry * cos_a) * inv_y + hy
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
