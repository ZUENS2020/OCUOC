from ocuoc.server import mcp

EXPECTED = {
    "list_apps",
    "list_windows",
    "list_displays",
    "get_window",
    "get_window_state",
    "screenshot_desktop",
    "activate_window",
    "launch_app",
    "wait_for_window",
    "close_window",
    "click",
    "type_text",
    "press_key",
    "hold_key",
    "scroll",
    "drag",
    "mouse_down",
    "mouse_up",
    "set_value",
    "move_pointer",
    "perform_secondary_action",
    "browser_bridge_info",
    "browser_list_tabs",
    "browser_open_tab",
    "browser_close_tab",
    "browser_activate_tab",
    "browser_screenshot",
    "browser_click",
    "browser_double_click",
    "browser_right_click",
    "browser_type_text",
    "browser_press_keys",
    "browser_scroll",
    "browser_drag",
    "browser_get_state",
    "browser_eval",
    "browser_mark_deliverable",
    "browser_mark_handoff",
    "browser_handle_dialog",
}

BANNED = ("token", "chatgpt", "authorization", "api_key", "codex_cli")


def test_tools_match_window2_surface_without_auth_fields():
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED
    for tool in tools:
        blob = str(tool.parameters).lower()
        for word in BANNED:
            assert word not in blob, f"{tool.name} schema contains {word}"
