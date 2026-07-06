"""
Cat Speed Trap entry point — wires the sensor, dispenser, OLED and web server
into one process.

    python -m catspeed.main                 # on the Pi, real hardware
    python -m catspeed.main --simulate      # anywhere, fake pulses + stubs

Threads:
  - gpiozero callback thread  -> SpeedTracker.on_pulse
  - tick loop (TICK_HZ)       -> SpeedTracker.tick (run detection / idle)
  - OLED loop (OLED_REFRESH_HZ)
  - Socket.IO / Flask         -> main thread (socketio.run)
"""

import argparse
import logging
import threading
import time

from . import config, db
from .hardware import HallSensor, make_relay
from .oled import OledDisplay
from .sensor import SpeedTracker
from .state import AppState
from .treat import TreatDispenser
from . import web


def _tick_loop(tracker: SpeedTracker, stop: threading.Event) -> None:
    period = 1.0 / max(1.0, config.TICK_HZ)
    while not stop.is_set():
        tracker.tick()
        if stop.wait(period):
            break


def parse_args():
    p = argparse.ArgumentParser(description="Cat Speed Trap")
    p.add_argument("--simulate", action="store_true",
                   help="run without GPIO/OLED hardware (fake pulses + stub relay)")
    p.add_argument("--oled", dest="oled", action="store_true",
                   default=config.OLED_ENABLED,
                   help="enable the OLED loop (default: config.OLED_ENABLED)")
    p.add_argument("--no-oled", dest="oled", action="store_false",
                   help="disable the OLED loop entirely")
    p.add_argument("--host", default=config.WEB_HOST)
    p.add_argument("--port", type=int, default=config.WEB_PORT)
    p.add_argument("--db", default=config.DB_PATH, help="SQLite path")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-14s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("catspeed")

    db.init_db(args.db)
    log.info("Database ready at %s", args.db)

    # Runtime wheel-diameter override (set from the dashboard) beats the
    # env/default value. Clear it from the UI to fall back to the unit's
    # Environment= line.
    _dia_override = db.get_setting_float("wheel_diameter_m", 0.0)
    if _dia_override > 0:
        config.apply_wheel_diameter(_dia_override)
        log.info("Wheel diameter override from settings: %.4f m "
                 "(env/default was %.4f m)", _dia_override, config.BOOT_WHEEL_DIAMETER_M)

    # --- dispenser -------------------------------------------------------
    relay = make_relay(args.simulate)
    treat = TreatDispenser(relay, on_dispense=web.broadcast_treat)
    log.info("Treat: threshold=%.2f mph, cooldown=%.0fs",
             treat.threshold_mph, treat.cooldown_s)

    # --- state cache (peaks for OLED/web) --------------------------------
    # AppState needs the tracker; the tracker's callbacks need AppState and
    # treat. Build a holder so the closures can reach AppState once it exists.
    holder = {}

    def on_speed_update(mph: float) -> None:
        web.broadcast_speed(mph)
        if mph > 0:
            holder["state"].note_peak(mph)
            treat.maybe_dispense(mph)

    def on_run_complete(record) -> None:
        # Attribute a treat to this run if one fired during its window.
        if treat.last_treat_epoch and record.started_at <= treat.last_treat_epoch <= record.ended_at:
            record.treat_given = True
        db.save_run(record)
        holder["state"].refresh_from_db()
        web.broadcast_run(record)
        log.info("Run logged: peak %.2f mph, avg %.2f mph, %.1fs, %d rev%s",
                 record.peak_mph, record.avg_mph, record.duration_s,
                 record.revolutions, " +treat" if record.treat_given else "")

    tracker = SpeedTracker(on_speed_update=on_speed_update,
                           on_run_complete=on_run_complete)
    holder["state"] = AppState(tracker)
    state = holder["state"]

    # --- hardware --------------------------------------------------------
    # Every raw pulse also feeds the web calibrator (a no-op unless a
    # calibration session is active in the dashboard).
    def on_hall_pulse() -> None:
        web.calibrator.on_pulse()
        tracker.on_pulse()

    hall = HallSensor(on_hall_pulse, args.simulate)

    oled = None
    if args.oled:
        oled = OledDisplay(state.snapshot, simulate=args.simulate)
        oled.start()
    else:
        log.info("OLED disabled (enable with --oled or CATSPEED_OLED_ENABLED=1)")

    stop = threading.Event()
    tick_thread = threading.Thread(
        target=_tick_loop, args=(tracker, stop), name="tick", daemon=True
    )
    tick_thread.start()

    # --- web -------------------------------------------------------------
    app = web.create_app(tracker, treat, state.snapshot)

    run_kwargs = {"allow_unsafe_werkzeug": True}
    scheme = "http"
    if config.SSL_CERT and config.SSL_KEY:
        # werkzeug accepts a (certfile, keyfile) tuple; flask-socketio passes
        # extra kwargs straight through in threading mode.
        run_kwargs["ssl_context"] = (config.SSL_CERT, config.SSL_KEY)
        scheme = "https"
    elif config.SSL_CERT or config.SSL_KEY:
        log.warning("Only one of CATSPEED_SSL_CERT / CATSPEED_SSL_KEY is set — "
                    "both are required; serving plain HTTP")
    log.info("Dashboard: %s://%s:%d/", scheme, args.host, args.port)

    try:
        web.socketio.run(app, host=args.host, port=args.port, **run_kwargs)
    except KeyboardInterrupt:
        log.info("Shutting down…")
    finally:
        stop.set()
        if oled is not None:
            oled.stop()
        hall.close()
        try:
            relay.off()
        except Exception:
            pass


if __name__ == "__main__":
    main()
