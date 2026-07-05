"""Small shared helpers."""

import time
from typing import Optional


def format_ago(epoch: Optional[float], now: Optional[float] = None) -> str:
    """Human 'time since' for a wall-clock timestamp. '—' if never."""
    if not epoch:
        return "—"
    now = now if now is not None else time.time()
    secs = now - epoch
    if secs < 0:
        return "just now"
    if secs < 60:
        return "just now"
    mins = secs / 60
    if mins < 60:
        return f"{int(mins)}m ago"
    hours = mins / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    return f"{int(days)}d ago"
