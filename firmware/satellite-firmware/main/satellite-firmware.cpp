#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include <stdbool.h>
#include "driver/i2c_master.h"
#include "as7343.h"
#include "esp_err.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "EspHal.h"
#include "gps.h"
#include "rs_transciever.h"

/**
 * The satellite module utilizes deep sleep cycles to minimize power draw while sampling data
 * TRANSMIT_CYCLE_MS sets how often the satellite module transmits a data packet
 * SAMPLES_PER_TRANSMIT sets how many spectral samples (evenly spaced) are averaged into each daata packet
 * On a transmit cycle, the satellite also polls the gps for data including position and time
 */

// I2C AS7343 pin configuration
static constexpr gpio_num_t I2C_SCL_GPIO = GPIO_NUM_19;
static constexpr gpio_num_t I2C_SDA_GPIO = GPIO_NUM_18;
#define I2C_PORT I2C_NUM_0

// Sampling & transmit timing configuration
#define TRANSMIT_CYCLE_MS 1000ULL
#define SAMPLES_PER_TRANSMIT 1
#define GPS_LOCK_TIMEOUT_MS 5000ULL
#define SAMPLING_CYCLE_MS (uint64_t)(TRANSMIT_CYCLE_MS / SAMPLES_PER_TRANSMIT)

// RTC retained-state validation
#define RTC_STATE_MAGIC 0xA53443D1UL
#define RTC_STATE_VERSION 1UL

// SPI configuration
static constexpr gpio_num_t SPI_SCK  = GPIO_NUM_6;
static constexpr gpio_num_t SPI_MISO = GPIO_NUM_2;
static constexpr gpio_num_t SPI_MOSI = GPIO_NUM_7;

// LoRa pin configuration
static constexpr gpio_num_t LORA_CS    = GPIO_NUM_11;
static constexpr gpio_num_t LORA_DIO1  = GPIO_NUM_20;
static constexpr gpio_num_t LORA_RESET = GPIO_NUM_0;
static constexpr gpio_num_t LORA_BUSY  = GPIO_NUM_3;

// LoRa frequency configuration
#define LORA_FREQ 915.0
#define LORA_BANDWIDTH 250.0
#define LORA_SPREAD 9
#define LORA_CODING_RATE 7
#define LORA_SYNC_WORD 0x12

// RS-485 pin configuration
static constexpr gpio_num_t RS_SNS = GPIO_NUM_10;
static constexpr gpio_num_t RS_EN = GPIO_NUM_23;
static constexpr gpio_num_t RS_TX = GPIO_NUM_16;
static constexpr gpio_num_t RS_GRN = GPIO_NUM_21;
static constexpr gpio_num_t RS_YLW = GPIO_NUM_22;

// Light sensor setup
static i2c_master_bus_handle_t s_i2c_bus = NULL;
static as7343_handle_t s_sensor = NULL;

/* ---------- Data structures ---------- */

// GPS data struct
typedef struct
{
    bool valid;
    double latitude_deg;
    double longitude_deg;
    uint32_t unix_time;
} gps_fix_t;

// Transmit data struct
typedef struct
{
    uint32_t sample_count; // Average sample number
    uint16_t avg_f1;
    uint16_t avg_f2;
    uint16_t avg_fz;
    uint16_t avg_f3;
    uint16_t avg_f4;
    uint16_t avg_f5;
    uint16_t avg_fy;
    uint16_t avg_f6;
    uint16_t avg_fxl;
    uint16_t avg_f7;
    uint16_t avg_f8;
    uint16_t avg_nir;
    uint16_t avg_clear;
    gps_fix_t gps; // GPS data
} report_payload_t;

/* ---------- RTC-retained accumulator ---------- */

