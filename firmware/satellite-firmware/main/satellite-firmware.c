#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_sleep.h"
#include "driver/i2c_master.h"
#include "as7343.h"

// ULP Dependencies
#include "lp_core_main.h"
#include "ulp_lp_core.h"
#include "lp_core_i2c.h"

#define I2C_SCL_GPIO   19
#define I2C_SDA_GPIO   18
#define I2C_PORT       LP_I2C_NUM_0

extern const uint8_t lp_core_main_bin_start[] asm("_binary_lp_core_main_bin_start");
extern const uint8_t lp_core_main_bin_end[]   asm("_binary_lp_core_main_bin_end");

static void lp_core_init(void)
{
    esp_err_t ret = ESP_OK;

    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_HP_CPU,
    };

    ret = ulp_lp_core_load_binary(lp_core_main_bin_start, (lp_core_main_bin_end - lp_core_main_bin_start));
    if (ret != ESP_OK) {
        printf("LP Core load failed\n");
        abort();
    }

    ret = ulp_lp_core_run(&cfg);
    if (ret != ESP_OK) {
        printf("LP Core run failed\n");
        abort();
    }

    printf("LP core loaded with firmware successfully\n");
}


static void lp_i2c_init(void)
{
    esp_err_t ret = ESP_OK;

    /* Initialize LP I2C with default configuration */
    const lp_core_i2c_cfg_t i2c_cfg = LP_CORE_I2C_DEFAULT_CONFIG();
    ret = lp_core_i2c_master_init(I2C_PORT, &i2c_cfg);
    if (ret != ESP_OK) {
        printf("LP I2C init failed\n");
        abort();
    }

    printf("LP I2C initialized successfully\n");
}

void app_main(void)
{
    // // Setup I2C Bus
    // i2c_master_bus_config_t bus_cfg = {
    //     .clk_source               = I2C_CLK_SRC_DEFAULT,
    //     .i2c_port                 = I2C_PORT,
    //     .scl_io_num               = I2C_SCL_GPIO,
    //     .sda_io_num               = I2C_SDA_GPIO,
    //     .glitch_ignore_cnt        = 7,
    //     .flags.enable_internal_pullup = true,
    // };
    // i2c_master_bus_handle_t bus;
    // ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    // // Setup AS7343 configuration
    // as7343_config_t cfg = AS7343_CONFIG_DEFAULT;
    // cfg.gain  = AS7343_GAIN_16X;
    // cfg.atime = 0;
    // cfg.astep = 599;

    // // AS7343 setup
    // as7343_handle_t sensor;
    // ESP_ERROR_CHECK(as7343_init(bus, &cfg, &sensor));

    // Checks if boot is due to LP core or full restart
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    if (cause == ESP_SLEEP_WAKEUP_ULP) {
        printf("LP core woke up the main CPU\n");

        // TODO: LP core wakes up the main CPU

    } else {
        printf("Not an LP core wakeup\n");
        printf("Initializing...\n");

        // TODO: Full restart wakes up the main CPU

        /* Initialize LP_I2C from the main processor */
        lp_i2c_init();

        /* Load LP Core binary and start the coprocessor */
        lp_core_init();
    }

    // 1. Enable the ULP as a wakeup source
    ESP_ERROR_CHECK(esp_sleep_enable_ulp_wakeup());

    // 2. Enter deep sleep
    printf("Entering deep sleep...\n");
    esp_deep_sleep_start();
}