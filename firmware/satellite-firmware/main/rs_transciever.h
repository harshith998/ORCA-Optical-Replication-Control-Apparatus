#pragma once

#include <stdbool.h>
#include <stdint.h>

// Forward-declare the payload type so this header stays self-contained.
// The full definition lives in satellite-firmware.cpp; include that or
// redefine locally before including this header.
typedef struct {
    bool valid;
    double latitude_deg;
    double longitude_deg;
    uint32_t unix_time;
} rs_gps_fix_t;

typedef struct {
    uint32_t sample_count;
    uint16_t avg_f1, avg_f2, avg_fz, avg_f3, avg_f4, avg_f5;
    uint16_t avg_fy, avg_f6, avg_fxl, avg_f7, avg_f8, avg_nir, avg_clear;
    rs_gps_fix_t gps;
} rs_report_payload_t;

#ifdef __cplusplus
extern "C" {
#endif

// Returns true if RS_SNS pin is HIGH (device connected), false if LOW.
bool is_connected(void);

// Encode payload as ASCII and transmit over RS-485.
// Returns true on success.
bool rs485_send(const rs_report_payload_t *payload);

#ifdef __cplusplus
}
#endif
