from __future__ import annotations

import atexit
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Image

from ocuoc.engine import ComputerUseEngine, ViewResult
from ocuoc.errors import EngineError

engine = ComputerUseEngine()
mcp = MCPServer(
    name="ocuoc",
    version="0.1.0",
    instructions=(
        "Windows computer-use MCP. Window-scoped tools: list windows, screenshot, "
        "UIA/WebView elements, click/type/key/scroll/drag. Coordinates for click, drag, "
        "move_pointer, mouse_down/up, and scroll are client-area pixels of the last "
        "screenshot (top-left). Pass screenshot_id from get_window_state when clicking "
        "by x,y. Pass generation into mutating calls. Esc aborts input. Run the host "
        "elevated for UIPI / cross-user / protected-window capture."
    ),
)


def _wrap(fn, **kwargs) -> dict[str, Any]:
    try:
        return {"ok": True, "result": fn(**kwargs)}
    except EngineError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "internal", "message": str(exc)}}


def _wrap_view(fn, **kwargs) -> list[Any] | dict[str, Any]:
    try:
        out = fn(**kwargs)
        if isinstance(out, ViewResult):
            items: list[Any] = [{"ok": True, "result": out.payload}]
            if out.png:
                items.append(Image(data=out.png, format="png"))
            return items
        return {"ok": True, "result": out}
    except EngineError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "internal", "message": str(exc)}}


@mcp.tool()
def list_apps() -> dict[str, Any]:
    """List launchable apps from Start Menu, App Paths, execution aliases, and recent usage."""
    return _wrap(engine.list_apps)


@mcp.tool()
def list_windows() -> dict[str, Any]:
    """List visible top-level windows with bounds, exe, user, integrity, and generation."""
    return _wrap(engine.list_windows)


@mcp.tool()
def list_displays() -> dict[str, Any]:
    """List attached monitors and their bounds."""
    return _wrap(engine.list_displays)


@mcp.tool()
def get_window(window_id: str) -> dict[str, Any]:
    """Re-read one window's bounds, title, generation, and process identity."""
    return _wrap(engine.get_window, window_id=window_id)


@mcp.tool(structured_output=False)
def get_window_state(
    window_id: str,
    include_screenshot: bool = True,
    include_text: bool = True,
    include_elements: bool = True,
    max_elements: int = 200,
) -> Any:
    """Read one window. Screenshot is an MCP image of the client area; click x,y uses screenshot_id pixels."""
    return _wrap_view(
        engine.get_window_state,
        window_id=window_id,
        include_screenshot=include_screenshot,
        include_text=include_text,
        include_elements=include_elements,
        max_elements=max_elements,
    )


@mcp.tool(structured_output=False)
def screenshot_desktop() -> Any:
    """Capture the virtual desktop as an MCP image. Coordinates are image pixels."""
    return _wrap_view(engine.screenshot_desktop)


@mcp.tool()
def activate_window(window_id: str, generation: str | None = None) -> dict[str, Any]:
    """Bring a window to the foreground."""
    return _wrap(engine.activate_window, window_id=window_id, generation=generation)


