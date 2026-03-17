/*
 * AS7343 14-Channel Multi-Spectral Sensor – ESP-IDF v5.x driver
 * Based on SparkFun AS7343 Arduino Library (MIT License)
 * https://github.com/sparkfun/SparkFun_AS7343_Arduino_Library
 */

#include "include/as7343.h"

#include <stdlib.h>
#include <string.h>
#include <esp_log.h>
#include <esp_check.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

static const char *TAG = "AS7343";

/* ── Timing ───────────────────────────────────────────────────────────────── */
#define AS7343_POWERUP_DELAY_MS     UINT16_C(200)
#define AS7343_APPSTART_DELAY_MS    UINT16_C(200)
#define AS7343_CMD_DELAY_MS         UINT16_C(5)
#define AS7343_DATA_READY_DELAY_MS  UINT16_C(1)
#define AS7343_POLL_TIMEOUT_MS      UINT16_C(2000)
#define I2C_XFR_TIMEOUT_MS          (500)

#define ESP_ARG_CHECK(VAL) do { if (!(VAL)) return ESP_ERR_INVALID_ARG; } while (0)
#define ESP_TIMEOUT_CHECK(start, len) ((uint64_t)(esp_timer_get_time() - (start)) >= (len))

/* ── Register addresses ───────────────────────────────────────────────────── */
#define AS7343_REG_ENABLE       UINT8_C(0x80)
#define AS7343_REG_ATIME        UINT8_C(0x81)
#define AS7343_REG_STATUS2      UINT8_C(0x90)
#define AS7343_REG_DATA0        UINT8_C(0x95)   /* first of 18×2 data bytes  */
#define AS7343_REG_CFG0         UINT8_C(0xBF)
#define AS7343_REG_CFG1         UINT8_C(0xC6)
#define AS7343_REG_CFG20        UINT8_C(0xD6)   /* auto_smux bits [6:5]       */
#define AS7343_REG_ASTEP_L      UINT8_C(0xD4)
#define AS7343_REG_ASTEP_H      UINT8_C(0xD5)
#define AS7343_REG_ID           UINT8_C(0x5A)   /* bank-1                     */

#define AS7343_PART_ID          UINT8_C(0x81)

/*
 * auto_smux=3 channel order in DATA registers (from SparkFun library header):
 *   Cycle 1: FZ, FY, FXL, NIR, VIS1, FD1    → DATA_0  .. DATA_5
 *   Cycle 2: F2, F3, F4,  F6,  VIS2, FD2    → DATA_6  .. DATA_11
 *   Cycle 3: F1, F7, F8,  F5,  VIS3, FD3    → DATA_12 .. DATA_17
 *
 * Each DATA register is 2 bytes (little-endian), so 36 bytes total from 0x95.
 */
#define CH_FZ    0
#define CH_FY    1
#define CH_FXL   2
#define CH_NIR   3
#define CH_VIS1  4
/* CH_FD1 = 5 – skipped */
#define CH_F2    6
#define CH_F3    7
#define CH_F4    8
#define CH_F6    9
#define CH_VIS2  10
/* CH_FD2 = 11 – skipped */
#define CH_F1    12
#define CH_F7    13
#define CH_F8    14
#define CH_F5    15
#define CH_VIS3  16
/* CH_FD3 = 17 – skipped */

/* ── Register bitfield unions ─────────────────────────────────────────────── */

typedef union __attribute__((packed)) {
    struct {
        bool    power_on:1;
        bool    spectral_enabled:1;
        uint8_t reserved1:1;
        bool    wait_enabled:1;
        bool    smux_enabled:1;
        uint8_t reserved2:1;
        bool    flicker_enabled:1;
        uint8_t reserved3:1;
    } bits;
    uint8_t reg;
} as7343_enable_reg_t;

typedef union __attribute__((packed)) {
    struct {
        uint8_t reserved1:2;
        uint8_t wlong:1;
        uint8_t reserved2:1;
        uint8_t reg_bank:1;   /* 0=bank0 (≥0x80), 1=bank1 (0x58–0x66) */
        uint8_t low_power:1;
        uint8_t reserved3:2;
    } bits;
    uint8_t reg;
} as7343_cfg0_reg_t;

