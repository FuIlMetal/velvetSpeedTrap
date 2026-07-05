"""
Flask + Socket.IO dashboard.

- GET  /                 leaderboard + live speed gauge
- GET  /api/state        current speed and peaks (JSON)
- GET  /api/top?n=10     top runs by peak speed (JSON)
- GET  /api/recent?n=20  most recent runs (JSON)
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
from datetime import datetime
from typing import Callable, Dict, List

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from . import db
from .util import format_ago

log = logging.getLogger("catspeed.web")

socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")

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


def create_app(tracker, treat, get_state: Callable[[], Dict[str, float]]) -> Flask:
    app = Flask(__name__)
    _ctx["tracker"] = tracker
    _ctx["treat"] = treat
    _ctx["get_state"] = get_state

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
