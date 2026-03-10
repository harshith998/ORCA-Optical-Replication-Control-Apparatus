#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// This is the entry point for all ESP-IDF apps
void app_main(void)
{
    printf("Hello, world! Starting my ESP32 journey.\n");

    // A simple loop to keep the program running
    int count = 0;
    while (1) {
        printf("Loop count: %d\n", count++);
        
        // Delay for 1000ms (1 second)
        // vTaskDelay uses "ticks," so we divide by portTICK_PERIOD_MS
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}