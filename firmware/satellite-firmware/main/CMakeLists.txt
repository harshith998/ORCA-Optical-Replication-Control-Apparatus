idf_component_register(
    SRCS "satellite-firmware.cpp" "gps.c" "rs_transciever.c"
    INCLUDE_DIRS "."
    REQUIRES as7343 radiolib esp_timer driver
)
