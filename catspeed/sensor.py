"""
Hall-sensor pulse handling and speed calculation.

The wheel carries one (or more) magnet(s); each pass triggers a GPIO edge,
which calls SpeedTracker.on_pulse() from gpiozero's callback thread. A
separate 5 Hz loop calls SpeedTracker.tick() to detect when a run ends.

Timing note: interval math uses time.monotonic() (immune to wall-clock
jumps / NTP steps); stored timestamps use time.time() (real wall-clock).
"""

import threading
import time
from collections import deque
from typing import Callable, Optional

from . import config
from .models import RunRecord


class SpeedTracker:
    def __init__(
        self,
        on_speed_update: Callable[[float], None],
        on_run_complete: Callable[[RunRecord], None],
    ):
        self.on_speed_update = on_speed_update
        self.on_run_complete = on_run_complete

        self._lock = threading.Lock()
        self._smooth = deque(maxlen=max(1, config.SPEED_SMOOTHING_SAMPLES))

        self.current_mph = 0.0

        self.last_pulse_mono: Optional[float] = None
        self.last_pulse_epoch: Optional[float] = None

        self.run_active = False
        self.run_start_mono = 0.0
        self.run_start_epoch = 0.0
        self.run_pulses = 0
        self.run_peak_mph = 0.0

    # -- called from the GPIO edge callback ------------------------------
    def on_pulse(self) -> None:
        now_mono = time.monotonic()
        now_epoch = time.time()
        emit_speed: Optional[float] = None

        with self._lock:
            inst_mph: Optional[float] = None
            if self.last_pulse_mono is not None:
                dt = now_mono - self.last_pulse_mono
                if dt * 1000.0 < config.PULSE_DEBOUNCE_MS:
                    return  # contact bounce / double trigger — ignore entirely
                inst_mph = (config.DISTANCE_PER_PULSE_M / dt) * config.MPS_TO_MPH

            if not self.run_active:
                self.run_active = True
                self.run_start_mono = now_mono
                self.run_start_epoch = now_epoch
                self.run_pulses = 0
                self.run_peak_mph = 0.0
                self._smooth.clear()

            self.run_pulses += 1
            self.last_pulse_mono = now_mono
            self.last_pulse_epoch = now_epoch

            # First pulse of a run has no interval yet; and reject noise spikes.
            if inst_mph is not None and inst_mph <= config.MAX_PLAUSIBLE_MPH:
                self._smooth.append(inst_mph)
                self.current_mph = sum(self._smooth) / len(self._smooth)
                self.run_peak_mph = max(self.run_peak_mph, self.current_mph)
                emit_speed = self.current_mph

        if emit_speed is not None:
            self.on_speed_update(emit_speed)

    # -- called from the 5 Hz tick loop ----------------------------------
    def tick(self) -> None:
        record: Optional[RunRecord] = None
        went_idle = False

        with self._lock:
            if self.last_pulse_mono is None:
                return
            idle = time.monotonic() - self.last_pulse_mono
            if idle <= config.IDLE_TIMEOUT_S:
                return

            if self.current_mph != 0.0:
                self.current_mph = 0.0
                went_idle = True

            if self.run_active:
                duration = self.last_pulse_mono - self.run_start_mono
                # Need at least two pulses to have measured any speed.
                if duration >= config.RUN_MIN_DURATION_S and self.run_pulses >= 2:
                    # Distance travelled = (pulses - 1) intervals between pulses.
                    distance_m = (self.run_pulses - 1) * config.DISTANCE_PER_PULSE_M
                    avg_mph = (distance_m / duration) * config.MPS_TO_MPH if duration > 0 else 0.0
                    revolutions = max(1, round(self.run_pulses / config.MAGNETS_PER_REV))
                    record = RunRecord(
                        started_at=self.run_start_epoch,
                        ended_at=self.last_pulse_epoch,
                        peak_mph=round(self.run_peak_mph, 3),
                        avg_mph=round(avg_mph, 3),
                        duration_s=round(duration, 3),
                        revolutions=revolutions,
                    )
                self.run_active = False
                self.run_peak_mph = 0.0
                self.run_pulses = 0

        if went_idle:
            self.on_speed_update(0.0)
        if record is not None:
            self.on_run_complete(record)

    def snapshot_speed(self) -> float:
        with self._lock:
            return self.current_mph
