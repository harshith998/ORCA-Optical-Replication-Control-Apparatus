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
| `src/config.py` | All hardware pin assignments, timing constants, I2C/SPI/UART config |
| `src/io_controller.py` | GPIO, SPI (MCP3008 ADC), UART abstraction; lux rolling buffer |
| `src/lcd_display.py` | I2C 16x2 LCD (PCF8574 expander at 0x27) |
| `src/database.py` | SQLite logging (`chamber_data.db`), web control state persistence |
| `src/usb_logger.py` | CSV export to auto-detected USB drives |
| `src/web_server.py` | Flask REST API + SSE dashboard on port 5000 |

### Control Loop Logic

Each 100ms tick:
- Reads switch states (GPIO), potentiometer (SPI/MCP3008), and lux (UART from ESP32)
- Determines active control mode (priority: web manual > automatic lux > potentiometer)
- Outputs PWM value (0–1023, 5 kHz) to LED driver
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

- **UART** (`/dev/serial0`, 115200 baud): Receives ASCII lux values from ESP32 sensor module (`"1234\n"` format)
- **SPI** (`/dev/spidev0.0`): MCP3008 ADC reads potentiometer on channel 0
- **I2C** (bus 1): LCD display at address `0x27`
- **GPIO PWM** (BCM 12): LED driver output at 5 kHz

All pin assignments are in `src/config.py`. Change hardware wiring there first.

### Firmware Context

The `firmware/` directory contains ESP32 firmware. The active firmware is `firmware/satellite-firmware/` (AS7343 spectral sensor + GPS + LoRa). The `chamber-esp32/` and `module-esp32/` directories are deprecated.
