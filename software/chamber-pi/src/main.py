#!/usr/bin/env python3
"""
Chamber Controller - Raspberry Pi Version
Replicates ESP32 chamber functionality for nitrogen fixation light control.
Includes web server for remote monitoring and control.
"""

import signal
import threading
import time
from config import LOOP_DELAY_MS, MAX_PWM_VALUE, SCALE_CONSTANT
from database import db
from io_controller import IOController
from lcd_display import LCDDisplay
from usb_logger import usb_logger
from web_server import update_current_state, run_server, water_scheduler, register_solenoid_setter
from solar_check import check_reading


io = IOController()
lcd = LCDDisplay()

pwm_enabled = False
running = True


def signal_handler(sig, frame):
    global running
    print("\nShutting down...")
    running = False


def setup():
    """Initialize all peripherals."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    io.begin()
    lcd.begin()

    print("========================")
    print(" Hardware Init Summary ")
    print("========================")
    for name, status in io.get_init_report().items():
        print(f"{name.upper():>4}: {status}")
    print(f" LCD: {lcd.get_init_report()}")
    print("------------------------")
    print("The controller will keep running even if optional hardware is missing.")
    print("Missing hardware reports mean 'not connected' or 'not responding'.")
    print("------------------------")

    if lcd.available:
        lcd.set_backlight(True)
        lcd.clear()
        lcd.set_cursor(0, 0)
        lcd.print("RPi Init...")
        time.sleep(1)

        lcd.clear()
        lcd.set_cursor(0, 0)
        lcd.print("System Ready")
        lcd.set_cursor(0, 1)
        lcd.print("Web: port 5000")
        time.sleep(2)

    io.set_pwm(0)
    register_solenoid_setter(io.set_solenoid)


def loop():
    global pwm_enabled

    io.update()

    sw1 = io.get_switch1()
    sw2 = io.get_switch2()

    web_state = db.get_web_control_state()
    web_manual_enabled = web_state['web_manual_enabled']
    web_manual_pwm = web_state['web_manual_pwm']

    if sw2:
        pwm_enabled = False
    else:
        pwm_enabled = True

    raw_lux = io.get_lux_value()
    clamped_lux = io.get_clamped_lux(raw_lux)
    spectral = io.get_spectral_channels()
    gps = io.get_last_gps()

    sanity_flag = False
    if gps.get('valid') and spectral:
        sanity_flag = check_reading(
            clear_value=spectral.get('clear', raw_lux),
            lat=gps['latitude'],
            lon=gps['longitude'],
            unix_time=gps['unix_time'],
        )

    actual_pwm = 0
    actual_mode = 'lux'

    if web_manual_enabled:
        actual_pwm = web_manual_pwm
        actual_mode = 'web_manual'
    elif pwm_enabled:
        input_norm = clamped_lux / SCALE_CONSTANT
        input_norm = max(0.0, min(1.0, input_norm))
        actual_mode = 'lux'
        actual_pwm = int(input_norm * MAX_PWM_VALUE + 0.5)
        actual_pwm = min(actual_pwm, MAX_PWM_VALUE)

    io.set_pwm(actual_pwm)

    if lcd.available:
        lcd.clear()
        lcd.set_cursor(0, 0)

        if web_manual_enabled:
            lcd.print("Mode: WEB CTRL")
        else:
            lcd.print("Mode: LUX")

        lcd.set_cursor(0, 1)
        lcd.print(f"Lux:{raw_lux}")

    db.log_reading(
        raw_lux=raw_lux,
        clamped_lux=clamped_lux,
        pwm_value=actual_pwm,
        mode=actual_mode,
        bounds_min=io.live_min,
        bounds_max=io.live_max
    )

    usb_logger.log_reading(raw_lux, clamped_lux, actual_pwm, actual_mode,
                           io.live_min, io.live_max)

    if spectral:
        db.log_spectral(channels=spectral, gps=gps, sanity_flag=sanity_flag)

    update_current_state(
        raw_lux=raw_lux,
        clamped_lux=clamped_lux,
        pwm_value=actual_pwm,
        mode=actual_mode,
        bounds_min=io.live_min,
        bounds_max=io.live_max,
        sw1=sw1,
        sw2=sw2,
        sanity_flag=sanity_flag,
        wired_connected=io.is_wired_connected(),
    )

    duty_pct = (actual_pwm / MAX_PWM_VALUE) * 100.0
    print(f"{io.to_string()} | [PWM] {actual_pwm}/{MAX_PWM_VALUE} ({duty_pct:.1f}%) mode={actual_mode}")


def main_loop():
    global running
    loop_delay = LOOP_DELAY_MS / 1000.0

    while running:
        try:
            loop()
            time.sleep(loop_delay)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(1)

    io.set_pwm(0)
    water_scheduler.stop()
    io.cleanup()
    lcd.cleanup()
    db.close()


def run_web_server():
    run_server(host='0.0.0.0', port=5000, debug=False)


def main():
    print("Starting Chamber Controller...")
    setup()

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    water_scheduler.start()

    print("=" * 50)
    print("  Chamber Controller Started")
    print("  Web interface: http://localhost:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    main_loop()


if __name__ == "__main__":
    main()
