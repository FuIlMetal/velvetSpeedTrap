"""
Hardware backends.

On the Pi this wraps gpiozero. Anywhere else (or with --simulate) it falls
back to stubs so the rest of the system — dashboard, database, OLED-to-console
— still runs. That's not a test harness; it just keeps the process alive when
the GPIO/I2C peripherals aren't present.
"""

import logging
import random
import threading
import time
from typing import Callable

from . import config
from .treat import Relay

log = logging.getLogger("catspeed.hw")


def gpio_available() -> bool:
    """True if gpiozero can talk to real pins on this machine."""
    try:
        import gpiozero  # noqa: F401
        from gpiozero import Device
        # Touch the default pin factory; raises off-Pi (no /dev/gpiomem etc.).
        Device._default_pin_factory()  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


# --- Relay backends -------------------------------------------------------

class GpiozeroRelay(Relay):
    def __init__(self):
        from gpiozero import OutputDevice
        self._dev = OutputDevice(
            config.RELAY_PIN,
            active_high=config.RELAY_ACTIVE_HIGH,
            initial_value=False,
        )

    def on(self) -> None:
        self._dev.on()

    def off(self) -> None:
        self._dev.off()


class StubRelay(Relay):
    def on(self) -> None:
        log.info("[stub relay] CLOSED (treat button bridged)")

    def off(self) -> None:
        log.info("[stub relay] open")


def make_relay(simulate: bool) -> Relay:
    if simulate or not gpio_available():
        log.warning("Using stub relay (no GPIO)")
        return StubRelay()
    return GpiozeroRelay()


# --- Hall sensor ----------------------------------------------------------

class HallSensor:
    """Owns the gpiozero Button (or the simulator) so it isn't garbage-collected."""

    def __init__(self, on_pulse: Callable[[], None], simulate: bool):
        self._on_pulse = on_pulse
        self._button = None
        self._sim = None

        if simulate or not gpio_available():
            log.warning("Using pulse simulator (no GPIO)")
            self._sim = PulseSimulator(on_pulse)
            self._sim.start()
        else:
            from gpiozero import Button
            # pull_up=True: A3144 open-collector output idles HIGH via the
            # external 10k pull-up and is pulled LOW when the magnet passes.
            #
            # bounce_time must be None: under the lgpio pin factory it maps to
            # kernel debounce, whose semantics are "the level must be STABLE
            # for the whole period before the edge is reported". The Hall LOW
            # pulse is only a few ms at running speed, so bounce_time=20ms
            # silently swallowed real pulses (module LED lit, no callback).
            # Double-trigger rejection is handled in software by
            # SpeedTracker.on_pulse via PULSE_DEBOUNCE_MS.
            self._button = Button(
                config.HALL_PIN,
                pull_up=True,
                bounce_time=None,
            )
            self._button.when_pressed = on_pulse

    def close(self) -> None:
        if self._sim:
            self._sim.stop()
        if self._button:
            self._button.close()


class PulseSimulator:
    """
    Fakes a cat that sprints in bursts, so the dashboard/DB can be developed
    off-Pi. Generates pulse trains with realistic-ish speeds and idle gaps.
    """

    def __init__(self, on_pulse: Callable[[], None]):
        self._on_pulse = on_pulse
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="pulse-sim", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Idle between runs.
            if self._stop.wait(random.uniform(4.0, 10.0)):
                return
            # One run: ramp up to a peak speed, hold, ramp down.
            peak_mph = random.uniform(4.0, 12.0)
            steps = random.randint(15, 40)
            for i in range(steps):
                if self._stop.is_set():
                    return
                # Triangle speed profile across the run.
                frac = 1.0 - abs((i / steps) * 2 - 1)
                mph = max(1.0, peak_mph * (0.3 + 0.7 * frac))
                mps = mph / config.MPS_TO_MPH
                interval = config.DISTANCE_PER_PULSE_M / mps
                self._on_pulse()
                if self._stop.wait(interval):
                    return
