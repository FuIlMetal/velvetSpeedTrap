# Cat Speed Trap — Project Plan

A Raspberry Pi-based system that measures your cat's running wheel speed, displays it on an OLED, hosts a web leaderboard, and dispenses a treat when she hits a target speed.

---

## 1. System Overview

```
   [Magnet on wheel]                  [Hacked pet feeder]
          |                                   ^
          v                                   | (5V relay trigger)
   [Hall sensor A3144] --GPIO 17-->  [Raspberry Pi Zero 2 W] --GPIO 23--> [Relay module]
                                              |
                                              |--I2C--> [OLED SSD1306]
                                              |
                                              +--WiFi--> [Browser dashboard + leaderboard]
                                                          (Flask + SQLite)
```

**Core loop:**
1. Magnet passes Hall sensor once per wheel revolution → GPIO interrupt
2. Pi calculates speed from time-between-pulses × wheel circumference
3. Speed shown on OLED in real time, broadcast to web dashboard
4. When speed ≥ user-set threshold, relay closes → triggers feeder button → treat drops (with cooldown)
5. Each "run" (activity bracketed by inactivity) written to SQLite for leaderboard

---

## 2. Shopping List

Buy in phases. Don't order the feeder until the sensor + display + dashboard are all working — that way if the project stalls, you haven't bought a feeder you won't use, and by the time you're ready to integrate it you'll know exactly how you want to wire the trigger.

### Phase A — Buy now (sensor + brain + display)
Everything needed to build through Phases 1-4 of the build sequence (sensor smoke test → speed math → OLED → web dashboard + leaderboard).

| Item | Purpose | ~Cost |
|---|---|---|
| Raspberry Pi Zero 2 W (with pre-soldered headers) | Brain | $15 |
| 32GB microSD card (A1 rated) | OS + database | $8 |
| Official Pi 2.5A USB power supply (micro-USB) | Power | $10 |
| A3144 Hall effect sensor (pack of 5) | Wheel revolution detection | $5 |
| Small neodymium magnets (6mm disc, pack of 10+) | Mounts on wheel | $4 |
| 0.96" SSD1306 OLED, I2C, 128x64 (white or blue) | On-wheel speed display | $7 |
| 10kΩ resistor (or a small assorted resistor pack) | Pull-up for Hall sensor | $1-5 |
| Mini breadboard + jumper wires (M-F, M-M, ~40 each) | Prototyping | $8 |

**Phase A subtotal: ~$60**

### Phase B — Buy later (treat dispenser integration)
Order these only after Phase A hardware is working and the dashboard is live.

| Item | Purpose | ~Cost |
|---|---|---|
| **PETGEEK Automatic Dog Treat Dispenser with Button** (Amazon B09H6KHFRM) | Dispenser body + RF remote | $30-40 |
| 1-channel 5V relay module (opto-isolated, active-LOW) | Closes the remote's button contact from Pi GPIO | $4 |
| Spare USB-A to micro-USB cable | Powers the dispenser host off USB instead of C batteries | $3 |
| 3× AAA batteries | For the PETGEEK remote (or skip and splice 4.5V) | $3 |
| Thin hookup wire, 28-30 AWG (red + black) | Soldered across the remote's button contacts | $5 |

**Phase B subtotal: ~$45-55**

> **Why the PETGEEK B09H6KHFRM specifically:** the trigger lives on a separate wireless remote, so we hack the remote (simple — one momentary switch to bridge) and leave the dispenser body factory-stock. The host can be USB-powered, sits next to her food dish, and we hide the remote inside the project enclosure next to the Pi. One press = one portion (calibrate via the adjustable window).

### Optional (any phase)
| Item | Purpose | ~Cost |
|---|---|---|
| Small project enclosure | Tidy install | $8 |
| LED + 220Ω resistor | "Treat dispensed" indicator | $0.50 |
| Soldering iron + solder + flux + heat shrink | If you don't have them | $25-40 |
| Multimeter | Confirms button contacts, debugs power | $15 |

**Estimated total (Phase A + B): ~$105-115**, plus tools if needed.

---

## 3. Wiring Diagram

