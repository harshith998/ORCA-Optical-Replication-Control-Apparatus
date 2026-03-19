#ifndef ESP_HAL_H
#define ESP_HAL_H

#include <RadioLib.h>

// Target guard: ESP32-C6 only (RISC-V, IDF target = esp32c6)
#if CONFIG_IDF_TARGET_ESP32C6 == 0
  #error This HAL targets ESP32-C6 only.
#endif

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
// ROM GPIO header path changed on C6 — use the soc-agnostic driver instead
#include "driver/gpio.h"
#include "driver/spi_master.h"   // C6 does NOT expose raw spi_dev_t safely; use the driver
#include "hal/gpio_hal.h"
#include "hal/spi_hal.h"
#include "soc/gpio_sig_map.h"    // C6-specific GPIO matrix signal indices
#include "soc/soc.h"
#include "soc/rtc.h"
// DPORT_* registers do not exist on C6 (RISC-V); clock gating uses PCR peripheral
#include "soc/pcr_reg.h"
#include "esp_timer.h"
#include "esp_log.h"

// Arduino-style macros
#define LOW                      (0x0)
#define HIGH                     (0x1)
#define INPUT                    (0x01)
#define OUTPUT                   (0x03)
#define RISING                   (0x01)
#define FALLING                  (0x02)
#define NOP()                    asm volatile ("nop")

// GPIO matrix detach sentinels (same values on C6)
#define MATRIX_DETACH_OUT_SIG    (0x100)
#define MATRIX_DETACH_IN_LOW_PIN (0x3C)   // C6 uses 0x3C, not 0x30

// ── SPI clock divider ────────────────────────────────────────────────────────
// On C6 the APB clock is always 80 MHz when the CPU runs at full speed,
// but rtc_clk_apb_freq_get() is the correct portable call.
uint32_t getApbFrequency() {
  // rtc_clk_apb_freq_get() is available on all modern IDF targets including C6
  return rtc_clk_apb_freq_get();
}

// The raw SPI register layout changed on C6.  Rather than bit-banging clock
// divider registers directly we use the IDF spi_master driver (see spiBegin).
// This helper is kept only for reference / documentation; it is no longer
// called from spiBegin below.
uint32_t spiFrequencyToClockDiv(uint32_t freq) {
  uint32_t apb = getApbFrequency();
  if (freq >= apb) return 0;          // eq-sysclk flag in driver terms
  uint32_t div = apb / freq;
  if (div < 2)  div = 2;
  if (div > 8192) div = 8192;
  return div;                         // used as pre-divider value
}

// ── HAL class ────────────────────────────────────────────────────────────────
class EspHal : public RadioLibHal {
public:
  EspHal(int8_t sck, int8_t miso, int8_t mosi)
    : RadioLibHal(INPUT, OUTPUT, LOW, HIGH, RISING, FALLING),
      spiSCK(sck), spiMISO(miso), spiMOSI(mosi) {}

  void init() override {
    spiBegin();
  }

  void term() override {
    spiEnd();
  }

  // ── GPIO ──────────────────────────────────────────────────────────────────
  void pinMode(uint32_t pin, uint32_t mode) override {
    if (pin == RADIOLIB_NC) return;

    gpio_config_t conf = {
      .pin_bit_mask  = (1ULL << pin),
      .mode          = (gpio_mode_t)mode,
      .pull_up_en    = GPIO_PULLUP_DISABLE,
      .pull_down_en  = GPIO_PULLDOWN_DISABLE,
      // preserve existing interrupt type rather than clobbering it
      .intr_type     = GPIO_INTR_DISABLE,
    };
    gpio_config(&conf);
  }

  void digitalWrite(uint32_t pin, uint32_t value) override {
    if (pin == RADIOLIB_NC) return;
    gpio_set_level((gpio_num_t)pin, value);
  }

  uint32_t digitalRead(uint32_t pin) override {
    if (pin == RADIOLIB_NC) return 0;
    return gpio_get_level((gpio_num_t)pin);
  }

