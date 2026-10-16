from __future__ import annotations

from ocuoc.errors import EngineError
from ocuoc.wm.windows import WindowInfo

INTERACTIVE = {
    "ButtonControl",
    "EditControl",
    "DocumentControl",
    "ComboBoxControl",
    "CheckBoxControl",
    "RadioButtonControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
    "TabItemControl",
    "TreeItemControl",
    "SplitButtonControl",
    "DataItemControl",
    "SpinnerControl",
    "SliderControl",
    "TextControl",
}

SECONDARY_ACTIONS = {
    "expand",
    "collapse",
    "raise",
    "invoke",
    "toggle",
    "scroll_up",
    "scroll_down",
    "scroll_left",
    "scroll_right",
}


def _root(hwnd: int):
    import uiautomation as auto

    ctrl = auto.ControlFromHandle(hwnd)
    if ctrl is None:
        raise EngineError("uia_failed", "ControlFromHandle returned None")
    return ctrl


def _origin(info: WindowInfo) -> tuple[int, int]:
    if info.client_rect[2] > info.client_rect[0] and info.client_rect[3] > info.client_rect[1]:
        return info.client_rect[0], info.client_rect[1]
    return info.rect[0], info.rect[1]


def describe_elements(info: WindowInfo, max_elements: int = 80, max_depth: int = 10) -> list[dict]:
    return describe_snapshot(info, max_elements=max_elements, max_depth=max_depth)["elements"]


def describe_snapshot(info: WindowInfo, max_elements: int = 80, max_depth: int = 10) -> dict:
    root = _root(info.hwnd)
    left, top = _origin(info)
    items: list[dict] = []
    focused: dict | None = None
    selected_elements: list[dict] = []
    document_chunks: list[str] = []
    selected_chunks: list[str] = []

    def emit(ctrl, name: str, ctype: str, aid: str, sx: int, sy: int, width: int, height: int) -> dict:
        row = {
            "index": len(items),
            "name": name,
            "control_type": ctype.replace("Control", ""),
            "automation_id": aid,
            "source": "uia",
            "rect": {
                "x": sx - left,
                "y": sy - top,
                "width": width,
                "height": height,
            },
        }
        items.append(row)
        return row

    def walk(ctrl, depth: int) -> None:
        nonlocal focused
        if len(items) >= max_elements or depth > max_depth:
            return
        try:
            name = ctrl.Name or ""
            ctype = ctrl.ControlTypeName or ""
            aid = ctrl.AutomationId or ""
            rect = ctrl.BoundingRectangle
        except Exception:
            return
        try:
            width = int(rect.width())
            height = int(rect.height())
            sx = int(rect.left)
            sy = int(rect.top)
        except Exception:
            width = height = sx = sy = 0
        interesting = ctype in INTERACTIVE or bool(name.strip())
        row = None
        if interesting and width > 1 and height > 1:
            row = emit(ctrl, name, ctype, aid, sx, sy, width, height)
            try:
                if ctrl.HasKeyboardFocus:
                    focused = row
            except Exception:
                pass
            try:
                if ctrl.GetSelectionItemPattern().IsSelected:
                    selected_elements.append(row)
            except Exception:
                pass
        if ctype in {"EditControl", "DocumentControl"}:
            text, selection = _text_pattern_bits(ctrl)
            if text:
                document_chunks.append(text)
            if selection:
                selected_chunks.append(selection)
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for child in children:
            walk(child, depth + 1)

    walk(root, 0)
    if focused is None:
        focused = _focused_from_system(items)
    return {
        "elements": items,
        "focused_element": focused,
        "selected_text": "\n".join(selected_chunks),
        "selected_elements": selected_elements,
        "document_text": "\n".join(document_chunks),
    }


def _text_pattern_bits(ctrl) -> tuple[str, str]:
    try:
        pattern = ctrl.GetTextPattern()
    except Exception:
        pattern = None
    if not pattern:
        return "", ""
    document = ""
    selected = ""
    try:
        rng = pattern.DocumentRange
        document = (rng.GetText(-1) if rng else "") or ""
    except Exception:
        document = ""
    try:
        ranges = pattern.GetSelection() or []
        bits = []
        for rng in ranges:
            try:
                bits.append(rng.GetText(-1) or "")
            except Exception:
                continue
        selected = "".join(bits)
    except Exception:
        selected = ""
    return document, selected


def _focused_from_system(items: list[dict]) -> dict | None:
    try:
        import uiautomation as auto

        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return None
        name = ctrl.Name or ""
        aid = ctrl.AutomationId or ""
        ctype = (ctrl.ControlTypeName or "").replace("Control", "")
    except Exception:
        return None
    for row in items:
        if row.get("name") == name and row.get("automation_id") == aid:
            return row
        if row.get("name") == name and row.get("control_type") == ctype:
            return row
    return None


def collect_text(info: WindowInfo) -> str:
    classic = _win32_edit_text(info.hwnd)
    if classic:
        return classic
    root = _root(info.hwnd)
    values: list[str] = []

    def walk(ctrl, depth: int) -> None:
        if depth > 12 or len(values) > 8:
            return
        try:
            ctype = ctrl.ControlTypeName or ""
            if ctype in {"EditControl", "DocumentControl"}:
                try:
                    pattern = ctrl.GetValuePattern()
                    value = pattern.Value if pattern else ""
                except Exception:
                    value = ""
                if value:
                    values.append(value)
        except Exception:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for child in children:
            walk(child, depth + 1)

    walk(root, 0)
    if values:
        return "\n".join(values)
    return info.title


