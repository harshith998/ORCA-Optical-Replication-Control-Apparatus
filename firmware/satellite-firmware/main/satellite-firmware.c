#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "as7343.h"
#include "esp_timer.h"

#define I2C_SCL_GPIO   19
#define I2C_SDA_GPIO   18
#define I2C_PORT       I2C_NUM_0

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(100));

    i2c_master_bus_config_t bus_cfg = {
        .clk_source               = I2C_CLK_SRC_DEFAULT,
        .i2c_port                 = I2C_PORT,
        .scl_io_num               = I2C_SCL_GPIO,
        .sda_io_num               = I2C_SDA_GPIO,
        .glitch_ignore_cnt        = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    /* Set gain and integration time in config BEFORE init —
     * init enables SP_EN so the first measurement must use
     * the correct settings to avoid saturation on Cycle 1. */
    as7343_config_t cfg = AS7343_CONFIG_DEFAULT;

    as7343_handle_t sensor;
    ESP_ERROR_CHECK(as7343_init(bus, &cfg, &sensor));

    as7343_channels_t ch;
    while (1) {

        int64_t timer = esp_timer_get_time();

        esp_err_t err = as7343_get_spectral_data(sensor, &ch);

        int64_t elapsed = esp_timer_get_time() - timer;

        if (err != ESP_OK) {
            printf("Read error: %s\n", esp_err_to_name(err));
        } else {
            printf("F1(405)=%5u  F2(425)=%5u  FZ(450)=%5u  F3(475)=%5u\n",
                   ch.f1, ch.f2, ch.fz, ch.f3);
            printf("F4(515)=%5u  F5(550)=%5u  FY(555)=%5u  F6(640)=%5u\n",
                   ch.f4, ch.f5, ch.fy, ch.f6);
            printf("FXL(600)=%4u  F7(690)=%5u  F8(745)=%5u  NIR(855)=%5u\n",
                   ch.fxl, ch.f7, ch.f8, ch.nir);
            printf("CLEAR=%5u\n\n", ch.clear);
            printf("Spectral request took %.3f milliseconds", elapsed / 1000.0);
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}