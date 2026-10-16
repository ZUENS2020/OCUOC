import tempfile
import time
from pathlib import Path

import pytest

from ocuoc.engine import ComputerUseEngine, ViewResult
from ocuoc.errors import EngineError

MARKER = "OCUOC-LIVE-PROBE-7f3a"


def _payload(state):
    if isinstance(state, ViewResult):
        return state.payload, state.png
    return state, None


@pytest.mark.live
def test_notepad_roundtrip():
    engine = ComputerUseEngine()
    launched = None
    probe = Path(tempfile.gettempdir()) / "ocuoc-live-probe.txt"
    probe.write_text("", encoding="utf-8")
    try:
        engine.start()
        launched = engine.launch_app("notepad.exe", extra_args=[str(probe)])
        window_id = launched["window_id"]
        time.sleep(0.4)
        bundle = engine.get_window_state(
            window_id,
            include_screenshot=True,
            include_text=True,
            include_elements=True,
        )
        state, png = _payload(bundle)
        assert png is not None and png.startswith(b"\x89PNG")
        assert "screenshot_png_base64" not in state
        assert state["screenshot_size"]["width"] > 10
        assert "scale" in state
        assert state.get("screenshot_id")
        assert "client_bounds" in state
        assert state.get("human_takeover") is False
        assert "focused_element" in state
        assert "selected_text" in state
        assert "selected_elements" in state
        assert "document_text" in state
        assert engine.get_window(window_id)["window_id"] == window_id
        generation = state["generation"]
        screenshot_id = state["screenshot_id"]
        engine.click(window_id, generation=generation, x=8, y=8, screenshot_id=screenshot_id)
        try:
            engine.click(window_id, generation=generation, x=8, y=8, screenshot_id="deadbeefdeadbeef")
            raise AssertionError("stale screenshot_id must fail")
        except EngineError as exc:
            assert exc.code == "unknown_screenshot_id"

        element_index = None
        for el in state.get("elements") or []:
            if el.get("control_type") in {"Document", "Edit"}:
                element_index = el["index"]
                break

        engine.type_text(window_id, MARKER, generation=generation, element_index=element_index)
        time.sleep(0.4)
        after_bundle = engine.get_window_state(
            window_id,
            include_screenshot=False,
            include_text=True,
            include_elements=False,
        )
        after, _ = _payload(after_bundle)
        blob = (after.get("text") or "") + (after.get("title") or "")
        on_disk = probe.read_text(encoding="utf-8", errors="ignore")
        assert MARKER in blob or MARKER in on_disk

        try:
            engine.click(window_id, generation="ffffffffffffffff", x=12, y=12)
            raise AssertionError("stale generation must fail")
        except EngineError as exc:
            assert exc.code == "generation_mismatch"

        engine.close_window(window_id, generation=after["generation"])
        time.sleep(0.5)
        ids = {w["window_id"] for w in engine.list_windows()["windows"]}
        assert window_id not in ids
        launched = None
    finally:
        if launched is not None:
            try:
                now, _ = _payload(
                    engine.get_window_state(
                        launched["window_id"],
                        include_screenshot=False,
                        include_text=False,
                        include_elements=False,
                    )
                )
                engine.close_window(launched["window_id"], generation=now["generation"])
            except EngineError:
                pass
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        engine.stop()