def _win32_edit_text(hwnd: int) -> str:
    from ocuoc.winapi import WM_GETTEXT, WM_GETTEXTLENGTH, user32
    import ctypes

    edit = user32.FindWindowExW(hwnd, None, "Edit", None)
    if not edit:
        return ""
    length = int(user32.SendMessageW(edit, WM_GETTEXTLENGTH, 0, 0))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(edit, WM_GETTEXT, length + 1, ctypes.addressof(buf))
    return buf.value


def element_center(info: WindowInfo, element_index: int, elements: list[dict] | None = None) -> tuple[int, int]:
    if elements is None:
        elements = describe_elements(info)
    if element_index < 0 or element_index >= len(elements):
        raise EngineError("bad_element", f"element_index {element_index} out of range")
    rect = elements[element_index]["rect"]
    left, top = _origin(info)
    x = left + rect["x"] + rect["width"] // 2
    y = top + rect["y"] + rect["height"] // 2
    return x, y


def _find_control(info: WindowInfo, element_index: int, elements: list[dict] | None = None):
    if elements is None:
        elements = describe_elements(info)
    if element_index < 0 or element_index >= len(elements):
        raise EngineError("bad_element", f"element_index {element_index} out of range")
    target = elements[element_index]
    root = _root(info.hwnd)

    def walk(ctrl, depth: int):
        if depth > 16:
            return None
        try:
            name = ctrl.Name or ""
            aid = ctrl.AutomationId or ""
            if name == target["name"] and aid == target.get("automation_id", ""):
                return ctrl
        except Exception:
            return None
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for child in children:
            found = walk(child, depth + 1)
            if found is not None:
                return found
        return None

    ctrl = walk(root, 0)
    if ctrl is None:
        raise EngineError("bad_element", f"element_index {element_index} no longer belongs to the cached target")
    return ctrl


def set_element_value(info: WindowInfo, element_index: int, text: str, elements: list[dict] | None = None) -> bool:
    ctrl = _find_control(info, element_index, elements)
    try:
        pattern = ctrl.GetValuePattern()
        if pattern:
            pattern.SetValue(text)
            return True
    except Exception:
        pass
    try:
        ctrl.GetLegacyIAccessiblePattern().SetValue(text)
        return True
    except Exception:
        return False


def normalize_action(action: str) -> str:
    key = (action or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "scrollup": "scroll_up",
        "scrolldown": "scroll_down",
        "scrollleft": "scroll_left",
        "scrollright": "scroll_right",
        "scroll_up": "scroll_up",
        "scroll_down": "scroll_down",
        "scroll_left": "scroll_left",
        "scroll_right": "scroll_right",
        "expand": "expand",
        "collapse": "collapse",
        "raise": "raise",
        "invoke": "invoke",
        "toggle": "toggle",
    }
    if key not in aliases:
        raise EngineError("bad_action", f"unsupported secondary action: {action}")
    return aliases[key]


def perform_secondary_action(
    info: WindowInfo, element_index: int, action: str, elements: list[dict] | None = None
) -> str:
    import uiautomation as auto

    name = normalize_action(action)
    ctrl = _find_control(info, element_index, elements)
    try:
        if name == "expand":
            ctrl.GetExpandCollapsePattern().Expand()
            return "expand"
        if name == "collapse":
            ctrl.GetExpandCollapsePattern().Collapse()
            return "collapse"
        if name == "toggle":
            ctrl.GetTogglePattern().Toggle()
            return "toggle"
        if name in {"raise", "invoke"}:
            try:
                ctrl.GetInvokePattern().Invoke()
                return name
            except Exception:
                ctrl.SetFocus()
                return name
        amount = getattr(auto.ScrollAmount, "SmallIncrement", 1)
        if name == "scroll_down":
            try:
                ctrl.GetScrollPattern().Scroll(auto.ScrollAmount.NoAmount, amount)
            except Exception:
                ctrl.GetScrollItemPattern().ScrollIntoView()
            return name
        if name == "scroll_up":
            try:
                ctrl.GetScrollPattern().Scroll(auto.ScrollAmount.NoAmount, getattr(auto.ScrollAmount, "SmallDecrement", 0))
            except Exception:
                ctrl.GetScrollItemPattern().ScrollIntoView()
            return name
        if name == "scroll_right":
            ctrl.GetScrollPattern().Scroll(amount, auto.ScrollAmount.NoAmount)
            return name
        if name == "scroll_left":
            ctrl.GetScrollPattern().Scroll(getattr(auto.ScrollAmount, "SmallDecrement", 0), auto.ScrollAmount.NoAmount)
            return name
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError("uia_action_failed", f"{name} failed: {exc}") from exc
    raise EngineError("bad_action", f"unsupported secondary action: {action}")


def scroll_element(info: WindowInfo, element_index: int, dy: int, dx: int, elements: list[dict] | None = None) -> bool:
    import uiautomation as auto

    ctrl = _find_control(info, element_index, elements)
    try:
        pattern = ctrl.GetScrollPattern()
        if pattern:
            h = auto.ScrollAmount.NoAmount
            v = auto.ScrollAmount.NoAmount
            if dy > 0:
                v = getattr(auto.ScrollAmount, "SmallIncrement", 1)
            elif dy < 0:
                v = getattr(auto.ScrollAmount, "SmallDecrement", 0)
            if dx > 0:
                h = getattr(auto.ScrollAmount, "SmallIncrement", 1)
            elif dx < 0:
                h = getattr(auto.ScrollAmount, "SmallDecrement", 0)
            for _ in range(max(abs(int(dy)), abs(int(dx)), 1)):
                pattern.Scroll(h, v)
            return True
    except Exception:
        pass
    try:
        ctrl.GetScrollItemPattern().ScrollIntoView()
        return True
    except Exception:
        return False
