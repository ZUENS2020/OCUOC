from ocuoc.collab.cursor_agent import apply_restore, apply_suppress


def test_apply_suppress_does_not_reset_scheme(monkeypatch):
    calls = []
    monkeypatch.setattr("ocuoc.collab.cursor_agent._reset_scheme", lambda: calls.append("reset"))
    monkeypatch.setattr("ocuoc.collab.cursor_agent._suppress", lambda: calls.append("hide"))
    assert apply_suppress(False) is True
    assert calls == ["hide"]
    assert apply_restore(True) is False
    assert calls == ["hide", "reset"]
    assert apply_restore(False) is False
    assert calls == ["hide", "reset", "reset"]
