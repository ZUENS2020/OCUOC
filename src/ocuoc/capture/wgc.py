"""WinRT Graphics.Capture one-shot grab. Failures return None for the existing fallback chain."""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes

from PIL import Image
from comtypes import GUID

_unavailable = False
_worker: _WgcWorker | None = None
_worker_lock = threading.Lock()

RO_INIT_MULTITHREADED = 1
D3D_DRIVER_TYPE_HARDWARE = 1
D3D_DRIVER_TYPE_WARP = 5
D3D11_CREATE_DEVICE_BGRA_SUPPORT = 0x20
D3D11_SDK_VERSION = 7
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
DXGI_FORMAT_B8G8R8A8_UNORM = 87
PIXEL_BGRA8 = 87
MONITOR_DEFAULTTONEAREST = 2

IID_IGraphicsCaptureItemInterop = GUID("{3628E81B-3CAC-4C60-B7F4-23CE0E0C3356}")
IID_IGraphicsCaptureItem = GUID("{79C3F95B-31F7-4EC2-A464-632EF5D30760}")
# GetIids on this OS; windows-rs Statics/Statics2 suffixes (B96D... / 0118AB0DCB36) E_NOINTERFACE.
IID_IDirect3D11CaptureFramePoolStatics = GUID("{7784056A-67AA-4D53-AE54-1088D5A8CA21}")
IID_IDirect3D11CaptureFramePoolStatics2 = GUID("{589B103F-6BBC-5DF5-A991-02E28B3B66D5}")
IID_IActivationFactory = GUID("{00000035-0000-0000-C000-000000000046}")
IID_IUnknown = GUID("{00000000-0000-0000-C000-000000000046}")
IID_IDirect3D11CaptureFramePool = GUID("{24EB6D22-1975-422E-82E7-780DBD8DDF24}")
IID_IDirect3D11CaptureFrame = GUID("{FA50C623-38DA-4B32-ACF3-FA9734AD800E}")
IID_IGraphicsCaptureSession = GUID("{814E42A9-F70F-4AD7-939F-AFD39C9A69E2}")
IID_IGraphicsCaptureSession2 = GUID("{2C39AE40-7D2E-5044-804E-8B6799D4CF9E}")
IID_IClosable = GUID("{30D5A829-7FA4-4026-83BB-D75BAE4EA99E}")
IID_IDirect3DDxgiInterfaceAccess = GUID("{A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1}")
IID_ID3D11Texture2D = GUID("{6F15AAF2-D208-4E89-9AB4-489535D34F9C}")
IID_IDXGIDevice = GUID("{54EC77FA-1377-44E6-8C32-88FD5F44C84C}")
IID_IDirect3DDevice = GUID("{A3763389-3327-4578-9CE8-D3BF66E1F2C5}")

CLASS_CAPTURE_ITEM = "Windows.Graphics.Capture.GraphicsCaptureItem"
CLASS_FRAME_POOL = "Windows.Graphics.Capture.Direct3D11CaptureFramePool"


class SizeInt32(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_int32), ("Height", ctypes.c_int32)]


class DXGI_SAMPLE_DESC(ctypes.Structure):
    _fields_ = [("Count", ctypes.c_uint), ("Quality", ctypes.c_uint)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("MipLevels", ctypes.c_uint),
        ("ArraySize", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("SampleDesc", DXGI_SAMPLE_DESC),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
    ]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [
        ("pData", ctypes.c_void_p),
        ("RowPitch", ctypes.c_uint),
        ("DepthPitch", ctypes.c_uint),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", ctypes.c_uint),
    ]


def _load():
    combase = ctypes.WinDLL("combase")
    d3d11 = ctypes.WinDLL("d3d11")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    combase.RoInitialize.argtypes = [ctypes.c_uint]
    combase.RoInitialize.restype = ctypes.c_long
    combase.WindowsCreateString.argtypes = [wintypes.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    combase.WindowsCreateString.restype = ctypes.c_long
    combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
    combase.WindowsDeleteString.restype = ctypes.c_long
    combase.RoGetActivationFactory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    combase.RoGetActivationFactory.restype = ctypes.c_long
    d3d11.D3D11CreateDevice.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    d3d11.D3D11CreateDevice.restype = ctypes.c_long
    d3d11.CreateDirect3D11DeviceFromDXGIDevice.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    d3d11.CreateDirect3D11DeviceFromDXGIDevice.restype = ctypes.c_long
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), ctypes.c_uint]
    user32.MonitorFromRect.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    return combase, d3d11, user32


