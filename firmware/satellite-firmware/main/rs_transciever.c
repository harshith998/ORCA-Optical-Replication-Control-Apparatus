#include "rs_transciever.h"

#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// RS-485 pin configuration (mirrors satellite-firmware.cpp)
#define RS_SNS_PIN  GPIO_NUM_10   // Sense: HIGH = device connected
#define RS_EN_PIN   GPIO_NUM_23   // TX enable: HIGH = drive RS-485 bus

// RS_TX is GPIO_NUM_16, which is also the console UART0 TX pin.
// We do NOT reassign it — printf already drives it. We only need RS_EN
// to gate the RS-485 transceiver.

// -----------------------------------------------------------------------

static bool s_gpio_ready = false;

static void init_gpio(void)
{
    if (s_gpio_ready) return;

    gpio_config_t sns_cfg = {
        .pin_bit_mask = (1ULL << RS_SNS_PIN),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&sns_cfg);

    gpio_config_t en_cfg = {
        .pin_bit_mask = (1ULL << RS_EN_PIN),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&en_cfg);
    gpio_set_level(RS_EN_PIN, 0);  // Idle low

    s_gpio_ready = true;
}

// -----------------------------------------------------------------------

bool is_connected(void)
{
    init_gpio();
    return gpio_get_level(RS_SNS_PIN) == 1;
}

bool rs485_send(const rs_report_payload_t *payload)
{
    if (!payload) return false;
    init_gpio();

    // Build single-line ASCII packet: START <fields> END
    char buf[512];
    int n = snprintf(buf, sizeof(buf),
        "START "
        "sample_count:%" PRIu32 ","
        "f1:%" PRIu16 ","
        "f2:%" PRIu16 ","
        "fz:%" PRIu16 ","
        "f3:%" PRIu16 ","
        "f4:%" PRIu16 ","
        "f5:%" PRIu16 ","
        "fy:%" PRIu16 ","
        "f6:%" PRIu16 ","
        "fxl:%" PRIu16 ","
        "f7:%" PRIu16 ","
        "f8:%" PRIu16 ","
        "nir:%" PRIu16 ","
        "clear:%" PRIu16 ","
        "gps_valid:%d,"
        "lat:%.6f,"
        "lon:%.6f,"
        "time:%" PRIu32
        " END\n",
        payload->sample_count,
        payload->avg_f1,  payload->avg_f2,  payload->avg_fz,
        payload->avg_f3,  payload->avg_f4,  payload->avg_f5,
        payload->avg_fy,  payload->avg_f6,  payload->avg_fxl,
        payload->avg_f7,  payload->avg_f8,  payload->avg_nir,
        payload->avg_clear,
        (int)payload->gps.valid,
        payload->gps.latitude_deg,
        payload->gps.longitude_deg,
        payload->gps.unix_time);

    if (n >= (int)sizeof(buf)) return false;  // Overflowed

    // Assert RS_EN to drive the RS-485 bus, send via the console UART
    // (GPIO 16 = UART0 TX = RS_TX — same pin, no reassignment needed),
    // then wait for the hardware TX FIFO to drain before releasing.
    gpio_set_level(RS_EN_PIN, 1);
    printf("%s", buf);
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(30));  // Wait for UART0 TX FIFO to drain (~17 ms at 115200)
    gpio_set_level(RS_EN_PIN, 0);

    return true;
}