typedef union __attribute__((packed)) {
    struct {
        uint8_t again:5;
        uint8_t reserved:3;
    } bits;
    uint8_t reg;
} as7343_cfg1_reg_t;

typedef union __attribute__((packed)) {
    struct {
        uint8_t reserved1:5;  /* bits [4:0] */
        uint8_t auto_smux:2;  /* bits [6:5]: 0=6ch, 2=12ch, 3=18ch */
        uint8_t fd_fifo_8b:1; /* bit  [7]   */
    } bits;
    uint8_t reg;
} as7343_cfg20_reg_t;

typedef union __attribute__((packed)) {
    struct {
        uint8_t fdsat_digital:1;
        uint8_t fdsat_analog:1;
        uint8_t reserved1:1;
        uint8_t asat_analog:1;
        uint8_t asat_digital:1;
        uint8_t reserved2:1;
        bool    avalid:1;
        uint8_t reserved3:1;
    } bits;
    uint8_t reg;
} as7343_status2_reg_t;

/* ── Device struct ────────────────────────────────────────────────────────── */
typedef struct {
    i2c_master_dev_handle_t i2c_handle;
    as7343_config_t         config;
} as7343_device_t;

/* ════════════════════════════════════════════════════════════════════════════
 * I²C HAL
 * ════════════════════════════════════════════════════════════════════════════ */

static inline esp_err_t as7343_i2c_write_byte(as7343_device_t *dev,
                                               uint8_t reg, uint8_t val)
{
    uint8_t tx[2] = { reg, val };
    ESP_RETURN_ON_ERROR(
        i2c_master_transmit(dev->i2c_handle, tx, sizeof(tx), I2C_XFR_TIMEOUT_MS),
        TAG, "i2c write 0x%02X=0x%02X failed", reg, val);
    return ESP_OK;
}

static inline esp_err_t as7343_i2c_read_bytes(as7343_device_t *dev,
                                               uint8_t reg,
                                               uint8_t *buf, size_t len)
{
    ESP_RETURN_ON_ERROR(
        i2c_master_transmit_receive(dev->i2c_handle,
                                    &reg, 1, buf, len, I2C_XFR_TIMEOUT_MS),
        TAG, "i2c read %u bytes from 0x%02X failed", (unsigned)len, reg);
    return ESP_OK;
}

static inline esp_err_t as7343_i2c_read_byte(as7343_device_t *dev,
                                              uint8_t reg, uint8_t *val)
{
    return as7343_i2c_read_bytes(dev, reg, val, 1);
}

/* ── Bank switching (matches SparkFun readRegisterBank logic) ─────────────── *
 * Registers ≥ 0x80 → bank 0.  Registers < 0x80 → bank 1.                   */
static inline esp_err_t as7343_set_bank(as7343_device_t *dev, uint8_t bank)
{
    as7343_cfg0_reg_t cfg0 = { .reg = 0 };
    /* CFG0 is at 0xBF so always accessible from bank-0 */
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_CFG0, &cfg0.reg),
                        TAG, "read CFG0 failed");
    cfg0.bits.reg_bank = bank & 1;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_CFG0, cfg0.reg),
                        TAG, "write CFG0 bank=%u failed", bank);
    return ESP_OK;
}

/* ── Poll AVALID ──────────────────────────────────────────────────────────── */
static esp_err_t as7343_wait_avalid(as7343_device_t *dev)
{
    const uint64_t t0 = esp_timer_get_time();
    while (true) {
        as7343_status2_reg_t s2 = { .reg = 0 };
        ESP_RETURN_ON_ERROR(
            as7343_i2c_read_byte(dev, AS7343_REG_STATUS2, &s2.reg),
            TAG, "read STATUS2 failed");
        if (s2.bits.avalid) {
            if (s2.bits.asat_analog || s2.bits.asat_digital)
                ESP_LOGW(TAG, "Saturation (STATUS2=0x%02X) – "
                              "reduce gain or integration time", s2.reg);
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(AS7343_DATA_READY_DELAY_MS));
        if (ESP_TIMEOUT_CHECK(t0, (uint64_t)AS7343_POLL_TIMEOUT_MS * 1000)) {
            ESP_LOGE(TAG, "Timeout waiting for AVALID");
            return ESP_ERR_TIMEOUT;
        }
    }
}

