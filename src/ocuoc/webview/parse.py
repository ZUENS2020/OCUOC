from __future__ import annotations

from ocuoc.uia import tree as uia
from ocuoc.webview.cdp import fetch_ax_tree
from ocuoc.webview.detect import classify_webview, debug_port_from_cmdline
from ocuoc.wm.processes import process_command_line
from ocuoc.wm.windows import WindowInfo, child_class_names, child_hwnds, snapshot


def parse_webview(info: WindowInfo, max_elements: int = 200) -> dict:
    children = child_class_names(info.hwnd)
    kind = classify_webview(info.class_name, info.exe, children)
    result = {
        "kind": kind,
        "source": "none",
        "parsed": False,
        "reason": None,
        "child_classes": children[:12],
    }
    if kind is None:
        result["reason"] = "not_webview"
        return result

    cmdline = process_command_line(info.pid)
    port = debug_port_from_cmdline(cmdline)
    elements: list[dict] = []
    source = "none"
    reason = None

    render_hwnds = [
        hwnd
        for hwnd in child_hwnds(info.hwnd)
        if _class_of(hwnd).lower() in {"chrome_renderwidgethosthwnd", "cefbrowserwindow", "chrome_widgetwin_0"}
    ]
    walk_hwnds = [info.hwnd, *render_hwnds]
    uia_elements: list[dict] = []
    seen: set[tuple] = set()
    budget = max(max_elements, 200)
    for hwnd in walk_hwnds:
        piece = _describe_hwnd(hwnd, info, budget - len(uia_elements))
        for item in piece:
            key = (
                item.get("name"),
                item.get("control_type"),
                item.get("rect", {}).get("x"),
                item.get("rect", {}).get("y"),
                item.get("rect", {}).get("width"),
                item.get("rect", {}).get("height"),
            )
            if key in seen:
                continue
            seen.add(key)
            uia_elements.append(item)
        if len(uia_elements) >= budget:
            break

    interesting = [
        el
        for el in uia_elements
        if el.get("control_type") not in {"Window", ""} or (el.get("name") and el.get("control_type") != "Window")
    ]
    if len(interesting) >= 3:
        elements = uia_elements
        source = "uia"
    elif uia_elements:
        elements = uia_elements
        source = "uia"
        reason = "uia_sparse"

    if port:
        try:
            cdp_nodes, cdp_source = fetch_ax_tree(port)
        except Exception as exc:
            cdp_nodes, cdp_source = [], f"cdp_failed:{exc}"
        if cdp_nodes:
            origin = _render_origin(info, render_hwnds)
            client_origin = _client_origin(info)
            converted = []
            for node in cdp_nodes:
                rect = node.get("rect")
                if rect:
                    node = {
                        **node,
                        "rect": {
                            "x": int(rect["x"] + origin[0] - client_origin[0]),
                            "y": int(rect["y"] + origin[1] - client_origin[1]),
                            "width": rect["width"],
                            "height": rect["height"],
                        },
                    }
                converted.append(node)
            elements = converted
            source = "cdp"
            reason = None
        elif source != "uia":
            reason = cdp_source or "cdp_empty"
    elif source != "uia":
        reason = "no_cdp_port"

    if source in {"uia", "cdp"} and elements:
        # Sparse UIA (Steam: Window + empty Document) is not a real parse.
        named = [el for el in elements if (el.get("name") or "").strip()]
        if source == "uia" and len(named) <= 1 and len(elements) <= 3:
            result["source"] = "none"
            result["parsed"] = False
            result["reason"] = "uia_empty_document"
            result["elements"] = _reindex(elements[:max_elements])
            return result
        result["source"] = source
        result["parsed"] = True
        result["reason"] = reason
        result["elements"] = _reindex(elements[:max_elements])
        return result

    result["source"] = "none"
    result["parsed"] = False
    result["reason"] = reason or "unparsed"
    result["elements"] = _reindex(elements[:max_elements]) if elements else []
    return result


def _reindex(elements: list[dict]) -> list[dict]:
    out = []
    for i, item in enumerate(elements):
        row = dict(item)
        row["index"] = i
        row.setdefault("source", "uia")
        out.append(row)
    return out


def _class_of(hwnd: int) -> str:
    from ocuoc.wm.windows import snapshot as snap

    info = snap(hwnd)
    return info.class_name if info else ""


def _client_origin(info: WindowInfo) -> tuple[int, int]:
    cl, ct, cr, cb = info.client_rect
    if cr > cl and cb > ct:
        return cl, ct
    return info.rect[0], info.rect[1]


def _render_origin(info: WindowInfo, render_hwnds: list[int]) -> tuple[int, int]:
    for hwnd in render_hwnds:
        child = snapshot(hwnd)
        if child:
            return _client_origin(child)
    return _client_origin(info)


def _describe_hwnd(hwnd: int, parent: WindowInfo, max_elements: int) -> list[dict]:
    if max_elements <= 0:
        return []
    fake = parent
    if hwnd != parent.hwnd:
        child = snapshot(hwnd)
        if child is None:
            return []
        fake = child
    try:
        items = uia.describe_elements(fake, max_elements=max_elements, max_depth=16)
    except Exception:
        return []
    left, top = _client_origin(parent)
    fox, foy = _client_origin(fake)
    out = []
    for item in items:
        rect = item.get("rect") or {}
        abs_x = fox + int(rect.get("x") or 0)
        abs_y = foy + int(rect.get("y") or 0)
        row = dict(item)
        row["rect"] = {
            "x": abs_x - left,
            "y": abs_y - top,
            "width": rect.get("width") or 0,
            "height": rect.get("height") or 0,
        }
        row["source"] = "uia"
        out.append(row)
    return out
