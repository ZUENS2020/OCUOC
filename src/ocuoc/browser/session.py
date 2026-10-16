"""Tab registry: generation fingerprint is tab_id + url (plan §2.5)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ocuoc.errors import EngineError


def tab_generation(tab_id: int, url: str) -> str:
    payload = json.dumps(
        {"tabId": int(tab_id), "url": str(url or "")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class TabRegistry:
    def __init__(self) -> None:
        self._tabs: dict[int, dict[str, Any]] = {}
        self._dpr: dict[int, float] = {}
        self.events: list[dict[str, Any]] = []
        self.dialogs: list[dict[str, Any]] = []

    def stamp(self, tab: dict[str, Any]) -> dict[str, Any]:
        tid = int(tab.get("tabId") or tab.get("id") or 0)
        url = str(tab.get("url") or "")
        row = dict(tab)
        row["tabId"] = tid
        row["generation"] = tab_generation(tid, url)
        self._tabs[tid] = row
        return row

    def get(self, tab_id: int) -> dict[str, Any] | None:
        return self._tabs.get(int(tab_id))

    def require(self, tab_id: int, generation: str | None = None) -> dict[str, Any]:
        info = self._tabs.get(int(tab_id))
        if generation:
            if info is None:
                raise EngineError("generation_mismatch", f"unknown tab {tab_id} for generation {generation}")
            if info.get("generation") != generation:
                raise EngineError(
                    "generation_mismatch",
                    f"tab changed (expected {generation}, now {info.get('generation')})",
                )
        return info or {"tabId": int(tab_id), "url": "", "generation": tab_generation(int(tab_id), "")}

    def remember_dpr(self, tab_id: int, dpr: float) -> float:
        value = float(dpr) if dpr else 1.0
        if value <= 0:
            value = 1.0
        self._dpr[int(tab_id)] = value
        return value

    def dpr(self, tab_id: int) -> float | None:
        return self._dpr.get(int(tab_id))

    def on_tab_event(self, data: dict[str, Any]) -> None:
        self.events.append(data)
        kind = data.get("kind")
        if kind == "removed":
            tid = int(data.get("tabId") or -1)
            self._tabs.pop(tid, None)
            self._dpr.pop(tid, None)
            return
        tab = data.get("tab") if isinstance(data.get("tab"), dict) else None
        if kind == "replaced":
            removed = int(data.get("removedTabId") or -1)
            self._tabs.pop(removed, None)
            self._dpr.pop(removed, None)
            if tab:
                self.stamp(tab)
            return
        if tab:
            self.stamp(tab)

    def on_dialog(self, data: dict[str, Any]) -> None:
        self.dialogs.append(data)

    def pop_dialogs(self) -> list[dict[str, Any]]:
        items = list(self.dialogs)
        self.dialogs.clear()
        return items
