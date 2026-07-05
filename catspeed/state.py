"""Tiny shared snapshot the OLED and web layers read each frame."""

import threading
from typing import Dict

from . import db


class AppState:
    """Caches the peak figures so the 5 Hz OLED loop isn't hitting SQLite
    on every frame. Live speed is read straight from the tracker."""

    def __init__(self, tracker):
        self._tracker = tracker
        self._lock = threading.Lock()
        self._peak_today = 0.0
        self._all_time_peak = 0.0
        self._last_run_epoch = 0.0
        self.refresh_from_db()

    def refresh_from_db(self) -> None:
        peak_today = db.peak_today()
        all_time = db.all_time_peak()
        last_run = db.last_run_time()
        with self._lock:
            self._peak_today = peak_today
            self._all_time_peak = all_time
            self._last_run_epoch = last_run

    def note_peak(self, mph: float) -> None:
        """Cheap live update so the OLED reflects a new record mid-run."""
        with self._lock:
            self._peak_today = max(self._peak_today, mph)
            self._all_time_peak = max(self._all_time_peak, mph)

    def snapshot(self) -> Dict[str, float]:
        with self._lock:
            peak_today = self._peak_today
            all_time = self._all_time_peak
            last_run = self._last_run_epoch
        return {
            "current_mph": self._tracker.snapshot_speed(),
            "peak_today": peak_today,
            "all_time_peak": all_time,
            "last_run_epoch": last_run,
        }
