"""
USB CSV Logger - Saves readings to CSV on mounted USB drive.
"""

import os
import csv
import time
from datetime import datetime
from typing import Optional

# Common USB mount points on Raspberry Pi
USB_MOUNT_PATHS = [
    "/media/pi",      # Default Raspbian mount point
    "/media",         # Alternative
    "/mnt/usb",       # Manual mount point
    "/mnt",           # Generic mount
]

CSV_FILENAME = "chamber_readings.csv"
CSV_HEADERS = ["timestamp", "datetime", "raw_lux", "clamped_lux", "pwm_value",
               "mode", "bounds_min", "bounds_max"]


_USB_RETRY_INTERVAL = 10.0  # seconds between find_usb() attempts when no USB present

class USBLogger:
    def __init__(self):
        self.usb_path: Optional[str] = None
        self.csv_path: Optional[str] = None
        self._file_initialized = False
        self._file_handle = None
        self._writer = None
        self._next_usb_retry = 0.0

    def find_usb(self) -> Optional[str]:
        """Find mounted USB drive."""
        for mount_base in USB_MOUNT_PATHS:
            if not os.path.exists(mount_base):
                continue

            # Check if it's a direct mount point with files
            if os.path.ismount(mount_base):
                return mount_base

            # Check subdirectories (e.g., /media/pi/USBDRIVE)
            try:
                for subdir in os.listdir(mount_base):
                    full_path = os.path.join(mount_base, subdir)
                    if os.path.ismount(full_path) or os.path.isdir(full_path):
                        # Verify it's writable
                        try:
                            test_file = os.path.join(full_path, ".write_test")
                            with open(test_file, 'w') as f:
                                f.write("test")
                            os.remove(test_file)
                            return full_path
                        except (IOError, OSError):
                            continue
            except (IOError, OSError):
                continue

        return None

    def _init_csv(self):
        """Open the CSV file for appending, writing headers if new."""
        if self._file_initialized or not self.csv_path:
            return
        try:
            write_header = not os.path.exists(self.csv_path)
            self._file_handle = open(self.csv_path, 'a', newline='')
            self._writer = csv.writer(self._file_handle)
            if write_header:
                self._writer.writerow(CSV_HEADERS)
                self._file_handle.flush()
                print(f"[USB] Created CSV: {self.csv_path}")
            self._file_initialized = True
        except IOError as e:
            print(f"[USB] Failed to open CSV: {e}")
            self._file_handle = None
            self._writer = None

    def log_reading(self, raw_lux: int, clamped_lux: int, pwm_value: int,
                    mode: str, bounds_min: int, bounds_max: int) -> bool:
        """Log a reading to CSV on USB. Returns True if successful."""
        # Throttle USB detection attempts — only retry every _USB_RETRY_INTERVAL seconds
        if not self.usb_path:
            now = time.monotonic()
            if now < self._next_usb_retry:
                return False
            self.usb_path = self.find_usb()
            if self.usb_path:
                self.csv_path = os.path.join(self.usb_path, CSV_FILENAME)
                print(f"[USB] Found USB at: {self.usb_path}")
            else:
                self._next_usb_retry = now + _USB_RETRY_INTERVAL
                return False

        # Open persistent file handle on first use
        self._init_csv()

        if not self._file_initialized or self._writer is None:
            return False

        try:
            now = datetime.now()
            self._writer.writerow([
                now.timestamp(),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                raw_lux, clamped_lux, pwm_value, mode, bounds_min, bounds_max,
            ])
            self._file_handle.flush()
            return True
        except IOError as e:
            print(f"[USB] Write failed: {e}")
            self._reset()
            return False

    def _reset(self):
        """Close file handle and clear state so next call retries USB detection."""
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception:
                pass
        self._file_handle = None
        self._writer = None
        self.usb_path = None
        self.csv_path = None
        self._file_initialized = False
        self._next_usb_retry = time.monotonic() + _USB_RETRY_INTERVAL

    def get_status(self) -> dict:
        """Get USB logger status."""
        return {
            "usb_connected": self.usb_path is not None,
            "usb_path": self.usb_path,
            "csv_path": self.csv_path
        }


# Global instance
usb_logger = USBLogger()