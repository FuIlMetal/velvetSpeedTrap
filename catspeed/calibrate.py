"""
Calibration & sensor-check helper.

    python -m catspeed.calibrate monitor          # live pulse + speed monitor
    python -m catspeed.calibrate monitor --simulate
    python -m catspeed.calibrate revs --revs 10   # verify pulses-per-revolution
    python -m catspeed.calibrate circ --circumference 0.96   # -> diameter + env line
    python -m catspeed.calibrate circ --diameter 0.305       # -> circumference + env line

Honest note on circumference: you can't derive it from revolutions alone — a
pulse count has no built-in distance reference. So measure it physically (tape
a string to the rim, mark one full revolution, lay it flat and measure — plan
§8). The `circ` command just converts that measurement into the exact config
value the code wants and prints the env line to set. The `revs` command then
confirms the sensor counts that circumference once per turn (no missed/double
pulses), and `monitor` lets you watch live speed for a final sanity check.
"""

import argparse
import threading
import time
from math import pi

from . import config
from .hardware import HallSensor


def _fmt(mph: float) -> str:
    return f"{mph:6.2f}"


def cmd_monitor(args) -> None:
    state = {"count": 0, "last": None, "peak": 0.0}
    lock = threading.Lock()

    def on_pulse():
        now = time.monotonic()
        with lock:
            state["count"] += 1
            n = state["count"]
            last = state["last"]
            state["last"] = now
        if last is None:
            print(f"pulse {n:4d}   (first — no interval yet)")
            return
        dt = now - last
        if dt * 1000.0 < config.PULSE_DEBOUNCE_MS:
            print(f"pulse {n:4d}   dt={dt*1000:6.1f} ms   <debounce, would be ignored>")
            return
        mph = (config.DISTANCE_PER_PULSE_M / dt) * config.MPS_TO_MPH
        with lock:
            state["peak"] = max(state["peak"], mph)
            peak = state["peak"]
        flag = "  !! exceeds MAX_PLAUSIBLE" if mph > config.MAX_PLAUSIBLE_MPH else ""
        print(f"pulse {n:4d}   dt={dt*1000:6.1f} ms   {_fmt(mph)} mph   (peak {_fmt(peak)}){flag}")

    print(f"Wheel: diameter={config.WHEEL_DIAMETER_M:.3f} m  "
          f"circumference={config.WHEEL_CIRCUMFERENCE:.3f} m  "
          f"magnets/rev={config.MAGNETS_PER_REV}  "
          f"distance/pulse={config.DISTANCE_PER_PULSE_M:.4f} m")
    print("Spin the wheel. Ctrl-C to stop.\n")

    hall = HallSensor(on_pulse, simulate=args.simulate)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        hall.close()
    print(f"\nTotal pulses: {state['count']}   peak: {_fmt(state['peak'])} mph")


def cmd_revs(args) -> None:
    target = args.revs
    expected = target * config.MAGNETS_PER_REV
    count = {"n": 0}
    lock = threading.Lock()

    def on_pulse():
        with lock:
            count["n"] += 1

    print(f"Pulses-per-revolution check (magnets/rev configured = {config.MAGNETS_PER_REV}).")
    hall = HallSensor(on_pulse, simulate=args.simulate)
    try:
        input(f"Get ready to rotate the wheel EXACTLY {target} full revolutions, "
              f"then press Enter to start... ")
        with lock:
            count["n"] = 0
        input(f"Counting now — rotate {target} revolutions slowly and steadily, "
              f"then press Enter to stop... ")
        measured = count["n"]
    finally:
        hall.close()

    print(f"\nMeasured pulses: {measured}   (expected ~{expected} for {target} revs)")
    if measured == 0:
        print("No pulses — check wiring, pin (CATSPEED_HALL_PIN), magnet gap (3-5 mm), "
              "and sensor flat-face orientation.")
        return
    per_rev = measured / target
    print(f"Pulses per revolution: {per_rev:.2f}")
    nearest = round(per_rev)
    if abs(per_rev - nearest) < 0.15 and nearest >= 1:
        if nearest != config.MAGNETS_PER_REV:
            print(f"-> Looks like {nearest} pulse(s)/rev. Set "
                  f"CATSPEED_MAGNETS_PER_REV={nearest}")
        else:
            print("-> Matches your configured magnets/rev. Sensor counting looks good.")
    else:
        print("-> Non-integer pulses/rev suggests missed or double pulses. "
              "Re-check the magnet gap and debounce (CATSPEED_PULSE_DEBOUNCE_MS).")


def cmd_circ(args) -> None:
    if args.circumference is not None:
        circ = args.circumference
        dia = circ / pi
    elif args.diameter is not None:
        dia = args.diameter
        circ = dia * pi
    else:
        raise SystemExit("Provide --circumference <m> or --diameter <m>")
    print(f"Diameter:      {dia:.4f} m  ({dia*100:.1f} cm, {dia/0.0254:.1f} in)")
    print(f"Circumference: {circ:.4f} m  ({circ*100:.1f} cm)")
    print("\nThe code is configured by DIAMETER. Set:")
    print(f"    CATSPEED_WHEEL_DIAMETER_M={dia:.4f}")
    print("(add it to deploy/catspeed.service or export it before running)")


def main() -> None:
    p = argparse.ArgumentParser(description="Cat Speed Trap calibration helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("monitor", help="live pulse + speed monitor")
    m.add_argument("--simulate", action="store_true")
    m.set_defaults(func=cmd_monitor)

    r = sub.add_parser("revs", help="verify pulses per revolution")
    r.add_argument("--revs", type=int, default=10)
    r.add_argument("--simulate", action="store_true")
    r.set_defaults(func=cmd_revs)

    c = sub.add_parser("circ", help="convert measured circumference/diameter to config")
    c.add_argument("--circumference", type=float, help="measured circumference in metres")
    c.add_argument("--diameter", type=float, help="measured diameter in metres")
    c.set_defaults(func=cmd_circ)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