// RTC data struct to retain information between deep sleeps
RTC_DATA_ATTR static struct
{
    // Check RTC
    uint32_t magic;
    uint32_t version;

    // Check cycle counts
    uint32_t cycle_sample_count; // Number of samples in the sum
    uint32_t total_sample_count; // Overall sample number post-averaging

    uint64_t first_sample_time_us;
    uint64_t last_sample_time_us;

    uint64_t sum_f1;
    uint64_t sum_f2;
    uint64_t sum_fz;
    uint64_t sum_f3;
    uint64_t sum_f4;
    uint64_t sum_f5;
    uint64_t sum_fy;
    uint64_t sum_f6;
    uint64_t sum_fxl;
    uint64_t sum_f7;
    uint64_t sum_f8;
    uint64_t sum_nir;
    uint64_t sum_clear;
} s_rtc_state;

/* ---------- RTC-retained state helpers ---------- */

// Clear the s_rtc_state data struct
static void rtc_state_clear_accumulator(void)
{
    s_rtc_state.cycle_sample_count = 0;
    s_rtc_state.first_sample_time_us = 0;
    s_rtc_state.last_sample_time_us = 0;

    s_rtc_state.sum_f1 = 0;
    s_rtc_state.sum_f2 = 0;
    s_rtc_state.sum_fz = 0;
    s_rtc_state.sum_f3 = 0;
    s_rtc_state.sum_f4 = 0;
    s_rtc_state.sum_f5 = 0;
    s_rtc_state.sum_fy = 0;
    s_rtc_state.sum_f6 = 0;
    s_rtc_state.sum_fxl = 0;
    s_rtc_state.sum_f7 = 0;
    s_rtc_state.sum_f8 = 0;
    s_rtc_state.sum_nir = 0;
    s_rtc_state.sum_clear = 0;
}

// Reset the s_rtc_state data struct
static void rtc_state_full_reset(void)
{
    memset(&s_rtc_state, 0, sizeof(s_rtc_state));
    s_rtc_state.magic = RTC_STATE_MAGIC;
    s_rtc_state.version = RTC_STATE_VERSION;
    rtc_state_clear_accumulator();
    s_rtc_state.total_sample_count = 0;
}

// Init the s_rtc_state data struct if uninitialized
static void rtc_state_init_if_needed(void)
{
    if (s_rtc_state.magic != RTC_STATE_MAGIC ||
        s_rtc_state.version != RTC_STATE_VERSION)
    {
        rtc_state_full_reset();
    }
}

// Add a sample to the s_rtc_state data struct
static void rtc_state_add_sample(const as7343_channels_t *ch, uint64_t timestamp_us)
{
    // If adding the first sample, record the first_sample_time_us
    if (s_rtc_state.cycle_sample_count == 0)
    {
        s_rtc_state.first_sample_time_us = timestamp_us;
    }

    s_rtc_state.last_sample_time_us = timestamp_us;
    s_rtc_state.cycle_sample_count++;

    s_rtc_state.sum_f1 += ch->f1;
    s_rtc_state.sum_f2 += ch->f2;
    s_rtc_state.sum_fz += ch->fz;
    s_rtc_state.sum_f3 += ch->f3;
    s_rtc_state.sum_f4 += ch->f4;
    s_rtc_state.sum_f5 += ch->f5;
    s_rtc_state.sum_fy += ch->fy;
    s_rtc_state.sum_f6 += ch->f6;
    s_rtc_state.sum_fxl += ch->fxl;
    s_rtc_state.sum_f7 += ch->f7;
    s_rtc_state.sum_f8 += ch->f8;
    s_rtc_state.sum_nir += ch->nir;
    s_rtc_state.sum_clear += ch->clear;
}

// Averaging function with edge case check
static uint16_t avg_u16(uint64_t sum, uint32_t count)
{
    if (count == 0)
    {
        return 0;
    }
    return (uint16_t)(sum / count);
}