@mcp.tool()
def launch_app(
    app_id: str,
    extra_args: list[str] | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Launch an app by exe: path or command name and wait for a matching window (child processes included)."""
    return _wrap(engine.launch_app, app_id=app_id, extra_args=extra_args, timeout_s=timeout_s)


@mcp.tool()
def wait_for_window(
    title_contains: str | None = None,
    exe_contains: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Wait until a top-level window matching title and/or exe appears."""
    return _wrap(
        engine.wait_for_window,
        title_contains=title_contains,
        exe_contains=exe_contains,
        timeout_s=timeout_s,
    )


@mcp.tool()
def close_window(window_id: str, generation: str | None = None) -> dict[str, Any]:
    """Close the target window (not the MCP server)."""
    return _wrap(engine.close_window, window_id=window_id, generation=generation)


@mcp.tool()
def click(
    window_id: str,
    generation: str | None = None,
    x: int | None = None,
    y: int | None = None,
    element_index: int | None = None,
    button: str = "left",
    count: int = 1,
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Click client-area screenshot pixels or a UIA/CDP element index. Pass screenshot_id for x,y."""
    return _wrap(
        engine.click,
        window_id=window_id,
        generation=generation,
        x=x,
        y=y,
        element_index=element_index,
        button=button,
        count=count,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def type_text(
    window_id: str,
    text: str,
    generation: str | None = None,
    element_index: int | None = None,
) -> dict[str, Any]:
    """Type Unicode text into the window, optionally clicking an element first."""
    return _wrap(
        engine.type_text,
        window_id=window_id,
        text=text,
        generation=generation,
        element_index=element_index,
    )


@mcp.tool()
def press_key(window_id: str, keys: str, generation: str | None = None) -> dict[str, Any]:
    """Press a key or chord such as enter, esc, or ctrl+s."""
    return _wrap(engine.press_key, window_id=window_id, keys=keys, generation=generation)


@mcp.tool()
def hold_key(window_id: str, keys: str, action: str, generation: str | None = None) -> dict[str, Any]:
    """Press or release keys (action=down|up) without an automatic matching up/down."""
    return _wrap(engine.hold_key, window_id=window_id, keys=keys, action=action, generation=generation)


@mcp.tool()
def scroll(
    window_id: str,
    generation: str | None = None,
    dy: int = 0,
    dx: int = 0,
    x: int | None = None,
    y: int | None = None,
    element_index: int | None = None,
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Scroll. dy/dx are wheel ticks. Prefer element_index; x,y are client-area screenshot pixels."""
    return _wrap(
        engine.scroll,
        window_id=window_id,
        generation=generation,
        dy=dy,
        dx=dx,
        x=x,
        y=y,
        element_index=element_index,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def drag(
    window_id: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    generation: str | None = None,
    button: str = "left",
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Drag between two client-area screenshot points."""
    return _wrap(
        engine.drag,
        window_id=window_id,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        generation=generation,
        button=button,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def mouse_down(
    window_id: str,
    x: int,
    y: int,
    generation: str | None = None,
    button: str = "left",
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Press a mouse button at client-area screenshot coordinates without releasing."""
    return _wrap(
        engine.mouse_down,
        window_id=window_id,
        x=x,
        y=y,
        generation=generation,
        button=button,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def mouse_up(
    window_id: str,
    x: int,
    y: int,
    generation: str | None = None,
    button: str = "left",
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Release a mouse button at client-area screenshot coordinates."""
    return _wrap(
        engine.mouse_up,
        window_id=window_id,
        x=x,
        y=y,
        generation=generation,
        button=button,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def set_value(
    window_id: str,
    text: str,
    element_index: int,
    generation: str | None = None,
) -> dict[str, Any]:
    """Set an element's value via UI Automation, falling back to type_text."""
    return _wrap(
        engine.set_value,
        window_id=window_id,
        text=text,
        element_index=element_index,
        generation=generation,
    )


@mcp.tool()
def move_pointer(
    window_id: str,
    x: int,
    y: int,
    generation: str | None = None,
    screenshot_id: str | None = None,
) -> dict[str, Any]:
    """Move the pointer without clicking. x,y are client-area screenshot pixels."""
    return _wrap(
        engine.move_pointer,
        window_id=window_id,
        x=x,
        y=y,
        generation=generation,
        screenshot_id=screenshot_id,
    )


@mcp.tool()
def perform_secondary_action(
    window_id: str,
    element_index: int,
    action: str,
    generation: str | None = None,
) -> dict[str, Any]:
    """UIA secondary action on an element: expand, collapse, raise, invoke, toggle, scroll_up/down/left/right."""
    return _wrap(
        engine.perform_secondary_action,
        window_id=window_id,
        element_index=element_index,
        action=action,
        generation=generation,
    )


def main() -> None:
    engine.start()
    atexit.register(engine.stop)
    try:
        mcp.run()
    finally:
        engine.stop()
