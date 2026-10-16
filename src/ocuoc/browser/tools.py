"""Register browser_* MCP tools on the existing FastMCP server."""

from __future__ import annotations

from typing import Any

from ocuoc.engine import ViewResult


def install_browser_tools(mcp, engine) -> None:
    def host():
        return engine.browser

    @mcp.tool()
    def browser_bridge_info() -> dict[str, Any]:
        """Local WebSocket URL and pairing secret for the unpacked OCUOC Browser Bridge extension."""
        from ocuoc.server import _wrap

        return _wrap(host().info)

    @mcp.tool()
    def browser_list_tabs() -> dict[str, Any]:
        """List Chrome tabs attached through the browser bridge, with generation fingerprints."""
        from ocuoc.server import _wrap

        return _wrap(host().list_tabs)

    @mcp.tool()
    def browser_open_tab(url: str | None = None, active: bool = True) -> dict[str, Any]:
        """Open a tab. url defaults to about:blank."""
        from ocuoc.server import _wrap

        return _wrap(host().open_tab, url=url, active=active)

    @mcp.tool()
    def browser_close_tab(tab_id: int, generation: str | None = None) -> dict[str, Any]:
        """Close a tab by tab_id."""
        from ocuoc.server import _wrap

        return _wrap(host().close_tab, tab_id=tab_id, generation=generation)

    @mcp.tool()
    def browser_activate_tab(tab_id: int, generation: str | None = None) -> dict[str, Any]:
        """Focus a tab."""
        from ocuoc.server import _wrap

        return _wrap(host().activate_tab, tab_id=tab_id, generation=generation)

    @mcp.tool(structured_output=False)
    def browser_screenshot(tab_id: int, generation: str | None = None) -> Any:
        """Capture a tab via CDP without activating it. Device-pixel PNG; click coords are CSS px. Includes dpr."""
        from ocuoc.server import _wrap_view

        def _shot() -> ViewResult:
            payload, png = host().screenshot(tab_id, generation=generation)
            return ViewResult(payload=payload, png=png)

        return _wrap_view(_shot)

    @mcp.tool()
    def browser_click(
        tab_id: int,
        x: float | None = None,
        y: float | None = None,
        element_index: int | None = None,
        button: str = "left",
        count: int = 1,
        generation: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Click CSS-pixel coordinates or an element_index from browser_get_state. Waits for cursor arrival first."""
        from ocuoc.server import _wrap

        return _wrap(
            host().click,
            tab_id=tab_id,
            x=x,
            y=y,
            button=button,
            count=count,
            element_index=element_index,
            generation=generation,
            snapshot_id=snapshot_id,
        )

    @mcp.tool()
    def browser_double_click(
        tab_id: int,
        x: float | None = None,
        y: float | None = None,
        element_index: int | None = None,
        generation: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Double-click CSS-pixel coordinates or element_index."""
        from ocuoc.server import _wrap

        return _wrap(
            host().click,
            tab_id=tab_id,
            x=x,
            y=y,
            button="left",
            count=2,
            element_index=element_index,
            generation=generation,
            snapshot_id=snapshot_id,
        )

    @mcp.tool()
    def browser_right_click(
        tab_id: int,
        x: float | None = None,
        y: float | None = None,
        element_index: int | None = None,
        generation: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        """Right-click CSS-pixel coordinates or element_index."""
        from ocuoc.server import _wrap

        return _wrap(
            host().click,
            tab_id=tab_id,
            x=x,
            y=y,
            button="right",
            count=1,
            element_index=element_index,
            generation=generation,
            snapshot_id=snapshot_id,
        )

    @mcp.tool()
    def browser_type_text(tab_id: int, text: str, generation: str | None = None) -> dict[str, Any]:
        """Insert Unicode text into the page via CDP."""
        from ocuoc.server import _wrap

        return _wrap(host().type_text, tab_id=tab_id, text=text, generation=generation)

    @mcp.tool()
    def browser_press_keys(tab_id: int, keys: str, generation: str | None = None) -> dict[str, Any]:
        """Press keys or chords such as Enter, ArrowDown, or ctrl+a (comma-separated sequence, plus-separated modifiers)."""
        from ocuoc.server import _wrap

        return _wrap(host().press_keys, tab_id=tab_id, keys=keys, generation=generation)

    @mcp.tool()
    def browser_scroll(
        tab_id: int,
        dy: int = 0,
        dx: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        generation: str | None = None,
    ) -> dict[str, Any]:
        """Wheel scroll. dy/dx are ticks; x,y are CSS px."""
        from ocuoc.server import _wrap

        return _wrap(host().scroll, tab_id=tab_id, dy=dy, dx=dx, x=x, y=y, generation=generation)

    @mcp.tool()
    def browser_drag(
        tab_id: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        button: str = "left",
        generation: str | None = None,
    ) -> dict[str, Any]:
        """Drag between two CSS-pixel points. The move while pressed does not wait for cursor arrival."""
        from ocuoc.server import _wrap

        return _wrap(host().drag, tab_id=tab_id, x1=x1, y1=y1, x2=x2, y2=y2, button=button, generation=generation)

    @mcp.tool(structured_output=False)
    def browser_get_state(
        tab_id: int,
        generation: str | None = None,
        include_screenshot: bool = True,
        include_elements: bool = True,
        max_elements: int = 200,
    ) -> Any:
        """AX+DOM element tree with CSS-px rects, generation, snapshot_id, optional screenshot (device pixels) and dpr. Screenshot does not activate the tab. AX timeout falls back to DOM layout boxes."""
        from ocuoc.server import _wrap_view

        def _state() -> ViewResult:
            payload, png = host().get_state(
                tab_id,
                generation=generation,
                include_screenshot=include_screenshot,
                include_elements=include_elements,
                max_elements=max_elements,
            )
            return ViewResult(payload=payload, png=png)

        return _wrap_view(_state)

    @mcp.tool()
    def browser_eval(tab_id: int, expression: str, await_promise: bool = False) -> dict[str, Any]:
        """Runtime.evaluate. Disabled unless OCUOC_BROWSER_EVAL=1."""
        from ocuoc.server import _wrap

        return _wrap(host().eval_js, tab_id=tab_id, expression=expression, await_promise=await_promise)

    @mcp.tool()
    def browser_mark_deliverable(tab_id: int) -> dict[str, Any]:
        """Set the tab favicon badge to deliverable (green)."""
        from ocuoc.server import _wrap

        return _wrap(host().mark_deliverable, tab_id=tab_id)

    @mcp.tool()
    def browser_mark_handoff(tab_id: int) -> dict[str, Any]:
        """Set the tab favicon badge to handoff (amber)."""
        from ocuoc.server import _wrap

        return _wrap(host().mark_handoff, tab_id=tab_id)

    @mcp.tool()
    def browser_handle_dialog(tab_id: int, accept: bool = True, prompt_text: str = "") -> dict[str, Any]:
        """Accept or dismiss a JavaScript dialog on the tab."""
        from ocuoc.server import _wrap

        return _wrap(host().handle_dialog, tab_id=tab_id, accept=accept, prompt_text=prompt_text)