// Populate a report_payload_t struct
static void rtc_state_build_report(report_payload_t *report, const gps_fix_t *gps)
{
    memset(report, 0, sizeof(*report));

    report->sample_count = s_rtc_state.total_sample_count;
    report->avg_f1 = avg_u16(s_rtc_state.sum_f1, s_rtc_state.cycle_sample_count);
    report->avg_f2 = avg_u16(s_rtc_state.sum_f2, s_rtc_state.cycle_sample_count);
    report->avg_fz = avg_u16(s_rtc_state.sum_fz, s_rtc_state.cycle_sample_count);
    report->avg_f3 = avg_u16(s_rtc_state.sum_f3, s_rtc_state.cycle_sample_count);
    report->avg_f4 = avg_u16(s_rtc_state.sum_f4, s_rtc_state.cycle_sample_count);
    report->avg_f5 = avg_u16(s_rtc_state.sum_f5, s_rtc_state.cycle_sample_count);
    report->avg_fy = avg_u16(s_rtc_state.sum_fy, s_rtc_state.cycle_sample_count);
    report->avg_f6 = avg_u16(s_rtc_state.sum_f6, s_rtc_state.cycle_sample_count);
    report->avg_fxl = avg_u16(s_rtc_state.sum_fxl, s_rtc_state.cycle_sample_count);
    report->avg_f7 = avg_u16(s_rtc_state.sum_f7, s_rtc_state.cycle_sample_count);
    report->avg_f8 = avg_u16(s_rtc_state.sum_f8, s_rtc_state.cycle_sample_count);
    report->avg_nir = avg_u16(s_rtc_state.sum_nir, s_rtc_state.cycle_sample_count);
    report->avg_clear = avg_u16(s_rtc_state.sum_clear, s_rtc_state.cycle_sample_count);

    if (gps != NULL)
    {
        report->gps = *gps;
    }
}

/* ---------- Hardware init ---------- */

static void init_i2c_and_sensor(void)
{
    i2c_master_bus_config_t bus_cfg = {};
    bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_cfg.i2c_port = I2C_PORT;
    bus_cfg.scl_io_num = I2C_SCL_GPIO;
    bus_cfg.sda_io_num = I2C_SDA_GPIO;
    bus_cfg.glitch_ignore_cnt = 7;
    bus_cfg.flags.enable_internal_pullup = true;

    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &s_i2c_bus));

    as7343_config_t cfg = AS7343_CONFIG_DEFAULT;
    ESP_ERROR_CHECK(as7343_init(s_i2c_bus, &cfg, &s_sensor));
}

/* ---------- Sensor ---------- */

// Poll sensor and record sample to s_rtc_state data struct
static esp_err_t read_sensor_and_accumulate(void)
{
    as7343_channels_t ch = {0};
    uint64_t now_us = (uint64_t)esp_timer_get_time();

    esp_err_t err = as7343_get_spectral_data(s_sensor, &ch);
    if (err != ESP_OK)
    {
        return err;
    }

    // Add local sample to s_rtc_state data struct
    rtc_state_add_sample(&ch, now_us);

    // DEBUG: Reports sampling event to Serial monitor
    printf("Stored sample #%lu\n", (unsigned long)s_rtc_state.total_sample_count);
    printf("F1=%u F2=%u FZ=%u F3=%u\n", ch.f1, ch.f2, ch.fz, ch.f3);
    printf("F4=%u F5=%u FY=%u F6=%u\n", ch.f4, ch.f5, ch.fy, ch.f6);
    printf("FXL=%u F7=%u F8=%u NIR=%u CLEAR=%u\n",
           ch.fxl, ch.f7, ch.f8, ch.nir, ch.clear);

    return ESP_OK;
}

/* ---------- GPS / LoRa placeholders ---------- */