def _call(this: int, index: int, restype, argtypes, *args):
    vtbl = ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))[0]
    slot = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    if restype is ctypes.HRESULT:
        restype = ctypes.c_long
    func = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(slot)
    return func(this, *args)


def _release(this: int | None) -> None:
    if this:
        _call(this, 2, ctypes.c_ulong, [])


def _qi(this: int, iid: GUID) -> int:
    out = ctypes.c_void_p()
    hr = _call(
        this,
        0,
        ctypes.HRESULT,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        ctypes.byref(iid),
        ctypes.byref(out),
    )
    if hr != 0 or not out.value:
        return 0
    return int(out.value)


def _hstring(combase, text: str) -> int:
    handle = ctypes.c_void_p()
    hr = combase.WindowsCreateString(text, len(text), ctypes.byref(handle))
    if hr != 0 or not handle.value:
        return 0
    return int(handle.value)


def _inspectable_iids(this: int) -> list[GUID]:
    count = ctypes.c_ulong(0)
    raw = ctypes.c_void_p()
    hr = _call(
        this,
        3,
        ctypes.c_long,
        [ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)],
        ctypes.byref(count),
        ctypes.byref(raw),
    )
    if hr != 0 or not raw.value or count.value <= 0:
        return []
    try:
        arr = ctypes.cast(raw, ctypes.POINTER(GUID))
        return [GUID(str(arr[i])) for i in range(int(count.value))]
    finally:
        ctypes.WinDLL("ole32").CoTaskMemFree(raw)


def _pool_factory(combase) -> int:
    ctypes.WinDLL("kernel32").LoadLibraryW("Windows.Graphics.dll")
    base = _factory(combase, CLASS_FRAME_POOL, IID_IActivationFactory)
    if not base:
        return 0
    skip = {
        str(IID_IActivationFactory).upper(),
        str(IID_IUnknown).upper(),
    }
    discovered = _inspectable_iids(base)
    preferred: list[GUID] = []
    rest: list[GUID] = []
    for iid in discovered:
        key = str(iid).upper()
        if key in skip:
            continue
        if key.startswith("{589B103F"):
            preferred.append(iid)
        else:
            rest.append(iid)
    for iid in [*preferred, *rest, IID_IDirect3D11CaptureFramePoolStatics2, IID_IDirect3D11CaptureFramePoolStatics]:
        found = _qi(base, iid)
        if found:
            _release(base)
            return found
    _release(base)
    return 0


def _factory(combase, class_name: str, iid: GUID) -> int:
    hs = _hstring(combase, class_name)
    if not hs:
        return 0
    try:
        out = ctypes.c_void_p()
        hr = combase.RoGetActivationFactory(hs, ctypes.byref(iid), ctypes.byref(out))
        if hr != 0 or not out.value:
            return 0
        return int(out.value)
    finally:
        combase.WindowsDeleteString(hs)


def _close(this: int | None) -> None:
    if not this:
        return
    closable = _qi(this, IID_IClosable)
    if closable:
        _call(closable, 6, ctypes.HRESULT, [])
        _release(closable)


def _monitor_rect(user32, monitor) -> tuple[int, int, int, int] | None:
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return int(r.left), int(r.top), int(r.right), int(r.bottom)


def reset_for_tests() -> None:
    global _unavailable, _worker
    _unavailable = False
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


class _WgcWorker:
    def __init__(self) -> None:
        self.jobs: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="ocuoc-wgc", daemon=True)
        self._thread.start()
        self.ready.wait(timeout=3.0)

    def stop(self) -> None:
        self.jobs.put(None)
        self._thread.join(timeout=1.5)

    def capture(self, job: dict, timeout: float = 0.8) -> Image.Image | None:
        reply: queue.Queue = queue.Queue()
        self.jobs.put((job, reply))
        try:
            return reply.get(timeout=timeout)
        except queue.Empty:
            return None

    def _loop(self) -> None:
        global _unavailable
        try:
            combase, d3d11, user32 = _load()
            hr = combase.RoInitialize(RO_INIT_MULTITHREADED)
            if hr not in {0, 1, -2147417850}:
                _unavailable = True
                self.ready.set()
                return
            device, context, winrt_device = _create_d3d(d3d11)
            item_factory = _factory(combase, CLASS_CAPTURE_ITEM, IID_IGraphicsCaptureItemInterop)
            pool_factory = _pool_factory(combase)
            if not device or not winrt_device or not item_factory or not pool_factory:
                _unavailable = True
                self.ready.set()
                return
            self.ready.set()
            while True:
                item = self.jobs.get()
                if item is None:
                    break
                job, reply = item
                image = None
                try:
                    image = _grab(
                        user32,
                        item_factory,
                        pool_factory,
                        device,
                        context,
                        winrt_device,
                        job,
                    )
                except Exception:
                    image = None
                reply.put(image)
        except Exception:
            _unavailable = True
            self.ready.set()


