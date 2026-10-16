from ocuoc.engine import ComputerUseEngine
from ocuoc.privilege import snapshot


def test_privilege_snapshot_has_elevated_flag():
    info = snapshot()
    data = info.to_dict()
    assert isinstance(data["elevated"], bool)
    assert data["integrity"]
    assert "uac_secure_desktop" in data
    if not data["elevated"]:
        assert "warning" in data


def test_list_windows_includes_privilege_fields():
    engine = ComputerUseEngine()
    payload = engine.list_windows()
    assert "elevated" in payload
    assert isinstance(payload["elevated"], bool)
    for item in payload["windows"]:
        assert "user" in item
        assert "integrity" in item
        assert "elevated" in item
