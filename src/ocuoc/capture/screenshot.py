from __future__ import annotations

import ctypes
import io
import os
import secrets
from dataclasses import dataclass

from PIL import Image

from ocuoc.capture.coords import fit_size
from ocuoc.errors import EngineError
from ocuoc.winapi import (
    BITMAPINFO,
    PW_RENDERFULLCONTENT,
    SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN,
    SM_XVIRTUALSCREEN,
    SM_YVIRTUALSCREEN,
    SRCCOPY,
    gdi32,
    user32,
)
from ocuoc.wm.windows import WindowInfo, snapshot

DEFAULT_MAX_EDGE = int(os.environ.get("OCUOC_MAX_IMAGE_EDGE", "1600") or "1600")
_dxcam_cam = None
_dxcam_unavailable = False


@dataclass(frozen=True)
class CaptureResult:
    png: bytes
    image_w: int
    image_h: int
    src_w: int
    src_h: int
    origin_x: int
    origin_y: int
    backend: str
    screenshot_id: str
    warning: str | None = None

    @property
    def scale(self) -> dict[str, float]:
        return {
            "x": (self.src_w / self.image_w) if self.image_w else 1.0,
            "y": (self.src_h / self.image_h) if self.image_h else 1.0,
        }

    def meta(self) -> dict:
        data = {
            "screenshot_id": self.screenshot_id,
            "screenshot_size": {"width": self.image_w, "height": self.image_h},
            "source_size": {"width": self.src_w, "height": self.src_h},
            "scale": self.scale,
            "capture_backend": self.backend,
            "origin": {"x": self.origin_x, "y": self.origin_y},
        }
        if self.warning:
            data["capture_warning"] = self.warning
        return data


def capture_window(info: WindowInfo, max_edge: int = DEFAULT_MAX_EDGE) -> CaptureResult:
    current = snapshot(info.hwnd)
    if current is None:
        raise EngineError("window_gone", "cannot capture missing window")
    cl, ct, cr, cb = current.client_rect
    width = cr - cl
    height = cb - ct
    if width < 1 or height < 1:
        left, top, right, bottom = current.rect
        cl, ct, cr, cb = left, top, right, bottom
        width, height = cr - cl, cb - ct
    if width < 1 or height < 1:
        raise EngineError("bad_rect", "window has empty client rectangle")

    image, backend = _capture_rect(cl, ct, width, height, hwnd=info.hwnd, window_rect=current.rect, client_rect=(cl, ct, cr, cb))
    if image is None:
        raise EngineError("capture_failed", "all capture backends failed")
    warning = "image_mostly_black" if _mostly_black(image) else None
    return _encode(image, cl, ct, width, height, backend, max_edge, warning)


def capture_desktop(max_edge: int = DEFAULT_MAX_EDGE) -> CaptureResult:
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if width < 1 or height < 1:
        raise EngineError("bad_rect", "virtual screen is empty")
    image, backend = _capture_rect(left, top, width, height, hwnd=None)
    if image is None:
        raise EngineError("capture_failed", "desktop capture failed")
    warning = "image_mostly_black" if _mostly_black(image) else None
    return _encode(image, left, top, width, height, backend, max_edge, warning)


def capture_window_png(info: WindowInfo) -> tuple[str, int, int]:
    """Back-compat helper used by older tests; returns base64 plus source size."""
    import base64

    result = capture_window(info, max_edge=0)
    return base64.b64encode(result.png).decode("ascii"), result.src_w, result.src_h


def _capture_rect(
    left: int,
    top: int,
    width: int,
    height: int,
    hwnd: int | None,
    window_rect: tuple[int, int, int, int] | None = None,
    client_rect: tuple[int, int, int, int] | None = None,
) -> tuple[Image.Image | None, str]:
    wgc = _capture_wgc(left, top, width, height, hwnd=hwnd, window_rect=window_rect, client_rect=client_rect)
    if wgc is not None and not _mostly_black(wgc):
        return wgc, "wgc"
    dxgi = _capture_dxgi(left, top, width, height)
    if dxgi is not None and not _mostly_black(dxgi):
        return dxgi, "dxgi"
    image = _capture_mss(left, top, width, height)
    if image is not None and not _mostly_black(image):
        return image, "mss"
    printed = _printwindow(hwnd, window_rect, client_rect) if hwnd else None
    if printed is not None and not _mostly_black(printed):
        return printed, "printwindow"
    blt_win = _bitblt_window(hwnd, window_rect, client_rect) if hwnd else None
    if blt_win is not None and not _mostly_black(blt_win):
        return blt_win, "bitblt_window"
    screen = _bitblt_screen(left, top, width, height)
    if screen is not None:
        backend = "bitblt_screen"
        chosen = screen
        if wgc is not None:
            chosen, backend = wgc, "wgc"
        elif dxgi is not None:
            chosen, backend = dxgi, "dxgi"
        elif image is not None:
            chosen, backend = image, "mss"
        elif printed is not None:
            chosen, backend = printed, "printwindow"
        elif blt_win is not None:
            chosen, backend = blt_win, "bitblt_window"
        return chosen, backend
    for candidate, name in (
        (wgc, "wgc"),
        (dxgi, "dxgi"),
        (image, "mss"),
        (printed, "printwindow"),
        (blt_win, "bitblt_window"),
    ):
        if candidate is not None:
            return candidate, name
    return None, ""


