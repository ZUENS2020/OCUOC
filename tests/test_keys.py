from ocuoc.keys import parse_hotkey, vk_name


def test_parse_ctrl_s():
    mods, key = parse_hotkey("ctrl+s")
    assert "ctrl" in mods
    assert key == "s"
    assert vk_name("s") == 0x53


def test_parse_escape_aliases():
    _, key = parse_hotkey("esc")
    assert vk_name(key) == 0x1B
    _, key2 = parse_hotkey("escape")
    assert vk_name(key2) == 0x1B


def test_parse_enter():
    _, key = parse_hotkey("enter")
    assert vk_name(key) == 0x0D


def test_parse_x11_control_l():
    mods, key = parse_hotkey("Control_L+a")
    assert "ctrl" in mods
    assert key == "a"
    assert vk_name("Return") == 0x0D
    assert vk_name("Alt_R") == 0x12
