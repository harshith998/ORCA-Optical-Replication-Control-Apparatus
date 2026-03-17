#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include "ulp_lp_core_i2c.h"
#include "ulp_lp_core_utils.h"

int main (void)
{
    while (1) {
        /* 1. Wake up the main CPU */
        ulp_lp_core_wakeup_main_processor();

        /* 2. Wait for 5 seconds (5,000,000 microseconds) */
        /* Note: Ensure your LP core clock frequency allows for this long of a delay */
        ulp_lp_core_delay_us(5000000);
    }

    return 0;
}