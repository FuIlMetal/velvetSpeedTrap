"""
Treat dispenser control.

Closes the relay for a short pulse, which bridges the hacked PETGEEK remote's
"release" button and drops one portion. Enforces a speed threshold and a
cooldown so a chain of sprints can't cause a treat avalanche.
"""

import logging
import threading
import time
from typing import Callable, Optional

from . import config, db

log = logging.getLogger("catspeed.treat")


class Relay:
    """Minimal interface the dispenser needs. Backed by gpiozero or a stub."""

    def on(self) -> None:  # energise (bridge the button)
        raise NotImplementedError

    def off(self) -> None:
        raise NotImplementedError


class TreatDispenser:
    def __init__(self, relay: Relay, on_dispense: Optional[Callable[[], None]] = None):
        self.relay = relay
        self.on_dispense = on_dispense
        self._lock = threading.Lock()
        self._last_treat_mono = 0.0
        self.last_treat_epoch = 0.0  # wall-clock of most recent dispense (0 = never)

        self.threshold_mph = db.get_setting_float(
            "treat_threshold_mph", config.DEFAULT_THRESHOLD_MPH
        )
        self.cooldown_s = db.get_setting_float(
            "treat_cooldown_s", config.DEFAULT_COOLDOWN_S
        )

    # -- configuration ----------------------------------------------------
    def set_threshold(self, mph: float) -> None:
        with self._lock:
            self.threshold_mph = float(mph)
        db.set_setting("treat_threshold_mph", self.threshold_mph)

    def set_cooldown(self, seconds: float) -> None:
        with self._lock:
            self.cooldown_s = float(seconds)
        db.set_setting("treat_cooldown_s", self.cooldown_s)

    def cooldown_remaining(self) -> float:
        with self._lock:
            if self._last_treat_mono == 0.0:
                return 0.0
            remaining = self.cooldown_s - (time.monotonic() - self._last_treat_mono)
        return max(0.0, remaining)

    # -- dispensing -------------------------------------------------------
    def maybe_dispense(self, current_mph: float) -> bool:
        """Called on each speed update. Returns True if a treat was dropped."""
        now = time.monotonic()
        with self._lock:
            if current_mph < self.threshold_mph:
                return False
            if self._last_treat_mono and (now - self._last_treat_mono) < self.cooldown_s:
                return False
            # Reserve the cooldown slot inside the lock to avoid double-fire.
            self._last_treat_mono = now
            self.last_treat_epoch = time.time()
        self._fire(reason=f"{current_mph:.2f} mph >= {self.threshold_mph:.2f}")
        return True

    def dispense(self) -> None:
        """Force a dispense (manual test button on the dashboard). Ignores cooldown."""
        with self._lock:
            self._last_treat_mono = time.monotonic()
            self.last_treat_epoch = time.time()
        self._fire(reason="manual")

    def _fire(self, reason: str) -> None:
        log.info("Dispensing treat (%s)", reason)
        self.relay.on()
        time.sleep(config.TREAT_PULSE_MS / 1000.0)
        self.relay.off()
        if self.on_dispense:
            try:
                self.on_dispense()
            except Exception:  # never let a callback break the relay path
                log.exception("on_dispense callback failed")
