"""GIF / pixel self-check for browser cursor (writes gitignored docs/assets)."""

from __future__ import annotations

from array import array
from pathlib import Path

from PIL import Image

from ocuoc.collab.cursor_glyph import blit_browser_visual, compose_axis_matrix
from ocuoc.input.motion_browser import (
    REST_ROT,
    THINK_AMPLITUDE_DEG,
    CursorState,
    delta_deg,
    iter_move_frames,
)

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "cursor_v2_selfcheck"
CANVAS = 96
HOT = (48, 48)
BOUNDS = (1280.0, 800.0)


def _frame(vis) -> Image.Image:
    px = array("I", [0] * (CANVAS * CANVAS))
    blit_browser_visual(px, CANVAS, HOT[0], HOT[1], vis)
    img = Image.new("RGBA", (CANVAS, CANVAS))
    for i, pix in enumerate(px):
        a = (pix >> 24) & 255
        r = (pix >> 16) & 255
        g = (pix >> 8) & 255
        b = pix & 255
        img.putpixel((i % CANVAS, i // CANVAS), (r, g, b, a))
    return img


def _write_gif(name: str, frames: list[Image.Image]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=16, loop=0, disposal=2)
    return path


def test_compose_axis_identity_at_rest():
    m = compose_axis_matrix(0.0, 1.0, 0.0, 1.0, 1.0)
    assert abs(m[0][0] - 1.0) < 1e-9
    assert abs(m[1][1] - 1.0) < 1e-9
    assert abs(m[0][1]) < 1e-9
    assert abs(m[1][0]) < 1e-9


def test_long_and_short_gifs_and_pixel_traits():
    long_frames = []
    ys = []
    for _t, st in iter_move_frames((100.0, 400.0), (1100.0, 400.0), BOUNDS):
        vis = st.render(_t)
        long_frames.append(_frame(vis))
        ys.append(st.point[1])
        if st.motion is None:
            break
    assert max(abs(y - 400.0) for y in ys) > 8
    _write_gif("long_bezier.gif", long_frames[::2] or long_frames)

    short_frames = []
    stretch = []
    for _t, st in iter_move_frames((400.0, 300.0), (400.0 + 180.0, 300.0), BOUNDS):
        vis = st.render(_t)
        short_frames.append(_frame(vis))
        stretch.append(float(st.scoot_stretch.value))
        if st.motion is None:
            break
    assert stretch
    assert max(stretch) > 1.02
    vis_stretch = []
    for _t, st in iter_move_frames((400.0, 300.0), (400.0 + 180.0, 300.0), BOUNDS):
        vis = st.render(_t)
        u = vis.get("axis_stretch")
        if u is not None:
            vis_stretch.append(float(u))
        if st.motion is None:
            break
    assert vis_stretch
    assert max(vis_stretch) > 1.02
    _write_gif("short_scoot.gif", short_frames[::2] or short_frames)

    st = CursorState.create((200.0, 200.0), True)
    st.set_target((200.0 + 40.0, 200.0), BOUNDS)
    t = 0.0
    while st.motion is not None:
        t += 1.0 / 60.0
        st.step(1.0 / 60.0, t)
    wobble = []
    rot0 = st.rotation
    frames = []
    for i in range(90):
        t += 1.0 / 60.0
        st.step(1.0 / 60.0, t)
        vis = st.render(t)
        frames.append(_frame(vis))
        wobble.append(abs(delta_deg(rot0, float(vis["rotate"]))))
    assert max(wobble) <= THINK_AMPLITUDE_DEG + 0.5
    assert max(wobble) > 1.0
    assert REST_ROT == -44.0
    _write_gif("think_wobble.gif", frames)


def test_badge_sprites_independent_redraw():
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {
        "badge_active.png": (17, 17, 17, 255),
        "badge_deliverable.png": (34, 197, 94, 255),
        "badge_handoff.png": (250, 204, 21, 255),
    }
    for name, color in specs.items():
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        if "active" in name:
            # Independent paper-plane-ish triangle (not an official path).
            for y in range(6, 26):
                for x in range(6, 20 + (y // 4)):
                    if 6 <= x <= 26:
                        img.putpixel((min(31, x), y), color)
        else:
            cx, cy, r = 16, 16, 7
            for y in range(32):
                for x in range(32):
                    if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                        img.putpixel((x, y), color)
        img.save(OUT / name)
        pix = img.getpixel((16, 16))
        assert pix[3] > 0
