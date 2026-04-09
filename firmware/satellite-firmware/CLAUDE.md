# satellite-firmware

ESP-IDF project targeting the **ESP32-C6**.

## Build & Flash

```bash
# Source IDF environment first (adjust path to your install)
. $IDF_PATH/export.sh

idf.py build
idf.py flash
idf.py monitor          # Ctrl-] to exit
idf.py flash monitor    # flash then immediately monitor
```

## Project structure

```
satellite-firmware/
├── main/
│   ├── satellite-firmware.cpp   # app_main, sensor/GPS/LoRa logic
│   ├── EspHal.h                 # RadioLib HAL for ESP-IDF SPI
│   ├── gps.c / gps.h            # NMEA GPS driver
│   └── idf_component.yml        # managed-component manifest for main
├── components/
│   └── as7343/                  # Custom IDF component: AS7343 spectral sensor
│       ├── as7343.c
│       └── include/as7343.h
├── managed_components/
│   └── jgromes__radiolib/       # RadioLib (auto-fetched via idf component manager)
├── CMakeLists.txt
└── sdkconfig                    # Board-specific KConfig selections (committed)
```

## Key hardware

| Peripheral | Interface | Pins |
|---|---|---|
| AS7343 spectral sensor | I2C | SDA=18, SCL=19 |
| SX1262 LoRa radio | SPI | SCK=6, MISO=2, MOSI=7, CS=11, DIO1=20, RST=0, BUSY=3 |
| GPS module | UART | (via `gps.c`) |

## LoRa config

- Frequency: 915.0 MHz
- Bandwidth: 250 kHz
- Spreading factor: 9
- Coding rate: 7
- Sync word: 0x12

## Deep-sleep / sampling model

`app_main` runs once per wakeup, then calls `esp_deep_sleep_start()`.

- `SAMPLING_CYCLE_MS` — sleep duration between wakeups (derived from `TRANSMIT_CYCLE_MS / SAMPLES_PER_TRANSMIT`)
- `SAMPLES_PER_TRANSMIT` — how many spectral samples are averaged before a LoRa packet is sent
- Accumulated sums are kept in `RTC_DATA_ATTR` storage across deep sleeps; validated with a magic number + version on each boot.

## LoRa payload layout (51 bytes, little-endian)

| Field | Size |
|---|---|
| sample_count (uint32) | 4 |
| avg_f1..f8, fz, f3–f5, fy, fxl, nir, clear (13 × uint16) | 26 |
| gps.valid (uint8) | 1 |
| latitude_deg (double) | 8 |
| longitude_deg (double) | 8 |
| unix_time (uint32) | 4 |

A static_assert in `lora_send_report` enforces this size at compile time.

## GPS behavior

- Polls until a valid fix with datetime is obtained or `GPS_LOCK_TIMEOUT_MS` (5 s) elapses.
- On timeout, `gps_fix_t.valid = false` and the packet is sent anyway.
- Timezone is forced to `UTC0`.
