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

// I2C AS7343 pin configuration
#define I2C_SCL_GPIO 19
#define I2C_SDA_GPIO 18
#define I2C_PORT I2C_NUM_0

// Sampling & transmit timing configuration
#define TRANSMIT_CYCLE_MS 60000ULL
#define SAMPLES_PER_TRANSMIT 4
#define SAMPLING_CYCLE_MS (uint64_t) (TRANSMIT_CYCLE_MS / SAMPLES_PER_TRANSMIT)

// RTC retained-state validation
#define RTC_STATE_MAGIC 0xA53443D1UL
#define RTC_STATE_VERSION 1UL

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
    uint32_t sample_count;  // Average sample number
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
    gps_fix_t gps;          // GPS data
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
    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_PORT,
        .scl_io_num = I2C_SCL_GPIO,
        .sda_io_num = I2C_SDA_GPIO,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };

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

// TODO
static esp_err_t get_gps_fix(gps_fix_t *fix)
{
    if (fix == NULL)
    {
        return ESP_ERR_INVALID_ARG;
    }

    memset(fix, 0, sizeof(*fix));

    /*
     * TODO:
     *   - power GPS on
     *   - wait for fix with timeout
     *   - fill fix->valid / latitude_deg / longitude_deg / hdop_x100
     *   - power GPS off
     */

    fix->valid = false;
    fix->latitude_deg = 0.0;
    fix->longitude_deg = 0.0;
    fix->unix_time = 0;

    return ESP_OK;
}

// TODO
static esp_err_t lora_send_report(const report_payload_t *report)
{
    if (report == NULL)
    {
        return ESP_ERR_INVALID_ARG;
    }
    

    /*
     * TODO:
     *   - pack report into payload
     *   - send over LoRa
     *   - wait for TX complete if needed
     */

    printf("Sending LoRa report:\n");
    printf("  sample_count=%lu\n", (unsigned long)report->sample_count);
    printf("  avg_clear=%u avg_f1=%u avg_f2=%u avg_nir=%u\n",
           report->avg_clear, report->avg_f1, report->avg_f2, report->avg_nir);

    if (report->gps.valid)
    {
        printf("  gps=%.6f, %.6f hdop=%lu.\n",
               report->gps.latitude_deg,
               report->gps.longitude_deg,
               (unsigned long)(report->gps.unix_time));
    }
    else
    {
        printf("  gps=invalid\n");
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

    gps_fix_t gps = {0};
    report_payload_t report = {0};

    // Obtain gps data
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

void app_main(void)
{
    // Initialize RTC memory is needed
    rtc_state_init_if_needed();

    // DEBUG: Report expected cycle_sample_count and total_sample_count by end of cycle
    printf("RTC expected state: cycle sample count=%lu total_sample_count=%lu\n",
           (unsigned long)s_rtc_state.cycle_sample_count + 1,
           (unsigned long)s_rtc_state.total_sample_count + 1);

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