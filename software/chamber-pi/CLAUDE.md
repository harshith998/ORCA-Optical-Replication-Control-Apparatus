# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ORCA (Optical Replication & Control Apparatus) is a dynamic lighting control system for marine phytoplankton research. It replicates real-world light conditions inside laboratory incubation chambers aboard research vessels. The `chamber-pi` software runs on a Raspberry Pi and controls LED strips via PWM based on lux readings from a remote ESP32 sensor module.

## Development Commands

```bash
# Initial Raspberry Pi setup (first time only)
bash scripts/setup.sh

# Update to latest (git pull + reinstall deps)
update   # installed globally by setup.sh

# Start the application
start    # activates venv and runs python src/main.py

# Manual development
source .venv/bin/activate
python src/main.py

# Run tests
python -m pytest tests/
python -m pytest tests/test_chamber_logic.py  # single test file
```

**Dependencies** are managed via `requirements.txt` and installed into `.venv/`.

## Architecture

The application has a single entry point (`src/main.py`) that:
1. Initializes all hardware peripherals
2. Spawns the Flask web server as a background daemon thread
3. Runs a 100ms control loop indefinitely

### Component Map

| File | Responsibility |
|------|---------------|
| `src/config.py` | All hardware pin assignments, timing constants, I2C/SPI/LoRa config |
| `src/io_controller.py` | GPIO, SPI (MCP3008 ADC), UART abstraction; lux rolling buffer |
| `src/lora_receiver.py` | SX1262 receive-only driver (LoRaRF library); packet decoder |
| `src/lcd_display.py` | I2C 16x2 LCD (PCF8574 expander at 0x27) |
| `src/database.py` | SQLite logging (`chamber_data.db`), web control state persistence |
| `src/usb_logger.py` | CSV export to auto-detected USB drives |
| `src/web_server.py` | Flask REST API + SSE dashboard on port 5000 |

### Control Loop Logic

Each 100ms tick:
- Reads switch states (GPIO), potentiometer (SPI/MCP3008), and lux (UART from ESP32)
- Determines active control mode (priority: web manual > automatic lux > potentiometer)
- Outputs PWM value (0–1023, 500 Hz) to LED driver
- Updates LCD, logs to SQLite, broadcasts via SSE

### Key Design Patterns

**Graceful degradation**: Every hardware peripheral is optional. Missing LCD, ADC, or UART is logged and skipped — the system keeps running with safe defaults.

**Lux clamping via rolling buffer**: `io_controller.py` maintains a 600-sample (~1 minute) buffer of lux readings. Min/max bounds from this buffer prevent sudden LED intensity jumps when the sensor value changes drastically.

**Thread safety**: `database.py` uses thread-local SQLite connections. The web server and main loop share state via locks. SSE subscribers are tracked with a lock.

### Web API (port 5000)

- `GET /` — Dashboard HTML
- `GET /api/status` — Current lux, PWM, mode, hardware diagnostics
- `GET|POST /api/control` — Read/set web manual control (enable flag + PWM value)
- `GET /api/history` — Time-series data (`?hours=24&limit=1000`)
- `GET /api/stream` — SSE live updates
- `GET /api/usb` — USB logger status

### Hardware Interfaces

- **SPI (`/dev/spidev0.1`, CE1)**: SX1262 LoRa hat — receives binary spectral + GPS packets from the satellite (see packet format below). Driven by `lora_receiver.py` via the `LoRaRF` library (`SX126x`). The module has an onboard TCXO controlled via DIO3 — `setDio3TcxoCtrl()` must be called during init or the chip will not lock onto any frequency.
- **SPI (`/dev/spidev0.0`, CE0)**: MCP3008 ADC reads potentiometer on channel 0
- **I2C** (bus 1): LCD display at address `0x27`
- **GPIO PWM** (BCM 12): LED driver output at 500 Hz (RPi.GPIO software PWM). 0% duty = LEDs off, 100% duty = LEDs full on.

#### LoRa Hat Pin Assignments (BCM, from `src/config.py`)

| Signal | BCM pin |
|---|---|
| NRESET | 8 |
| CS (CE1) | 7 |
| BUSY | 20 |
| DIO1 | 21 |
| SCK/MOSI/MISO | SPI0 hardware pins |

All pin assignments are in `src/config.py`. Change hardware wiring there first.

### Firmware Context

The `firmware/` directory contains ESP32 firmware. `firmware/satellite-firmware/` is the active transmitter; `chamber-esp32/` and `module-esp32/` are deprecated.

#### Satellite Firmware (transmitter)

The satellite runs on an ESP32 and uses **deep sleep** between cycles to minimize power draw. On each wakeup it takes a spectral sample, accumulates it in RTC-retained memory, and on every Nth wakeup transmits an averaged packet via LoRa and queries the GPS.

**Timing** (configured at top of `main.cpp`):
- `TRANSMIT_CYCLE_MS = 10000` — full transmit cycle (10 s)
- `SAMPLES_PER_TRANSMIT = 2` — samples averaged per packet
- `SAMPLING_CYCLE_MS = TRANSMIT_CYCLE_MS / SAMPLES_PER_TRANSMIT` — sleep duration between wakeups

**Sensor**: AS7343 14-channel spectral sensor over I2C (SCL=GPIO19, SDA=GPIO18). Channels transmitted: F1–F8, FZ, FY, FXL, NIR, Clear (13 values).

**LoRa radio**: SX1262 over SPI (SCK=GPIO6, MISO=GPIO2, MOSI=GPIO7, CS=GPIO11, DIO1=GPIO20, RST=GPIO0, BUSY=GPIO3).
- 915 MHz, 250 kHz bandwidth, SF9, CR7, sync word `0x12`

**Binary packet format** (51 bytes, little-endian):

| Offset | Size | Field |
|--------|------|-------|
| 0 | 4 | `sample_count` (uint32) |
| 4 | 26 | 13 × uint16 spectral channels (F1 F2 FZ F3 F4 F5 FY F6 FXL F7 F8 NIR Clear) |
| 30 | 1 | `gps.valid` (uint8) |
| 31 | 8 | `latitude_deg` (double) |
| 39 | 8 | `longitude_deg` (double) |
| 47 | 4 | `unix_time` (uint32, UTC) |

**GPS**: polled only on transmit cycles, 5 s lock timeout (`GPS_LOCK_TIMEOUT_MS`). If lock fails, `gps.valid = 0` and coordinates are zeroed.

**Outstanding TODOs in firmware**: GPS warm-sleep between cycles; RS-485/Ethernet integration on the receiver side.
