from ocuoc.webview.detect import classify_webview, debug_port_from_cmdline


def test_steam_is_cef():
    assert classify_webview("SDL_app", r"F:\steam\steamwebhelper.exe", []) == "cef"


def test_cursor_is_electron():
    kind = classify_webview(
        "Chrome_WidgetWin_1",
        r"C:\Users\me\AppData\Local\Programs\cursor\Cursor.exe",
        ["Chrome_RenderWidgetHostHWND"],
    )
    assert kind == "electron"


def test_webview2_from_child_class():
    assert classify_webview("Chrome_WidgetWin_0", r"C:\Windows\System32\msedgewebview2.exe", []) == "webview2"


def test_debug_port_from_cmdline():
    assert debug_port_from_cmdline("app.exe --remote-debugging-port=9222") == 9222
    assert debug_port_from_cmdline("electron --inspect=9229") == 9229
    assert debug_port_from_cmdline("steam.exe -silent") is None