```
                    Raspberry Pi Zero 2 W (GPIO header, top-down)
                    
                          3.3V  [ 1] [ 2]  5V  ----------+
                  SDA  GPIO2  [ 3] [ 4]  5V             |
                  SCL  GPIO3  [ 5] [ 6]  GND  --------+ |
                       GPIO4  [ 7] [ 8]  GPIO14       | |
                          GND [ 9] [10]  GPIO15       | |
              HALL IN  GPIO17 [11] [12]  GPIO18       | |
                       GPIO27 [13] [14]  GND          | |
                       GPIO22 [15] [16]  GPIO23  -----|-|---- RELAY IN
                          3.3V[17] [18]  GPIO24       | |
                       ...                            | |
                                                      | |
   HALL SENSOR (A3144)                                | |
   flat side facing magnet                            | |
   ┌─────────┐                                        | |
   │  1 2 3  │                                        | |
   └─┬─┬─┬───┘                                        | |
     │ │ └── pin 3 (GND)  ────────────────────────────┘ |
     │ └──── pin 2 (VCC)  ──── 3.3V (Pi pin 1) ─────────+--+
     └────── pin 1 (OUT)  ──┬─ GPIO17 (Pi pin 11)          |
                            │                              |
                            └─── 10kΩ pull-up ─────────────+  (to 3.3V)
   
   OLED (SSD1306, I2C)                RELAY MODULE (5V)
   ┌──────────┐                       ┌──────────────┐
   │ VCC ─────┼── 3.3V (Pi pin 1)     │ VCC ─ 5V (Pi pin 2)
   │ GND ─────┼── GND  (Pi pin 9)     │ GND ─ GND (Pi pin 6)
   │ SCL ─────┼── GPIO3 (Pi pin 5)    │ IN  ─ GPIO23 (Pi pin 16)
   │ SDA ─────┼── GPIO2 (Pi pin 3)    │ COM ─┐
   └──────────┘                       │ NO  ─┴── soldered across
                                      └──────────  the "release" button
                                                   inside the PETGEEK REMOTE
                                                   (NOT the dispenser body)
   
   PETGEEK remote ───wireless RF (50m)───> PETGEEK dispenser body (USB powered)
```

**Notes:**
- The Hall sensor's output is open-collector; the 10kΩ pull-up to 3.3V is required.
- A3144 is 3.3V-tolerant on VCC despite being commonly powered at 5V. Using 3.3V keeps the OUT line safe for the Pi's GPIO.
- Mount the sensor with its flat (labeled) face toward the magnet's path, gap ~3-5mm.
- Most cheap relay modules trigger on LOW. Confirm yours, and invert the GPIO logic if needed (`active_high=False` in gpiozero).
- **Feeder hack target = the PETGEEK remote, not the dispenser body.** Open the remote, locate the "release" momentary switch on the PCB, solder two thin wires across the two pads that bridge when pressed (verify with a multimeter in continuity mode). Route the wires out through the battery compartment seam to the relay's COM/NO terminals. The dispenser body stays factory-stock and gets its own USB power.

---

## 4. Mounting

- **Magnet:** epoxy or hot-glue to the outer rim of the wheel, balanced (consider a second dummy weight 180° opposite to avoid wobble).
- **Hall sensor:** zip-tie or bracket to the stationary frame, aligned with magnet's path, 3-5mm gap.
- **OLED:** mount on a small bracket on the wheel's frame at cat's-eye level (and yours), facing outward.
- **Pi + relay + PETGEEK remote:** all live together in a project box near the wheel, out of paw range.
- **PETGEEK dispenser body:** placed wherever the treats should actually drop (next to her food dish, on top of the wheel frame, wherever convenient). It receives the relay-triggered button press wirelessly from the remote in the project box.

---

## 5. Software Architecture

Single Python process, three threads/components:

```
┌────────────────────────────────────────────────────────────────┐
│                       main.py (Python 3)                        │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐    │
│  │  Sensor      │   │  State       │   │  Flask + SocketIO│    │
│  │  thread      │──▶│  manager     │──▶│  web server      │    │
│  │  (gpiozero   │   │  - current   │   │  - GET /         │    │
│  │   interrupt) │   │    speed     │   │  - GET /api/top  │    │
│  └──────────────┘   │  - run detect│   │  - WS speed feed │    │
│                     │  - threshold │   └──────────────────┘    │
│                     │    check     │                            │
│                     │  - cooldown  │   ┌──────────────────┐    │
│                     └──────┬───────┘   │  OLED writer     │    │
│                            │           │  (loop, 5 Hz)    │    │
│                            ├──────────▶│                  │    │
│                            │           └──────────────────┘    │
│                            │                                    │
│                            ▼                                    │
│                     ┌──────────────┐                            │
│                     │  SQLite      │                            │
│                     │  runs table  │                            │
│                     └──────────────┘                            │
└────────────────────────────────────────────────────────────────┘
```

**Libraries:** `gpiozero`, `flask`, `flask-socketio`, `luma.oled`, `sqlite3` (stdlib).

