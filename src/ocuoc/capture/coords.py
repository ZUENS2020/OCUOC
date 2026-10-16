from __future__ import annotations


def image_xy_to_screen(
    x: float,
    y: float,
    *,
    origin: tuple[int, int],
    src_size: tuple[int, int],
    image_size: tuple[int, int],
) -> tuple[int, int]:
    """Map a pixel on the (possibly scaled) screenshot back to screen coordinates."""
    origin_x, origin_y = origin
    src_w, src_h = src_size
    image_w, image_h = image_size
    if image_w < 1 or image_h < 1:
        return origin_x + int(x), origin_y + int(y)
    sx = origin_x + int(round(x * (src_w / image_w)))
    sy = origin_y + int(round(y * (src_h / image_h)))
    return sx, sy


def fit_size(width: int, height: int, max_edge: int) -> tuple[int, int]:
    if max_edge <= 0 or width < 1 or height < 1:
        return width, height
    longest = max(width, height)
    if longest <= max_edge:
        return width, height
    scale = max_edge / longest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))
