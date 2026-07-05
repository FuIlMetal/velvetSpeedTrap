# Cat Speed Trap 🐈‍⬛💨

Raspberry Pi system that measures the cat's running-wheel speed from a Hall
sensor, shows it on an OLED, serves a live web leaderboard, and drops a treat
when she hits a target speed.

See [cat_speed_trap_plan.md](cat_speed_trap_plan.md) for the hardware build,
wiring, and shopping list. This README covers the **software**.

## Layout

```
catspeed/
  config.py     constants (all overridable via CATSPEED_* env vars)
  models.py     RunRecord dataclass
  db.py         SQLite storage (runs + settings)
  sensor.py     SpeedTracker — pulse timing, smoothing, run detection
  treat.py      TreatDispenser — threshold + cooldown + relay pulse
  hardware.py   gpiozero/luma backends, with stubs + a pulse simulator
  oled.py       SSD1306 display loop (console fallback off-Pi)
  state.py      cached peaks shared by OLED + web
  web.py        Flask + Socket.IO dashboard and JSON API
  main.py       wires it all together
  templates/dashboard.html
deploy/catspeed.service   systemd unit
```

## Run it

**On the Pi (real hardware):**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m catspeed.main
```
Then open `http://<pi-ip>:5000/`.

**On your laptop (no hardware) — develop the dashboard with fake runs:**
```bash
pip install Flask Flask-SocketIO simple-websocket
python -m catspeed.main --simulate
```
`--simulate` feeds the tracker a fake cat that sprints in bursts, uses a stub
relay, and prints the OLED to the console. Real DB, real dashboard.

## Configuration

Everything in [catspeed/config.py](catspeed/config.py) reads an environment
variable of the same name prefixed with `CATSPEED_`. The ones you'll actually
touch:

| Env var | Default | What |
|---|---|---|
| `CATSPEED_WHEEL_DIAMETER_M` | `0.30` | **Measure this precisely** — drives all speeds |
| `CATSPEED_MAGNETS_PER_REV` | `1` | Set to `2` if you add a second magnet |
| `CATSPEED_HALL_PIN` | `17` | Hall sensor BCM pin |
| `CATSPEED_RELAY_PIN` | `23` | Relay BCM pin |
| `CATSPEED_RELAY_ACTIVE_HIGH` | `0` | Set `1` if your relay triggers on HIGH |
| `CATSPEED_DEFAULT_THRESHOLD_MPH` | `8.0` | Initial treat threshold |
| `CATSPEED_DEFAULT_COOLDOWN_S` | `60` | Min seconds between treats |
| `CATSPEED_DB_PATH` | `data/speed.db` | SQLite file |

Threshold and cooldown are also editable live from the dashboard and persist
in the `settings` table (they win over the env defaults once set).

## API

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/` | — | dashboard HTML |
| GET | `/api/state` | — | current speed, peaks, threshold, cooldown |
| GET | `/api/top?n=10` | — | top runs by peak mph |
| GET | `/api/recent?n=20` | — | most recent runs |
| POST | `/api/threshold` | `{"mph": 8.0}` | set + persist threshold |
| POST | `/api/cooldown` | `{"seconds": 60}` | set + persist cooldown |
| POST | `/api/test_treat` | — | dispense one treat now (ignores cooldown) |

Socket.IO events pushed to the browser: `speed`, `run`, `treat`.

## Run as a service

```bash
sudo cp deploy/catspeed.service /etc/systemd/system/
sudo systemctl enable --now catspeed
journalctl -u catspeed -f
```

## Build-sequence mapping (plan §7)

- **Phase 1–2 (sensor + speed math):** `python -m catspeed.main -v` and spin
  the wheel by hand — watch the console log the live mph and logged runs.
- **Phase 3 (OLED):** plug in the SSD1306; `oled.py` picks it up automatically.
- **Phase 4 (DB + dashboard):** already live at `:5000` — collect a few days of
  baseline data and read the leaderboard before ordering the feeder.
- **Phase 5–8 (feeder):** wire the relay, use the dashboard's **Test treat**
  button (`/api/test_treat`) to confirm one click = one treat, then set the
  threshold from your baseline data.
