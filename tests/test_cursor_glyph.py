import math

from ocuoc.collab.cursor_glyph import (
    CUBICS,
    FILL_RGB,
    GLYPH_PX,
    P0,
    REST_HEADING,
    heading_for_velocity,
    rasterize_sprite,
    sample_outline,
    sprite,
)
from ocuoc.input.motion import cubic3, cubic3_tangent


def test_outline_has_four_cubics_from_p0():
    assert P0 == (0.0060, 0.1586)
    assert len(CUBICS) == 4
    assert CUBICS[-1][-1] == (0.2451, 0.9172)


def test_outline_is_closed_teardrop():
    pts = sample_outline()
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert min(xs) < 0.01
    assert max(xs) > 0.9
    assert min(ys) < 0.02
    assert max(ys) > 0.95
    assert math.hypot(pts[0][0] - P0[0], pts[0][1] - P0[1]) < 1e-9


def test_left_edge_is_straighter_than_right_bulge():
    pts = sample_outline()
    xs = [p[0] for p in pts]
    assert max(xs) > 0.9
    assert P0[0] < 0.05
    assert CUBICS[-1][-1][0] < 0.3
    # Closing edge P12 → P0 is the straight left side; the cubics bulge right.


def test_rest_heading_is_up_left():
    assert REST_HEADING == math.atan2(-1.0, -1.0)
    extra = heading_for_velocity(1.0, 0.0)
    assert extra > 1.0


def test_sprite_fill_is_codex_blue_not_cyan():
    w, h, hx, hy, pixels = sprite()
    bx = int(hx + 0.42 * GLYPH_PX)
    by = int(hy + 0.42 * GLYPH_PX)
    pix = int(pixels[by * w + bx])
    a = (pix >> 24) & 255
    assert a > 80
    r = ((pix >> 16) & 255) * 255 // a
    g = ((pix >> 8) & 255) * 255 // a
    b = (pix & 255) * 255 // a
    assert r < 80
    assert 70 < g < 160
    assert b > 150
    assert FILL_RGB == (1, 105, 204)


def test_sprite_is_glyph_sized():
    w, h, _hx, _hy, _pixels = sprite()
    assert w <= 72
    assert h <= 72


def test_edges_are_antialiased():
    w, h, _hx, _hy, pixels = sprite()
    partial = 0
    for y in range(h):
        row = y * w
        for x in range(w):
            a = (int(pixels[row + x]) >> 24) & 255
            if 12 <= a <= 240:
                partial += 1
    assert partial > 40


def test_bezier_tangent_points_along_the_path():
    p0, p3 = (0.0, 0.0), (100.0, 0.0)
    p1, p2 = (100.0 / 3.0, 0.0), (200.0 / 3.0, 0.0)
    vx, vy = cubic3_tangent(p0, p1, p2, p3, 0.5)
    x, y = cubic3(p0, p1, p2, p3, 0.5)
    assert vx > 0
    assert vy == 0.0
    assert 0 < x < 100
    # tangent on a curved segment is non-zero everywhere
    c1, c2, c3 = CUBICS[0]
    for i in range(5):
        tx, ty = cubic3_tangent(P0, c1, c2, c3, i / 4.0)
        assert math.hypot(tx, ty) > 1e-6
