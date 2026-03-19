#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

/**
 * @brief GPS fix type (2D / 3D)
 */
typedef enum {
    GPS_FIX_TYPE_NONE = 1,
    GPS_FIX_TYPE_2D   = 2,
    GPS_FIX_TYPE_3D   = 3,
} gps_fix_type_t;

/**
 * @brief Aggregated GPS data, updated on each successful parse cycle.
 */
typedef struct {
    /* --- Position --- */
    double latitude;            /*!< Decimal degrees, positive = North */
    double longitude;           /*!< Decimal degrees, positive = East  */
    float  altitude_m;          /*!< Altitude above mean sea level, metres */

    /* --- Motion --- */
    float  speed_kmph;          /*!< Ground speed, km/h  */
    float  speed_knots;         /*!< Ground speed, knots */
    float  track_deg;           /*!< True track / heading, degrees */
    float  heading_deg;         /*!< Mag-variation-adjusted heading, degrees */

    /* --- Satellite info --- */
    int    satellites;          /*!< Number of satellites in use */
    float  hdop;                /*!< Horizontal dilution of precision */
    float  pdop;                /*!< Position dilution of precision */
    float  vdop;                /*!< Vertical dilution of precision */

    /* --- Fix status --- */
    gps_fix_type_t fix_type;    /*!< Fix type: none / 2D / 3D (GPGSA) */
    bool           valid;       /*!< True when GPRMC reports an active fix */

    /* --- Time / Date (UTC) --- */
    struct tm datetime;         /*!< UTC date & time from GPRMC */
    bool      datetime_valid;   /*!< True once a date/time sentence has been parsed */
} gps_data_t;

/**
 * @brief Initialise the UART interface to the GPS module.
 * Must be called once before gps_update().
 */
void gps_init(void);

/**
 * @brief Read and parse one NMEA sentence (100 ms timeout).
 *
 * Call repeatedly until you have a valid fix.
 *
 * @return true  if a sentence was successfully parsed.
 * @return false if no data arrived or parsing failed.
 */
bool gps_update(void);

/**
 * @brief Print the raw NMEA sentence from the GPS (for debugging).
 * Call instead of gps_update() to see what sentences the GPS is sending.
 */
void gps_print_raw(void);

/**
 * @brief Get a snapshot of the latest parsed GPS data.
 * @param[out] out  Caller-allocated gps_data_t to fill.
 */
void gps_get_data(gps_data_t *out);

/* --- Convenience getters --- */
double gps_get_latitude(void);
double gps_get_longitude(void);
float  gps_get_altitude_m(void);
float  gps_get_speed_kmph(void);
float  gps_get_heading_deg(void);
int    gps_get_satellites(void);
bool   gps_has_fix(void);

#ifdef __cplusplus
}
#endif