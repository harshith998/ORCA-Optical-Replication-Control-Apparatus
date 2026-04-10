#include "rs_transciever.h"

#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_err.h"

// RS-485 pin configuration (mirrors satellite-firmware.cpp)
#define RS_SNS_PIN  GPIO_NUM_10   // Sense: HIGH = device connected
#define RS_EN_PIN   GPIO_NUM_23   // TX enable: HIGH = transmit
#define RS_TX_PIN   GPIO_NUM_16   // UART TX

// Share UART_NUM_1 with GPS (GPS uses RX=5, RS-485 uses TX=16 — no conflict)
#define RS_UART_NUM  UART_NUM_1
#define RS_BAUD_RATE 9600

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
    gpio_set_level(RS_EN_PIN, 0);  // Idle low (receive/off)

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

    // GPS (UART_NUM_1, RX=5) should already have the driver installed.
    // Just assign the TX pin and set our baud rate; GPS only uses RX so
    // there is no wire conflict.
    if (!uart_is_driver_installed(RS_UART_NUM)) {
        uart_config_t cfg = {
            .baud_rate  = RS_BAUD_RATE,
            .data_bits  = UART_DATA_8_BITS,
            .parity     = UART_PARITY_DISABLE,
            .stop_bits  = UART_STOP_BITS_1,
            .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
        };
        uart_param_config(RS_UART_NUM, &cfg);
        uart_driver_install(RS_UART_NUM, 256, 0, 0, NULL, 0);
    }
    uart_set_pin(RS_UART_NUM, RS_TX_PIN,
                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);

    // Build ASCII message between START / END delimiters
    char buf[512];
    int n = 0;

    n += snprintf(buf + n, sizeof(buf) - n, "START\n");

    n += snprintf(buf + n, sizeof(buf) - n,
        "sample_count:%" PRIu32 "\n", payload->sample_count);

    n += snprintf(buf + n, sizeof(buf) - n,
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
        "clear:%" PRIu16 "\n",
        payload->avg_f1,  payload->avg_f2,  payload->avg_fz,
        payload->avg_f3,  payload->avg_f4,  payload->avg_f5,
        payload->avg_fy,  payload->avg_f6,  payload->avg_fxl,
        payload->avg_f7,  payload->avg_f8,  payload->avg_nir,
        payload->avg_clear);

    n += snprintf(buf + n, sizeof(buf) - n,
        "gps_valid:%d,lat:%.6f,lon:%.6f,time:%" PRIu32 "\n",
        (int)payload->gps.valid,
        payload->gps.latitude_deg,
        payload->gps.longitude_deg,
        payload->gps.unix_time);

    n += snprintf(buf + n, sizeof(buf) - n, "END\n");

    if (n >= (int)sizeof(buf)) return false;  // Overflowed

    // Assert TX enable, send, wait for drain, release
    gpio_set_level(RS_EN_PIN, 1);
    uart_write_bytes(RS_UART_NUM, buf, n);
    uart_wait_tx_done(RS_UART_NUM, pdMS_TO_TICKS(500));
    gpio_set_level(RS_EN_PIN, 0);

    return true;
}
