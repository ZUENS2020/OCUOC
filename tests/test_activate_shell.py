from ocuoc.wm.windows import SHELL_HOSTS, WindowInfo, activate


def test_shell_hosts_match_codex_list():
    assert SHELL_HOSTS == {"searchapp", "searchhost", "startmenuexperiencehost"}


def test_activate_injects_esc_when_search_host(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("ocuoc.wm.windows._foreground_stem", lambda: "SearchHost".lower())
    monkeypatch.setattr("ocuoc.input.sendinput.key_combo", lambda spec: calls.append(spec))
    monkeypatch.setattr("ocuoc.wm.windows.time.sleep", lambda _s: None)
    monkeypatch.setattr("ocuoc.wm.windows.user32.IsIconic", lambda _h: 0)
    monkeypatch.setattr("ocuoc.wm.windows.user32.GetForegroundWindow", lambda: 0)
    monkeypatch.setattr("ocuoc.wm.windows.user32.GetWindowThreadProcessId", lambda *_a: 0)
    monkeypatch.setattr("ocuoc.wm.windows.kernel32.GetCurrentThreadId", lambda: 1)
    monkeypatch.setattr("ocuoc.wm.windows.user32.BringWindowToTop", lambda _h: 1)
    monkeypatch.setattr("ocuoc.wm.windows.user32.SetForegroundWindow", lambda _h: 1)
    monkeypatch.setattr("ocuoc.wm.windows.user32.SetFocus", lambda _h: 1)
    info = WindowInfo(hwnd=1, title="x", pid=1, exe=r"C:\Windows\notepad.exe", class_name="Notepad", rect=(0, 0, 10, 10))
    activate(info)
    assert calls == ["esc"]
