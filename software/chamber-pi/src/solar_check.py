"""
Solar position sanity checker.

Uses pysolar to estimate sun elevation from GPS lat/lon/time, then checks
whether the received `clear` channel reading is plausible given the expected
solar irradiance. Returns True (flag raised) if the reading looks suspicious.

Requires: pysolar  (pip install pysolar)
"""

import datetime
import math

try:
    from pysolar.solar import get_altitude
    from pysolar.radiation import get_radiation_direct
    _PYSOLAR_AVAILABLE = True
except ImportError:
    _PYSOLAR_AVAILABLE = False
    print("[SolarCheck] pysolar not installed — sanity checking disabled. Run: pip install pysolar")


# Empirical scaling: approximate AS7343 `clear` counts per W/m²
# Tune this once you have real paired measurements.
CLEAR_PER_WM2 = 5.0

# How many times outside the expected range before we flag it.
# e.g. 5 means the reading must be <1/5 or >5x the expected value to be flagged.
SANITY_TOLERANCE = 5.0

# Minimum sun elevation (degrees) before we bother checking.
# Below this the sun is near the horizon and irradiance models are unreliable.
MIN_ELEVATION_DEG = 5.0


def check_reading(clear_value: int, lat: float, lon: float, unix_time: int) -> bool:
    """
    Returns True if the reading appears suspicious (sanity flag raised),
    False if it looks plausible or if the check cannot be performed.

    Args:
        clear_value:  AS7343 clear channel count from the satellite
        lat:          GPS latitude in decimal degrees
        lon:          GPS longitude in decimal degrees
        unix_time:    UTC Unix timestamp of the measurement

    Returns:
        True  → reading is suspect (flag it)
        False → reading looks fine (or check skipped)
    """
    if not _PYSOLAR_AVAILABLE:
        return False

    if lat == 0.0 and lon == 0.0:
        return False  # No valid GPS fix

    if unix_time <= 0:
        return False

    try:
        dt = datetime.datetime.fromtimestamp(unix_time, tz=datetime.timezone.utc)
        elevation_deg = get_altitude(lat, lon, dt)

        if elevation_deg < MIN_ELEVATION_DEG:
            # Sun is below or near horizon — nighttime/twilight, expect near-zero
            # Flag only if reading is very high (sensor malfunction)
            return bool(clear_value > 1000)

        radiation = get_radiation_direct(dt, elevation_deg)  # W/m²
        expected_clear = radiation * CLEAR_PER_WM2

        if expected_clear <= 0:
            return False

        ratio = clear_value / expected_clear
        flagged = bool(ratio < (1.0 / SANITY_TOLERANCE) or ratio > SANITY_TOLERANCE)

        if flagged:
            print(f"[SolarCheck] FLAGGED — clear={clear_value}, expected≈{expected_clear:.0f} "
                  f"(elev={elevation_deg:.1f}°, ratio={ratio:.2f})")

        return flagged

    except Exception as exc:
        print(f"[SolarCheck] Error during check: {exc}")
        return False
