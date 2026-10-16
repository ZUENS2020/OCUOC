from __future__ import annotations

from pathlib import Path

PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
    "steam": ("steam", "登录 steam", "login steam", "steam setup"),
    "notepad": ("notepad", "记事本"),
}


def launch_aliases(stem: str) -> tuple[str, ...]:
    key = stem.lower()
    extra = PRODUCT_ALIASES.get(key, ())
    names = [key, *extra]
    return tuple(dict.fromkeys(names))


def window_matches_launch(
    info,
    *,
    root_pid: int | None,
    descendant_pids: set[int],
    stem: str,
    aliases: tuple[str, ...] | None = None,
) -> bool:
    names = aliases if aliases is not None else launch_aliases(stem)
    pid = getattr(info, "pid", 0)
    if root_pid and pid == root_pid:
        return True
    if pid in descendant_pids:
        return True
    exe = getattr(info, "exe", "") or ""
    exe_name = Path(exe).name.lower()
    exe_stem = Path(exe).stem.lower()
    needle = stem.lower()
    if needle and (needle == exe_stem or needle in exe_name or needle in exe_stem):
        return True
    title = (getattr(info, "title", "") or "").lower()
    for alias in names:
        if alias and alias in title:
            return True
    return False
