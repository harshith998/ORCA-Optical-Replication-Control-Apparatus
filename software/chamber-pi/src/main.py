#!/usr/bin/env python3
"""
Chamber Controller - Raspberry Pi Version
Replicates ESP32 chamber functionality for nitrogen fixation light control.
Includes web server for remote monitoring and control.
"""

import datetime
import signal
import subprocess
import threading
import time
from config import LOOP_DELAY_MS, MAX_PWM_VALUE, SCALE_CONSTANT, LCD_COLS, KNOB_STEP, HOTSPOT_IP, HOTSPOT_SSID, WEB_PORT
from database import db
from io_controller import IOController
from lcd_display import LCDDisplay
from usb_logger import usb_logger
from web_server import update_current_state, run_server, get_web_control, set_web_control
from solar_check import get_expected_clear, get_sun_elevation

io = IOController()
lcd = LCDDisplay()

pwm_enabled       = False
running           = True
last_knob_pos     = 0       # previous encoder position for delta tracking
_lcd_cache        = ['', '', '', '']  # last-written content per row; skip write if unchanged
_log_tick         = 0       # counts 100 ms ticks; DB write happens every 10 (1 s)
_last_sanity_flag = False   # persists across ticks so the UI badge stays visible


def lcd_row(row: int, text: str):
    """Write text to an LCD row only if the content has changed."""
    padded = f"{text:<{LCD_COLS}}"[:LCD_COLS]
    if padded != _lcd_cache[row]:
        _lcd_cache[row] = padded
        lcd.set_cursor(0, row)
        lcd.print(padded)


def signal_handler(sig, frame):
    global running
    print("\nShutting down...")
    running = False


def setup():
    """Initialize all peripherals."""
    signal.signal(signal.SIGINT, signal_handler)    # Catches Ctrl+C termination
    signal.signal(signal.SIGTERM, signal_handler)   # Catches other termination signals

    io.begin()
    lcd.begin()

    print("==================")
    print(" Init Diagnostics ")
    print("==================")
    for name, status in io.get_init_report().items():
        print(f"{name.upper():>6}: {status}")
    print(f"{'LCD':>6}: {lcd.get_init_report()}")

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

    # Restore last known mode from DB so a reboot resumes the previous state
    last = db.get_latest_state()
    if last:
        set_web_control(
            enabled=bool(last.get('led_mode', 0)),
            pwm=last.get('led_lux', 0),
        )



