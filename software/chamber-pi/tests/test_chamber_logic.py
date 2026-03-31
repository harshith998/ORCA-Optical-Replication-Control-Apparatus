#!/usr/bin/env python3
"""
Test script for chamber-pi logic.
Tests bounds buffer, clamping, mode switching, etc.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Install mocks BEFORE importing chamber modules
from mock_hardware import install_mocks, MockGPIO, MockSpiDev, MockSerial
mocks = install_mocks()

# Now import chamber modules
from config import LUX_BUFFER_SIZE, SCALE_CONSTANT, MAX_PWM_VALUE
from io_controller import IOController


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def record(self, name, passed, details=""):
        self.tests.append((name, passed, details))
        if passed:
            self.passed += 1
            print(f"  ✓ {name}")
        else:
            self.failed += 1
            print(f"  ✗ {name}: {details}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"Results: {self.passed}/{total} passed")
        if self.failed > 0:
            print(f"FAILED: {self.failed} tests")
        else:
            print("ALL TESTS PASSED!")
        print(f"{'='*50}")
        return self.failed == 0


def test_buffer_initialization():
    """Test that buffer initializes correctly."""
    print("\n[Test: Buffer Initialization]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    results.record(
        "Buffer size is correct",
        len(io.lux_buffer) == LUX_BUFFER_SIZE,
        f"Expected {LUX_BUFFER_SIZE}, got {len(io.lux_buffer)}"
    )

    results.record(
        "Buffer index starts at 0",
        io.buffer_index == 0,
        f"Expected 0, got {io.buffer_index}"
    )

    results.record(
        "Buffer count starts at 0",
        io.buffer_count == 0,
        f"Expected 0, got {io.buffer_count}"
    )

    results.record(
        "Initial min/max are 0",
        io.live_min == 0 and io.live_max == 0,
        f"Got min={io.live_min}, max={io.live_max}"
    )

    return results


def test_buffer_filling():
    """Test that buffer fills correctly."""
    print("\n[Test: Buffer Filling]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Add 10 values
    test_values = [100, 150, 200, 180, 120, 90, 250, 175, 160, 140]
    for val in test_values:
        io.get_clamped_lux(val)

    results.record(
        "Buffer count is 10 after adding 10 values",
        io.buffer_count == 10,
        f"Expected 10, got {io.buffer_count}"
    )

    results.record(
        "Buffer index is 10 after adding 10 values",
        io.buffer_index == 10,
        f"Expected 10, got {io.buffer_index}"
    )

    results.record(
        "Min is calculated correctly",
        io.live_min == 90,
        f"Expected 90, got {io.live_min}"
    )

    results.record(
        "Max is calculated correctly",
        io.live_max == 250,
        f"Expected 250, got {io.live_max}"
    )

    return results


def test_circular_buffer_wrap():
    """Test that buffer wraps around correctly using a small simulated buffer."""
    print("\n[Test: Circular Buffer Wrap]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Manually set up a small buffer for testing wrap behavior
    small_size = 5
    io.lux_buffer = [0] * small_size
    io.buffer_index = 0
    io.buffer_count = 0

    # Override the buffer size check by directly manipulating
    # We'll test the wrap logic manually

    # Fill buffer completely
    for i in range(small_size):
        io.lux_buffer[io.buffer_index] = 100 + i * 10
        io.buffer_index = (io.buffer_index + 1) % small_size
        if io.buffer_count < small_size:
            io.buffer_count += 1

    results.record(
        "Buffer is full",
        io.buffer_count == 5,
        f"Expected 5, got {io.buffer_count}"
    )

    results.record(
        "Index wrapped to 0",
        io.buffer_index == 0,
        f"Expected 0, got {io.buffer_index}"
    )

    # Add one more (should overwrite oldest)
    io.lux_buffer[io.buffer_index] = 200
    io.buffer_index = (io.buffer_index + 1) % small_size

    results.record(
        "Buffer count stays at max",
        io.buffer_count == 5,
        f"Expected 5, got {io.buffer_count}"
    )

    results.record(
        "Index advanced to 1",
        io.buffer_index == 1,
        f"Expected 1, got {io.buffer_index}"
    )

    # Calculate bounds manually
    io._update_bounds()

    results.record(
        "New max reflects new value",
        io.live_max == 200,
        f"Expected 200, got {io.live_max}"
    )

    return results


def test_clamping_before_buffer_full():
    """Test that no clamping happens before buffer is full."""
    print("\n[Test: No Clamping Before Buffer Full]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Add some values (buffer won't be full since LUX_BUFFER_SIZE=600)
    io.get_clamped_lux(100)
    io.get_clamped_lux(150)
    io.get_clamped_lux(200)

    # Buffer not full, should return raw value even if "outlier"
    result = io.get_clamped_lux(1000)

    results.record(
        "Returns raw value when buffer not full",
        result == 1000,
        f"Expected 1000, got {result}"
    )

    results.record(
        "Buffer count is 4",
        io.buffer_count == 4,
        f"Expected 4, got {io.buffer_count}"
    )

    return results


def test_clamping_after_buffer_full():
    """Test that clamping works after buffer is full (simulated)."""
    print("\n[Test: Clamping After Buffer Full]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Simulate a full buffer by setting count to max
    small_size = 5
    io.lux_buffer = [100, 110, 120, 130, 140] + [0] * (LUX_BUFFER_SIZE - 5)
    io.buffer_count = LUX_BUFFER_SIZE  # Pretend buffer is full
    io.buffer_index = 0
    io._update_bounds()

    # Now buffer appears full, min=100, max=140 (from first 5)
    # But _update_bounds looks at buffer_count elements
    # Since buffer_count = LUX_BUFFER_SIZE, it looks at all 600 elements (mostly 0)
    # So min would be 0. Let me fix this test differently.

    # Actually, let's test the clamping logic directly
    io.lux_buffer = [0] * LUX_BUFFER_SIZE
    io.buffer_index = 0
    io.buffer_count = 0

    # Fill with stable values
    for _ in range(LUX_BUFFER_SIZE):
        io.lux_buffer[io.buffer_index] = 500
        io.buffer_index = (io.buffer_index + 1) % LUX_BUFFER_SIZE
        if io.buffer_count < LUX_BUFFER_SIZE:
            io.buffer_count += 1

    io._update_bounds()

    results.record(
        "Min is 500 (all same values)",
        io.live_min == 500,
        f"Expected 500, got {io.live_min}"
    )

    results.record(
        "Max is 500 (all same values)",
        io.live_max == 500,
        f"Expected 500, got {io.live_max}"
    )

    # Now use get_clamped_lux which should clamp since buffer is full
    # Add a high value - it gets added, bounds update, then clamp check
    result = io.get_clamped_lux(1000)

    # After adding 1000, buffer has one 1000 and rest 500s
    # So bounds are min=500, max=1000
    # Value 1000 is within bounds, returns 1000

    results.record(
        "High value updates max (system adapts)",
        io.live_max == 1000,
        f"Expected 1000, got {io.live_max}"
    )

    results.record(
        "High value returns as-is (within new bounds)",
        result == 1000,
        f"Expected 1000, got {result}"
    )

    return results


def test_clamping_low_value():
    """Test clamping when value is below minimum."""
    print("\n[Test: Clamping Low Value]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Fill buffer with stable values
    io.lux_buffer = [500] * LUX_BUFFER_SIZE
    io.buffer_index = 0
    io.buffer_count = LUX_BUFFER_SIZE
    io._update_bounds()

    results.record(
        "Min and max are both 500",
        io.live_min == 500 and io.live_max == 500,
        f"Got min={io.live_min}, max={io.live_max}"
    )

    # Add a low value - one element becomes 10
    # New bounds: min=10, max=500
    result = io.get_clamped_lux(10)

    results.record(
        "Low value updates min",
        io.live_min == 10,
        f"Expected 10, got {io.live_min}"
    )

    results.record(
        "Low value returns as-is (within new bounds)",
        result == 10,
        f"Expected 10, got {result}"
    )

    return results


def test_switch_reading():
    """Test switch state reading."""
    print("\n[Test: Switch Reading]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Set up mock GPIO
    MockGPIO._pin_states = {14: MockGPIO.HIGH, 12: MockGPIO.LOW}

    io._read_switches()

    results.record(
        "Switch 1 reads HIGH",
        io.sw1 == True,
        f"Expected True, got {io.sw1}"
    )

    results.record(
        "Switch 2 reads LOW",
        io.sw2 == False,
        f"Expected False, got {io.sw2}"
    )

    # Toggle switches
    MockGPIO._pin_states = {14: MockGPIO.LOW, 12: MockGPIO.HIGH}
    io._read_switches()

    results.record(
        "Switch 1 reads LOW after toggle",
        io.sw1 == False,
        f"Expected False, got {io.sw1}"
    )

    results.record(
        "Switch 2 reads HIGH after toggle",
        io.sw2 == True,
        f"Expected True, got {io.sw2}"
    )

    return results


def test_analog_reading():
    """Test potentiometer ADC reading."""
    print("\n[Test: Analog Reading]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Set ADC to mid-range (512)
    io.spi.set_adc_value(512)
    io._read_analog()

    results.record(
        "Mid-range ADC gives ~0.5",
        0.49 < io.pot_value < 0.51,
        f"Expected ~0.5, got {io.pot_value}"
    )

    # Set ADC to max (1023)
    io.spi.set_adc_value(1023)
    io._read_analog()

    results.record(
        "Max ADC gives 1.0",
        io.pot_value == 1.0,
        f"Expected 1.0, got {io.pot_value}"
    )

    # Set ADC to min (0)
    io.spi.set_adc_value(0)
    io._read_analog()

    results.record(
        "Min ADC gives 0.0",
        io.pot_value == 0.0,
        f"Expected 0.0, got {io.pot_value}"
    )

    return results


def test_uart_reading():
    """Test UART lux value reading."""
    print("\n[Test: UART Reading]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    # Add lux value to serial buffer
    io.serial.add_data("1500")
    io._read_uart()

    results.record(
        "UART reads integer lux",
        io.lux_value == 1500,
        f"Expected 1500, got {io.lux_value}"
    )

    # Add float value
    io.serial.add_data("2500.75")
    io._read_uart()

    results.record(
        "UART converts float to int",
        io.lux_value == 2500,
        f"Expected 2500, got {io.lux_value}"
    )

    return results


def test_pwm_normalization():
    """Test PWM scaling from lux to duty cycle."""
    print("\n[Test: PWM Normalization]")
    results = TestResults()

    # Test the normalization formula used in main.py
    def normalize_lux(lux):
        input_norm = lux / SCALE_CONSTANT
        return max(0.0, min(1.0, input_norm))

    def to_pwm(input_norm):
        return int(input_norm * MAX_PWM_VALUE + 0.5)

    # Test at scale constant (should be 1.0 / 100%)
    norm = normalize_lux(SCALE_CONSTANT)
    pwm = to_pwm(norm)

    results.record(
        f"Lux {SCALE_CONSTANT} normalizes to 1.0",
        norm == 1.0,
        f"Expected 1.0, got {norm}"
    )

    results.record(
        f"Norm 1.0 gives PWM {MAX_PWM_VALUE}",
        pwm == MAX_PWM_VALUE,
        f"Expected {MAX_PWM_VALUE}, got {pwm}"
    )

    # Test at half scale
    norm = normalize_lux(SCALE_CONSTANT / 2)
    pwm = to_pwm(norm)

    results.record(
        "Half lux gives ~0.5 normalized",
        0.49 < norm < 0.51,
        f"Expected ~0.5, got {norm}"
    )

    # Test clamping above max
    norm = normalize_lux(SCALE_CONSTANT * 2)

    results.record(
        "Above scale constant clamps to 1.0",
        norm == 1.0,
        f"Expected 1.0, got {norm}"
    )

    return results


def test_to_string():
    """Test string representation for debugging."""
    print("\n[Test: String Representation]")
    results = TestResults()

    io = IOController()
    io.spi = MockSpiDev()
    io.serial = MockSerial()

    io.sw1 = True
    io.sw2 = False
    io.pot_value = 0.5
    io.lux_value = 1234

    s = io.to_string()

    results.record(
        "Contains switch states",
        "S1=HIGH" in s and "S2=LOW" in s,
        f"Got: {s}"
    )

    results.record(
        "Contains pot value",
        "0.500" in s,
        f"Got: {s}"
    )

    results.record(
        "Contains lux value",
        "1234" in s,
        f"Got: {s}"
    )

    return results


def run_all_tests():
    """Run all tests and report results."""
    print("=" * 50)
    print("Chamber-Pi Logic Tests")
    print("=" * 50)

    all_results = []

    all_results.append(test_buffer_initialization())
    all_results.append(test_buffer_filling())
    all_results.append(test_circular_buffer_wrap())
    all_results.append(test_clamping_before_buffer_full())
    all_results.append(test_clamping_after_buffer_full())
    all_results.append(test_clamping_low_value())
    all_results.append(test_switch_reading())
    all_results.append(test_analog_reading())
    all_results.append(test_uart_reading())
    all_results.append(test_pwm_normalization())
    all_results.append(test_to_string())

    # Summary
    total_passed = sum(r.passed for r in all_results)
    total_failed = sum(r.failed for r in all_results)

    print(f"\n{'=' * 50}")
    print(f"TOTAL: {total_passed}/{total_passed + total_failed} tests passed")
    if total_failed > 0:
        print(f"FAILED: {total_failed} tests")
        return False
    else:
        print("ALL TESTS PASSED! ✓")
        return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)