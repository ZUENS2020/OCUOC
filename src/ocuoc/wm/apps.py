from __future__ import annotations

import os
import struct
import winreg
from datetime import datetime, timezone
from pathlib import Path


def _start_menu_roots() -> list[Path]:
    roots: list[Path] = []
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    appdata = os.environ.get("APPDATA", "")
    roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _add(bucket: dict[str, dict], item: dict) -> None:
    exe = (item.get("exe") or "").strip()
    if not exe:
        return
    key = exe.lower()
    existing = bucket.get(key)
    if existing is None:
        bucket[key] = item
        return
    for field in ("last_used", "use_count", "name", "source"):
        if not existing.get(field) and item.get(field) is not None:
            existing[field] = item[field]
    sources = existing.setdefault("sources", [existing.get("source")] if existing.get("source") else [])
    src = item.get("source")
    if src and src not in sources:
        sources.append(src)
    if item.get("use_count") and (existing.get("use_count") or 0) < item["use_count"]:
        existing["use_count"] = item["use_count"]
        existing["last_used"] = item.get("last_used") or existing.get("last_used")


def list_start_menu_apps(limit: int = 400) -> list[dict]:
    try:
        import pythoncom
        from win32com.client import Dispatch
    except Exception:
        return []
    pythoncom.CoInitialize()
    try:
        shell = Dispatch("WScript.Shell")
    except Exception:
        return []
    seen: dict[str, dict] = {}
    for root in _start_menu_roots():
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            if len(seen) >= limit:
                return list(seen.values())
            try:
                shortcut = shell.CreateShortCut(str(lnk))
                target = str(shortcut.Targetpath or "")
            except Exception:
                continue
            if not target.lower().endswith(".exe"):
                continue
            _add(
                seen,
                {
                    "id": f"exe:{target}",
                    "name": lnk.stem,
                    "exe": target,
                    "source": "start_menu",
                },
            )
    return list(seen.values())


def list_app_paths() -> list[dict]:
    out: list[dict] = []
    for hive, view in (
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
    ):
        try:
            key = winreg.OpenKey(
                hive,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
                0,
                winreg.KEY_READ | view,
            )
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    sub = winreg.OpenKey(key, name)
                except OSError:
                    continue
                try:
                    target, _typ = winreg.QueryValueEx(sub, None)
                except OSError:
                    target = ""
                finally:
                    winreg.CloseKey(sub)
                target = str(target or "").strip().strip('"')
                if not target.lower().endswith(".exe"):
                    continue
                out.append(
                    {
                        "id": f"exe:{target}",
                        "name": Path(name).stem,
                        "exe": target,
                        "source": "app_paths",
                    }
                )
        finally:
            winreg.CloseKey(key)
    return out


def list_execution_aliases() -> list[dict]:
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    if not root.is_dir():
        return []
    out: list[dict] = []
    try:
        for path in root.glob("*.exe"):
            out.append(
                {
                    "id": f"exe:{path}",
                    "name": path.stem,
                    "exe": str(path),
                    "source": "execution_alias",
                }
            )
    except OSError:
        return []
    return out


def _rot13(text: str) -> str:
    chars = []
    for ch in text:
        o = ord(ch)
        if 65 <= o <= 90:
            chars.append(chr((o - 65 + 13) % 26 + 65))
        elif 97 <= o <= 122:
            chars.append(chr((o - 97 + 13) % 26 + 97))
        else:
            chars.append(ch)
    return "".join(chars)


def _filetime_iso(raw: int) -> str | None:
    if raw <= 0:
        return None
    unix = raw / 10_000_000 - 11_644_473_600
    if unix < 0 or unix > 4_000_000_000:
        return None
    try:
        return datetime.fromtimestamp(unix, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, OverflowError, ValueError):
        return None


def list_user_assist() -> list[dict]:
    guids = (
        "{CEBFF5CD-ACE2-4F4F-9178-9926F41749EA}",
        "{F4E57C4B-2036-45F0-A9AB-443BCFE33D9F}",
    )
    out: list[dict] = []
    for guid in guids:
        path = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist\{guid}\Count"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name, data, typ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                decoded = _rot13(str(name))
                lower = decoded.lower()
                if lower.startswith("ueme_runpath:"):
                    decoded = decoded.split(":", 1)[1]
                    lower = decoded.lower()
                elif lower.startswith("ueme_"):
                    continue
                exe = ""
                if lower.endswith(".exe"):
                    exe = decoded
                elif ".lnk" in lower:
                    continue
                else:
                    continue
                use_count = 0
                last_used = None
                if typ == winreg.REG_BINARY and isinstance(data, (bytes, bytearray)) and len(data) >= 8:
                    use_count = int(struct.unpack_from("<I", data, 4)[0])
                    if len(data) >= 68:
                        ft = int(struct.unpack_from("<Q", data, 60)[0])
                        last_used = _filetime_iso(ft)
                out.append(
                    {
                        "id": f"exe:{exe}",
                        "name": Path(exe).stem,
                        "exe": exe,
                        "source": "user_assist",
                        "use_count": use_count,
                        "last_used": last_used,
                    }
                )
        finally:
            winreg.CloseKey(key)
    return out


def list_catalog_apps(limit: int = 500) -> list[dict]:
    bucket: dict[str, dict] = {}
    for item in list_start_menu_apps(limit=limit):
        _add(bucket, item)
    for item in list_app_paths():
        _add(bucket, item)
        if len(bucket) >= limit:
            break
    for item in list_execution_aliases():
        _add(bucket, item)
        if len(bucket) >= limit:
            break
    for item in list_user_assist():
        _add(bucket, item)
    items = list(bucket.values())
    items.sort(key=lambda a: (-int(a.get("use_count") or 0), (a.get("name") or "").lower()))
    return items[:limit]
