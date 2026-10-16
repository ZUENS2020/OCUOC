"""Cursor sequence numbers and arrival waiters (1500ms, plan §2.4)."""

from __future__ import annotations

import asyncio
import time

from ocuoc.browser.protocol import ARRIVAL_TIMEOUT_MS


class CursorController:
    def __init__(self) -> None:
        self._next_seq = 1
        self._waiters: dict[tuple[int, int], asyncio.Future] = {}

    def next_seq(self) -> int:
        seq = self._next_seq
        self._next_seq += 1
        return seq

    def register(self, tab_id: int, seq: int) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters[(int(tab_id), int(seq))] = fut
        return fut

    def arrived(self, tab_id: int, seq: int) -> None:
        fut = self._waiters.pop((int(tab_id), int(seq)), None)
        if fut and not fut.done():
            fut.set_result(time.monotonic())

    def forget(self, tab_id: int, seq: int) -> None:
        self._waiters.pop((int(tab_id), int(seq)), None)

    def abort_all(self) -> None:
        for fut in list(self._waiters.values()):
            if not fut.done():
                fut.cancel()
        self._waiters.clear()

    @staticmethod
    def timeout_s() -> float:
        return ARRIVAL_TIMEOUT_MS / 1000.0
