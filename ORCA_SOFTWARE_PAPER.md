# ORCA: Optical Replication & Control Apparatus
## Software System Architecture for Marine Phytoplankton Light Replication

---

## Abstract

ORCA is a two-node embedded software system designed to replicate natural spectral light environments inside sealed laboratory incubation chambers for marine phytoplankton and nitrogen fixation research. A remote satellite sensor module, built on the ESP32-C6 microcontroller, periodically wakes from deep sleep to acquire a 13-channel spectral measurement of the ambient environment, accumulates samples across sleep cycles using RTC-retained memory, and transmits an averaged report via LoRa radio along with a GPS fix. A chamber controller running on a Raspberry Pi receives these packets, drives LED output via PWM scaled to the measured light intensity, controls a water solenoid on configurable schedules, validates incoming readings against a solar position model, and presents a real-time web dashboard for remote monitoring and manual override. This document describes the complete software architecture of both subsystems, the mathematical models underlying their key algorithms, and the design rationale for each major component.

---

## 1. Introduction

Replicating natural light cycles in a controlled laboratory chamber is a non-trivial problem. Light intensity varies continuously with solar angle, cloud cover, sea state, and time of day. A static simulated cycle misses the temporal structure of real photosynthetically active radiation. ORCA addresses this by deploying a sensor physically exposed to the target environment — in this case, on the deck of a research vessel — and using live spectral data to continuously drive the LED output inside an incubation chamber below deck.

The system must operate with minimal intervention: the sensor node may be in a location that is difficult to access, the chamber must run unattended for multi-day experiments, and any downtime due to software failures would compromise the experiment. These requirements motivate the architectural decisions described in this paper: aggressive power management on the sensor, graceful degradation at every hardware boundary, and redundant state persistence across power cycles.

---

## 2. System Overview

ORCA consists of two physically separate computational nodes connected by a one-way LoRa radio link:

- **Satellite Sensor Module** — an ESP32-C6 embedded system that samples the environment and transmits averaged spectral packets at a configurable interval.
- **Chamber Controller** — a Raspberry Pi running Python that receives these packets, drives actuators, logs data, and serves a local network web dashboard.

The high-level data flow is unidirectional: the satellite transmits, the Pi only receives. There is no feedback path from the chamber back to the sensor, by design — the sensor's only job is to measure and report the real world.

```
┌─────────────────────────────────┐        LoRa 915 MHz        ┌────────────────────────────────────┐
│       Satellite (ESP32-C6)      │  ─────────────────────────► │      Chamber Controller (RPi)      │
│                                 │                             │                                    │
│  AS7343 ──► RTC accumulator     │        51 bytes             │  SX1262 ──► decoder ──► DB         │
│  GPS    ──► gps_fix_t           │        every T_tx           │  spectral ──► PWM ──► LEDs         │
│  SX1262 ──► lora_send_report()  │                             │  GPS ──► solar check ──► flag      │
│  deep sleep between wakeups     │                             │  solenoid scheduler ──► valve      │
└─────────────────────────────────┘                             │  Flask ──► SSE ──► dashboard       │
                                                                └────────────────────────────────────┘
```

---

## 3. Satellite Sensor Module

### 3.1 Execution Model: Deep Sleep Cycles

The central design constraint for the satellite is power. The node is solar-powered with a 3000 mAh LiPo cell and must survive overnight, overcast conditions, and potentially long periods without charging. The solution is to eliminate idle power consumption entirely: the ESP32-C6 spends virtually all of its time in deep sleep, drawing only the microamps required to maintain RTC SRAM and the sleep timer.

The execution model is not a conventional loop. `app_main()` runs once per wakeup, performs a sensor read, optionally transmits, and then calls `esp_deep_sleep_start()`. From the operating system's perspective, the program ends and the chip powers down. On the next wakeup, `app_main()` is called again from the top. This means that ordinary C variables do not persist — every local and global variable is re-initialized on each wakeup. The only memory that survives deep sleep is the RTC SRAM domain, explicitly marked with the `RTC_DATA_ATTR` attribute.

Two timing constants govern the cycle:

| Parameter | Symbol | Purpose |
|---|---|---|
| `TRANSMIT_CYCLE_MS` | T_tx | How often a LoRa packet is sent |
| `SAMPLES_PER_TRANSMIT` | N | How many spectral readings are averaged per packet |
| `SAMPLING_CYCLE_MS` | T_s | Sleep duration between wakeups |

These are related by:

$$T_s = \frac{T_{tx}}{N}$$