/* ════════════════════════════════════════════════════════════════════════════
 * Register setup
 * ════════════════════════════════════════════════════════════════════════════ */
static esp_err_t as7343_setup_registers(as7343_device_t *dev)
{
    /* 1. Ensure bank-0 */
    ESP_RETURN_ON_ERROR(as7343_set_bank(dev, 0), TAG, "set bank0 failed");

    /* 2. PON=1 */
    as7343_enable_reg_t en = { .reg = 0 };
    en.bits.power_on = true;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write PON failed");
    vTaskDelay(pdMS_TO_TICKS(AS7343_CMD_DELAY_MS));

    /* 3. Verify part ID (bank-1) */
    ESP_RETURN_ON_ERROR(as7343_set_bank(dev, 1), TAG, "set bank1 for ID failed");
    uint8_t id = 0;
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_ID, &id),
                        TAG, "read ID failed");
    ESP_RETURN_ON_ERROR(as7343_set_bank(dev, 0), TAG, "restore bank0 failed");

    if (id != AS7343_PART_ID) {
        ESP_LOGE(TAG, "Wrong part ID: 0x%02X (expected 0x%02X)", id, AS7343_PART_ID);
        return ESP_ERR_NOT_FOUND;
    }
    ESP_LOGI(TAG, "AS7343 found (ID=0x%02X)", id);

    /* 4. ATIME */
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ATIME,
                                               dev->config.atime),
                        TAG, "write ATIME failed");

    /* 5. ASTEP (LSB first) */
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ASTEP_L,
                                               (uint8_t)(dev->config.astep & 0xFF)),
                        TAG, "write ASTEP_L failed");
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ASTEP_H,
                                               (uint8_t)(dev->config.astep >> 8)),
                        TAG, "write ASTEP_H failed");

    /* 6. Gain */
    as7343_cfg1_reg_t cfg1 = { .reg = 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_CFG1, &cfg1.reg),
                        TAG, "read CFG1 failed");
    cfg1.bits.again = (uint8_t)dev->config.gain;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_CFG1, cfg1.reg),
                        TAG, "write CFG1 failed");

    /* 7. auto_smux = 3 → 18-channel mode
     *    Must be set before SP_EN=1 and must not change during measurement */
    as7343_cfg20_reg_t cfg20 = { .reg = 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_CFG20, &cfg20.reg),
                        TAG, "read CFG20 failed");
    cfg20.bits.auto_smux = 3;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_CFG20, cfg20.reg),
                        TAG, "write CFG20 auto_smux=3 failed");

    /* Verify CFG20 was written correctly */
    uint8_t cfg20_verify = 0;
    as7343_i2c_read_byte(dev, AS7343_REG_CFG20, &cfg20_verify);
    ESP_LOGI(TAG, "CFG20 written=0x%02X readback=0x%02X (auto_smux bits=%d)",
             cfg20.reg, cfg20_verify, (cfg20_verify >> 5) & 0x3);

    /* 8. SP_EN=1 — leave spectral measurement running continuously,
     *    exactly as the SparkFun library does.
     *    Delay afterwards to let the first full 3-cycle auto_smux pass complete
     *    before any read is attempted. */
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_ENABLE, &en.reg),
                        TAG, "read ENABLE for SP_EN failed");
    en.bits.spectral_enabled = true;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write SP_EN=1 failed");

    /* Wait for first complete measurement cycle (3 × t_int + margin) */
    uint32_t t_int_us = (uint32_t)(dev->config.atime + 1) *
                        (uint32_t)(dev->config.astep + 1) * 278 / 100; /* ×2.78 µs */
    uint32_t t_int_ms = (t_int_us * 3) / 1000 + 50;
    vTaskDelay(pdMS_TO_TICKS(t_int_ms));

    ESP_LOGI(TAG, "Setup complete: gain=%d atime=%u astep=%u auto_smux=3",
             dev->config.gain, dev->config.atime, dev->config.astep);
    return ESP_OK;
}

