"""Runtime cursor motion profile: desktop (default) or browser."""

from __future__ import annotations

import os

PROFILE_DESKTOP = "desktop"
PROFILE_BROWSER = "browser"
ENV_PROFILE = "OCUOC_CURSOR_PROFILE"


def cursor_profile(override: str | None = None) -> str:
    raw = (override if override is not None else os.environ.get(ENV_PROFILE, PROFILE_DESKTOP))
    value = str(raw or PROFILE_DESKTOP).strip().lower()
    return PROFILE_BROWSER if value == PROFILE_BROWSER else PROFILE_DESKTOP
