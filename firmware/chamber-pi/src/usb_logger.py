"""
USB CSV Logger - Saves readings to CSV on mounted USB drive.
"""

import os
import csv
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


class USBLogger:
    def __init__(self):
        self.usb_path: Optional[str] = None
        self.csv_path: Optional[str] = None
        self._file_initialized = False

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
        """Initialize CSV file with headers if needed."""
        if self._file_initialized or not self.csv_path:
            return

        # Create file with headers if it doesn't exist
        if not os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(CSV_HEADERS)
                print(f"[USB] Created CSV: {self.csv_path}")
            except IOError as e:
                print(f"[USB] Failed to create CSV: {e}")
                return

        self._file_initialized = True

    def log_reading(self, raw_lux: int, clamped_lux: int, pwm_value: int,
                    mode: str, bounds_min: int, bounds_max: int) -> bool:
        """Log a reading to CSV on USB. Returns True if successful."""
        # Try to find USB if not already found
        if not self.usb_path:
            self.usb_path = self.find_usb()
            if self.usb_path:
                self.csv_path = os.path.join(self.usb_path, CSV_FILENAME)
                print(f"[USB] Found USB at: {self.usb_path}")
            else:
                return False  # No USB found

        # Initialize CSV if needed
        self._init_csv()

        if not self._file_initialized:
            return False

        # Write reading
        try:
            now = datetime.now()
            row = [
                now.timestamp(),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                raw_lux,
                clamped_lux,
                pwm_value,
                mode,
                bounds_min,
                bounds_max
            ]

            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(row)

            return True
        except IOError as e:
            # USB might have been removed
            print(f"[USB] Write failed: {e}")
            self.usb_path = None
            self.csv_path = None
            self._file_initialized = False
            return False

    def get_status(self) -> dict:
        """Get USB logger status."""
        return {
            "usb_connected": self.usb_path is not None,
            "usb_path": self.usb_path,
            "csv_path": self.csv_path
        }


# Global instance
usb_logger = USBLogger()