With `TRANSMIT_CYCLE_MS = 1000` and `SAMPLES_PER_TRANSMIT = 1`, the node wakes and transmits every second (used for development). In a deployment setting with `TRANSMIT_CYCLE_MS = 10000` and `SAMPLES_PER_TRANSMIT = 2`, the node wakes every 5 seconds to take a sample, and transmits every 10 seconds with an average of two readings — reducing both power draw and LoRa channel occupancy.

The wakeup schedule is set by the ESP-IDF timer wakeup mechanism. At the end of each `app_main()`, the firmware computes the sleep duration in microseconds and arms the timer:

```
sleep_us = SAMPLING_CYCLE_MS × 1000
esp_sleep_enable_timer_wakeup(sleep_us)
esp_deep_sleep_start()
```

The sleep duration does not account for the time spent awake. If execution time is a meaningful fraction of T_s, the effective sample interval will be slightly longer than intended. For T_s ≥ 1 second and execution times of ~100–300 ms (dominated by GPS acquisition), this error is less than 30% in the worst case and is acceptable for light monitoring applications where the input signal changes slowly.

### 3.2 RTC-Retained Accumulation and Averaging

Since variables do not survive deep sleep, any state that must persist across wakeups must live in RTC SRAM. The satellite firmware maintains a single RTC-retained accumulator struct, `s_rtc_state`, that holds running sums for all 13 spectral channels across a transmit interval.

The struct contains:

- `magic` and `version` — integrity check values
- `cycle_sample_count` — number of samples accumulated in the current transmit interval
- `total_sample_count` — global count of transmitted reports (for sequencing on the receiver)
- `sum_f1` through `sum_clear` — 64-bit integer sums for each channel
- `first_sample_time_us` and `last_sample_time_us` — timestamps for the interval

**Integrity validation.** On every boot (including from deep sleep), the firmware checks whether the magic number and version match expected constants before trusting the accumulator. If they do not match — which occurs on the very first power-on, or after a power failure that lost RTC memory — the struct is zeroed and reinitialized. This prevents corrupted partial sums from propagating into transmitted data.

```
if (s_rtc_state.magic ≠ RTC_STATE_MAGIC or s_rtc_state.version ≠ RTC_STATE_VERSION):
    rtc_state_full_reset()
```

**Accumulation.** Each wakeup adds one spectral reading to the running sums:

$$\text{sum}_{ch} \mathrel{+}= \text{ch}_{ch}^{(i)}$$

for each channel $ch \in \{F1, F2, \ldots, \text{clear}\}$. The 64-bit integer type was chosen to prevent overflow: with a maximum per-sample value of 65535 (uint16 max) and N up to a reasonable limit of 1000 samples, the maximum accumulated sum is $65535 \times 1000 = 65,535,000$, well within the uint64 range.

**Averaging.** When `cycle_sample_count >= SAMPLES_PER_TRANSMIT`, a transmit cycle is triggered. The average for each channel is computed as:

$$\bar{C}_{ch} = \left\lfloor \frac{\text{sum}_{ch}}{N} \right\rfloor$$

