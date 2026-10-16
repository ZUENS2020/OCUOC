from __future__ import annotations

from ocuoc.collab.inject import OCUOC_EXTRA, in_flight

VK_ESCAPE = 0x1B
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
LLMHF_LOWER_IL_INJECTED = 0x02
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B

MOUSE_DOWN = {WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN}


def is_key_injected(flags: int, extra: int = 0) -> bool:
    if int(extra) == OCUOC_EXTRA:
        return True
    return bool(flags & LLKHF_INJECTED)


def is_mouse_injected(flags: int, extra: int = 0) -> bool:
    if in_flight() or int(extra) == OCUOC_EXTRA:
        return True
    return bool(flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED))


def should_swallow_esc(*, supervising: bool, injected: bool, vk: int, wparam: int) -> bool:
    """Physical Esc during an AI session is swallowed so it does not hit the target app."""
    if not supervising or injected:
        return False
    if vk != VK_ESCAPE:
        return False
    return int(wparam) in {WM_KEYDOWN, WM_SYSKEYDOWN}


def should_interrupt_click(*, supervising: bool, injected: bool, wparam: int, same_target: bool) -> bool:
    """Physical click on the controlled app interrupts AI input but is not swallowed."""
    if not supervising or injected or not same_target:
        return False
    return int(wparam) in MOUSE_DOWN


def same_process(pid_a: int, pid_b: int) -> bool:
    return bool(pid_a) and pid_a == pid_b