/* ════════════════════════════════════════════════════════════════════════════
 * Public API
 * ════════════════════════════════════════════════════════════════════════════ */

esp_err_t as7343_init(i2c_master_bus_handle_t bus_handle,
                      const as7343_config_t *config,
                      as7343_handle_t *handle)
{
    ESP_ARG_CHECK(bus_handle && config && handle);

    vTaskDelay(pdMS_TO_TICKS(AS7343_POWERUP_DELAY_MS));

    esp_err_t ret = i2c_master_probe(bus_handle, config->i2c_address,
                                     I2C_XFR_TIMEOUT_MS);
    ESP_GOTO_ON_ERROR(ret, err, TAG, "probe failed at 0x%02X", config->i2c_address);

    as7343_device_t *dev = (as7343_device_t *)calloc(1, sizeof(as7343_device_t));
    ESP_GOTO_ON_FALSE(dev, ESP_ERR_NO_MEM, err, TAG, "no memory");

    dev->config = *config;

    const i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address  = config->i2c_address,
        .scl_speed_hz    = config->i2c_clock_speed,
    };
    ESP_GOTO_ON_ERROR(i2c_master_bus_add_device(bus_handle, &dev_cfg,
                                                 &dev->i2c_handle),
                      err_free, TAG, "add device failed");

    vTaskDelay(pdMS_TO_TICKS(AS7343_CMD_DELAY_MS));

    ESP_GOTO_ON_ERROR(as7343_setup_registers(dev),
                      err_handle, TAG, "setup_registers failed");

    *handle = (as7343_handle_t)dev;
    vTaskDelay(pdMS_TO_TICKS(AS7343_APPSTART_DELAY_MS));
    return ESP_OK;

err_handle:
    i2c_master_bus_rm_device(dev->i2c_handle);
err_free:
    free(dev);
err:
    return ret;
}

esp_err_t as7343_get_spectral_data(as7343_handle_t handle,
                                   as7343_channels_t *channels)
{
    as7343_device_t *dev = (as7343_device_t *)handle;
    ESP_ARG_CHECK(dev && channels);

    /* Wait for a complete 3-cycle auto_smux measurement before reading.
     * t_int per cycle = (ATIME+1) × (ASTEP+1) × 2.78 µs  (datasheet eq. 1)
     * Total for 3 cycles + 50 ms margin. */
    uint32_t t_int_us = (uint32_t)(dev->config.atime + 1) *
                        (uint32_t)(dev->config.astep + 1) * 278 / 100; /* ×2.78 µs */
    uint32_t delay_ms = (t_int_us * 3) / 1000 + 50;
    vTaskDelay(pdMS_TO_TICKS(delay_ms));

    /* Ensure bank-0 before read (matches SparkFun readSpectraDataFromSensor) */
    ESP_RETURN_ON_ERROR(as7343_set_bank(dev, 0), TAG, "set bank0 before read failed");

    /* Datasheet section 10.2.7: reading ASTATUS (0x94) latches all 36 spectral
     * data bytes, and those bytes must be read consecutively in the SAME I²C
     * transaction. Two separate transactions allow the sensor to overwrite
     * cycle-1 DATA registers (FZ/FY/FXL/NIR/CLEAR) between the reads, producing
     * zeros on those channels. Fix: single 37-byte burst from 0x94. */
    uint8_t buf[37] = { 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_bytes(dev, 0x94, buf, sizeof(buf)),
                        TAG, "burst read ASTATUS+data failed");

    uint8_t astatus = buf[0];          /* ASTATUS at 0x94          */
    uint8_t *raw    = &buf[1];         /* DATA_0..DATA_17 at 0x95+ */
    (void)astatus;                     /* suppress unused-variable warning */

#define RD16(ch) ((uint16_t)raw[(ch)*2] | ((uint16_t)raw[(ch)*2+1] << 8))

    /* Map channels per auto_smux=3 order (SparkFun header, lines 70-72):
     * Cycle 1: FZ, FY, FXL, NIR, VIS, FD
     * Cycle 2: F2, F3, F4,  F6,  VIS, FD
     * Cycle 3: F1, F7, F8,  F5,  VIS, FD */
    channels->fz    = RD16(CH_FZ);
    channels->fy    = RD16(CH_FY);
    channels->fxl   = RD16(CH_FXL);
    channels->nir   = RD16(CH_NIR);
    channels->clear = RD16(CH_VIS1);
    channels->f2    = RD16(CH_F2);
    channels->f3    = RD16(CH_F3);
    channels->f4    = RD16(CH_F4);
    channels->f6    = RD16(CH_F6);
    channels->f1    = RD16(CH_F1);
    channels->f7    = RD16(CH_F7);
    channels->f8    = RD16(CH_F8);
    channels->f5    = RD16(CH_F5);

#undef RD16

    return ESP_OK;
}

