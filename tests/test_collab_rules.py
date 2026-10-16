from ocuoc.collab.inject import OCUOC_EXTRA, reset_for_tests
from ocuoc.collab.rules import (
    is_key_injected,
    is_mouse_injected,
    same_process,
    should_interrupt_click,
    should_swallow_esc,
)


def test_injected_flags():
    reset_for_tests()
    assert is_key_injected(0x10) is True
    assert is_key_injected(0) is False
    assert is_mouse_injected(0x01) is True
    assert is_mouse_injected(0x02) is True
    assert is_mouse_injected(0) is False
    assert is_mouse_injected(0, extra=OCUOC_EXTRA) is True
    assert is_key_injected(0, extra=OCUOC_EXTRA) is True


def test_swallow_esc_only_when_supervising_physical_keydown():
    assert should_swallow_esc(supervising=True, injected=False, vk=0x1B, wparam=0x0100) is True
    assert should_swallow_esc(supervising=True, injected=False, vk=0x1B, wparam=0x0104) is True
    assert should_swallow_esc(supervising=True, injected=True, vk=0x1B, wparam=0x0100) is False
    assert should_swallow_esc(supervising=False, injected=False, vk=0x1B, wparam=0x0100) is False
    assert should_swallow_esc(supervising=True, injected=False, vk=0x41, wparam=0x0100) is False
    assert should_swallow_esc(supervising=True, injected=False, vk=0x1B, wparam=0x0101) is False


def test_interrupt_click_same_target_physical_down():
    assert (
        should_interrupt_click(supervising=True, injected=False, wparam=0x0201, same_target=True) is True
    )
    assert (
        should_interrupt_click(supervising=True, injected=False, wparam=0x0204, same_target=True) is True
    )
    assert (
        should_interrupt_click(supervising=True, injected=True, wparam=0x0201, same_target=True) is False
    )
    assert (
        should_interrupt_click(supervising=True, injected=False, wparam=0x0201, same_target=False) is False
    )
    assert (
        should_interrupt_click(supervising=False, injected=False, wparam=0x0201, same_target=True) is False
    )
    assert (
        should_interrupt_click(supervising=True, injected=False, wparam=0x0202, same_target=True) is False
    )


def test_same_process():
    assert same_process(42, 42) is True
    assert same_process(42, 7) is False
    assert same_process(0, 0) is False
