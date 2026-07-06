"""
Flask + Socket.IO dashboard.

- GET  /                 leaderboard + live speed gauge
- GET  /api/state        current speed and peaks (JSON)
- GET  /api/top?n=10     top runs by peak speed (JSON)
- GET  /api/recent?n=20  most recent runs (JSON)
- GET  /api/daily?days=84  per-day run count / avg / peak (JSON)
- DELETE /api/runs       {"ids": [1,2]} or {"all": true}  remove runs
- POST /api/threshold    {"mph": 8.0}      set treat threshold
- POST /api/cooldown     {"seconds": 60}   set treat cooldown
- POST /api/test_treat   manually dispense one treat
- WS   "speed"           live speed broadcasts
- WS   "run"             a completed run was logged
- WS   "treat"           a treat was dispensed

async_mode="threading" so the sensor/OLED background threads can emit without
eventlet/gevent — friendlier on a Pi Zero 2 W.
"""

import logging
import threading
import time
from datetime import datetime
from math import pi
from typing import Callable, Dict, List, Optional

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from . import config, db
from .util import format_ago

log = logging.getLogger("catspeed.web")

socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")


class Calibrator:
    """
    Web port of catspeed.calibrate — records raw Hall pulses while a session
    is active and streams them to the dashboard over Socket.IO.

    Modes:
      monitor : live per-pulse dt + implied mph (calibrate.py `monitor`)
      revs    : count pulses across N hand-turned revolutions (`revs`)

    main.py feeds every raw pulse in here; when no session is active this is
    a single lock-free-ish check and return, so it costs nothing in normal
    operation.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.mode: Optional[str] = None
        self.count = 0
        self.last: Optional[float] = None
        self.peak = 0.0
        self.target_revs = 0
        self.started_at = 0.0

    # -- pulse path (sensor callback thread) ------------------------------

    def on_pulse(self) -> None:
        if self.mode is None:          # fast path: not calibrating
            return
        now = time.monotonic()
        with self._lock:
            if self.mode is None:
                return
            self.count += 1
            n = self.count
            last = self.last
            self.last = now
            mode = self.mode

        payload = {"n": n, "mode": mode}
        if last is not None:
            dt_ms = (now - last) * 1000.0
            payload["dt_ms"] = round(dt_ms, 1)
            if dt_ms < config.PULSE_DEBOUNCE_MS:
                payload["debounced"] = True
            else:
                mph = (config.DISTANCE_PER_PULSE_M / (now - last)) * config.MPS_TO_MPH
                payload["mph"] = round(mph, 2)
                payload["implausible"] = mph > config.MAX_PLAUSIBLE_MPH
                with self._lock:
                    self.peak = max(self.peak, mph)
                    payload["peak"] = round(self.peak, 2)
        socketio.emit("cal_pulse", payload)

    # -- session control (Flask request threads) --------------------------

    def start(self, mode: str, target_revs: int = 0) -> dict:
        with self._lock:
            self.mode = mode
            self.count = 0
            self.last = None
            self.peak = 0.0
            self.target_revs = target_revs
            self.started_at = time.time()
        return self.state()

    def stop(self) -> dict:
        with self._lock:
            mode, count, peak, target = self.mode, self.count, self.peak, self.target_revs
            self.mode = None
        result = {"mode": mode, "pulses": count, "peak_mph": round(peak, 2)}
        if mode == "revs" and target > 0:
            result.update(self._analyze_revs(count, target))
        return result

    def state(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "pulses": self.count,
                "peak_mph": round(self.peak, 2),
                "target_revs": self.target_revs,
            }

    @staticmethod
    def _analyze_revs(measured: int, target: int) -> dict:
        """Same logic as calibrate.cmd_revs, returned as data for the UI."""
        expected = target * config.MAGNETS_PER_REV
        out = {"target_revs": target, "expected_pulses": expected}
        if measured == 0:
            out["verdict"] = "fail"
            out["message"] = ("No pulses — check wiring, pin (CATSPEED_HALL_PIN), "
                              "magnet gap (3-5 mm), and sensor flat-face orientation.")
            return out
        per_rev = measured / target
        out["pulses_per_rev"] = round(per_rev, 2)
        nearest = round(per_rev)
        if abs(per_rev - nearest) < 0.15 and nearest >= 1:
            if nearest != config.MAGNETS_PER_REV:
                out["verdict"] = "mismatch"
                out["message"] = (f"Looks like {nearest} pulse(s)/rev but config says "
                                  f"{config.MAGNETS_PER_REV}. Set "
                                  f"CATSPEED_MAGNETS_PER_REV={nearest}")
            else:
                out["verdict"] = "ok"
                out["message"] = "Matches configured magnets/rev. Sensor counting looks good."
        else:
            out["verdict"] = "noisy"
            out["message"] = ("Non-integer pulses/rev suggests missed or double pulses. "
                              "Re-check the magnet gap and debounce "
                              "(CATSPEED_PULSE_DEBOUNCE_MS).")
        return out


calibrator = Calibrator()

# Wired up by create_app(); set by main.py.
_ctx: Dict[str, object] = {}


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["started_at_iso"] = datetime.fromtimestamp(d["started_at"]).isoformat(timespec="seconds")
    d["started_at_human"] = datetime.fromtimestamp(d["started_at"]).strftime("%b %d, %I:%M %p")
    d["treat_given"] = bool(d["treat_given"])
    return d


def _rows(rows) -> List[dict]:
    return [_row_to_dict(r) for r in rows]


def create_app(
    tracker,
    treat,
    get_state: Callable[[], Dict[str, float]],
    refresh_state: Optional[Callable[[], None]] = None,
) -> Flask:
    app = Flask(__name__)
    _ctx["tracker"] = tracker
    _ctx["treat"] = treat
    _ctx["get_state"] = get_state
    _ctx["refresh_state"] = refresh_state

    @app.route("/")
    def index():
        last_run_epoch = db.last_run_time()
        return render_template(
            "dashboard.html",
            top=_rows(db.top_n(10)),
            recent=_rows(db.recent_runs(10)),
            all_time=db.all_time_peak(),
            peak_today=db.peak_today(),
            run_count=db.run_count(),
            treats_today=db.treats_today(),
            threshold=treat.threshold_mph,
            cooldown=treat.cooldown_s,
            last_run_epoch=last_run_epoch,
            last_run_ago=format_ago(last_run_epoch),
        )

    @app.route("/calibrate")
    def calibrate_page():
        return render_template(
            "calibrate.html",
            wheel={
                "diameter_m": config.WHEEL_DIAMETER_M,
                "circumference_m": config.WHEEL_CIRCUMFERENCE,
                "magnets_per_rev": config.MAGNETS_PER_REV,
                "distance_per_pulse_m": config.DISTANCE_PER_PULSE_M,
                "debounce_ms": config.PULSE_DEBOUNCE_MS,
                "max_plausible_mph": config.MAX_PLAUSIBLE_MPH,
                "override": db.get_setting("wheel_diameter_m") is not None,
            },
        )

    @app.route("/api/state")
    def api_state():
        state = get_state()
        last_run_epoch = state.get("last_run_epoch") or 0.0
        return jsonify(
            {
                **state,
                "running": state["current_mph"] > 0.0,
                "last_run_ago": format_ago(last_run_epoch),
                "threshold_mph": treat.threshold_mph,
                "cooldown_s": treat.cooldown_s,
                "cooldown_remaining_s": round(treat.cooldown_remaining(), 1),
            }
        )

    @app.route("/api/top")
    def api_top():
        n = request.args.get("n", default=10, type=int)
        return jsonify(_rows(db.top_n(n)))

    @app.route("/api/recent")
    def api_recent():
        n = request.args.get("n", default=20, type=int)
        return jsonify(_rows(db.recent_runs(n)))

    @app.route("/api/daily")
    def api_daily():
        days = request.args.get("days", default=84, type=int)
        days = max(1, min(days, 366))
        rows = [
            {
                "day": r["day"],                      # 'YYYY-MM-DD' local
                "runs": r["runs"],
                "avg_mph": round(r["avg_mph"] or 0.0, 2),
                "peak_mph": round(r["peak_mph"] or 0.0, 2),
                "total_s": round(r["total_s"] or 0.0, 1),
                "treats": r["treats"] or 0,
            }
            for r in db.daily_activity(days)
        ]
        return jsonify({"days": days, "activity": rows})

    def _stats_payload() -> dict:
        return {
            "run_count": db.run_count(),
            "all_time": round(db.all_time_peak(), 2),
            "peak_today": round(db.peak_today(), 2),
            "treats_today": db.treats_today(),
        }

    @app.route("/api/runs", methods=["DELETE"])
    def api_delete_runs():
        """Remove runs, then recompute cached peaks (OLED / /api/state).

        Body: {"ids": [1, 2, ...]}  or  {"all": true}
        """
        body = request.get_json(force=True) or {}
        if body.get("all") is True:
            deleted = db.delete_all_runs()
        else:
            ids = body.get("ids")
            if not isinstance(ids, list) or not ids:
                return jsonify({"ok": False,
                                "error": "expected {'ids': [..]} or {'all': true}"}), 400
            try:
                ids = [int(i) for i in ids]
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": "ids must be integers"}), 400
            deleted = db.delete_runs(ids)

        # The deleted run(s) may have held the record — refresh the in-memory
        # peak cache and tell any open dashboards to re-pull their tables.
        refresh = _ctx.get("refresh_state")
        if callable(refresh):
            refresh()
        stats = _stats_payload()
        socketio.emit("runs_changed", {"deleted": deleted, "stats": stats})
        log.info("Deleted %d run(s) via dashboard", deleted)
        return jsonify({"ok": True, "deleted": deleted, "stats": stats})

    @app.route("/api/threshold", methods=["POST"])
    def api_threshold():
        try:
            mph = float(request.get_json(force=True)["mph"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "expected {'mph': number}"}), 400
        treat.set_threshold(mph)
        return jsonify({"ok": True, "threshold_mph": treat.threshold_mph})

    @app.route("/api/cooldown", methods=["POST"])
    def api_cooldown():
        try:
            seconds = float(request.get_json(force=True)["seconds"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"ok": False, "error": "expected {'seconds': number}"}), 400
        treat.set_cooldown(seconds)
        return jsonify({"ok": True, "cooldown_s": treat.cooldown_s})

    @app.route("/api/test_treat", methods=["POST"])
    def api_test_treat():
        treat.dispense()
        return jsonify({"ok": True})

    # --- calibration (web port of catspeed.calibrate) --------------------

    @app.route("/api/calibrate/start", methods=["POST"])
    def api_cal_start():
        body = request.get_json(force=True) or {}
        mode = body.get("mode")
        if mode not in ("monitor", "revs"):
            return jsonify({"ok": False, "error": "mode must be 'monitor' or 'revs'"}), 400
        revs = int(body.get("revs", 10)) if mode == "revs" else 0
        if mode == "revs" and revs < 1:
            return jsonify({"ok": False, "error": "revs must be >= 1"}), 400
        return jsonify({"ok": True, **calibrator.start(mode, revs)})

    @app.route("/api/calibrate/stop", methods=["POST"])
    def api_cal_stop():
        return jsonify({"ok": True, **calibrator.stop()})

    @app.route("/api/calibrate/state")
    def api_cal_state():
        return jsonify(calibrator.state())

    @app.route("/api/calibrate/circ", methods=["POST"])
    def api_cal_circ():
        """Pure math: measured circumference <-> diameter + the env line to set."""
        body = request.get_json(force=True) or {}
        circ = body.get("circumference")
        dia = body.get("diameter")
        try:
            if circ is not None:
                circ = float(circ)
                dia = circ / pi
            elif dia is not None:
                dia = float(dia)
                circ = dia * pi
            else:
                raise ValueError
            if dia <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"ok": False,
                            "error": "expected {'circumference': m} or {'diameter': m}"}), 400
        return jsonify({
            "ok": True,
            "diameter_m": round(dia, 4),
            "diameter_in": round(dia / 0.0254, 1),
            "circumference_m": round(circ, 4),
            "env_line": f"CATSPEED_WHEEL_DIAMETER_M={dia:.4f}",
            "current_diameter_m": config.WHEEL_DIAMETER_M,
        })

    def _wheel_payload() -> dict:
        return {
            "diameter_m": round(config.WHEEL_DIAMETER_M, 4),
            "diameter_in": round(config.WHEEL_DIAMETER_M / 0.0254, 1),
            "circumference_m": round(config.WHEEL_CIRCUMFERENCE, 4),
            "distance_per_pulse_m": round(config.DISTANCE_PER_PULSE_M, 4),
            "magnets_per_rev": config.MAGNETS_PER_REV,
            "debounce_ms": config.PULSE_DEBOUNCE_MS,
            "override": db.get_setting("wheel_diameter_m") is not None,
            "boot_diameter_m": round(config.BOOT_WHEEL_DIAMETER_M, 4),
        }

    @app.route("/api/wheel", methods=["GET"])
    def api_wheel_get():
        return jsonify({"ok": True, **_wheel_payload()})

    @app.route("/api/wheel", methods=["POST"])
    def api_wheel_set():
        """Apply a new diameter (or circumference) live and persist it.

        Takes effect on the next pulse; survives restarts via the settings
        table, which beats the systemd Environment= line at boot.
        """
        body = request.get_json(force=True) or {}
        circ = body.get("circumference")
        dia = body.get("diameter")
        try:
            if circ is not None:
                dia = float(circ) / pi
            elif dia is not None:
                dia = float(dia)
            else:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"ok": False,
                            "error": "expected {'circumference': m} or {'diameter': m}"}), 400
        if not (0.1 <= dia <= 3.0):
            return jsonify({"ok": False,
                            "error": f"diameter {dia:.4f} m outside sane range 0.1-3.0 m "
                                     "(values are in metres)"}), 400
        config.apply_wheel_diameter(dia)
        db.set_setting("wheel_diameter_m", f"{dia:.4f}")
        return jsonify({"ok": True, **_wheel_payload()})

    @app.route("/api/wheel", methods=["DELETE"])
    def api_wheel_clear():
        """Remove the runtime override; revert to the env/default diameter."""
        db.delete_setting("wheel_diameter_m")
        config.apply_wheel_diameter(config.BOOT_WHEEL_DIAMETER_M)
        return jsonify({"ok": True, **_wheel_payload()})

    @socketio.on("connect")
    def on_connect():
        emit("speed", {"mph": tracker.snapshot_speed()})

    socketio.init_app(app)
    return app


# --- Broadcast helpers (called from background threads) -------------------

def broadcast_speed(mph: float) -> None:
    socketio.emit("speed", {"mph": round(mph, 2)})


def broadcast_run(record) -> None:
    socketio.emit(
        "run",
        {
            "peak_mph": record.peak_mph,
            "avg_mph": record.avg_mph,
            "duration_s": record.duration_s,
            "revolutions": record.revolutions,
            "treat_given": record.treat_given,
        },
    )


def broadcast_treat() -> None:
    socketio.emit("treat", {"at": datetime.now().isoformat(timespec="seconds")})
