#!/usr/bin/env python3
"""
Test script for web server API endpoints.
Uses mocks to run without Raspberry Pi hardware.
"""

import sys
import os
import json
import time
import tempfile

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Install mocks BEFORE importing anything else
from mock_hardware import install_mocks
mocks = install_mocks()

# Now we can import the web server (it imports io_controller which needs mocks)
from database import Database
from web_server import app, update_current_state, current_state


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def record(self, name, passed, details=""):
        if passed:
            self.passed += 1
            print(f"  ✓ {name}")
        else:
            self.failed += 1
            print(f"  ✗ {name}: {details}")


def test_database():
    """Test database operations."""
    print("\n[Test: Database Operations]")
    results = TestResults()

    # Use temp database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    db = Database(db_path)

    # Test logging
    db.log_reading(
        raw_lux=1000,
        clamped_lux=950,
        pwm_value=500,
        mode='lux',
        bounds_min=100,
        bounds_max=1000
    )

    results.record(
        "Log reading succeeds",
        True
    )

    # Test get latest
    latest = db.get_latest_reading()
    results.record(
        "Get latest reading",
        latest is not None and latest['raw_lux'] == 1000,
        f"Got: {latest}"
    )

    # Test history
    history = db.get_history(limit=10)
    results.record(
        "Get history",
        len(history) == 1,
        f"Got {len(history)} records"
    )

    # Test web control state
    state = db.get_web_control_state()
    results.record(
        "Get initial web control state",
        state['web_manual_enabled'] == False and state['web_manual_pwm'] == 0,
        f"Got: {state}"
    )

    # Test set web control
    db.set_web_control_state(True, 512)
    state = db.get_web_control_state()
    results.record(
        "Set web control state",
        state['web_manual_enabled'] == True and state['web_manual_pwm'] == 512,
        f"Got: {state}"
    )

    # Test stats
    stats = db.get_stats(hours=24)
    results.record(
        "Get stats",
        stats['count'] == 1 and stats['avg_lux'] == 1000,
        f"Got: {stats}"
    )

    db.close()
    os.unlink(db_path)

    return results


def test_api_endpoints():
    """Test Flask API endpoints."""
    print("\n[Test: API Endpoints]")
    results = TestResults()

    # Create test client
    app.config['TESTING'] = True
    client = app.test_client()

    # Test status endpoint
    response = client.get('/api/status')
    results.record(
        "GET /api/status returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    data = json.loads(response.data)
    results.record(
        "Status contains expected fields",
        'raw_lux' in data and 'pwm_value' in data and 'mode' in data,
        f"Got keys: {list(data.keys())}"
    )

    # Test control GET endpoint
    response = client.get('/api/control')
    results.record(
        "GET /api/control returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    # Test control POST endpoint
    response = client.post('/api/control',
                           data=json.dumps({'enabled': True, 'pwm': 750}),
                           content_type='application/json')
    results.record(
        "POST /api/control returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    data = json.loads(response.data)
    results.record(
        "Control update returns success",
        data.get('success') == True and data.get('pwm') == 750,
        f"Got: {data}"
    )

    # Test history endpoint
    response = client.get('/api/history?hours=1&limit=10')
    results.record(
        "GET /api/history returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    # Test stats endpoint
    response = client.get('/api/stats?hours=24')
    results.record(
        "GET /api/stats returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    # Test main page
    response = client.get('/')
    results.record(
        "GET / returns 200",
        response.status_code == 200,
        f"Got status {response.status_code}"
    )

    results.record(
        "Main page contains dashboard HTML",
        b'Chamber Control' in response.data,
        "Dashboard title not found"
    )

    return results


def test_state_updates():
    """Test state update broadcasting."""
    print("\n[Test: State Updates]")
    results = TestResults()

    # Update state
    update_current_state(
        raw_lux=2000,
        clamped_lux=1800,
        pwm_value=700,
        mode='lux',
        bounds_min=500,
        bounds_max=2000,
        pot_value=0.5,
        sw1=True,
        sw2=False
    )

    results.record(
        "State update succeeds",
        True
    )

    results.record(
        "Current state updated",
        current_state['raw_lux'] == 2000 and current_state['pwm_value'] == 700,
        f"Got: raw_lux={current_state['raw_lux']}, pwm={current_state['pwm_value']}"
    )

    results.record(
        "Switch states updated",
        current_state['sw1'] == True and current_state['sw2'] == False,
        f"Got: sw1={current_state['sw1']}, sw2={current_state['sw2']}"
    )

    return results


def test_pwm_validation():
    """Test PWM value validation in control endpoint."""
    print("\n[Test: PWM Validation]")
    results = TestResults()

    app.config['TESTING'] = True
    client = app.test_client()

    # Test PWM clamping - too high
    response = client.post('/api/control',
                           data=json.dumps({'enabled': True, 'pwm': 5000}),
                           content_type='application/json')
    data = json.loads(response.data)
    results.record(
        "PWM > 1023 clamped to 1023",
        data.get('pwm') == 1023,
        f"Got: {data.get('pwm')}"
    )

    # Test PWM clamping - negative
    response = client.post('/api/control',
                           data=json.dumps({'enabled': True, 'pwm': -100}),
                           content_type='application/json')
    data = json.loads(response.data)
    results.record(
        "PWM < 0 clamped to 0",
        data.get('pwm') == 0,
        f"Got: {data.get('pwm')}"
    )

    # Test valid PWM
    response = client.post('/api/control',
                           data=json.dumps({'enabled': True, 'pwm': 512}),
                           content_type='application/json')
    data = json.loads(response.data)
    results.record(
        "Valid PWM passes through",
        data.get('pwm') == 512,
        f"Got: {data.get('pwm')}"
    )

    return results


def run_all_tests():
    """Run all web server tests."""
    print("=" * 50)
    print("Web Server API Tests")
    print("=" * 50)

    all_results = []

    all_results.append(test_database())
    all_results.append(test_api_endpoints())
    all_results.append(test_state_updates())
    all_results.append(test_pwm_validation())

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