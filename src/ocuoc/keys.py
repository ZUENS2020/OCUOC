from __future__ import annotations

MODIFIERS = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "menu": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "super": 0x5B,
    "meta": 0x5B,
}

NAMED_KEYS = {
    "esc": 0x1B,
    "escape": 0x1B,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "pageup": 0x21,
    "pagedown": 0x22,
    "insert": 0x2D,
}

_TOKEN_ALIASES = {
    "control": "ctrl",
    "menu": "alt",
    "super": "win",
    "meta": "win",
    "return": "enter",
    "escape": "esc",
}


def canonical_token(token: str) -> str:
    key = token.strip().lower()
    if len(key) > 2 and key[-2:] in {"_l", "_r"}:
        key = key[:-2]
    return _TOKEN_ALIASES.get(key, key)


def parse_hotkey(spec: str) -> tuple[list[str], str]:
    parts = [canonical_token(p) for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    mods = [p for p in parts[:-1] if p in MODIFIERS]
    unknown = [p for p in parts[:-1] if p not in MODIFIERS]
    if unknown:
        raise ValueError(f"unknown modifier: {unknown[0]}")
    return mods, parts[-1]


def vk_name(name: str) -> int:
    key = canonical_token(name)
    if key in NAMED_KEYS:
        return NAMED_KEYS[key]
    if key in MODIFIERS:
        return MODIFIERS[key]
    if len(key) >= 2 and key[0] == "f" and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    raise ValueError(f"unknown key: {name}")


def modifier_vk(name: str) -> int:
    key = canonical_token(name)
    if key not in MODIFIERS:
        raise ValueError(f"unknown modifier: {name}")
    return MODIFIERS[key]
