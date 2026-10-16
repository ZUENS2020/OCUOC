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