esp_err_t as7343_set_gain(as7343_handle_t handle, as7343_gain_t gain)
{
    as7343_device_t *dev = (as7343_device_t *)handle;
    ESP_ARG_CHECK(dev);

    /* Must disable SP_EN before changing gain */
    as7343_enable_reg_t en = { .reg = 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_ENABLE, &en.reg),
                        TAG, "read ENABLE failed");
    en.bits.spectral_enabled = false;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write SP_EN=0 failed");

    as7343_cfg1_reg_t cfg1 = { .reg = 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_CFG1, &cfg1.reg),
                        TAG, "read CFG1 failed");
    cfg1.bits.again = (uint8_t)gain;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_CFG1, cfg1.reg),
                        TAG, "write CFG1 failed");
    dev->config.gain = gain;

    /* Re-enable SP_EN */
    en.bits.spectral_enabled = true;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write SP_EN=1 failed");
    return ESP_OK;
}

esp_err_t as7343_set_integration_time(as7343_handle_t handle,
                                      uint8_t atime, uint16_t astep)
{
    as7343_device_t *dev = (as7343_device_t *)handle;
    ESP_ARG_CHECK(dev);
    if (atime == 0 && astep == 0) return ESP_ERR_INVALID_ARG;

    /* Must disable SP_EN before changing timing */
    as7343_enable_reg_t en = { .reg = 0 };
    ESP_RETURN_ON_ERROR(as7343_i2c_read_byte(dev, AS7343_REG_ENABLE, &en.reg),
                        TAG, "read ENABLE failed");
    en.bits.spectral_enabled = false;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write SP_EN=0 failed");

    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ATIME, atime),
                        TAG, "write ATIME failed");
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ASTEP_L,
                                               (uint8_t)(astep & 0xFF)),
                        TAG, "write ASTEP_L failed");
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ASTEP_H,
                                               (uint8_t)(astep >> 8)),
                        TAG, "write ASTEP_H failed");
    dev->config.atime = atime;
    dev->config.astep = astep;

    /* Re-enable SP_EN */
    en.bits.spectral_enabled = true;
    ESP_RETURN_ON_ERROR(as7343_i2c_write_byte(dev, AS7343_REG_ENABLE, en.reg),
                        TAG, "write SP_EN=1 failed");
    return ESP_OK;
}

esp_err_t as7343_remove(as7343_handle_t handle)
{
    as7343_device_t *dev = (as7343_device_t *)handle;
    ESP_ARG_CHECK(dev);
    if (dev->i2c_handle) {
        esp_err_t ret = i2c_master_bus_rm_device(dev->i2c_handle);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "rm_device failed: %s", esp_err_to_name(ret));
            return ret;
        }
        dev->i2c_handle = NULL;
    }
    return ESP_OK;
}

esp_err_t as7343_delete(as7343_handle_t handle)
{
    ESP_ARG_CHECK(handle);
    esp_err_t ret = as7343_remove(handle);
    free(handle);
    return ret;
}