def loop():
    global pwm_enabled, last_knob_pos, _log_tick, _last_sanity_flag

    io.update()

    sw1 = io.get_switch1()
    sw2 = io.get_switch2()
    sw3 = io.get_switch3()

    web_manual_enabled, web_manual_pwm = get_web_control()

    pwm_enabled = bool(sw2)

    # Rotary: compute delta and toggle mode on button click
    knob_pos = io.get_rotary_position()
    clicked  = io.consume_rotary_click()
    delta    = knob_pos - last_knob_pos
    last_knob_pos = knob_pos

    physical_change = False

    if clicked:
        init_pwm = web_manual_pwm if web_manual_enabled else 0
        web_manual_enabled = not web_manual_enabled
        web_manual_pwm = init_pwm
        set_web_control(web_manual_enabled, web_manual_pwm)
        physical_change = True

    if web_manual_enabled and delta != 0:
        web_manual_pwm = max(0, min(MAX_PWM_VALUE, web_manual_pwm + delta * KNOB_STEP))
        set_web_control(True, web_manual_pwm)
        physical_change = True

    raw_lux = io.get_lux_value()
    new_packet = io.consume_new_packet()
    spectral = io.get_spectral_channels() if new_packet else {}
    gps = io.get_last_gps()

    # Sync timestamp from GPS when a valid fix arrives
    if new_packet and gps.get('valid') and gps.get('unix_time', 0) > 0:
        db.notify_gps_time(gps['unix_time'])

    if new_packet and gps.get('valid') and spectral:
        clear_val  = spectral.get('clear', 0)
        solar_max  = get_expected_clear(gps['latitude'], gps['longitude'], gps['unix_time'])
        if solar_max is not None:
            _last_sanity_flag = clear_val > solar_max
            if _last_sanity_flag:
                print(f"[SolarCheck] FLAGGED — clear={clear_val} > solar_max={solar_max:.0f}")
        else:
            _last_sanity_flag = False
    sanity_flag = _last_sanity_flag

    actual_pwm = 0
    actual_mode = 'auto'

    if web_manual_enabled:
        actual_pwm = web_manual_pwm
        actual_mode = 'manual'
    elif pwm_enabled:
        input_norm = raw_lux / SCALE_CONSTANT
        input_norm = max(0.0, min(1.0, input_norm))
        actual_pwm = int(input_norm * MAX_PWM_VALUE + 0.5)
        actual_pwm = min(actual_pwm, MAX_PWM_VALUE)

    io.set_pwm(actual_pwm)

    if lcd.available:
        conn_str     = "WIRE" if io.is_wired_connected() else "LORA"
        duty_pct_int = int((actual_pwm / MAX_PWM_VALUE) * 100.0)
        mode_str     = "MANUAL" if web_manual_enabled else "AUTO  "

        lcd_row(0, f"Mode:{mode_str:<6} [{conn_str}] {duty_pct_int:>3}%")
        lcd_row(1, f"Lux:{raw_lux:<7} PWM:{actual_pwm:<6}")

        if gps.get('valid'):
            lcd_row(2, f"{gps['latitude']:>9.4f} {gps['longitude']:>10.4f}")
        else:
            lcd_row(2, "NO GPS")

        if gps.get('valid') and gps.get('unix_time', 0) > 0:
            t = datetime.datetime.fromtimestamp(gps['unix_time'], tz=datetime.timezone.utc)
            lcd_row(3, f"UTC {t.strftime('%H:%M:%S')}")
        else:
            lcd_row(3, "NO SAT TIME")

    # Log to DB and USB once per second (every 10 ticks at 100 ms)
    _log_tick += 1
    if _log_tick >= 10:
        _log_tick = 0
        led_mode_int = 1 if web_manual_enabled else 0
        db.log_chamber(
            led_lux=actual_pwm,
            led_mode=led_mode_int,
            s1=1 if sw1 else 0,
            s2=1 if sw2 else 0,
            s3=1 if sw3 else 0,
        )
        usb_logger.log_reading(actual_pwm, led_mode_int,
                               1 if sw1 else 0,
                               1 if sw2 else 0,
                               1 if sw3 else 0)

    if new_packet and spectral:
        db.log_sensor(channels=spectral, gps=gps, sanity_flag=sanity_flag)

    update_current_state(
        raw_lux=raw_lux,
        pwm_value=actual_pwm,
        mode=actual_mode,
        sw1=sw1,
        sw2=sw2,
        sw3=sw3,
        sanity_flag=sanity_flag,
        wired_connected=io.is_wired_connected(),
        gps=gps,
        web_manual_enabled=web_manual_enabled,
        web_manual_pwm=web_manual_pwm,
        physical_change=physical_change,
    )



def main_loop():
    global running
    loop_delay = LOOP_DELAY_MS / 1000.0
    # Purge data older than 7 days every ~1 hour (36000 ticks at 100 ms)
    _cleanup_interval = 36000
    _tick = 0

    while running:
        try:
            loop()
            _tick += 1
            if _tick >= _cleanup_interval:
                db.cleanup_old_data()
                _tick = 0
            time.sleep(loop_delay)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(1)

    io.set_pwm(0)
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

    print("=" * 50)
    print("  Chamber Controller Started")
    try:
        iface_ips = {}
        for iface, label in (('eth0', 'ethernet'), ('wlan0', 'wifi')):
            out = subprocess.check_output(
                ['ip', '-4', 'addr', 'show', iface],
                timeout=2, stderr=subprocess.DEVNULL,
            ).decode()
            for line in out.splitlines():
                line = line.strip()
                if line.startswith('inet '):
                    ip = line.split()[1].split('/')[0]
                    iface_ips[ip] = label
        for ip, label in iface_ips.items():
            if ip == HOTSPOT_IP:
                print(f"  http://{ip}:{WEB_PORT}  (hotspot: join {HOTSPOT_SSID})")
            else:
                print(f"  http://{ip}:{WEB_PORT}  ({label})")
    except Exception:
        print(f"  http://localhost:{WEB_PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    main_loop()


if __name__ == "__main__":
    main()
