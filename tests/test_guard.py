from ocuoc.policy.guard import Guard


def test_abort_blocks_input_actions():
    g = Guard()
    assert g.allow_input() is True
    g.abort("esc")
    assert g.allow_input() is False
    assert g.reason() == "esc"


def test_reset_clears_abort():
    g = Guard()
    g.abort("esc")
    g.reset()
    assert g.allow_input() is True
    assert g.reason() == ""


def test_no_allowlist_or_uac_block_api():
    g = Guard.from_env()
    assert not hasattr(g, "exe_allowed")
    assert not hasattr(g, "is_protected_window")