The result is truncated to a uint16 (matching the sensor's native output width) using a guarded division function that returns zero if the count is zero. After the report is built and transmitted, `rtc_state_clear_accumulator()` resets the sums and count to zero, while `total_sample_count` is preserved and incremented — it monotonically increases across the entire deployment lifetime.

This design has an important reliability property: if a LoRa transmission fails, the firmware logs the error but does **not** clear the accumulator. The next transmit cycle will attempt again with the same accumulated data. If the subsequent transmission also fails, the data is lost — but the accumulator is cleared regardless so that staleness does not compound. Future improvement could retain failed data across one additional cycle.

### 3.3 AS7343 Spectral Sensor

The AS7343 is a 14-channel photodetector array measuring light intensity across the visible and near-infrared spectrum. It communicates with the ESP32-C6 over I2C at 100 kHz (I2C address `0x39`). Of its 14 output registers, 13 are used:

| Channel | Center Wavelength | Spectral Region |
|---|---|---|
| F1 | ~405 nm | Violet |
| F2 | ~425 nm | Violet |
| FZ | ~450 nm | Blue |
| F3 | ~475 nm | Blue |
| F4 | ~515 nm | Green |
| F5 | ~550 nm | Green |
| FY | ~555 nm | Green-Yellow |
| F6 | ~640 nm | Red |
| FXL | ~600 nm | Orange |
| F7 | ~690 nm | Deep Red |
| F8 | ~745 nm | Near-IR boundary |
| NIR | ~855 nm | Near-Infrared |
| Clear | broadband | Broadband (all wavelengths) |

The sensor's output depends on two integration parameters: ATIME and ASTEP. These control the integration time according to:

$$t_{int} = (\text{ATIME} + 1) \times (\text{ASTEP} + 1) \times 2.78\,\mu s$$

With the deployed configuration of `atime=0`, `astep=599`:

$$t_{int} = 1 \times 600 \times 2.78\,\mu s = 1668\,\mu s \approx 1.67\,\text{ms}$$

The gain is set to 256×, maximizing sensitivity for the low-light conditions encountered at sea. The AS7343's output is a 16-bit integer per channel, where a larger value represents greater photon flux at that wavelength. The sensor is initialized once per wakeup (I2C state does not survive deep sleep), which adds approximately 1–2 ms of setup overhead per sample.

### 3.4 GPS Acquisition

On every transmit cycle, the satellite queries a NMEA GPS module (Quectel LC86GLA) over UART. The GPS driver parses incoming NMEA sentences — specifically GPRMC for position and fix validity, and GPGSA for dilution-of-precision values — into a structured `gps_data_t` containing latitude, longitude, altitude, speed, heading, satellite count, HDOP/PDOP/VDOP, and UTC datetime.

The acquisition loop polls `gps_update()` until the parsed data reports both a valid position fix and a valid datetime, or until a 5-second timeout elapses:

```
start = now()
while not (data.valid and data.datetime_valid):
    gps_update()
    if (now() - start) >= 5000 ms:
        fix.valid = false
        return
```

When a fix is obtained, the UTC datetime from the NMEA sentences is converted to a Unix timestamp using the C standard library's `mktime()` function, with the timezone explicitly forced to `UTC0` to prevent any local time offset from corrupting the timestamp.

If the 5-second timeout elapses without a fix — which occurs at first power-on before the GPS has acquired satellites, or in environments with poor sky visibility — the `gps_fix_t.valid` flag is set to false and the GPS fields in the transmitted packet are zeroed. The LoRa packet is still sent. The receiver on the Pi side checks `gps.valid` before attempting any GPS-dependent computation.

A known limitation is GPS cold-start latency. A cold-start (no previously acquired almanac) can take 30–60 seconds. The 5-second timeout means the first several packets after power-on will carry no GPS data. This is acceptable for the use case, as positional data is used only for sanity checking and timestamps — neither is critical for the light replication function. A future improvement noted in the firmware is GPS warm-sleep (maintaining the GPS receiver's power between transmit cycles via a UART TX line), which would reduce fix time to under 1 second on subsequent cycles.

### 3.5 LoRa Transmission

The SX1262 transceiver (RadioLib, via a custom ESP-IDF HAL) transmits the packed report on the 915 MHz ISM band. The radio configuration is:

| Parameter | Value | Effect |
|---|---|---|
| Frequency | 915.0 MHz | North American ISM band |
| Bandwidth | 250 kHz | Moderate — balances range and data rate |
| Spreading Factor | 9 | Higher = longer range, lower throughput |
| Coding Rate | 4/7 | Moderate forward error correction |
| Sync Word | 0x12 | Private network (non-LoRaWAN) |

The key performance parameters follow from these settings. The symbol duration is:

$$T_{sym} = \frac{2^{SF}}{BW} = \frac{2^9}{250{,}000} = 2.048\,\text{ms}$$

The effective raw bit rate, accounting for spreading and coding rate, is approximately:

$$R_b = SF \times \frac{BW}{2^{SF}} \times \frac{4}{4 + CR} = 9 \times \frac{250{,}000}{512} \times \frac{4}{11} \approx 1{,}596\,\text{bps}$$

For a 51-byte payload, the time on air is on the order of 300–400 ms, which dominates the active power budget of each transmit cycle. At SF9 and 250 kHz BW, the system achieves a link budget sufficient for line-of-sight ranges exceeding 1 km in open water conditions — well beyond the inter-deck distances encountered on a research vessel.

### 3.6 Binary Payload Format

The 51-byte packet is packed little-endian without any struct padding, defined by a C `static_assert` at compile time to catch any accidental layout change:

| Offset | Size | Type | Field |
|---|---|---|---|
| 0 | 4 | uint32 | `sample_count` — monotonic report index |
| 4 | 26 | 13 × uint16 | Averaged spectral channels (F1, F2, FZ, F3, F4, F5, FY, F6, FXL, F7, F8, NIR, Clear) |
| 30 | 1 | uint8 | `gps.valid` |
| 31 | 8 | double | `latitude_deg` |
| 39 | 8 | double | `longitude_deg` |
| 47 | 4 | uint32 | `unix_time` (UTC) |

The `sample_count` field allows the receiver to detect dropped packets — a gap in the sequence indicates missed transmissions. The GPS fields are always present in the packet even when invalid; the receiver must check `gps.valid` before using them.

---

## 4. Chamber Controller (Raspberry Pi)

### 4.1 System Architecture

The chamber controller runs as a single Python process with multiple concurrent threads:

- **Main control loop** — executes every 100 ms, reads all hardware inputs, drives actuators, logs data, and broadcasts state updates.
- **Flask web server thread** — handles HTTP and SSE connections in parallel with the control loop.
- **Water scheduler thread** — drives the solenoid valve independently of the 100 ms loop, on timescales of seconds to hours.

All shared state is protected by Python threading locks. The database uses thread-local SQLite connections to avoid cross-thread contention. The web server is deliberately isolated from hardware — it reads from and writes to the database and an in-memory state dict, but never touches GPIO directly. This means the web interface continues to function even if hardware initialization fails.

The 100 ms loop period was chosen to match the natural update rate of the LoRa link (packets arrive every 1–10 seconds) while remaining fast enough to respond promptly to physical switch changes and provide smooth SSE updates to the dashboard.

### 4.2 LoRa Reception

The Pi receives LoRa packets using a Python driver for the SX1262 chip (`lora_receiver.py`), implemented directly over `spidev` and `RPi.GPIO` without any RadioLib dependency. The driver implements a minimal subset of the SX1262 register interface: initialization, modulation parameter configuration, continuous receive mode, and non-blocking packet polling.

Radio parameters on the receiver exactly mirror the transmitter (915 MHz, 250 kHz BW, SF9, CR4/7, sync word 0x12). Any mismatch in any parameter results in zero received packets — there is no partial decode.

The receiver uses the SX1262's DIO1 interrupt pin as a polling indicator rather than a true hardware interrupt. Each time the main loop calls `io.update()`, the driver checks the GPIO level of DIO1:

```
if GPIO(DIO1) is LOW:
    return None  # No packet ready

irq = read_irq_status()
clear_irq(irq)

if CRC_ERROR in irq:
    return None

if RX_DONE in irq:
    payload_len, buf_offset = read_buffer_status()
    return read_buffer(buf_offset, payload_len)
```

This non-blocking design ensures the 100 ms loop is not stalled waiting for a packet. If a packet is available it is read immediately; otherwise the loop continues with the previous lux value unchanged.

Received bytes are decoded using Python's `struct.unpack` with the format string `'<I 13H B d d I'` (little-endian: one uint32, thirteen uint16s, one uint8, two doubles, one uint32), exactly matching the transmitter's packed layout.

### 4.3 Lux Clamping and PWM Control

The raw `clear` channel value from the AS7343 is used as the primary light intensity signal for LED control. The Pi must map this value to a PWM duty cycle in the range [0, 1023] while suppressing noise and preventing sudden brightness jumps that could shock biological samples.

**PWM Scaling.** The baseline linear mapping is:

$$pwm = \text{clamp}\!\left(\frac{L_{raw}}{K}, 0, 1\right) \times 1023$$

where $K = 2750$ is a tunable scaling constant (`SCALE_CONSTANT` in `config.py`) that maps the expected maximum lux value to full LED output. The constant must be calibrated to the specific sensor, enclosure geometry, and LED assembly used in each deployment.

**Note on PWM inversion.** The MOSFET driver circuit between the Pi's GPIO and the LED array inverts the signal — 0% duty cycle corresponds to full LED brightness and 100% corresponds to off. The software accounts for this by computing the complement:

$$\text{duty} = 100\% - \left(\frac{pwm}{1023}\right) \times 100\%$$

This inversion is handled within `set_pwm()` so the rest of the system always works in the intuitive direction (higher pwm value = brighter).

**Rolling Bounds Buffer.** Instantaneous lux values can exhibit rapid transients: a wave crest momentarily exposes the sensor to direct sunlight, a shadow passes overhead, or the sensor is briefly occluded. Directly mapping these transients to LED output would produce rapid, biologically stressful flicker.

The solution is a circular buffer of 600 samples, representing approximately 60 seconds of history at the 100 ms loop rate. Each new reading is added to the buffer, which maintains a running minimum and maximum:

$$L_{min} = \min_{i \in [0, 599]} B[i], \quad L_{max} = \max_{i \in [0, 599]} B[i]$$

Incoming readings are clamped to these bounds:

$$L_{clamped} = \text{clamp}(L_{raw},\; L_{min},\; L_{max})$$

During the first 60 seconds after startup (while the buffer fills), no clamping is applied and raw values pass through directly. Once the buffer is full, the 60-second rolling window ensures that $L_{min}$ and $L_{max}$ represent the recent behavioral range of the environment, not all-time extremes. Gradual changes in light level — the natural progression of sunrise to noon to sunset — move the bounds with them, while spikes beyond the recent range are suppressed.

**Control Mode Priority.** The system supports three input sources for PWM, resolved in priority order:

1. **Web manual override** — set via the web dashboard API. Takes highest priority; physical switches are ignored when active.
2. **Analog potentiometer** — when SW1 is high, the potentiometer position (0–1 normalized) drives the PWM directly.
3. **Automatic lux tracking** — the default mode; uses the clamped lux value through the scaling formula.

SW2 acts as a global enable: when high, PWM output is forced to zero regardless of mode.

### 4.4 Solenoid Water Control

The water delivery system uses a solenoid valve — a binary device that is either energized (valve open, water flows) or de-energized (valve closed). The software supports two operating modes:

**Manual mode.** The user sends an open or close command via the web API. The water scheduler thread polls the database for the current target state every 500 ms and drives the GPIO accordingly.

**Auto (scheduled) mode.** The user configures two parameters:
- **Interval** $T_I$ — time between valve activations (seconds)
- **Duration** $T_D$ — how long the valve stays open each activation (seconds)

The scheduler thread runs the following cycle:

```
loop:
    open valve
    sleep T_D
    close valve
    sleep (T_I - T_D)
```

This produces a periodic duty cycle of $T_D / T_I$. For example, with `interval=7200 s` (2 hours) and `duration=10 s`, the valve opens for 10 seconds every 2 hours — a duty cycle of approximately 0.14%.

The scheduler runs in its own daemon thread and is completely decoupled from the 100 ms control loop. This is necessary because the sleep durations (seconds to hours) are orders of magnitude longer than the loop period, and blocking the main loop would suspend LED control and data logging.

The solenoid GPIO pin (BCM 26) is initialized to LOW (valve closed) at startup. On clean shutdown, `water_scheduler.stop()` closes the valve and signals the thread to exit before the process terminates.

### 4.5 Solar Sanity Checker

The solar sanity checker (`solar_check.py`) validates each incoming lux reading against an independent expected value derived solely from the GPS coordinates and UTC timestamp already present in the LoRa packet — no external API or network call is required. A reading dramatically inconsistent with the expected solar geometry indicates sensor obstruction, hardware failure, or data corruption.

#### 4.5.1 Solar Position

The pipeline from GPS fix to sun elevation proceeds through four quantities.

**Declination** $\delta$ is the angle between the sun's rays and Earth's equatorial plane, driven by the 23.45° axial tilt. For day of year $n$:

$$\delta = 23.45° \times \sin\!\left(\frac{360}{365}(n - 81)\right)$$

ranging from $-23.45°$ (December solstice) to $+23.45°$ (June solstice).

**Equation of time** corrects for the fact that solar noon does not coincide exactly with clock noon due to orbital eccentricity and axial obliquity. With $B = \tfrac{360}{365}(n-81)$:

$$E_{qt} = 9.87\sin(2B) - 7.53\cos(B) - 1.5\sin(B) \quad [\text{minutes}]$$

**Hour angle** $H$ converts UTC time and longitude $\lambda$ into angular distance from solar noon:

$$\text{LST} = \text{UTC} + \frac{\lambda}{15} + \frac{E_{qt}}{60}, \qquad H = 15°\times(\text{LST} - 12)$$

where the factor of 15°/hr comes from Earth's 360°/24 hr rotation rate. $H = 0°$ at solar noon, negative before, positive after.

**Altitude angle** $\alpha$ follows from spherical trigonometry projecting the equatorial sun position $(\delta, H)$ into the observer's local horizontal frame at latitude $\phi$:

$$\alpha = \arcsin\!\bigl(\sin\phi\sin\delta + \cos\phi\cos\delta\cos H\bigr)$$

When $\alpha \leq 0°$ the sun is below the horizon. An atmospheric refraction correction (Bennett's formula) adds up to ~0.6° near the horizon but is negligible above 10°:

$$\Delta\alpha = \frac{1.02}{\tan\!\left(\alpha + \frac{10.3}{\alpha+5.11}\right)} \times \frac{P}{1010} \times \frac{283}{273+T} \quad [\text{arcminutes}]$$

#### 4.5.2 Expected Irradiance

The solar constant $E_{sc} = 1361\,\text{W/m}^2$ is modulated by Earth's elliptical orbit ($\pm 3.3\%$ between perihelion and aphelion):

$$E_{ext}(n) = 1361 \times \left(1 + 0.033\cos\!\tfrac{360n}{365}\right)$$

Atmospheric attenuation follows Bouguer's Law. The air mass $m$ — the number of atmosphere-thicknesses the beam traverses — is given by the Kasten–Young formula:

$$m = \frac{1}{\sin\alpha + 0.50572\,(\alpha+6.07995)^{-1.6364}}$$

($m=1$ at zenith, $m\approx5.6$ at $\alpha=10°$). Clear-sky surface irradiance is then:

$$E_{surface} = E_{ext} \times 0.7^{\,m^{0.678}}$$

where 0.7 is the standard broadband clear-sky transmittance and the exponent 0.678 corrects for the non-uniform vertical distribution of the atmosphere. At zenith this yields $\approx 953\,\text{W/m}^2$, consistent with the commonly cited clear-sky peak. Projecting onto a horizontal sensor surface:

$$E_{horiz} = E_{surface} \times \sin(\alpha)$$

#### 4.5.3 Sensor Scaling and Sanity Threshold

The AS7343 `clear` channel count is proportional to broadband irradiance. A single empirical constant $k_{scale}$ (counts per W/m²) converts $E_{horiz}$ to expected counts:

$$C_{expected} = E_{horiz} \times k_{scale}, \qquad k_{scale} = 5.0 \text{ [placeholder]}$$

Once field data is available, $k_{scale}$ should be estimated by single-parameter OLS through the origin:

$$\hat{k}_{scale} = \frac{\sum_i E_i \cdot C_i}{\sum_i E_i^2}$$

The sanity flag is raised when the actual-to-expected ratio falls outside the tolerance band $[1/\tau,\,\tau]$, equivalently $|\log(C_{actual}/C_{expected})| > \log\tau$:

$$\text{flag} = \frac{C_{actual}}{C_{expected}} \notin \left[\frac{1}{\tau},\;\tau\right], \qquad \tau = 5.0$$

The factor-of-5 tolerance accommodates the dominant uncertainty sources: heavy overcast can reduce irradiance to 10–20% of the clear-sky value (approaching the lower bound), sea-surface reflectance adds up to 20% excess (well inside the upper bound), and a 30° sensor tilt reduces the cosine projection by only ~13%. The check is skipped when $\alpha < 5°$, when GPS is invalid, or when `pysolar` is not installed.

### 4.6 Data Pipeline and Storage

All data is stored locally in a SQLite database (`chamber_data.db`) on the Pi's SD card. SQLite was chosen for its zero-configuration deployment, embedded operation, and sufficient performance for the ~10 Hz write rate. The database uses thread-local connections to allow simultaneous access from the main loop, the web server, and the water scheduler without locking contention.

**Schema.** The database contains four tables:

`lux_history` — primary time-series log, written every 100 ms loop iteration:

| Column | Type | Description |
|---|---|---|
| timestamp | REAL | Unix time of sample |
| raw_lux | INTEGER | Unfiltered clear channel value |
| clamped_lux | INTEGER | After rolling-bounds clamping |
| pwm_value | INTEGER | Actual PWM output [0–1023] |
| mode | TEXT | `lux`, `analog`, or `web_manual` |
| bounds_min, bounds_max | INTEGER | Current rolling window bounds |

`spectral_history` — full 13-channel reading, written only when a new LoRa packet is received:

| Column | Type | Description |
|---|---|---|
| timestamp | REAL | Unix time |
| f1–clear | INTEGER | All 13 spectral channels |
| gps_valid | INTEGER | 0 or 1 |
| gps_lat, gps_lon | REAL | Decimal degrees |
| gps_unix_time | INTEGER | UTC Unix timestamp from GPS |
| sanity_flag | INTEGER | 0 or 1, from solar checker |

`system_state` — single-row table holding the web manual control state (enabled flag + PWM value). Persists across restarts so the last-set value is remembered.

`water_control` — single-row table holding the solenoid mode, manual state, interval, and duration. Persists across restarts.

**Data retention.** A background cleanup task deletes records from `lux_history` older than 7 days. At 10 Hz, this accumulates approximately 6 million rows per day; 7-day retention thus caps the table at ~42 million rows. SQLite handles this volume adequately for the query patterns used (time-range queries on an indexed `timestamp` column), though performance degrades on very long historical queries. The `spectral_history` table grows more slowly (one row per LoRa packet) and does not yet have a cleanup policy.

**USB export.** An optional `usb_logger.py` module detects mounted USB drives and writes a CSV file (`chamber_readings.csv`) with each loop iteration's data. This enables field data collection without network access — the drive can be removed and read on any computer.

### 4.7 Web Interface and Real-Time Monitoring

The web dashboard is served by a Flask application embedded within `web_server.py`. The entire frontend — HTML, CSS, and JavaScript — is rendered as a single template string, requiring no static file serving and simplifying deployment. The dashboard is available at `http://<pi-ip>:5000` on the local network.

**Server-Sent Events.** Real-time updates are delivered via the SSE protocol (`/api/stream`), which provides a persistent one-way HTTP connection from the server to the browser. Each 100 ms loop iteration, after computing the new system state, calls `broadcast_sse()` which places a JSON-serialized state snapshot into each active subscriber's queue:

```
state = {raw_lux, clamped_lux, pwm_value, mode,
         bounds_min, bounds_max, pot_value, sw1, sw2,
         web_manual_enabled, web_manual_pwm,
         sanity_flag, timestamp}
```

Each connected browser receives this message within milliseconds. The browser's `EventSource` API handles reconnection automatically on disconnect with a 3-second backoff.

SSE was preferred over WebSockets because it is unidirectional (the server pushes data; user commands use separate REST POST requests), simpler to implement correctly with Flask's threading model, and natively supported in all modern browsers without any client-side library.

**Spectral History Chart.** The dashboard provides a Chart.js line chart of historical data with four time-range buttons (1H, 6H, 24H, 7D). By default, the chart displays the `raw_lux` and `clamped_lux` columns from `lux_history`. A dropdown selector allows switching to any of the 13 individual spectral channels, fetching from the `spectral_history` table via `/api/spectrum`. When a spectral channel is selected, the clamped line is hidden (it is only defined for the clear channel), and the chart redraws with the appropriate axis scale.

**Web Manual Control.** The dashboard provides a toggle to enable web manual override and a slider to set PWM value [0–1023]. Commands are sent via `POST /api/control`. The main loop reads this state from the database on every iteration, ensuring that a command takes effect within 100 ms of being submitted. The web control state persists in the database so it survives a Pi reboot — if the LED was set to a specific brightness before a crash, it returns to that brightness automatically on restart.

**Water System Control.** A dedicated section provides mode toggle (manual vs. auto), OPEN/CLOSE buttons for manual mode, and interval/duration inputs for auto mode. Commands are sent via `POST /api/water` and immediately reflected in the scheduler thread via the database. The current valve state is polled from `/api/water` every 2 seconds and displayed as a colored badge (green = OPEN, red = CLOSED).

**REST API Summary.**

| Endpoint | Method | Description |
|---|---|---|
| `/api/status` | GET | Current full system state snapshot |
| `/api/stream` | GET | SSE live update stream |
| `/api/control` | GET/POST | Web manual LED control state |
| `/api/history` | GET | Lux time-series (`?hours=24&limit=1000`) |
| `/api/spectrum` | GET | Spectral history all channels (`?hours=6`) |
| `/api/stats` | GET | Aggregate statistics (`?hours=24`) |
| `/api/water` | GET/POST | Solenoid control state |
| `/api/usb` | GET | USB logger status |

---

## 5. Cross-System Data Flow

A single end-to-end data cycle proceeds as follows:

1. The satellite's ESP32-C6 wakes from deep sleep. The RTC state integrity check passes.
2. The I2C bus is initialized and the AS7343 integrates for ~1.67 ms. All 13 channel values are read.
3. The new readings are added to the RTC accumulator sums; `cycle_sample_count` is incremented.
4. If `cycle_sample_count < SAMPLES_PER_TRANSMIT`, the firmware proceeds directly to sleep. No radio activity occurs.
5. If `cycle_sample_count >= SAMPLES_PER_TRANSMIT`, a transmit cycle begins.
6. The GPS module is queried. The firmware waits up to 5 seconds for a valid NMEA fix with UTC datetime. `mktime()` produces a Unix timestamp.
7. Channel averages are computed: $\bar{C}_{ch} = \lfloor \text{sum}_{ch} / N \rfloor$ for all 13 channels.
8. A 51-byte binary payload is packed, little-endian, in the order: `sample_count`, 13 × channel avg, `gps.valid`, `lat`, `lon`, `unix_time`.
9. The SX1262 transmits the payload at 915 MHz, SF9, BW250, CR4/7. Time on air ≈ 300–400 ms.
10. The RTC accumulator sums and count are cleared. `total_sample_count` increments.
11. The firmware sleeps for $T_s = T_{tx} / N$ milliseconds.

Concurrently, on the Pi:

12. The main loop's 100 ms tick calls `io.update()`, which polls DIO1 of the receiver SX1262.
13. If DIO1 is high, the IRQ register is read. If RX_DONE and no CRC error, the buffer is read and returned as raw bytes.
14. `decode_packet()` unpacks the 51 bytes using `struct.unpack('<I 13H B d d I')`.
15. `self.spectral_channels` is updated with all 13 channel values. `self.lux_value` is set to the `clear` channel. `self.last_gps` is populated.
16. In `loop()`: raw_lux is passed through the 600-sample rolling bounds buffer → clamped_lux. PWM is computed and applied.
17. If GPS is valid: `solar_check.check_reading()` computes sun elevation via `pysolar`, estimates expected clear-channel counts, and returns a boolean flag.
18. `db.log_reading()` writes to `lux_history`. If a new LoRa packet was received, `db.log_spectral()` writes all 13 channels plus GPS and sanity flag to `spectral_history`.
19. `update_current_state()` updates the in-memory state dict and calls `broadcast_sse()`, placing a JSON message into every active SSE subscriber queue.
20. Connected browsers receive the SSE message and update the dashboard within milliseconds.

---

## 6. Design Observations and Limitations

**Single-path communication.** The LoRa link is one-way by design; the satellite cannot receive commands. Operational changes to the sensor (e.g., changing integration time or transmit rate) require physical access to reflash the firmware. This is a deliberate simplification — adding a bidirectional link would require the sensor node to stay awake listening for downlink messages, which would substantially increase power draw.

**No time synchronization between nodes.** The Pi logs data using its own system clock; the GPS timestamp in the packet represents the time on the satellite when the sample was taken. These two clocks are not synchronized. If the Pi's system time is accurate (via NTP over WiFi), the GPS timestamp can be compared directly. If not, there may be a constant offset. Future work could use the GPS unix_time to discipline the Pi's clock when GPS data is valid.

**Solar model accuracy.** The sanity checker's irradiance model assumes clear-sky conditions. In overcast weather, actual irradiance may be a factor of 5–10 below the clear-sky prediction, which would trigger false positive flags under the current tolerance setting. Tuning the tolerance to a larger value, or applying a cloud-cover correction using satellite weather data, would reduce false positives in real-world conditions.

**Database growth.** The 7-day rolling deletion policy keeps `lux_history` bounded, but the `spectral_history` table is not yet cleaned up. Since spectral entries are written once per LoRa packet (not every 100 ms), the growth rate is much lower — approximately 8,640 rows/day at a 10-second transmit interval — but a retention policy should be added before long deployments.

**Authentication.** The web dashboard has no authentication. All API endpoints are accessible to any device on the local network. This is acceptable for a dedicated lab network but should be addressed before any public or multi-tenant deployment.

---

## 7. Conclusion

ORCA demonstrates a practical architecture for closed-loop environmental replication using a two-node embedded system. The satellite's deep sleep execution model, RTC-retained accumulation, and compact binary LoRa payload achieve efficient remote sensing with minimal power draw. The chamber controller's multi-threaded design separates real-time control (100 ms loop), long-period scheduling (water solenoid), and user interaction (Flask/SSE) into independent concerns while maintaining thread-safe shared state. The addition of a solar position model as an independent sanity check provides a layer of data quality assurance that does not depend on redundant sensors.

The most significant ongoing development areas are GPS warm-sleep (to reduce per-transmit power draw on the satellite), the RS-485/Ethernet wired fallback path (noted as a TODO in the firmware), and calibration of the CLEAR_PER_WM2 scaling constant for the solar sanity checker once field measurement pairs become available.

---

*System firmware: ESP-IDF 5.x, C++17 (satellite). Chamber software: Python 3.11+, Flask 3.x, SQLite 3 (controller). LoRa: RadioLib (transmit), custom spidev driver (receive). Solar model: pysolar 0.13.*
