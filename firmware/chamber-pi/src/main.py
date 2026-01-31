#!/usr/bin/env python3
"""
Chamber Controller - Raspberry Pi Version
Replicates ESP32 chamber functionality for nitrogen fixation light control.
Includes web server for remote monitoring and control.
"""

import time
import signal
import sys
import threading
from enum import IntEnum

from config import LOOP_DELAY_MS, MAX_PWM_VALUE, SCALE_CONSTANT
from io_controller import IOController
from lcd_display import LCDDisplay
from database import db
from web_server import app, update_current_state, run_server


class DisplayMode(IntEnum):
    ANALOG = 0
    LUX = 1


# Global instances
io = IOController()
lcd = LCDDisplay()

# Runtime state
display_mode = DisplayMode.LUX
pwm_enabled = False
running = True


def signal_handler(sig, frame):
    """Handle Ctrl+C for clean shutdown."""
    global running
    print("\nShutting down...")
    running = False


def setup():
    """Initialize all peripherals."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    io.begin()
    lcd.begin()
    lcd.set_backlight(True)

    # Display init message
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

    # Ensure PWM off at start
    io.set_pwm(0)


def loop():
    """Main control loop - single iteration."""
    global display_mode, pwm_enabled

    io.update()

    # Read switches (pull-up: True=HIGH=released, False=LOW=pressed)
    sw1 = io.get_switch1()
    sw2 = io.get_switch2()

    # Check web manual control state
    web_state = db.get_web_control_state()
    web_manual_enabled = web_state['web_manual_enabled']
    web_manual_pwm = web_state['web_manual_pwm']

    # Determine mode from physical switch
    if sw1:
        display_mode = DisplayMode.ANALOG
    else:
        display_mode = DisplayMode.LUX

    # Physical PWM enable switch
    if sw2:
        pwm_enabled = False
    else:
        pwm_enabled = True

    # Get sensor values
    raw_lux = io.get_lux_value()
    clamped_lux = io.get_clamped_lux(raw_lux)
    pot = io.get_analog_value()

    # Determine PWM output
    actual_pwm = 0
    actual_mode = 'lux'

    if web_manual_enabled:
        # Web manual control takes priority
        actual_pwm = web_manual_pwm
        actual_mode = 'web_manual'
    elif pwm_enabled:
        if display_mode == DisplayMode.ANALOG:
            input_norm = pot
            actual_mode = 'analog'
        else:
            input_norm = clamped_lux / SCALE_CONSTANT
            input_norm = max(0.0, min(1.0, input_norm))
            actual_mode = 'lux'

        actual_pwm = int(input_norm * MAX_PWM_VALUE + 0.5)
        actual_pwm = min(actual_pwm, MAX_PWM_VALUE)

    # Apply PWM
    io.set_pwm(actual_pwm)

    # Update LCD display
    lcd.clear()
    lcd.set_cursor(0, 0)

    if web_manual_enabled:
        lcd.print("Mode: WEB CTRL")
    elif display_mode == DisplayMode.ANALOG:
        lcd.print("Mode: ANALOG")
    else:
        lcd.print("Mode: LUX")

    lcd.set_cursor(0, 1)
    if display_mode == DisplayMode.ANALOG and not web_manual_enabled:
        lcd.print(f"Pot:{pot:.3f}")
    else:
        lcd.print(f"Lux:{raw_lux}")

    # Log to database
    db.log_reading(
        raw_lux=raw_lux,
        clamped_lux=clamped_lux,
        pwm_value=actual_pwm,
        mode=actual_mode,
        bounds_min=io.live_min,
        bounds_max=io.live_max
    )

    # Update web server state for SSE
    update_current_state(
        raw_lux=raw_lux,
        clamped_lux=clamped_lux,
        pwm_value=actual_pwm,
        mode=actual_mode,
        bounds_min=io.live_min,
        bounds_max=io.live_max,
        pot_value=pot,
        sw1=sw1,
        sw2=sw2
    )

    # Debug output
    print(io.to_string())


def main_loop():
    """Run the main control loop."""
    global running
    loop_delay = LOOP_DELAY_MS / 1000.0

    while running:
        try:
            loop()
            time.sleep(loop_delay)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(1)

    # Cleanup
    io.set_pwm(0)
    io.cleanup()
    lcd.cleanup()
    db.close()


def run_web_server():
    """Run the web server in a separate thread."""
    run_server(host='0.0.0.0', port=5000, debug=False)


def main():
    """Entry point."""
    setup()

    # Start web server in background thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    print("=" * 50)
    print("  Chamber Controller Started")
    print("  Web interface: http://localhost:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    # Run main loop
    main_loop()


if __name__ == "__main__":
    main()