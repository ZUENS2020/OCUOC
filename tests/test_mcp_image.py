from mcp.server.mcpserver import Image
from mcp.server.mcpserver.utilities.func_metadata import _convert_to_content
from mcp_types import ImageContent

from ocuoc.server import mcp


def test_image_helper_becomes_image_content():
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    blocks = _convert_to_content([{"ok": True, "result": {"screenshot_size": {"width": 1, "height": 1}}}, Image(data=png, format="png")])
    types = [getattr(b, "type", None) for b in blocks]
    assert "image" in types
    image = next(b for b in blocks if isinstance(b, ImageContent) or getattr(b, "type", None) == "image")
    assert image.mime_type == "image/png"


def test_screenshot_tools_are_unstructured():
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    assert tools["get_window_state"].fn_metadata.output_schema is None
    assert tools["screenshot_desktop"].fn_metadata.output_schema is None
