from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ocuoc.browser.api import BrowserHost
from ocuoc.capture.coords import image_xy_to_screen
from ocuoc.capture.screenshot import CaptureResult, capture_desktop, capture_window
from ocuoc.collab import Collaboration
from ocuoc.errors import EngineError
from ocuoc.input import sendinput
from ocuoc.policy.guard import Guard
from ocuoc.privilege import snapshot as privilege_snapshot
from ocuoc.uia import tree as uia
from ocuoc.webview.parse import parse_webview
from ocuoc.winapi import enable_dpi_awareness, user32
from ocuoc.wm import windows as wm
from ocuoc.wm.apps import list_catalog_apps
from ocuoc.wm.displays import list_displays
from ocuoc.wm.launch import launch_aliases, window_matches_launch
from ocuoc.wm.processes import descendant_pids, snapshot_toolhelp


@dataclass
class ViewResult:
    payload: dict
    png: bytes | None = None


class ComputerUseEngine:
    def __init__(self, guard: Guard | None = None, collab: Collaboration | None = None) -> None:
        enable_dpi_awareness()
        self.guard = guard or Guard.from_env()
        self.collab = collab if collab is not None else Collaboration(self.guard)
        self.browser = BrowserHost()
        self._started = False
        self._shot: dict[str, CaptureResult] = {}
        self._elements: dict[str, list[dict]] = {}

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.collab.start()
        self.collab.on_abort = self.browser.abort

    def stop(self) -> None:
        try:
            self.browser.stop()
        except Exception:
            pass
        self.collab.stop()
        self._started = False

    def _overlay_alive(self) -> bool:
        return bool(getattr(self.collab.overlay, "alive", False))

    def _pointer_animate(self) -> bool:
        return not self._overlay_alive()

    def _handoff(self) -> None:
        """Give the human the system cursor back after an AI input burst."""
        try:
            self.collab.end_session(restore=True)
        except Exception:
            pass

    def _drive(self, info: wm.WindowInfo, x: int | None = None, y: int | None = None, press: bool = False) -> None:
        self.collab.begin(info.hwnd, info.pid)
        if x is None or y is None:
            return
        self.collab.point_to(x, y, press=press)
        if self._overlay_alive():
            self.collab.wait_overlay()

    def _check_abort(self) -> None:
        if not self.guard.allow_input():
            raise EngineError("aborted", f"input aborted: {self.guard.reason()}")

    def _priv(self) -> dict:
        return privilege_snapshot().to_dict()

    def _require(self, window_id: str, generation: str | None, *, mutating: bool) -> wm.WindowInfo:
        info = wm.get_window(window_id)
        if mutating:
            if not self.guard.allow_input():
                raise EngineError("aborted", f"input aborted: {self.guard.reason()}")
            if generation and info.generation != generation:
                raise EngineError(
                    "generation_mismatch",
                    f"window changed (expected {generation}, now {info.generation})",
                )
            helper = privilege_snapshot()
            if info.elevated and not helper.elevated:
                raise EngineError(
                    "integrity_limited",
                    "Accessibility is limited because the target window has higher Windows integrity than the helper.",
                )
        return info

    def _client_origin(self, info: wm.WindowInfo) -> tuple[int, int]:
        cl, ct, cr, cb = info.client_rect
        if cr > cl and cb > ct:
            return cl, ct
        return info.rect[0], info.rect[1]

    def _require_shot(self, window_id: str, screenshot_id: str | None) -> CaptureResult | None:
        shot = self._shot.get(window_id)
        if screenshot_id:
            if shot is None or shot.screenshot_id != screenshot_id:
                raise EngineError(
                    "unknown_screenshot_id",
                    "activate the target or take a fresh screenshot before retrying",
                )
        return shot

    def _map_xy(self, info: wm.WindowInfo, x: int, y: int, screenshot_id: str | None = None) -> tuple[int, int]:
        shot = self._require_shot(info.window_id, screenshot_id)
        origin = self._client_origin(info)
        if shot is None:
            return origin[0] + int(x), origin[1] + int(y)
        return image_xy_to_screen(
            x,
            y,
            origin=origin,
            src_size=(shot.src_w, shot.src_h),
            image_size=(shot.image_w, shot.image_h),
        )

    def list_apps(self) -> dict:
        apps: dict[str, dict] = {}
        for item in list_catalog_apps():
            exe = item.get("exe") or ""
            if exe:
                apps[exe.lower()] = item
        windows = wm.list_windows()
        by_exe: dict[str, list[dict]] = {}
        for info in windows:
            if not info.exe:
                continue
            key = info.exe.lower()
            by_exe.setdefault(key, []).append(
                {
                    "window_id": info.window_id,
                    "title": info.title,
                    "generation": info.generation,
                }
            )
            apps.setdefault(
                key,
                {
                    "id": f"exe:{info.exe}",
                    "name": Path(info.exe).stem,
                    "exe": info.exe,
                    "source": "window",
                },
            )
        notepad = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "notepad.exe"
        if notepad.is_file():
            apps.setdefault(
                str(notepad).lower(),
                {"id": f"exe:{notepad}", "name": "notepad", "exe": str(notepad), "source": "system"},
            )
        out = []
        for key, item in apps.items():
            wins = by_exe.get(key, [])
            row = dict(item)
            row["windows"] = wins
            row["is_running"] = bool(wins)
            out.append(row)
        return {"apps": out, **self._priv()}

    def get_window(self, window_id: str) -> dict:
        info = self._require(window_id, None, mutating=False)
        return {**info.to_dict(), **self._priv()}

    def list_windows(self) -> dict:
        return {"windows": [w.to_dict() for w in wm.list_windows()], **self._priv()}

    def list_displays(self) -> dict:
        return {"displays": list_displays(), **self._priv()}

    def get_window_state(
        self,
        window_id: str,
        include_screenshot: bool = True,
        include_text: bool = True,
        include_elements: bool = True,
        max_elements: int = 200,
    ) -> ViewResult:
        info = self._require(window_id, None, mutating=False)
        result = info.to_dict()
        result.update(self._priv())
        webview = parse_webview(info, max_elements=max_elements)
        result["webview"] = {
            "kind": webview.get("kind"),
            "source": webview.get("source"),
            "parsed": webview.get("parsed"),
            "reason": webview.get("reason"),
            "child_classes": webview.get("child_classes") or [],
        }
        ax: dict = {}
        try:
            ax = uia.describe_snapshot(info, max_elements=max_elements)
        except Exception as exc:
            ax = {}
            result["elements_error"] = str(exc)
        if include_text:
            try:
                result["text"] = uia.collect_text(info)
            except Exception as exc:
                result["text"] = info.title
                result["text_error"] = str(exc)
            if not result.get("text") and ax.get("document_text"):
                result["text"] = ax["document_text"]
        elements: list[dict] = []
        if include_elements:
            parsed_els = webview.get("elements") if webview.get("kind") else None
            if parsed_els:
                elements = parsed_els
            else:
                elements = ax.get("elements") or []
            result["elements"] = elements
            self._elements[window_id] = elements
        ax_meta = {
            "focused_element": ax.get("focused_element"),
            "selected_text": ax.get("selected_text") or "",
            "selected_elements": ax.get("selected_elements") or [],
            "document_text": ax.get("document_text") or "",
        }
        png = None
        if include_screenshot:
            try:
                try:
                    self.collab.overlay.hide()
                except Exception:
                    pass
                cap = capture_window(info)
                self._shot[window_id] = cap
                result.update(cap.meta())
                png = cap.png
            except EngineError as exc:
                result["screenshot_error"] = {"code": exc.code, "message": str(exc)}
        latest = wm.get_window(window_id)
        webview_meta = result.get("webview")
        shot_meta = {
            key: result[key]
            for key in (
                "screenshot_id",
                "screenshot_size",
                "source_size",
                "scale",
                "capture_backend",
                "capture_warning",
                "screenshot_error",
                "origin",
            )
            if key in result
        }
        result.update(latest.to_dict())
        result.update(self._priv())
        if webview_meta is not None:
            result["webview"] = webview_meta
        result.update(shot_meta)
        result.update(ax_meta)
        result.update(self.collab.resume_after_observe())
        return ViewResult(payload=result, png=png)

    def screenshot_desktop(self) -> ViewResult:
        try:
            self.collab.overlay.hide()
        except Exception:
            pass
        cap = capture_desktop()
        self._shot["desktop"] = cap
        payload = {"ok": True, **cap.meta(), **self._priv()}
        return ViewResult(payload=payload, png=cap.png)

    def activate_window(self, window_id: str, generation: str | None = None) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            self._drive(info)
            wm.activate(info)
            time.sleep(0.08)
            return wm.get_window(window_id).to_dict()
        finally:
            self._handoff()

    def launch_app(self, app_id: str, extra_args: list[str] | None = None, timeout_s: float = 30.0) -> dict:
        if not self.guard.allow_input():
            raise EngineError("aborted", f"input aborted: {self.guard.reason()}")
        cmd = app_id[4:] if app_id.startswith("exe:") else app_id
        if not cmd:
            raise EngineError("bad_app", "empty app_id")
        stem = Path(cmd).stem
        aliases = launch_aliases(stem)
        if extra_args:
            extra_path = Path(extra_args[-1])
            aliases = tuple(dict.fromkeys([*aliases, extra_path.stem.lower(), extra_path.name.lower()]))
        before = {w.hwnd for w in wm.list_windows()}
        existing = [w for w in wm.list_windows() if window_matches_launch(w, root_pid=None, descendant_pids=set(), stem=stem, aliases=aliases)]
        argv = [cmd, *(extra_args or [])]
        try:
            try:
                proc = subprocess.Popen(argv, shell=False)
            except OSError as exc:
                raise EngineError("launch_failed", str(exc)) from exc
            root_pid = proc.pid
            deadline = time.time() + timeout_s
            found = None
            while time.time() < deadline:
                rows = snapshot_toolhelp()
                kids = descendant_pids(root_pid, rows)
                windows = wm.list_windows()
                newcomers = [w for w in windows if w.hwnd not in before]
                pool = newcomers or windows
                for cand in pool:
                    if window_matches_launch(cand, root_pid=root_pid, descendant_pids=kids, stem=stem, aliases=aliases):
                        found = cand
                        break
                if found is None and newcomers:
                    found = newcomers[0]
                if found is not None:
                    break
                if proc.poll() is not None and existing:
                    found = existing[0]
                    break
                time.sleep(0.2)
            if found is None and existing:
                found = existing[0]
            if found is None:
                raise EngineError("launch_timeout", f"timed out waiting for {cmd}")
            wm.activate(found)
            self._drive(found)
            return found.to_dict()
        finally:
            self._handoff()

    def wait_for_window(
        self,
        title_contains: str | None = None,
        exe_contains: str | None = None,
        timeout_s: float = 30.0,
    ) -> dict:
        if not title_contains and not exe_contains:
            raise EngineError("bad_wait", "need title_contains or exe_contains")
        deadline = time.time() + timeout_s
        title_n = (title_contains or "").lower()
        exe_n = (exe_contains or "").lower()
        while time.time() < deadline:
            for info in wm.list_windows():
                if title_n and title_n not in info.title.lower():
                    continue
                if exe_n and exe_n not in (info.exe or "").lower() and exe_n not in Path(info.exe).name.lower():
                    continue
                return info.to_dict()
            time.sleep(0.2)
        raise EngineError("wait_timeout", "window did not appear")

    def close_window(self, window_id: str, generation: str | None = None) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            self._drive(info)
            wm.activate(info)
            wm.close_window(info)
            time.sleep(0.35)
            if user32.IsWindow(info.hwnd):
                sendinput.key_combo("n")
                time.sleep(0.2)
            gone = not user32.IsWindow(info.hwnd)
            return {"closed": gone, "window_id": window_id}
        finally:
            self._handoff()

    def click(
        self,
        window_id: str,
        generation: str | None = None,
        x: int | None = None,
        y: int | None = None,
        element_index: int | None = None,
        button: str = "left",
        count: int = 1,
        screenshot_id: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            time.sleep(0.05)
            info = wm.get_window(window_id)
            if element_index is not None:
                sx, sy = self._element_center(info, element_index)
            else:
                if x is None or y is None:
                    raise EngineError("bad_click", "need x,y or element_index")
                sx, sy = self._map_xy(info, x, y, screenshot_id)
            self._drive(info, x=sx, y=sy, press=True)
            sendinput.click_abs(
                sx, sy, button=button, count=count, proceed=self.guard.allow_input, animate=self._pointer_animate()
            )
            self._check_abort()
            return {"ok": True, "screen_x": sx, "screen_y": sy}
        finally:
            self._handoff()

    def _element_center(self, info: wm.WindowInfo, element_index: int) -> tuple[int, int]:
        elements = self._elements.get(info.window_id)
        if not elements:
            elements = uia.describe_elements(info)
            self._elements[info.window_id] = elements
        return uia.element_center(info, element_index, elements)

    def type_text(
        self,
        window_id: str,
        text: str,
        generation: str | None = None,
        element_index: int | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            time.sleep(0.05)
            info = wm.get_window(window_id)
            if element_index is not None:
                sx, sy = self._element_center(info, element_index)
                self._drive(info, x=sx, y=sy, press=True)
                sendinput.click_abs(sx, sy, proceed=self.guard.allow_input, animate=self._pointer_animate())
                time.sleep(0.05)
            else:
                self._drive(info)
            written = sendinput.type_text(text, proceed=self.guard.allow_input)
            self._check_abort()
            return {"ok": True, "chars": written}
        finally:
            self._handoff()

    def press_key(self, window_id: str, keys: str, generation: str | None = None) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            self._drive(info)
            wm.activate(info)
            time.sleep(0.05)
            sendinput.key_combo(keys)
            return {"ok": True, "keys": keys}
        finally:
            self._handoff()

    def hold_key(self, window_id: str, keys: str, action: str, generation: str | None = None) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            self._drive(info)
            wm.activate(info)
            sendinput.hold_key(keys, action)
            return {"ok": True, "keys": keys, "action": action}
        finally:
            if str(action).lower().strip() != "down":
                self._handoff()

    def scroll(
        self,
        window_id: str,
        generation: str | None = None,
        dy: int = 0,
        dx: int = 0,
        x: int | None = None,
        y: int | None = None,
        element_index: int | None = None,
        screenshot_id: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            info = wm.get_window(window_id)
            if element_index is not None:
                elements = self._elements.get(window_id)
                if uia.scroll_element(info, element_index, dy=dy, dx=dx, elements=elements):
                    self._drive(info)
                    return {"ok": True, "via_uia": True}
                sx, sy = self._element_center(info, element_index)
                self._drive(info, x=sx, y=sy)
                sendinput.scroll(
                    sx, sy, dy=dy, dx=dx, proceed=self.guard.allow_input, animate=self._pointer_animate()
                )
                self._check_abort()
                return {"ok": True, "via_uia": False, "screen_x": sx, "screen_y": sy}
            if x is None or y is None:
                cl, ct, cr, cb = info.client_rect
                if cr <= cl or cb <= ct:
                    cl, ct, cr, cb = info.rect
                sx, sy = (cl + cr) // 2, (ct + cb) // 2
            else:
                sx, sy = self._map_xy(info, x, y, screenshot_id)
            self._drive(info, x=sx, y=sy)
            sendinput.scroll(
                sx, sy, dy=dy, dx=dx, proceed=self.guard.allow_input, animate=self._pointer_animate()
            )
            self._check_abort()
            return {"ok": True}
        finally:
            self._handoff()

    def drag(
        self,
        window_id: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        generation: str | None = None,
        button: str = "left",
        screenshot_id: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            info = wm.get_window(window_id)
            a = self._map_xy(info, x1, y1, screenshot_id)
            b = self._map_xy(info, x2, y2, screenshot_id)
            self._drive(info, x=a[0], y=a[1], press=True)
            sendinput.drag(
                a[0], a[1], b[0], b[1], button=button, proceed=self.guard.allow_input, animate=self._pointer_animate()
            )
            self._check_abort()
            return {"ok": True, "button": button}
        finally:
            self._handoff()

    def mouse_down(
        self,
        window_id: str,
        x: int,
        y: int,
        generation: str | None = None,
        button: str = "left",
        screenshot_id: str | None = None,
    ) -> dict:
        info = self._require(window_id, generation, mutating=True)
        wm.activate(info)
        info = wm.get_window(window_id)
        sx, sy = self._map_xy(info, x, y, screenshot_id)
        self._drive(info, x=sx, y=sy, press=True)
        sendinput.mouse_down(
            sx, sy, button=button, proceed=self.guard.allow_input, animate=self._pointer_animate()
        )
        self._check_abort()
        return {"ok": True, "screen_x": sx, "screen_y": sy, "button": button}

    def mouse_up(
        self,
        window_id: str,
        x: int,
        y: int,
        generation: str | None = None,
        button: str = "left",
        screenshot_id: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            info = wm.get_window(window_id)
            sx, sy = self._map_xy(info, x, y, screenshot_id)
            self._drive(info, x=sx, y=sy, press=False)
            sendinput.mouse_up(
                sx, sy, button=button, proceed=self.guard.allow_input, animate=self._pointer_animate()
            )
            self._check_abort()
            return {"ok": True, "screen_x": sx, "screen_y": sy, "button": button}
        finally:
            self._handoff()

    def set_value(
        self,
        window_id: str,
        text: str,
        element_index: int,
        generation: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            time.sleep(0.05)
            info = wm.get_window(window_id)
            self._drive(info)
            ok = uia.set_element_value(info, element_index, text, self._elements.get(window_id))
            if not ok:
                sx, sy = self._element_center(info, element_index)
                self._drive(info, x=sx, y=sy, press=True)
                sendinput.click_abs(sx, sy, proceed=self.guard.allow_input, animate=self._pointer_animate())
                sendinput.key_combo("ctrl+a")
                sendinput.type_text(text, proceed=self.guard.allow_input)
            self._check_abort()
            return {"ok": True, "via_uia": ok}
        finally:
            self._handoff()

    def move_pointer(
        self,
        window_id: str,
        x: int,
        y: int,
        generation: str | None = None,
        screenshot_id: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            info = wm.get_window(window_id)
            sx, sy = self._map_xy(info, x, y, screenshot_id)
            self._drive(info, x=sx, y=sy)
            sendinput.move_abs(sx, sy, proceed=self.guard.allow_input, animate=self._pointer_animate())
            self._check_abort()
            return {"ok": True, "screen_x": sx, "screen_y": sy}
        finally:
            self._handoff()

    def perform_secondary_action(
        self,
        window_id: str,
        element_index: int,
        action: str,
        generation: str | None = None,
    ) -> dict:
        try:
            info = self._require(window_id, generation, mutating=True)
            wm.activate(info)
            time.sleep(0.05)
            info = wm.get_window(window_id)
            self._drive(info)
            used = uia.perform_secondary_action(info, element_index, action, self._elements.get(window_id))
            return {"ok": True, "action": used}
        finally:
            self._handoff()
