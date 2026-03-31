# Firmware

This folder contains all firmware code for the ORCA Optical Replication Control Apparatus. It is organized by target device and includes the active satellite firmware implementation plus older chamber and module ESP32 firmware modules (deprecated). Use this README for overview, build instructions, and supported hardware.

## Contents

- `satellite-firmware/` (active)
  - ESP-IDF project for an all-in-one remote sensor and LoRa transmitter.
  - Features spectrum acquisition via AS7343, GPS locking, LoRa reporting, and deep sleep cycles.
- `chamber-esp32/` (deprecated)
  - Legacy sensor-conditioning and LED PWM feedback application.
  - Uses `InputOutput` hardware abstraction and 16x2 I2C LCD display.
- `module-esp32/` (deprecated)
  - Legacy dual VEML7700 lux measurement and UART output module.

## satellite-firmware (primary)

### Overview

- Uses AS7343 spectral sensor.
- Uses GPS module for location and time (`gps.c`, `gps.h`).
- Transmits packed reading batches over LoRa SX1262.
- Uses RTC fast memory (`RTC_DATA_ATTR`) to retain accumulation across deep sleep cycles.
- Configured for 10s transmit cycle and 2 samples per transmit by default (change `TRANSMIT_CYCLE_MS` and `SAMPLES_PER_TRANSMIT`).

### Build

1. Install ESP-IDF and toolchain as per Espressif docs.
2. `cd firmware/satellite-firmware`
3. `idf.py set-target esp32` (or appropriate target)
4. `idf.py menuconfig` to verify pinouts and config.
5. `idf.py build` and `idf.py flash`.

### Key files

- `main/satellite-firmware.cpp` — main application logic.
- `main(EspHal.h)` — hardware abstraction for module-specific SPI/LoRa.
- `main/gps.c/h` — GPS initialization/data parsing.
- `components/as7343/` — AS7343 sensor driver (project component).

## chamber-esp32 (deprecated)

### Overview

- Uses `InputOutput` class to read switches, lux/analog inputs and control PWM and LCD.
- Main loop selects display mode and scales output for LED driver.

### Build

1. `cd firmware/chamber-esp32`
2. `platformio run --target upload`

## module-esp32 (deprecated)

### Overview

- Reads two VEML7700 light sensors over separate I2C buses.
- Averages lux and sends via UART.

### Build

1. `cd firmware/module-esp32`
2. `platformio run --target upload`

## Contributing

- Prefer changes in `satellite-firmware` unless working on legacy compatibility.
- Keep comments in deep sleep timer and RTC accumulation logic to maintain low-power behavior.

## Notes

- Replace deprecated modules only after validating behavior on hardware.
- Check `firmware/README.md` frequently for updates as implementation evolves.
