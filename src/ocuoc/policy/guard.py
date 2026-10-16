from __future__ import annotations


class Guard:
    """Operator abort only. Esc sets the flag; there is no allowlist or UAC block."""

    def __init__(self) -> None:
        self._aborted = False
        self._reason = ""

    @classmethod
    def from_env(cls) -> Guard:
        return cls()

    def abort(self, reason: str) -> None:
        self._aborted = True
        self._reason = reason

    def reset(self) -> None:
        self._aborted = False
        self._reason = ""

    def allow_input(self) -> bool:
        return not self._aborted

    def reason(self) -> str:
        return self._reason
