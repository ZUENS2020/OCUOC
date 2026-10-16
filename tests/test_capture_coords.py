from PIL import Image

from ocuoc.capture.coords import fit_size, image_xy_to_screen
from ocuoc.capture.screenshot import _capture_dxgi, _crop_client


def test_image_xy_to_screen_identity():
    assert image_xy_to_screen(10, 20, origin=(100, 200), src_size=(100, 100), image_size=(100, 100)) == (110, 220)


def test_image_xy_to_screen_scaled():
    x, y = image_xy_to_screen(
        400,
        200,
        origin=(0, 0),
        src_size=(1600, 800),
        image_size=(800, 400),
    )
    assert (x, y) == (800, 400)


def test_fit_size_caps_long_edge():
    assert fit_size(3200, 1600, 1600) == (1600, 800)
    assert fit_size(800, 600, 1600) == (800, 600)


def test_crop_client_drops_window_chrome():
    image = Image.new("RGB", (200, 120), (10, 20, 30))
    cropped = _crop_client(image, window_rect=(0, 0, 200, 120), client_rect=(8, 32, 192, 112))
    assert cropped is not None
    assert cropped.size == (184, 80)


def test_wgc_unavailable_is_silent():
    import ocuoc.capture.wgc as wgc
    from ocuoc.capture.screenshot import _capture_wgc

    wgc._unavailable = True
    try:
        assert _capture_wgc(0, 0, 16, 16) is None
    finally:
        wgc.reset_for_tests()


def test_wgc_invalid_hwnd_is_silent():
    import ocuoc.capture.wgc as wgc
    from ocuoc.capture.screenshot import _capture_wgc

    wgc.reset_for_tests()
    try:
        assert _capture_wgc(0, 0, 16, 16, hwnd=1) is None
    finally:
        wgc.reset_for_tests()


def test_dxgi_backend_absent_is_silent():
    import ocuoc.capture.screenshot as shot

    shot._dxcam_unavailable = True
    try:
        assert _capture_dxgi(0, 0, 16, 16) is None
    finally:
        shot._dxcam_unavailable = False
        shot._dxcam_cam = None
