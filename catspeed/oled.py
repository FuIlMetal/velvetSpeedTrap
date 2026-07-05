"""
SSD1306 OLED display loop.

State-aware, because the cat is idle most of the time:
  - RUNNING  -> giant live speed (plus today/record)
  - IDLE     -> record to beat, today's peak, time since last run
Dims the panel after a stretch of no running to limit OLED burn-in; wakes back
to full brightness on the next pulse. Falls back to console output if
luma.oled / the panel isn't present.
"""

import logging
import threading
import time
from typing import Callable, Dict

from . import config
from .util import format_ago

log = logging.getLogger("catspeed.oled")

# state dict: {"current_mph", "peak_today", "all_time_peak", "last_run_epoch"}
StateFn = Callable[[], Dict[str, float]]


def _load_fonts():
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return (
                ImageFont.truetype(path, 32),  # big
                ImageFont.truetype(path, 11),  # small
                ImageFont.truetype(path, 10),  # tiny
            )
        except (OSError, IOError):
            continue
    log.warning("No TrueType font found; install with: "
                "sudo apt install fonts-dejavu-core")
    default = ImageFont.load_default()
    return default, default, default


class OledDisplay:
    def __init__(self, get_state: StateFn, simulate: bool = False):
        self.get_state = get_state
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="oled", daemon=True)
        self._device = None
        self._big = self._small = self._tiny = None
        self._contrast = None  # last contrast we set; avoids redundant I2C writes

        if not simulate:
            try:
                from luma.core.interface.serial import i2c
                from luma.oled.device import ssd1306
                serial = i2c(port=config.OLED_I2C_PORT, address=config.OLED_I2C_ADDR)
                self._device = ssd1306(serial)
                self._big, self._small, self._tiny = _load_fonts()
            except Exception as exc:  # no panel / no luma -> console fallback
                log.warning("OLED unavailable (%s); using console fallback", exc)
                self._device = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _set_contrast(self, level: int) -> None:
        if self._device is None or level == self._contrast:
            return
        try:
            self._device.contrast(max(0, min(255, level)))
            self._contrast = level
        except Exception:
            pass

    def _run(self) -> None:
        period = 1.0 / max(1.0, config.OLED_REFRESH_HZ)
        last_active = time.monotonic()  # last time she was running
        last_console = 0.0

        while not self._stop.is_set():
            state = self.get_state()
            running = state["current_mph"] > 0.0
            now = time.monotonic()
            if running:
                last_active = now

            if self._device is not None:
                # Brightness: full while running / recently active, dim once idle.
                idle_for = now - last_active
                if running or idle_for < config.OLED_DIM_AFTER_S:
                    self._set_contrast(config.OLED_FULL_CONTRAST)
                else:
                    self._set_contrast(config.OLED_DIM_CONTRAST)

                if running:
                    self._render_running(state)
                else:
                    self._render_idle(state)
            else:
                now_wall = time.monotonic()
                if now_wall - last_console >= 1.0:
                    last_console = now_wall
                    if running:
                        log.info("RUNNING %5.2f mph | today %.2f | record %.2f",
                                 state["current_mph"], state["peak_today"],
                                 state["all_time_peak"])
                    else:
                        log.info("idle | record %.2f | today %.2f | last run %s",
                                 state["all_time_peak"], state["peak_today"],
                                 format_ago(state.get("last_run_epoch")))

            if self._stop.wait(period):
                break

    def _right(self, draw, y, text, font, right=128):
        w = draw.textlength(text, font=font)
        draw.text((right - w, y), text, font=font, fill="white")

    def _render_running(self, state: Dict[str, float]) -> None:
        # Two-color panel: rows 0-15 are yellow, 16-63 blue. Keep the big
        # number fully below y=16 so it never straddles the color split.
        from luma.core.render import canvas
        with canvas(self._device) as draw:
            draw.text((0, 2), "VELVET", font=self._small, fill="white")
            self._right(draw, 2, "mph", self._small)
            speed = f"{state['current_mph']:.2f}"
            w = draw.textlength(speed, font=self._big)
            draw.text(((128 - w) // 2, 17), speed, font=self._big, fill="white")
            draw.text((0, 53), f"today {state['peak_today']:.2f}", font=self._tiny, fill="white")
            self._right(draw, 53, f"top {state['all_time_peak']:.2f}", self._tiny)

    def _render_idle(self, state: Dict[str, float]) -> None:
        from luma.core.render import canvas
        ago = format_ago(state.get("last_run_epoch"))
        with canvas(self._device) as draw:
            draw.text((0, 2), "RECORD", font=self._small, fill="white")
            self._right(draw, 2, "mph", self._small)
            rec = f"{state['all_time_peak']:.2f}"
            w = draw.textlength(rec, font=self._big)
            draw.text(((128 - w) // 2, 17), rec, font=self._big, fill="white")
            draw.text((0, 53), f"today {state['peak_today']:.2f}", font=self._tiny, fill="white")
            self._right(draw, 53, ago, self._tiny)