static esp_err_t get_gps_fix(gps_fix_t *fix)
{
    if (fix == NULL)
    {
        return ESP_ERR_INVALID_ARG;
    }

    memset(fix, 0, sizeof(*fix));

    // Initialize GPS
    gps_init();
    gps_data_t data;

    setenv("TZ", "UTC0", 1); // GPS always outputs UTC
    tzset();

    int64_t start = esp_timer_get_time();
    do
    {
        gps_update();
        gps_get_data(&data);
        if ((esp_timer_get_time() - start) >= (int64_t)GPS_LOCK_TIMEOUT_MS * 1000)
        {
            fix->valid = false;
            fix->latitude_deg = 0.0;
            fix->longitude_deg = 0.0;
            fix->unix_time = 0;
            return ESP_OK;

            // TODO: Put GPS to warm-sleep between cycles via UART TX
        }
    } while (!data.valid || !data.datetime_valid);

    time_t unix_time = mktime(&data.datetime);

    printf("Lat:       %.6f\n", data.latitude);
    printf("Lon:       %.6f\n", data.longitude);
    printf("Unix Time: %lld\n", (long long)unix_time);

    fix->valid = true;
    fix->latitude_deg = data.latitude;
    fix->longitude_deg = data.longitude;
    fix->unix_time = unix_time;

    return ESP_OK;
}

// Send LoRa packet
static esp_err_t lora_send_report(const report_payload_t *report)
{
    if (report == NULL)
    {
        return ESP_ERR_INVALID_ARG;
    }

    // --- Build compact binary payload ---
    // Layout (little-endian):
    //   4  bytes - sample_count
    //   13x 2 bytes - avg_f1..f8, fz, f3..f5, fy, fxl, nir, clear (26 bytes)
    //   1  byte  - gps.valid
    //   8  bytes - latitude_deg  (double)
    //   8  bytes - longitude_deg (double)
    //   4  bytes - unix_time
    // Total: 51 bytes

    uint8_t buf[51];
    size_t  offset = 0;

    // sample_count (uint32_t)
    memcpy(buf + offset, &report->sample_count, sizeof(report->sample_count));
    offset += sizeof(report->sample_count);

    // Spectral channels in struct declaration order
    const uint16_t channels[] = {
        report->avg_f1,  report->avg_f2,  report->avg_fz,
        report->avg_f3,  report->avg_f4,  report->avg_f5,
        report->avg_fy,  report->avg_f6,  report->avg_fxl,
        report->avg_f7,  report->avg_f8,  report->avg_nir,
        report->avg_clear
    };
    for (size_t i = 0; i < sizeof(channels) / sizeof(channels[0]); i++)
    {
        memcpy(buf + offset, &channels[i], sizeof(uint16_t));
        offset += sizeof(uint16_t);
    }

    // GPS
    uint8_t gps_valid = report->gps.valid ? 1u : 0u;
    buf[offset++] = gps_valid;

    memcpy(buf + offset, &report->gps.latitude_deg,  sizeof(double)); offset += sizeof(double);
    memcpy(buf + offset, &report->gps.longitude_deg, sizeof(double)); offset += sizeof(double);
    memcpy(buf + offset, &report->gps.unix_time,     sizeof(uint32_t)); offset += sizeof(uint32_t);

    // Sanity-check at compile time
    static_assert(sizeof(buf) == 4 + (13 * 2) + 1 + 8 + 8 + 4,
                  "Payload size mismatch – update buf[] if struct changes");

    // --- Initialise radio ---
    EspHal  *hal   = new EspHal(SPI_SCK, SPI_MISO, SPI_MOSI);
    SX1262   radio = new Module(hal, LORA_CS, LORA_DIO1, LORA_RESET, LORA_BUSY);

    radio.begin(LORA_FREQ);
    radio.setBandwidth(LORA_BANDWIDTH);
    radio.setSpreadingFactor(LORA_SPREAD);
    radio.setCodingRate(LORA_CODING_RATE);
    radio.setSyncWord(LORA_SYNC_WORD);

    // --- Transmit ---
    int16_t state = radio.transmit(buf, offset);

    static const char *TAG = "lora_send";
    if (state == RADIOLIB_ERR_NONE)
    {
        ESP_LOGI(TAG, "LoRa TX OK  %u bytes | samples=%lu | gps=%s",
                 (unsigned)offset,
                 (unsigned long)report->sample_count,
                 report->gps.valid ? "valid" : "invalid");
    }
    else
    {
        ESP_LOGE(TAG, "LoRa TX failed, code %d", state);
        return ESP_FAIL;
    }

    return ESP_OK;
}