**Database schema:**
```sql
CREATE TABLE runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TIMESTAMP NOT NULL,
    ended_at     TIMESTAMP NOT NULL,
    peak_mph     REAL NOT NULL,
    avg_mph      REAL NOT NULL,
    duration_s   REAL NOT NULL,
    revolutions  INTEGER NOT NULL,
    treat_given  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_peak ON runs(peak_mph DESC);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- e.g. ('treat_threshold_mph', '8.0'), ('treat_cooldown_s', '60')
```

---

## 6. Pseudo-code

```python
# ============================================================
# config.py
# ============================================================
WHEEL_DIAMETER_M     = 0.30           # measure yours; 12" = ~0.305 m
WHEEL_CIRCUMFERENCE  = pi * WHEEL_DIAMETER_M

HALL_PIN             = 17
RELAY_PIN            = 23
OLED_I2C_ADDR        = 0x3C

PULSE_DEBOUNCE_MS    = 20             # ignore pulses closer than this
IDLE_TIMEOUT_S       = 3.0            # gap that ends a "run"
RUN_MIN_DURATION_S   = 1.0            # ignore single-twitch "runs"

DEFAULT_THRESHOLD_MPH = 8.0
DEFAULT_COOLDOWN_S    = 60
TREAT_PULSE_MS        = 250           # how long to hold the relay closed

DB_PATH = "/home/pi/catspeed/speed.db"


# ============================================================
# sensor.py — Hall sensor + speed calculation
# ============================================================
class SpeedTracker:
    def __init__(self, on_speed_update, on_run_complete):
        self.last_pulse_time = None
        self.current_mph     = 0.0
        self.run_active      = False
        self.run_start       = None
        self.run_pulse_times = []
        self.run_peak_mph    = 0.0
        self.on_speed_update = on_speed_update    # callback(mph)
        self.on_run_complete = on_run_complete    # callback(run_record)

    def on_pulse(self):
        now = time.monotonic()
        if self.last_pulse_time is not None:
            dt = now - self.last_pulse_time
            if dt * 1000 < PULSE_DEBOUNCE_MS:
                return                            # bounce, ignore
            mph = (WHEEL_CIRCUMFERENCE / dt) * 2.23694
            self.current_mph = smooth(mph)        # rolling avg of last 3
            self.run_peak_mph = max(self.run_peak_mph, self.current_mph)
            if not self.run_active:
                self.run_active = True
                self.run_start  = now
                self.run_pulse_times = []
            self.run_pulse_times.append(now)
            self.on_speed_update(self.current_mph)
        self.last_pulse_time = now

    def tick(self):                               # called from a 5 Hz loop
        if self.last_pulse_time is None:
            return
        idle = time.monotonic() - self.last_pulse_time
        if idle > IDLE_TIMEOUT_S:
            self.current_mph = 0.0
            self.on_speed_update(0.0)
            if self.run_active:
                duration = self.last_pulse_time - self.run_start
                if duration >= RUN_MIN_DURATION_S:
                    record = build_run_record(
                        start=self.run_start,
                        end=self.last_pulse_time,
                        peak=self.run_peak_mph,
                        revs=len(self.run_pulse_times),
                    )
                    self.on_run_complete(record)
                self.run_active = False
                self.run_peak_mph = 0.0


# ============================================================
# treat.py — dispenser control
# ============================================================
class TreatDispenser:
    def __init__(self, relay):
        self.relay        = relay
        self.last_treat_t = 0
        self.threshold    = load_setting("treat_threshold_mph", DEFAULT_THRESHOLD_MPH)
        self.cooldown_s   = load_setting("treat_cooldown_s",    DEFAULT_COOLDOWN_S)

    def maybe_dispense(self, current_mph):
        now = time.monotonic()
        if current_mph < self.threshold:
            return False
        if now - self.last_treat_t < self.cooldown_s:
            return False
        self.dispense()
        self.last_treat_t = now
        return True

    def dispense(self):
        self.relay.on()
        sleep_ms(TREAT_PULSE_MS)
        self.relay.off()
        log("Treat dispensed")


# ============================================================
# oled.py — display loop
# ============================================================
def oled_loop(get_state):
    device = init_ssd1306(OLED_I2C_ADDR)
    while True:
        state = get_state()                       # { current_mph, peak_today, all_time_peak }
        with canvas(device) as draw:
            draw.text((0, 0),  f"{state.current_mph:5.2f}", font=BIG)   # huge digits
            draw.text((0, 40), f"mph",                       font=SMALL)
            draw.text((60, 40), f"top: {state.all_time_peak:.2f}", font=SMALL)
            draw.text((0, 54), f"today peak: {state.peak_today:.2f}", font=SMALL)
        sleep(0.2)


# ============================================================
# db.py — leaderboard storage
# ============================================================
def save_run(record):
    conn.execute("""
        INSERT INTO runs (started_at, ended_at, peak_mph, avg_mph,
                          duration_s, revolutions, treat_given)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, record.as_tuple())
    conn.commit()

def top_n(n=10):
    return conn.execute("""
        SELECT peak_mph, started_at, duration_s
        FROM runs
        ORDER BY peak_mph DESC
        LIMIT ?
    """, (n,)).fetchall()

def all_time_peak():
    row = conn.execute("SELECT MAX(peak_mph) FROM runs").fetchone()
    return row[0] or 0.0


# ============================================================
# web.py — Flask dashboard
# ============================================================
@app.route("/")
def index():
    return render_template("dashboard.html",
                           top10=top_n(10),
                           all_time=all_time_peak(),
                           threshold=tracker.threshold)

@app.route("/api/threshold", methods=["POST"])
def set_threshold():
    mph = float(request.json["mph"])
    save_setting("treat_threshold_mph", mph)
    treat.threshold = mph
    return {"ok": True}

@app.route("/api/test_treat", methods=["POST"])
def test_treat():
    treat.dispense()
    return {"ok": True}

@socketio.on("connect")
def on_connect():
    emit("speed", {"mph": tracker.current_mph})

# In the speed-update callback, broadcast over websocket:
def on_speed_update(mph):
    socketio.emit("speed", {"mph": mph})


# ============================================================
# main.py — wiring it all together
# ============================================================
def main():
    init_db()
    relay   = OutputDevice(RELAY_PIN, active_high=False)   # invert if needed
    hall    = Button(HALL_PIN, pull_up=True, bounce_time=0.01)
    treat   = TreatDispenser(relay)
    tracker = SpeedTracker(
        on_speed_update=lambda mph: (on_speed_update(mph), treat.maybe_dispense(mph)),
        on_run_complete=save_run,
    )
    hall.when_pressed = tracker.on_pulse

    start_thread(oled_loop, args=(get_state_snapshot,))
    start_thread(idle_tick_loop, args=(tracker,))    # calls tracker.tick() at 5 Hz
    socketio.run(app, host="0.0.0.0", port=5000)
```

