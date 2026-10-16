from __future__ import annotations

from pathlib import Path

CHROMIUM_CLASSES = {
    "chrome_widgetwin_0",
    "chrome_widgetwin_1",
    "chrome_widgetwin_2",
    "chrome_renderwidgethosthwnd",
    "intermediate d3d window",
}
CEF_CLASSES = {
    "cefbrowserwindow",
    "cef-osc-widget",
    "sdl_app",
}
WEBVIEW2_HINTS = {
    "msedgewebview2.exe",
    "webview2",
}
ELECTRON_EXES = {
    "cursor.exe",
    "code.exe",
    "code - insiders.exe",
    "discord.exe",
    "slack.exe",
    "teams.exe",
}


def classify_webview(class_name: str, exe: str, child_classes: list[str] | None = None) -> str | None:
    cls = (class_name or "").lower()
    exe_name = Path(exe or "").name.lower()
    children = [c.lower() for c in (child_classes or [])]
    blob = " ".join([cls, exe_name, *children])

    if "steamwebhelper" in exe_name or "steamwebhelper" in blob:
        return "cef"
    if exe_name in ELECTRON_EXES or "electron" in blob:
        if cls in CHROMIUM_CLASSES or any(c in CHROMIUM_CLASSES for c in children):
            return "electron"
        if "chrome_widgetwin" in blob:
            return "electron"
    if exe_name in WEBVIEW2_HINTS or "msedgewebview2" in blob:
        return "webview2"
    if any(hint in exe_name for hint in WEBVIEW2_HINTS):
        return "webview2"
    if cls in CEF_CLASSES or "cefbrowserwindow" in blob:
        if cls == "sdl_app" and "steam" not in exe_name and "cef" not in blob and not any(
            "cef" in c or "chrome_" in c for c in children
        ):
            return None
        return "cef"
    if cls in CHROMIUM_CLASSES or any(c in CHROMIUM_CLASSES for c in children):
        if "webview" in blob:
            return "webview2"
        return "chromium"
    return None


def debug_port_from_cmdline(cmdline: str) -> int | None:
    import re

    if not cmdline:
        return None
    patterns = (
        r"--remote-debugging-port=(\d+)",
        r"--inspect(?:-brk)?=(\d+)",
        r"--inspect(?:-brk)?:(\d+)",
    )
    for pat in patterns:
        m = re.search(pat, cmdline)
        if m:
            port = int(m.group(1))
            if 1 <= port <= 65535:
                return port
    return None
