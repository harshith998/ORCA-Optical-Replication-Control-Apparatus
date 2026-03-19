#include "gps.h"

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_idf_version.h"

/* --------------------------------------------------------------------------
 * UART configuration — adjust to match your wiring
 * -------------------------------------------------------------------------- */
#define GPS_UART_NUM        UART_NUM_1
#define GPS_UART_RX_PIN     5
#define GPS_UART_BAUD       115200
#define GPS_UART_BUF_SIZE   1024

static const char *TAG = "gps";

/* --------------------------------------------------------------------------
 * UART read state
 * -------------------------------------------------------------------------- */
static char   s_buf[GPS_UART_BUF_SIZE + 1];
static size_t s_total_bytes;
static char  *s_last_buf_end;

/* --------------------------------------------------------------------------
 * Shared GPS state
 * -------------------------------------------------------------------------- */
static gps_data_t s_data = {0};

/* --------------------------------------------------------------------------
 * Internal: read one NMEA line from UART
 * -------------------------------------------------------------------------- */
static void uart_read_line(char **out_buf, size_t *out_len, int timeout_ms)
{
    *out_buf = NULL;
    *out_len = 0;

    if (s_last_buf_end != NULL) {
        size_t remaining = s_total_bytes - (s_last_buf_end - s_buf);
        memmove(s_buf, s_last_buf_end, remaining);
        s_last_buf_end = NULL;
        s_total_bytes  = remaining;
    }

    int read_bytes = uart_read_bytes(GPS_UART_NUM,
                                     (uint8_t *)s_buf + s_total_bytes,
                                     GPS_UART_BUF_SIZE - s_total_bytes,
                                     pdMS_TO_TICKS(timeout_ms));
    if (read_bytes <= 0) {
        return;
    }
    s_total_bytes += read_bytes;

    char *start = memchr(s_buf, '$', s_total_bytes);
    if (start == NULL) {
        s_total_bytes = 0;
        return;
    }

    char *end = memchr(start, '\r', s_total_bytes - (start - s_buf));
    if (end == NULL || *(++end) != '\n') {
        return;
    }
    end++;

    /* Null-terminate for easy string ops, then restore for length calc */
    end[-2] = '\0';

    *out_buf = start;
    *out_len = (end - 2) - start;  /* length without \r\n */

    if (end < s_buf + s_total_bytes) {
        s_last_buf_end = end;
    } else {
        s_total_bytes = 0;
    }
}

/* --------------------------------------------------------------------------
 * Internal: split a comma-separated NMEA sentence into fields
 * Returns number of fields found.
 * fields[] will point into the sentence buffer (which is modified in place).
 * -------------------------------------------------------------------------- */
#define MAX_NMEA_FIELDS 24
static int split_nmea(char *sentence, char *fields[], int max_fields)
{
    /* Strip checksum (*XX) if present */
    char *star = strchr(sentence, '*');
    if (star) *star = '\0';

    int count = 0;
    char *p = sentence;
    while (count < max_fields) {
        fields[count++] = p;
        char *comma = strchr(p, ',');
        if (!comma) break;
        *comma = '\0';
        p = comma + 1;
    }
    return count;
}

/* --------------------------------------------------------------------------
 * Internal: convert NMEA ddmm.mmmm + cardinal to signed decimal degrees
 * -------------------------------------------------------------------------- */
static double nmea_coord_to_dd(const char *coord, const char *card)
{
    if (!coord || coord[0] == '\0') return 0.0;
    double raw = atof(coord);
    int degrees = (int)(raw / 100);
    double minutes = raw - (degrees * 100);
    double dd = degrees + minutes / 60.0;
    if (card && (card[0] == 'S' || card[0] == 'W')) dd = -dd;
    return dd;
}

/* --------------------------------------------------------------------------
 * Internal: parse one null-terminated NMEA sentence
 * -------------------------------------------------------------------------- */