  void attachInterrupt(uint32_t interruptNum,
                       void (*interruptCb)(void),
                       uint32_t mode) override {
    if (interruptNum == RADIOLIB_NC) return;

    // ESP_INTR_FLAG_IRAM keeps ISR in IRAM — safe on C6 as well
    gpio_install_isr_service((int)ESP_INTR_FLAG_IRAM);
    gpio_set_intr_type((gpio_num_t)interruptNum,
                       (gpio_int_type_t)(mode & 0x7));
    gpio_isr_handler_add((gpio_num_t)interruptNum,
                         (void (*)(void *))interruptCb, NULL);
  }

  void detachInterrupt(uint32_t interruptNum) override {
    if (interruptNum == RADIOLIB_NC) return;
    gpio_isr_handler_remove((gpio_num_t)interruptNum);
    gpio_wakeup_disable((gpio_num_t)interruptNum);
    gpio_set_intr_type((gpio_num_t)interruptNum, GPIO_INTR_DISABLE);
  }

  // ── Timing ────────────────────────────────────────────────────────────────
  void delay(unsigned long ms) override {
    vTaskDelay(ms / portTICK_PERIOD_MS);
  }

  void delayMicroseconds(unsigned long us) override {
    uint64_t m = (uint64_t)esp_timer_get_time();
    if (us) {
      uint64_t e = m + us;
      if (m > e) {   // 64-bit overflow (takes ~584 years, but be safe)
        while ((uint64_t)esp_timer_get_time() > e) NOP();
      }
      while ((uint64_t)esp_timer_get_time() < e) NOP();
    }
  }

  unsigned long millis() override {
    return (unsigned long)(esp_timer_get_time() / 1000ULL);
  }

  unsigned long micros() override {
    return (unsigned long)(esp_timer_get_time());
  }

  long pulseIn(uint32_t pin, uint32_t state,
               unsigned long timeout) override {
    if (pin == RADIOLIB_NC) return 0;
    this->pinMode(pin, INPUT);
    uint32_t start   = this->micros();
    uint32_t curtick = this->micros();
    while (this->digitalRead(pin) == state) {
      if ((this->micros() - curtick) > timeout) return 0;
    }
    return this->micros() - start;
  }

  // ── SPI ───────────────────────────────────────────────────────────────────
  // The ESP32-C6 dropped the legacy HSPI/VSPI peripheral names and changed
  // the raw SPI register map.  The safest approach on IDF is the spi_master
  // driver which abstracts all of that away cleanly.
  void spiBegin() {
    spi_bus_config_t buscfg = {
      .mosi_io_num   = spiMOSI,
      .miso_io_num   = spiMISO,
      .sclk_io_num   = spiSCK,
      .quadwp_io_num = -1,
      .quadhd_io_num = -1,
      .max_transfer_sz = 64,
    };

    // SPI2_HOST is the general-purpose SPI on C6 (replaces HSPI on classic ESP32)
    spi_bus_initialize(SPI2_HOST, &buscfg, SPI_DMA_DISABLED);

    spi_device_interface_config_t devcfg = {
      .mode           = 0,               // SPI mode 0 (CPOL=0, CPHA=0)
      .clock_speed_hz = 2000000,         // 2 MHz — same as original
      .spics_io_num   = -1,              // CS managed by RadioLib
      .queue_size     = 1,
    };

    spi_bus_add_device(SPI2_HOST, &devcfg, &spiHandle);
  }

  void spiBeginTransaction() {
    // Nothing needed; IDF driver handles this per-transfer
  }

  uint8_t spiTransferByte(uint8_t b) {
    uint8_t rxByte = 0;
    spi_transaction_t t = {
      .length    = 8,         // bits
      .tx_buffer = &b,
      .rx_buffer = &rxByte,
    };
    spi_device_polling_transmit(spiHandle, &t);
    return rxByte;
  }

  void spiTransfer(uint8_t* out, size_t len, uint8_t* in) {
    for (size_t i = 0; i < len; i++) {
      in[i] = spiTransferByte(out[i]);
    }
  }

  void spiEndTransaction() {
    // Nothing needed
  }

  void spiEnd() {
    spi_bus_remove_device(spiHandle);
    spi_bus_free(SPI2_HOST);
  }

private:
  int8_t           spiSCK;
  int8_t           spiMISO;
  int8_t           spiMOSI;
  spi_device_handle_t spiHandle = nullptr;
};

#endif // ESP_HAL_H