def _encode(
    image: Image.Image,
    origin_x: int,
    origin_y: int,
    src_w: int,
    src_h: int,
    backend: str,
    max_edge: int,
    warning: str | None,
) -> CaptureResult:
    image = image.convert("RGB")
    if image.size != (src_w, src_h):
        image = image.resize((src_w, src_h), Image.Resampling.LANCZOS)
    out_w, out_h = fit_size(src_w, src_h, max_edge)
    if (out_w, out_h) != image.size:
        image = image.resize((out_w, out_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return CaptureResult(
        png=buf.getvalue(),
        image_w=out_w,
        image_h=out_h,
        src_w=src_w,
        src_h=src_h,
        origin_x=origin_x,
        origin_y=origin_y,
        backend=backend,
        screenshot_id=secrets.token_hex(8),
        warning=warning,
    )


def _mostly_black(image: Image.Image) -> bool:
    from PIL import ImageStat

    sample = image.convert("RGB").resize((32, 32))
    mean = ImageStat.Stat(sample).mean
    if not mean:
        return True
    return sum(mean) / len(mean) < 4.0


def _capture_wgc(
    left: int,
    top: int,
    width: int,
    height: int,
    hwnd: int | None = None,
    window_rect: tuple[int, int, int, int] | None = None,
    client_rect: tuple[int, int, int, int] | None = None,
) -> Image.Image | None:
    try:
        from ocuoc.capture.wgc import capture_wgc
    except Exception:
        return None
    try:
        return capture_wgc(
            left,
            top,
            width,
            height,
            hwnd=hwnd,
            window_rect=window_rect,
            client_rect=client_rect,
        )
    except Exception:
        return None


def _capture_dxgi(left: int, top: int, width: int, height: int) -> Image.Image | None:
    global _dxcam_cam, _dxcam_unavailable
    if _dxcam_unavailable:
        return None
    try:
        import dxcam
    except Exception:
        _dxcam_unavailable = True
        return None
    try:
        if _dxcam_cam is None:
            try:
                _dxcam_cam = dxcam.create(
                    output_idx=0,
                    output_color="RGB",
                    processor_backend="numpy",
                )
            except TypeError:
                _dxcam_cam = dxcam.create(output_idx=0)
        if _dxcam_cam is None:
            _dxcam_unavailable = True
            return None
        frame = _dxcam_cam.grab(region=(int(left), int(top), int(left + width), int(top + height)))
        if frame is None:
            return None
        return Image.fromarray(frame).convert("RGB")
    except Exception:
        return None


def _capture_mss(left: int, top: int, width: int, height: int) -> Image.Image | None:
    try:
        import mss
    except Exception:
        return None
    try:
        with mss.MSS() as sct:
            raw = sct.grab({"left": int(left), "top": int(top), "width": int(width), "height": int(height)})
        return Image.frombytes("RGB", (raw.width, raw.height), raw.bgra, "raw", "BGRX")
    except Exception:
        return None


def _from_dib(hdc_mem, hbmp, width: int, height: int) -> Image.Image | None:
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(bmi.bmiHeader)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = (ctypes.c_ubyte * (width * height * 4))()
    got = gdi32.GetDIBits(hdc_mem, hbmp, 0, height, ctypes.byref(buf), ctypes.byref(bmi), 0)
    if got == 0:
        return None
    return Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")


def _with_bitmap(hdc_src, width: int, height: int, blit) -> Image.Image | None:
    if not hdc_src:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_src)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_src, width, height)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        if not blit(hdc_mem):
            return None
        return _from_dib(hdc_mem, hbmp, width, height)
    finally:
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)


def _crop_client(
    image: Image.Image | None,
    window_rect: tuple[int, int, int, int] | None,
    client_rect: tuple[int, int, int, int] | None,
) -> Image.Image | None:
    if image is None or window_rect is None or client_rect is None:
        return image
    ox = client_rect[0] - window_rect[0]
    oy = client_rect[1] - window_rect[1]
    cw = client_rect[2] - client_rect[0]
    ch = client_rect[3] - client_rect[1]
    if cw < 1 or ch < 1:
        return image
    box = (max(0, ox), max(0, oy), max(0, ox) + cw, max(0, oy) + ch)
    if box[2] > image.width or box[3] > image.height:
        return image.crop(
            (
                max(0, ox),
                max(0, oy),
                min(image.width, max(0, ox) + cw),
                min(image.height, max(0, oy) + ch),
            )
        )
    return image.crop(box)


def _printwindow(
    hwnd: int | None,
    window_rect: tuple[int, int, int, int] | None,
    client_rect: tuple[int, int, int, int] | None,
) -> Image.Image | None:
    if not hwnd or window_rect is None:
        return None
    width = window_rect[2] - window_rect[0]
    height = window_rect[3] - window_rect[1]
    if width < 1 or height < 1:
        return None
    hdc_win = user32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    try:

        def blit(hdc_mem):
            return bool(user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT))

        image = _with_bitmap(hdc_win, width, height, blit)
        return _crop_client(image, window_rect, client_rect)
    finally:
        user32.ReleaseDC(hwnd, hdc_win)


def _bitblt_window(
    hwnd: int | None,
    window_rect: tuple[int, int, int, int] | None,
    client_rect: tuple[int, int, int, int] | None,
) -> Image.Image | None:
    if not hwnd or window_rect is None:
        return None
    width = window_rect[2] - window_rect[0]
    height = window_rect[3] - window_rect[1]
    if width < 1 or height < 1:
        return None
    hdc_win = user32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    try:

        def blit(hdc_mem):
            return bool(gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_win, 0, 0, SRCCOPY))

        image = _with_bitmap(hdc_win, width, height, blit)
        return _crop_client(image, window_rect, client_rect)
    finally:
        user32.ReleaseDC(hwnd, hdc_win)


def _bitblt_screen(left: int, top: int, width: int, height: int) -> Image.Image | None:
    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        return None
    try:

        def blit(hdc_mem):
            return bool(gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY))

        return _with_bitmap(hdc_screen, width, height, blit)
    finally:
        user32.ReleaseDC(None, hdc_screen)
