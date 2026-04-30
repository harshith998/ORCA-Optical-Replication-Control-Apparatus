# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# satellite-firmware

ESP-IDF project targeting the **ESP32-C6** (RISC-V architecture).

## Build & Flash

```bash
# Source IDF environment first (adjust path to your install)
. $IDF_PATH/export.sh

idf.py build
idf.py flash
idf.py monitor          # Ctrl-] to exit
idf.py flash monitor    # flash then immediately monitor
```

RadioLib is fetched automatically via the IDF component manager on first build (`idf_component.yml` pins it to v7.6.0+).

## Key hardware

| Peripheral | Interface | Pins |
|---|---|---|
| AS7343 spectral sensor | I2C @ 100 kHz | SDA=18, SCL=19, addr=0x39 |
| SX1262 LoRa radio | SPI @ 2 MHz | SCK=6, MISO=2, MOSI=7, CS=11, DIO1=20, RST=0, BUSY=3 |
| GPS module | UART1 @ 115200 | RX=5, TX=4, RESET_N=1 |

## LoRa config

- Frequency: 915.0 MHz, Bandwidth: 250 kHz, SF: 9, CR: 7, Sync: 0x12

## Deep-sleep / sampling model

`app_main` runs once per wakeup, then calls `esp_deep_sleep_start()`.

- `TRANSMIT_CYCLE_MS` (10000 ms) / `SAMPLES_PER_TRANSMIT` (2) = `SAMPLING_CYCLE_MS` sleep interval
- Each wakeup reads the AS7343 once and accumulates into RTC sums
- When `cycle_sample_count >= SAMPLES_PER_TRANSMIT`: attempt GPS fix, build and send LoRa packet, clear accumulators
- RTC state is validated on boot with magic `0xA53443D1` + version `1`; mismatches reset all accumulators

## Data flow

```
wake → validate RTC state → init I2C + AS7343 → read 13 spectral channels
     → accumulate into RTC sums → if transmit due:
           → poll GPS (UART, up to 5 s) → build report_payload_t → SPI LoRa TX
           → clear RTC accumulators
     → configure timer wakeup → deep sleep
```

## LoRa payload layout (51 bytes, little-endian)

| Field | Type | Size |
|---|---|---|
| sample_count | uint32 | 4 |
| avg_f1..f8, fz, f3–f5, fy, fxl, nir, clear | 13 × uint16 | 26 |
| gps.valid | uint8 | 1 |
| latitude_deg | double | 8 |
| longitude_deg | double | 8 |
| unix_time | uint32 | 4 |

A `static_assert` in `lora_send_report` enforces this size at compile time.

## AS7343 spectral sensor

Reads 13 channels in 18-channel auto-SMUX mode (3 measurement cycles per integration). The driver does a single 37-byte I2C burst read from register `0x94` to latch all channels simultaneously and avoid data overwrite. Registers are bank-switched via CFG0: addresses `0x80+` are bank 0, `<0x80` are bank 1.

Default config: gain=256×, atime=0, astep=599 → ~1.67 ms integration time.

## GPS behavior

- Each transmit cycle begins by pulsing RESET_N (GPIO1) low for 100 ms to wake the module from backup mode, then releases to input (module has internal 1.8 V pull-up; no external pull-up allowed). GPIO1 drives the base of Q1 (NPN MMBT3904) through R7 (4.7k), so the signal is inverted: GPIO1 must be driven **HIGH** to pull RESET_N low, then LOW to release it.
- Blocks in a polling loop for up to `GPS_LOCK_TIMEOUT_MS` (5 s) waiting for valid NMEA fix + datetime
- On valid fix: sends `$PAIR650,0*25` over UART TX to put the module into Backup Mode (Method 2, ~35 µA) before deep sleep; V_BCKP remains powered to preserve satellite data for warm start
- On timeout, `gps_fix_t.valid = false`, packet is transmitted anyway, and the GPS is left in continuous mode
- Timezone forced to `UTC0`; parsed from RMC + GGA + GSA + VTG sentences

## EspHal.h

RadioLib HAL for the ESP32-C6. Uses `spi_master` IDF driver (SPI2_HOST), `driver/gpio.h` (not ROM headers), and `esp_timer_get_time()` for microsecond timing. GPIO ISR registered with `ESP_INTR_FLAG_IRAM` for safety on RISC-V.

## rs_transciever.cpp

Currently an empty placeholder file. Intended for future RS-485 comms (see TODO comment at end of `satellite-firmware.cpp`). Not compiled yet.