static void parse_sentence(char *sentence)
{
    char *fields[MAX_NMEA_FIELDS];
    int n = split_nmea(sentence, fields, MAX_NMEA_FIELDS);
    if (n < 1) return;

    const char *type = fields[0] + 1;  /* skip '$', e.g. "GNRMC" */

    /* Match on last 3 chars of sentence type to handle GP/GN/GL/GA/GB */
    const char *mtype = type + (strlen(type) > 3 ? strlen(type) - 3 : 0);

    /* ------------------------------------------------------------------ */
    /* RMC – position, speed, track, date/time                            */
    /* $xxRMC,hhmmss,A/V,lat,N/S,lon,E/W,speed,track,date,,,mode         */
    /* ------------------------------------------------------------------ */
    if (strcmp(mtype, "RMC") == 0 && n >= 10) {
        /* Status: field[2] = 'A' active, 'V' void */
        s_data.valid = (n > 2 && fields[2][0] == 'A');

        if (n > 5) {
            s_data.latitude  = nmea_coord_to_dd(fields[3], fields[4]);
            s_data.longitude = nmea_coord_to_dd(fields[5], fields[6]);
        }
        if (n > 7 && fields[7][0]) s_data.speed_knots = atof(fields[7]);
        s_data.speed_kmph = s_data.speed_knots * 1.852f;
        if (n > 8 && fields[8][0]) s_data.track_deg = atof(fields[8]);

        /* Date: ddmmyy */
        if (n > 9 && strlen(fields[9]) == 6) {
            char tmp[3] = {0};
            strncpy(tmp, fields[9] + 0, 2); s_data.datetime.tm_mday  = atoi(tmp);
            strncpy(tmp, fields[9] + 2, 2); s_data.datetime.tm_mon   = atoi(tmp) - 1;
            strncpy(tmp, fields[9] + 4, 2); s_data.datetime.tm_year  = atoi(tmp) + 100;
        }
        /* Time: hhmmss.sss */
        if (n > 1 && strlen(fields[1]) >= 6) {
            char tmp[3] = {0};
            strncpy(tmp, fields[1] + 0, 2); s_data.datetime.tm_hour = atoi(tmp);
            strncpy(tmp, fields[1] + 2, 2); s_data.datetime.tm_min  = atoi(tmp);
            strncpy(tmp, fields[1] + 4, 2); s_data.datetime.tm_sec  = atoi(tmp);
            s_data.datetime_valid = true;
        }

        /* Mag variation */
        double heading = s_data.track_deg;
        if (n > 11 && fields[10][0]) {
            double magvar = atof(fields[10]);
            if (n > 11 && fields[11][0] == 'E') heading -= magvar;
            else if (n > 11 && fields[11][0] == 'W') heading += magvar;
        }
        s_data.heading_deg = (float)fmod(heading + 360.0, 360.0);
    }

    /* ------------------------------------------------------------------ */
    /* GGA – fix quality, altitude, satellite count                        */
    /* $xxGGA,time,lat,N,lon,E,quality,sats,hdop,alt,M,...                */
    /* ------------------------------------------------------------------ */
    else if (strcmp(mtype, "GGA") == 0 && n >= 10) {
        if (n > 7 && fields[7][0]) s_data.satellites = atoi(fields[7]);
        if (n > 9 && fields[9][0]) s_data.altitude_m = atof(fields[9]);
        if (n > 3 && fields[2][0]) {
            s_data.latitude  = nmea_coord_to_dd(fields[2], fields[3]);
            s_data.longitude = nmea_coord_to_dd(fields[4], fields[5]);
        }
    }

    /* ------------------------------------------------------------------ */
    /* GSA – fix type, DOP                                                 */
    /* $xxGSA,mode,fixtype,...,pdop,hdop,vdop                             */
    /* ------------------------------------------------------------------ */
    else if (strcmp(mtype, "GSA") == 0 && n >= 18) {
        if (fields[2][0]) s_data.fix_type = (gps_fix_type_t)atoi(fields[2]);
        if (fields[n-3][0]) s_data.pdop = atof(fields[n-3]);
        if (fields[n-2][0]) s_data.hdop = atof(fields[n-2]);
        if (fields[n-1][0]) s_data.vdop = atof(fields[n-1]);
    }

    /* ------------------------------------------------------------------ */
    /* VTG – speed / track                                                 */
    /* $xxVTG,track,T,,M,speed_knots,N,speed_kmph,K,mode                 */
    /* ------------------------------------------------------------------ */
    else if (strcmp(mtype, "VTG") == 0 && n >= 8) {
        if (fields[1][0]) s_data.track_deg   = atof(fields[1]);
        if (fields[5][0]) s_data.speed_knots = atof(fields[5]);
        if (fields[7][0]) s_data.speed_kmph  = atof(fields[7]);
    }
}

/* --------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------- */

void gps_init(void)
{
    uart_config_t cfg = {
        .baud_rate  = GPS_UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
        .source_clk = UART_SCLK_DEFAULT,
#endif
    };
    ESP_ERROR_CHECK(uart_param_config(GPS_UART_NUM, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(GPS_UART_NUM,
                                 UART_PIN_NO_CHANGE, GPS_UART_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(GPS_UART_NUM,
                                        GPS_UART_BUF_SIZE * 2, 0, 0, NULL, 0));

    memset(&s_data, 0, sizeof(s_data));
    s_total_bytes  = 0;
    s_last_buf_end = NULL;

    ESP_LOGI(TAG, "GPS UART%d initialised at %d baud on RX GPIO%d",
             GPS_UART_NUM, GPS_UART_BAUD, GPS_UART_RX_PIN);
}

void gps_print_raw(void)
{
    char  *line = NULL;
    size_t len  = 0;
    uart_read_line(&line, &len, 100);
    if (len > 0) {
        printf("%s\n", line);
    }
}

bool gps_update(void)
{
    char  *line = NULL;
    size_t len  = 0;

    uart_read_line(&line, &len, 100);
    if (len == 0 || line == NULL) {
        return false;
    }

    parse_sentence(line);
    return true;
}

void gps_get_data(gps_data_t *out)
{
    if (out != NULL) {
        memcpy(out, &s_data, sizeof(gps_data_t));
    }
}

double gps_get_latitude(void)    { return s_data.latitude;    }
double gps_get_longitude(void)   { return s_data.longitude;   }
float  gps_get_altitude_m(void)  { return s_data.altitude_m;  }
float  gps_get_speed_kmph(void)  { return s_data.speed_kmph;  }
float  gps_get_heading_deg(void) { return s_data.heading_deg; }
int    gps_get_satellites(void)  { return s_data.satellites;  }
bool   gps_has_fix(void)         { return s_data.valid;       }