# Satellite Firmware

ESP-IDF firmware for the ORCA satellite module, targeting the **ESP32-C6**.

## Overview

The satellite module collects 13-channel spectral light data using an **AS7343** sensor, averages multiple samples together, attaches a GPS fix, and transmits a compact binary packet over **LoRa** (SX1262) or **RS-485** (if a wired connection is detected).

To minimize power draw, `app_main` runs once per wakeup and then immediately calls `esp_deep_sleep_start()`. RTC memory is used to accumulate sample sums across sleep cycles so averaging works without staying awake.

---

## Timing Configuration

All timing constants are defined near the top of `main/satellite-firmware.cpp`:

```cpp
#define TRANSMIT_CYCLE_MS     60000ULL   // How often to transmit data (ms)
#define SAMPLES_PER_TRANSMIT  4          // How many samples to average per transmit
#define GPS_LOCK_TIMEOUT_MS   80000ULL   // Max time to wait for a GPS fix (ms)
```

| Constant | Default | What it controls |
|---|---|---|
| `TRANSMIT_CYCLE_MS` | 60000 ms (1 min) | How often a LoRa/RS-485 packet is sent. A larger value means less frequent transmissions and lower average power. |
| `SAMPLES_PER_TRANSMIT` | 4 | How many spectral readings are averaged into each packet. More samples = smoother data but the same transmit rate. |
| `GPS_LOCK_TIMEOUT_MS` | 80000 ms (80 s) | How long the firmware waits for a GPS fix before giving up and sending the packet anyway with `gps.valid = false`. |

A fourth value, `SAMPLING_CYCLE_MS`, is **derived automatically** and should not be edited directly:

```cpp
#define SAMPLING_CYCLE_MS  (TRANSMIT_CYCLE_MS / SAMPLES_PER_TRANSMIT)
```

This is the deep-sleep duration between each sensor reading. With the defaults above it equals **15 000 ms (15 s)**.

### Example: change to sample every 30 s and transmit every 2 minutes

```cpp
#define TRANSMIT_CYCLE_MS     120000ULL  // 2 minutes
#define SAMPLES_PER_TRANSMIT  4          // 4 samples → sleep 30 s between each
```

### Example: transmit every sample (no averaging)

```cpp
#define TRANSMIT_CYCLE_MS     30000ULL
#define SAMPLES_PER_TRANSMIT  1          // transmit immediately after every reading
```

> **Note:** `GPS_LOCK_TIMEOUT_MS` should always be less than `TRANSMIT_CYCLE_MS` or the GPS poll will never finish before the next sleep. The firmware does not enforce this automatically.

---

## Data Flow

```
wake up
  → validate RTC state (magic + version check)
  → init I2C bus + AS7343 sensor
  → check RS-485 connection
  → read 13 spectral channels → accumulate into RTC sums
  → if cycle_sample_count >= SAMPLES_PER_TRANSMIT:
        → poll GPS (up to GPS_LOCK_TIMEOUT_MS)
        → build report_payload_t (averaged channels + GPS)
        → transmit via RS-485 (if wired) or LoRa
        → clear RTC accumulators
  → set timer wakeup for SAMPLING_CYCLE_MS → deep sleep
```

---

## Hardware

| Peripheral | Interface | Pins |
|---|---|---|
| AS7343 spectral sensor | I2C @ 100 kHz | SDA=18, SCL=19 |
| SX1262 LoRa radio | SPI @ 2 MHz | SCK=6, MISO=2, MOSI=7, CS=11, DIO1=20, RST=0, BUSY=3 |
| GPS module | UART1 @ 115200 | RX=5, TX=4, RESET_N=GPIO1 |
| RS-485 transceiver | UART | TX=16, SNS=10, EN=23 |

**LoRa settings:** 915.0 MHz, 250 kHz bandwidth, SF9, CR7, sync word 0x12

---

## LoRa Packet Layout (51 bytes, little-endian)

| Field | Type | Bytes |
|---|---|---|
| `sample_count` | uint32 | 4 |
| `avg_f1` through `avg_clear` (13 channels) | 13 × uint16 | 26 |
| `gps.valid` | uint8 | 1 |
| `latitude_deg` | double | 8 |
| `longitude_deg` | double | 8 |
| `unix_time` | uint32 | 4 |

---

## Build & Flash

```bash
. $IDF_PATH/export.sh

idf.py build
idf.py flash monitor
```

RadioLib is fetched automatically via the IDF component manager on first build.
