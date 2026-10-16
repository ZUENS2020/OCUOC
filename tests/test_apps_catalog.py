from ocuoc.engine import ComputerUseEngine
from ocuoc.uia.tree import normalize_action
from ocuoc.wm.apps import _rot13, list_app_paths, list_catalog_apps


def test_rot13_roundtrip():
    assert _rot13("notepad.exe") == "abgrcnq.rkr"
    assert _rot13(_rot13("C:\\Windows\\notepad.exe")) == "C:\\Windows\\notepad.exe"


def test_app_paths_or_catalog_contains_exe():
    paths = list_app_paths()
    catalog = list_catalog_apps(limit=80)
    blob = paths + catalog
    assert any((item.get("exe") or "").lower().endswith(".exe") for item in blob)


def test_list_apps_exposes_catalog_sources():
    payload = ComputerUseEngine().list_apps()
    sources = {item.get("source") for item in payload["apps"]}
    assert sources & {"start_menu", "app_paths", "execution_alias", "user_assist", "window", "system"}


def test_list_apps_marks_running_windows():
    payload = ComputerUseEngine().list_apps()
    assert payload["apps"]
    for item in payload["apps"]:
        assert "windows" in item
        assert "is_running" in item
        assert item["is_running"] is bool(item["windows"])
    running = [item for item in payload["apps"] if item["is_running"]]
    assert running
    assert running[0]["windows"][0]["window_id"].startswith("hwnd:")


def test_secondary_action_aliases():
    assert normalize_action("Scroll Up") == "scroll_up"
    assert normalize_action("expand") == "expand"
    try:
        normalize_action("delete_system32")
    except Exception as exc:
        assert getattr(exc, "code", "") == "bad_action"
        return
    raise AssertionError("expected bad_action")