/* ---------- Report flow ---------- */

// Checks if a LoRa transmit is due
static bool transmit_due(void)
{
    return s_rtc_state.cycle_sample_count >= SAMPLES_PER_TRANSMIT;
}

// Performs transmit operations
static esp_err_t perform_transmit_cycle(void)
{
    // Update averaged sample count
    s_rtc_state.total_sample_count++;

    // Check for sensor data to transmit
    if (s_rtc_state.cycle_sample_count == 0)
    {
        printf("Report due, but no samples stored\n");
        return ESP_OK;
    }

    // Obtain GPS data
    gps_fix_t gps = {0};
    report_payload_t report = {0};
    esp_err_t err = get_gps_fix(&gps);
    if (err != ESP_OK)
    {
        printf("GPS acquisition failed: %s\n", esp_err_to_name(err));
        return err;
    }

    // Build report_payload_t struct using s_rtc_state and gps data
    rtc_state_build_report(&report, &gps);

    // Send report_payload_t struct using LoRa
    err = lora_send_report(&report);
    if (err != ESP_OK)
    {
        printf("LoRa transmit failed: %s\n", esp_err_to_name(err));
        return err;
    }

    // Reset the s_rtc_state data struct
    printf("Report sent successfully. Clearing retained accumulator.\n");
    rtc_state_clear_accumulator();

    return ESP_OK;
}

/* ---------- Sleep ---------- */

static void schedule_next_wakeup_and_sleep(void)
{
    const uint64_t sleep_us = SAMPLING_CYCLE_MS * 1000ULL;

    ESP_ERROR_CHECK(esp_sleep_enable_timer_wakeup(sleep_us));

    printf("Sleeping for %llu ms\n", SAMPLING_CYCLE_MS);
    fflush(stdout);

    esp_deep_sleep_start();
}

/* ---------- Main ---------- */

extern "C" void app_main(void)
{
    // Initialize RTC memory is needed
    rtc_state_init_if_needed();

    // DEBUG: Report expected cycle_sample_count and total_sample_count by end of cycle
    printf("RTC expected state: cycle sample count=%lu total_sample_count=%lu\n",
           (unsigned long)s_rtc_state.cycle_sample_count + 1,
           (unsigned long)s_rtc_state.total_sample_count + 1);

    // TODO: ADD RS-485 CHECK

    if (is_connected()) {
        printf("RS-485 device connected!\n");
    }
    else {
        printf("No RS-485 device detected.\n");
    }

    // Initialize I2C bus and sensor
    init_i2c_and_sensor();

    // Sensor sampling and RTC storage
    esp_err_t err = read_sensor_and_accumulate();
    if (err != ESP_OK)
    {
        printf("Sensor read failed: %s\n", esp_err_to_name(err));
        schedule_next_wakeup_and_sleep();
    }

    // Transmit averaged sample on transmit interval
    if (transmit_due())
    {
        err = perform_transmit_cycle();
        if (err != ESP_OK)
        {
            printf("Report cycle failed; retained data kept for retry.\n");
        }
    }

    schedule_next_wakeup_and_sleep();
}

// TODO: Implement default instantiation (below) to get rid of warnings

/**
 * 
size_t off = 0;
uint32_t sample_count; memcpy(&sample_count, buf+off, 4); off+=4;
uint16_t channels[13];
for(int i=0;i<13;i++){ memcpy(&channels[i], buf+off, 2); off+=2; }
bool valid = buf[off++];
double lat, lon; uint32_t ts;
memcpy(&lat, buf+off, 8); off+=8;
memcpy(&lon, buf+off, 8); off+=8;
memcpy(&ts,  buf+off, 4); off+=4;
 * 
 */

 // TODO

 // All RS-485 code via ethernet