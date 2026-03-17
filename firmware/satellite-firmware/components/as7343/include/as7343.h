/*
 * AS7343 14-Channel Multi-Spectral Sensor – ESP-IDF v5.x driver
 * Modelled on K0I05/ESP32-S3_ESP-IDF_COMPONENTS / esp_as7341
 */

#ifndef __AS7343_H__
#define __AS7343_H__

#include <stdint.h>
#include <stdbool.h>
#include <esp_err.h>
#include <driver/i2c_master.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── I²C defaults ─────────────────────────────────────────────────────────── */
#define I2C_AS7343_DEV_ADDR         UINT8_C(0x39)
#define I2C_AS7343_DEV_CLK_SPD      UINT32_C(100000)

/* ── Default config macro ─────────────────────────────────────────────────── *
 * atime=29, astep=599 → t_int = (29+1)×(599+1)×2.78µs ≈ 50 ms              */
#define AS7343_CONFIG_DEFAULT {                     \
    .i2c_address     = I2C_AS7343_DEV_ADDR,         \
    .i2c_clock_speed = I2C_AS7343_DEV_CLK_SPD,      \
    .gain            = AS7343_GAIN_64X,              \
    .atime           = 0,                            \
    .astep           = 599,                          \
}

/* ── Gain ─────────────────────────────────────────────────────────────────── */
typedef enum {
    AS7343_GAIN_0_5X  = 0,
    AS7343_GAIN_1X    = 1,
    AS7343_GAIN_2X    = 2,
    AS7343_GAIN_4X    = 3,
    AS7343_GAIN_8X    = 4,
    AS7343_GAIN_16X   = 5,
    AS7343_GAIN_32X   = 6,
    AS7343_GAIN_64X   = 7,
    AS7343_GAIN_128X  = 8,
    AS7343_GAIN_256X  = 9,
    AS7343_GAIN_512X  = 10,
    AS7343_GAIN_1024X = 11,
    AS7343_GAIN_2048X = 12,
} as7343_gain_t;

/* ── Channel data ─────────────────────────────────────────────────────────── */
typedef struct {
    uint16_t f1;    /* ~405 nm */
    uint16_t f2;    /* ~425 nm */
    uint16_t f3;    /* ~475 nm */
    uint16_t f4;    /* ~515 nm */
    uint16_t f5;    /* ~550 nm */
    uint16_t f6;    /* ~640 nm */
    uint16_t f7;    /* ~690 nm */
    uint16_t f8;    /* ~745 nm */
    uint16_t fz;    /* ~450 nm */
    uint16_t fy;    /* ~555 nm */
    uint16_t fxl;   /* ~600 nm */
    uint16_t nir;   /* ~855 nm */
    uint16_t clear; /* broadband */
} as7343_channels_t;

/* ── Config ───────────────────────────────────────────────────────────────── */
typedef struct {
    uint16_t      i2c_address;
    uint32_t      i2c_clock_speed;
    as7343_gain_t gain;
    uint8_t       atime;
    uint16_t      astep;
} as7343_config_t;

/* ── Opaque handle ────────────────────────────────────────────────────────── */
typedef void *as7343_handle_t;

/* ── API ──────────────────────────────────────────────────────────────────── */
esp_err_t as7343_init(i2c_master_bus_handle_t bus_handle,
                      const as7343_config_t *config,
                      as7343_handle_t *handle);

esp_err_t as7343_get_spectral_data(as7343_handle_t handle,
                                   as7343_channels_t *channels);

esp_err_t as7343_set_gain(as7343_handle_t handle, as7343_gain_t gain);

esp_err_t as7343_set_integration_time(as7343_handle_t handle,
                                      uint8_t atime, uint16_t astep);

esp_err_t as7343_remove(as7343_handle_t handle);
esp_err_t as7343_delete(as7343_handle_t handle);

#ifdef __cplusplus
}
#endif

#endif /* __AS7343_H__ */