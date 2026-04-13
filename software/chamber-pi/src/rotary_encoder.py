"""
Interrupt-driven rotary encoder with push-button.

Uses GPIO edge detection so pulses are never missed regardless of loop timing.
Thread-safe: position and click flag are protected by a lock.
"""

import threading
import RPi.GPIO as GPIO


class RotaryEncoder:
    """Tracks a rotary encoder position and latches button clicks.

    GPIO.setmode(GPIO.BCM) must be called before begin() (io_controller does this).
    """

    def __init__(self, pin_a: int, pin_b: int, pin_btn: int):
        self._pin_a   = pin_a
        self._pin_b   = pin_b
        self._pin_btn = pin_btn
        self._position    = 0
        self._btn_pressed = False
        self._lock        = threading.Lock()
        self.available    = False
        self.status       = 'Not initialized'

    def begin(self):
        try:
            GPIO.setup(self._pin_a,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._pin_b,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self._pin_btn, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # Clear any stale edge detection left over from a previous run
            for pin in (self._pin_a, self._pin_btn):
                try:
                    GPIO.remove_event_detect(pin)
                except Exception:
                    pass

            # Detect on both edges of A — check B state to determine direction
            GPIO.add_event_detect(self._pin_a, GPIO.BOTH, callback=self._on_a)
            # Button: falling edge (pull-up, active LOW), 200 ms debounce
            GPIO.add_event_detect(self._pin_btn, GPIO.FALLING,
                                  callback=self._on_btn, bouncetime=200)

            self.available = True
            self.status = (f'OK - encoder A=BCM{self._pin_a} B=BCM{self._pin_b} '
                           f'BTN=BCM{self._pin_btn}')
        except Exception as exc:
            self.available = False
            self.status = f'Unavailable - rotary encoder init failed: {exc}'

    def _on_a(self, channel):
        a = GPIO.input(self._pin_a)
        b = GPIO.input(self._pin_b)
        with self._lock:
            if a == GPIO.LOW:
                # Falling edge on A: B HIGH → CW (+1), B LOW → CCW (-1)
                self._position += 1 if b == GPIO.HIGH else -1

    def _on_btn(self, channel):
        with self._lock:
            self._btn_pressed = True

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
        if self.available:
            try:
                GPIO.remove_event_detect(self._pin_a)
                GPIO.remove_event_detect(self._pin_btn)
            except Exception:
                pass