---

## 7. Build Sequence (recap)

**Phase A hardware (everything but the feeder):**
1. **Sensor smoke test** — Hall sensor on breadboard, print "PULSE" on detection, spin wheel by hand.
2. **Speed math** — add timing, print live mph, tune debounce.
3. **OLED** — get current speed rendering big and bright.
4. **DB + Flask** — leaderboard page with top 10 + live speed via WebSocket.

**→ Stop here, collect a few days of baseline data, confirm the dashboard is solid, THEN order Phase B parts.**

**Phase B (feeder integration):**

5. **PETGEEK calibration (no Pi yet)** — fill with her actual treats, manually press the remote 10 times, count what falls. Adjust the dispensing window slider until **one press ≈ one treat consistently.** Do this before any soldering.
6. **Remote hack** — open the remote, find the release button's two pads with a multimeter (continuity mode while pressing), solder thin wires across them, route out through the battery seam.
7. **Relay wiring + bench test** — wire relay to Pi GPIO23 + remote button wires to relay COM/NO. Test from a `/api/test_treat` endpoint with treats loaded. Confirm one relay click = one treat.
8. **Threshold + cooldown** — wire the auto-dispense logic, start conservative (high threshold, long cooldown).
9. **Mount everything**, set the threshold based on the Phase A baseline data.

---

## 8. Calibration & Tuning Notes

- **Measure circumference precisely.** Tape a string to the rim, mark one full revolution, measure flat. Off by 1cm = ~3% error on every reading.
- **Set initial threshold from real data.** During Phase A (no feeder yet), run for 2-3 days and look at the top-10. Pick something around the 70th-80th percentile of her peaks so it's earnable but not trivial.
- **Watch the cooldown.** If she chains sprints, you don't want a treat avalanche. 60s is a reasonable start; tune up if needed.
- **Sanity-check with two magnets later** if you want higher temporal resolution at low speeds (just remember to halve the per-pulse distance in code).
- **PETGEEK chime:** the dispenser plays a sound on each trigger. Some firmware versions have an off position on the A/B switch; if not, a small piece of tape over the speaker grille tames it.

---

## 9. Open Questions To Resolve Before Coding

- Confirm wheel diameter (measure inside running surface, not outer rim).
- Decide on units: mph or km/h on the OLED.
- Project enclosure location: same as the dispenser, or separate? (Remote is RF, so they can be apart.)
