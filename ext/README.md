# OCUOC Browser Bridge

Unpacked Chrome MV3 extension. No sidebar, no account. It connects to the OCUOC MCP process on `ws://127.0.0.1:<port>` only.

## Load

1. Chrome → `chrome://extensions` → enable Developer mode → **Load unpacked** → this `ext/` folder.
2. Start MCP: `python -m ocuoc` (or `uv run ocuoc`).
3. Call `browser_bridge_info`. Paste `ws_url` and `pairing_secret` into the extension options page.

The toolbar badge is `●` when the WebSocket is up and `○` when it is not.

## Debugger banner

This extension uses `chrome.debugger` so it can dispatch CDP mouse/keyboard events and read AX/DOM. Chrome **will** show a system infobar while a tab is attached. That banner is expected; it is not a bug and cannot be hidden.

## Permissions

| Permission | Why |
|---|---|
| `debugger` | CDP input, accessibility tree, DOM snapshot |
| `tabs` | list / open / close / activate / screenshot |
| `scripting` | inject `content_cursor.js` |
| `storage` | remember the pairing endpoint |
| `host_permissions` 127.0.0.1 | local WebSocket only |

Screenshots use `Page.captureScreenshot` and do **not** call `tabs.update({active:true})`. Discarded or unpaintable background tabs return an error instead of stealing focus.

Identifiers on the wire are `cuoc.*` / `CUOC_*`. Page refresh hides the agent cursor (MVP; no GET restore).