def _create_d3d(d3d11):
    for driver in (D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP):
        device = ctypes.c_void_p()
        context = ctypes.c_void_p()
        hr = d3d11.D3D11CreateDevice(
            None,
            driver,
            None,
            D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            None,
            0,
            D3D11_SDK_VERSION,
            ctypes.byref(device),
            None,
            ctypes.byref(context),
        )
        if hr != 0 or not device.value:
            continue
        dxgi = _qi(int(device.value), IID_IDXGIDevice)
        if not dxgi:
            _release(int(device.value))
            _release(int(context.value) if context.value else 0)
            continue
        inspectable = ctypes.c_void_p()
        hr = d3d11.CreateDirect3D11DeviceFromDXGIDevice(dxgi, ctypes.byref(inspectable))
        _release(dxgi)
        if hr != 0 or not inspectable.value:
            _release(int(device.value))
            _release(int(context.value) if context.value else 0)
            continue
        winrt = _qi(int(inspectable.value), IID_IDirect3DDevice) or int(inspectable.value)
        if winrt != int(inspectable.value):
            _release(int(inspectable.value))
        return int(device.value), int(context.value) if context.value else 0, winrt
    return 0, 0, 0


def _grab(user32, item_factory, pool_factory, device, context, winrt_device, job: dict) -> Image.Image | None:
    item = 0
    pool = 0
    session = 0
    frame = 0
    try:
        item = _create_item(user32, item_factory, job)
        if not item:
            return None
        size = SizeInt32()
        hr = _call(item, 7, ctypes.HRESULT, [ctypes.POINTER(SizeInt32)], ctypes.byref(size))
        if hr != 0 or size.Width < 1 or size.Height < 1:
            return None
        pool_ptr = ctypes.c_void_p()
        hr = _call(
            pool_factory,
            6,
            ctypes.HRESULT,
            [ctypes.c_void_p, ctypes.c_int, ctypes.c_int32, SizeInt32, ctypes.POINTER(ctypes.c_void_p)],
            winrt_device,
            PIXEL_BGRA8,
            2,
            size,
            ctypes.byref(pool_ptr),
        )
        if hr != 0 or not pool_ptr.value:
            return None
        pool = int(pool_ptr.value)
        session_ptr = ctypes.c_void_p()
        hr = _call(
            pool,
            10,
            ctypes.HRESULT,
            [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            item,
            ctypes.byref(session_ptr),
        )
        if hr != 0 or not session_ptr.value:
            return None
        session = int(session_ptr.value)
        session2 = _qi(session, IID_IGraphicsCaptureSession2)
        if session2:
            _call(session2, 7, ctypes.HRESULT, [ctypes.c_ubyte], 0)
            _release(session2)
        hr = _call(session, 6, ctypes.HRESULT, [])
        if hr != 0:
            return None
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            frame_ptr = ctypes.c_void_p()
            hr = _call(pool, 7, ctypes.HRESULT, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(frame_ptr))
            if hr == 0 and frame_ptr.value:
                frame = int(frame_ptr.value)
                break
            time.sleep(0.01)
        if not frame:
            return None
        image = _frame_to_image(device, context, frame)
        if image is None:
            return None
        return _crop_job(user32, image, job)
    finally:
        _close(frame)
        _release(frame)
        _close(session)
        _release(session)
        _close(pool)
        _release(pool)
        _release(item)


def _create_item(user32, item_factory, job: dict) -> int:
    out = ctypes.c_void_p()
    if job.get("hwnd"):
        hr = _call(
            item_factory,
            3,
            ctypes.HRESULT,
            [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            job["hwnd"],
            ctypes.byref(IID_IGraphicsCaptureItem),
            ctypes.byref(out),
        )
    else:
        rect = wintypes.RECT(job["left"], job["top"], job["left"] + job["width"], job["top"] + job["height"])
        monitor = user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return 0
        job["monitor"] = int(monitor)
        hr = _call(
            item_factory,
            4,
            ctypes.HRESULT,
            [wintypes.HMONITOR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            monitor,
            ctypes.byref(IID_IGraphicsCaptureItem),
            ctypes.byref(out),
        )
    if hr != 0 or not out.value:
        return 0
    return int(out.value)


def _frame_to_image(device: int, context: int, frame: int) -> Image.Image | None:
    surface_ptr = ctypes.c_void_p()
    hr = _call(frame, 6, ctypes.HRESULT, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(surface_ptr))
    if hr != 0 or not surface_ptr.value:
        return None
    surface = int(surface_ptr.value)
    access = _qi(surface, IID_IDirect3DDxgiInterfaceAccess)
    _release(surface)
    if not access:
        return None
    tex_ptr = ctypes.c_void_p()
    hr = _call(
        access,
        3,
        ctypes.HRESULT,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
        ctypes.byref(IID_ID3D11Texture2D),
        ctypes.byref(tex_ptr),
    )
    _release(access)
    if hr != 0 or not tex_ptr.value:
        return None
    texture = int(tex_ptr.value)
    try:
        desc = D3D11_TEXTURE2D_DESC()
        _call(texture, 10, None, [ctypes.POINTER(D3D11_TEXTURE2D_DESC)], ctypes.byref(desc))
        staging_desc = D3D11_TEXTURE2D_DESC()
        staging_desc.Width = desc.Width
        staging_desc.Height = desc.Height
        staging_desc.MipLevels = 1
        staging_desc.ArraySize = 1
        staging_desc.Format = desc.Format or DXGI_FORMAT_B8G8R8A8_UNORM
        staging_desc.SampleDesc.Count = 1
        staging_desc.Usage = D3D11_USAGE_STAGING
        staging_desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ
        staging_ptr = ctypes.c_void_p()
        hr = _call(
            device,
            5,
            ctypes.HRESULT,
            [ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
            ctypes.byref(staging_desc),
            None,
            ctypes.byref(staging_ptr),
        )
        if hr != 0 or not staging_ptr.value:
            return None
        staging = int(staging_ptr.value)
        try:
            _call(context, 47, None, [ctypes.c_void_p, ctypes.c_void_p], staging, texture)
            mapped = D3D11_MAPPED_SUBRESOURCE()
            hr = _call(
                context,
                14,
                ctypes.HRESULT,
                [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE)],
                staging,
                0,
                D3D11_MAP_READ,
                0,
                ctypes.byref(mapped),
            )
            if hr != 0 or not mapped.pData:
                return None
            width, height = int(desc.Width), int(desc.Height)
            pitch = int(mapped.RowPitch)
            src = ctypes.string_at(mapped.pData, pitch * height)
            _call(context, 15, None, [ctypes.c_void_p, ctypes.c_uint], staging, 0)
            rows = [src[y * pitch : y * pitch + width * 4] for y in range(height)]
            buf = b"".join(rows)
            return Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB")
        finally:
            _release(staging)
    finally:
        _release(texture)


def _crop_job(user32, image: Image.Image, job: dict) -> Image.Image | None:
    if job.get("hwnd") and job.get("window_rect") and job.get("client_rect"):
        from ocuoc.capture.screenshot import _crop_client

        return _crop_client(image, job["window_rect"], job["client_rect"])
    left, top, width, height = job["left"], job["top"], job["width"], job["height"]
    monitor = job.get("monitor")
    if not monitor:
        rect = wintypes.RECT(left, top, left + width, top + height)
        monitor = user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST)
    bounds = _monitor_rect(user32, monitor)
    if bounds is None:
        if image.size == (width, height):
            return image
        return None
    ml, mt, _mr, _mb = bounds
    ox, oy = left - ml, top - mt
    box = (ox, oy, ox + width, oy + height)
    if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
        if image.size == (width, height):
            return image
        return image.crop(
            (
                max(0, ox),
                max(0, oy),
                min(image.width, ox + width),
                min(image.height, oy + height),
            )
        )
    return image.crop(box)


def capture_wgc(
    left: int,
    top: int,
    width: int,
    height: int,
    hwnd: int | None = None,
    window_rect: tuple[int, int, int, int] | None = None,
    client_rect: tuple[int, int, int, int] | None = None,
) -> Image.Image | None:
    global _unavailable, _worker
    if _unavailable or width < 1 or height < 1:
        return None
    with _worker_lock:
        if _worker is None:
            try:
                _worker = _WgcWorker()
            except Exception:
                _unavailable = True
                return None
        worker = _worker
    if _unavailable:
        return None
    job = {
        "left": int(left),
        "top": int(top),
        "width": int(width),
        "height": int(height),
        "hwnd": int(hwnd) if hwnd else 0,
        "window_rect": window_rect,
        "client_rect": client_rect,
    }
    try:
        return worker.capture(job)
    except Exception:
        return None
