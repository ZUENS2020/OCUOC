"""Optional live headless Chrome check (skipped without Chrome)."""

from __future__ import annotations

import pytest

from ocuoc.browser.headless import HeadlessCDP, find_chrome

pytestmark = pytest.mark.live


def test_headless_injects_and_reports_arrival():
    if not find_chrome():
        pytest.skip("Chrome not installed")
    session = HeadlessCDP()
    try:
        session.start("about:blank")
        session.set_cursor(120, 80, seq=1, animate=True)
        arrived = session.wait_arrived(1)
        assert arrived is True
        session.set_badge("deliverable")
        session.mouse("mouseMoved", 120, 80)
        session.mouse("mousePressed", 120, 80, "left")
        session.mouse("mouseReleased", 120, 80, "left")
    finally:
        session.stop()
