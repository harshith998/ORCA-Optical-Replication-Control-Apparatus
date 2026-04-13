"""
Polling-based rotary encoder with push-button.

Runs a 1 ms background thread that manually detects edges on the A pin
and debounces the button — avoids RPi.GPIO's unreliable add_event_detect.
"""

import threading
import time
import RPi.GPIO as GPIO


class RotaryEncoder:
    """Tracks a rotary encoder position and latches button clicks.

    GPIO.setmode(GPIO.BCM) must be called before begin() (io_controller does this).
    """

    _POLL_S    = 0.001   # 1 ms poll interval
    _DEBOUNCE_S = 0.200  # 200 ms button debounce

    def __init__(self, pin_a: int, pin_b: int, pin_btn: int):
        self._pin_a   = pin_a
        self._pin_b   = pin_b
        self._pin_btn = pin_btn
        self._position    = 0
        self._btn_pressed = False
        self._lock        = threading.Lock()
        self._stop        = threading.Event()
        self._thread      = None
        self.available    = False
        self.status       = 'Not initialized'

    def begin(self):
        try:
            GPIO.setup(self._pin_a,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._pin_b,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._pin_btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            self._stop.clear()
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()

            self.available = True
            self.status = (f'OK - encoder A=BCM{self._pin_a} B=BCM{self._pin_b} '
                           f'BTN=BCM{self._pin_btn} (polling)')
        except Exception as exc:
            self.available = False
            self.status = f'Unavailable - rotary encoder init failed: {exc}'

    def _poll_loop(self):
        last_a   = GPIO.input(self._pin_a)
        last_btn = GPIO.input(self._pin_btn)
        last_btn_time = 0.0

        while not self._stop.is_set():
            a   = GPIO.input(self._pin_a)
            b   = GPIO.input(self._pin_b)
            btn = GPIO.input(self._pin_btn)
            now = time.monotonic()

            # Rotary: falling edge on A → check B for direction
            if last_a == GPIO.HIGH and a == GPIO.LOW:
                with self._lock:
                    self._position += 1 if b == GPIO.HIGH else -1

            # Button: falling edge with debounce
            if last_btn == GPIO.HIGH and btn == GPIO.LOW:
                if now - last_btn_time > self._DEBOUNCE_S:
                    with self._lock:
                        self._btn_pressed = True
                    last_btn_time = now

            last_a   = a
            last_btn = btn
            time.sleep(self._POLL_S)

    def get_position(self) -> int:
        with self._lock:
            return self._position

    def consume_click(self) -> bool:
        """Returns True (and clears the flag) if the button was clicked since last call."""
        with self._lock:
            pressed = self._btn_pressed
            self._btn_pressed = False
            return pressed

    def cleanup(self):
        self._stop.set()
