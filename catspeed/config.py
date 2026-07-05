"""
Central configuration for the Cat Speed Trap.

Every value can be overridden with an environment variable of the same name,
e.g.  CATSPEED_WHEEL_DIAMETER_M=0.32  python -m catspeed.main
so you can tune things without editing code on the Pi.
"""

import os
from math import pi


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- Wheel geometry -------------------------------------------------------
# Measure yours precisely (tape a string to the rim, mark one revolution,
# measure it flat). A 1 cm error is ~3% error on every reading.
WHEEL_DIAMETER_M = _env_float("CATSPEED_WHEEL_DIAMETER_M", 0.30)  # 12" ~= 0.305 m
WHEEL_CIRCUMFERENCE = pi * WHEEL_DIAMETER_M

# Number of magnets on the wheel. With N evenly-spaced magnets each pulse
# covers circumference / N, so the per-pulse distance is divided accordingly.
MAGNETS_PER_REV = _env_int("CATSPEED_MAGNETS_PER_REV", 1)
DISTANCE_PER_PULSE_M = WHEEL_CIRCUMFERENCE / MAGNETS_PER_REV

# --- GPIO pins (BCM numbering) -------------------------------------------
HALL_PIN = _env_int("CATSPEED_HALL_PIN", 17)
RELAY_PIN = _env_int("CATSPEED_RELAY_PIN", 23)
# Most cheap relay boards are active-LOW (energise on a LOW signal).
# Set CATSPEED_RELAY_ACTIVE_HIGH=1 if yours is active-HIGH.
RELAY_ACTIVE_HIGH = bool(_env_int("CATSPEED_RELAY_ACTIVE_HIGH", 0))

# --- OLED -----------------------------------------------------------------
OLED_I2C_ADDR = int(_env_str("CATSPEED_OLED_I2C_ADDR", "0x3C"), 0)
OLED_I2C_PORT = _env_int("CATSPEED_OLED_I2C_PORT", 1)
OLED_REFRESH_HZ = _env_float("CATSPEED_OLED_REFRESH_HZ", 5.0)
# Burn-in protection: she's idle most of the time, so dim the panel after a
# while of no running. Contrast is 0-255; wakes back to full on the next pulse.
OLED_DIM_AFTER_S = _env_float("CATSPEED_OLED_DIM_AFTER_S", 180.0)
OLED_FULL_CONTRAST = _env_int("CATSPEED_OLED_FULL_CONTRAST", 255)
OLED_DIM_CONTRAST = _env_int("CATSPEED_OLED_DIM_CONTRAST", 8)

# --- Timing / signal conditioning ----------------------------------------
PULSE_DEBOUNCE_MS = _env_float("CATSPEED_PULSE_DEBOUNCE_MS", 20.0)  # ignore closer pulses
IDLE_TIMEOUT_S = _env_float("CATSPEED_IDLE_TIMEOUT_S", 3.0)        # gap that ends a run
RUN_MIN_DURATION_S = _env_float("CATSPEED_RUN_MIN_DURATION_S", 1.0)  # ignore twitches
TICK_HZ = _env_float("CATSPEED_TICK_HZ", 5.0)                       # idle/run-detect loop
SPEED_SMOOTHING_SAMPLES = _env_int("CATSPEED_SPEED_SMOOTHING_SAMPLES", 3)

# A physically impossible reading -> reject (e.g. electrical noise double-pulse).
MAX_PLAUSIBLE_MPH = _env_float("CATSPEED_MAX_PLAUSIBLE_MPH", 25.0)

# --- Treat dispensing -----------------------------------------------------
DEFAULT_THRESHOLD_MPH = _env_float("CATSPEED_DEFAULT_THRESHOLD_MPH", 8.0)
DEFAULT_COOLDOWN_S = _env_float("CATSPEED_DEFAULT_COOLDOWN_S", 60.0)
TREAT_PULSE_MS = _env_float("CATSPEED_TREAT_PULSE_MS", 250.0)  # how long relay stays closed

# --- Web ------------------------------------------------------------------
WEB_HOST = _env_str("CATSPEED_WEB_HOST", "0.0.0.0")
WEB_PORT = _env_int("CATSPEED_WEB_PORT", 5000)

# --- Storage --------------------------------------------------------------
# Default to a db/ folder next to the package so it works off-Pi too.
_DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "speed.db")
DB_PATH = _env_str("CATSPEED_DB_PATH", _DEFAULT_DB)

# Conversion constant
MPS_TO_MPH = 2.23694
