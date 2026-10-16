from ocuoc.generation import make_generation, make_window_id, parse_window_id


def test_window_id_roundtrip():
    assert make_window_id(123456) == "hwnd:123456"
    assert parse_window_id("hwnd:123456") == 123456


def test_parse_window_id_rejects_garbage():
    try:
        parse_window_id("abc")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_generation_changes_when_rect_changes():
    a = make_generation(1, "Notepad", (0, 0, 100, 100), "Notepad")
    b = make_generation(1, "Notepad", (0, 0, 200, 100), "Notepad")
    assert a != b
    assert len(a) == 16


def test_generation_ignores_title_churn():
    a = make_generation(1, "Untitled - Notepad", (0, 0, 800, 600), "Notepad")
    b = make_generation(1, "*Untitled - Notepad", (0, 0, 800, 600), "Notepad")
    assert a == b
