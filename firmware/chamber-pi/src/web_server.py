"""
Flask web server with REST API and Server-Sent Events for live updates.
"""

import json
import time
import threading
import queue
from flask import Flask, jsonify, request, Response, render_template_string
from typing import Generator

from database import db
from config import MAX_PWM_VALUE

app = Flask(__name__)

# SSE subscribers
sse_subscribers: list[queue.Queue] = []
sse_lock = threading.Lock()

# Current state cache (updated by main loop)
current_state = {
    'raw_lux': 0,
    'clamped_lux': 0,
    'pwm_value': 0,
    'mode': 'lux',
    'bounds_min': 0,
    'bounds_max': 0,
    'pot_value': 0.0,
    'sw1': False,
    'sw2': False,
    'web_manual_enabled': False,
    'web_manual_pwm': 0,
    'timestamp': time.time()
}
state_lock = threading.Lock()


def update_current_state(raw_lux: int, clamped_lux: int, pwm_value: int,
                         mode: str, bounds_min: int, bounds_max: int,
                         pot_value: float, sw1: bool, sw2: bool):
    """Update current state and notify SSE subscribers."""
    with state_lock:
        # Update in-place to preserve references
        current_state['raw_lux'] = raw_lux
        current_state['clamped_lux'] = clamped_lux
        current_state['pwm_value'] = pwm_value
        current_state['mode'] = mode
        current_state['bounds_min'] = bounds_min
        current_state['bounds_max'] = bounds_max
        current_state['pot_value'] = pot_value
        current_state['sw1'] = sw1
        current_state['sw2'] = sw2
        current_state['timestamp'] = time.time()
        state_copy = current_state.copy()

    # Notify SSE subscribers
    broadcast_sse(state_copy)


def broadcast_sse(data: dict):
    """Broadcast data to all SSE subscribers."""
    message = f"data: {json.dumps(data)}\n\n"
    dead_queues = []

    with sse_lock:
        for q in sse_subscribers:
            try:
                q.put_nowait(message)
            except queue.Full:
                dead_queues.append(q)

        # Remove dead queues
        for q in dead_queues:
            sse_subscribers.remove(q)


def sse_stream() -> Generator[str, None, None]:
    """Generator for SSE stream."""
    q: queue.Queue = queue.Queue(maxsize=100)

    with sse_lock:
        sse_subscribers.append(q)

    try:
        # Send initial state
        with state_lock:
            yield f"data: {json.dumps(current_state)}\n\n"

        while True:
            try:
                message = q.get(timeout=30)
                yield message
            except queue.Empty:
                # Send keepalive
                yield ": keepalive\n\n"
    finally:
        with sse_lock:
            if q in sse_subscribers:
                sse_subscribers.remove(q)


# ============== API Routes ==============

@app.route('/api/status')
def api_status():
    """Get current system status."""
    with state_lock:
        return jsonify(current_state)


@app.route('/api/control', methods=['GET', 'POST'])
def api_control():
    """Get or set web manual control state."""
    if request.method == 'GET':
        state = db.get_web_control_state()
        return jsonify(state)

    # POST - update control state
    data = request.get_json() or {}

    enabled = data.get('enabled', False)
    pwm = data.get('pwm', 0)

    # Validate PWM value
    pwm = max(0, min(MAX_PWM_VALUE, int(pwm)))

    db.set_web_control_state(enabled, pwm)

    # Update current state cache
    with state_lock:
        current_state['web_manual_enabled'] = enabled
        current_state['web_manual_pwm'] = pwm

    return jsonify({'success': True, 'enabled': enabled, 'pwm': pwm})


@app.route('/api/history')
def api_history():
    """Get historical data."""
    # Query parameters
    hours = request.args.get('hours', 24, type=float)
    limit = request.args.get('limit', 1000, type=int)

    start_time = time.time() - (hours * 3600)
    history = db.get_history(start_time=start_time, limit=limit)

    return jsonify(history)


@app.route('/api/stats')
def api_stats():
    """Get statistics."""
    hours = request.args.get('hours', 24, type=int)
    stats = db.get_stats(hours)
    return jsonify(stats)


@app.route('/api/stream')
def api_stream():
    """Server-Sent Events stream for live updates."""
    return Response(
        sse_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/')
def index():
    """Serve the main dashboard."""
    return render_template_string(DASHBOARD_HTML)


# ============== Dashboard HTML ==============

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chamber Control</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-primary: #0f0f0f;
            --bg-secondary: #1a1a1a;
            --bg-card: #242424;
            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --border: #333333;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.5;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid var(--border);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--accent), #8b5cf6);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .logo-icon svg {
            width: 24px;
            height: 24px;
            fill: white;
        }

        h1 {
            font-size: 24px;
            font-weight: 600;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: var(--bg-card);
            border-radius: 20px;
            font-size: 14px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
            animation: pulse 2s infinite;
        }

        .status-dot.disconnected {
            background: var(--danger);
            animation: none;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 24px;
            margin-bottom: 24px;
        }

        .card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid var(--border);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .card-title {
            font-size: 14px;
            font-weight: 500;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .card-icon {
            width: 36px;
            height: 36px;
            background: var(--bg-secondary);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .card-icon svg {
            width: 20px;
            height: 20px;
            fill: var(--accent);
        }

        .metric {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .metric-value {
            font-size: 48px;
            font-weight: 700;
            line-height: 1;
        }

        .metric-unit {
            font-size: 16px;
            color: var(--text-secondary);
        }

        .metric-label {
            font-size: 14px;
            color: var(--text-secondary);
        }

        .metric-row {
            display: flex;
            justify-content: space-between;
            padding: 12px 0;
            border-bottom: 1px solid var(--border);
        }

        .metric-row:last-child {
            border-bottom: none;
        }

        .control-section {
            margin-top: 20px;
        }

        .toggle-container {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px;
            background: var(--bg-secondary);
            border-radius: 12px;
            margin-bottom: 16px;
        }

        .toggle-label {
            font-weight: 500;
        }

        .toggle {
            position: relative;
            width: 56px;
            height: 28px;
        }

        .toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            inset: 0;
            background: var(--bg-card);
            border-radius: 14px;
            transition: 0.3s;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 22px;
            width: 22px;
            left: 3px;
            bottom: 3px;
            background: white;
            border-radius: 50%;
            transition: 0.3s;
        }

        .toggle input:checked + .toggle-slider {
            background: var(--accent);
        }

        .toggle input:checked + .toggle-slider:before {
            transform: translateX(28px);
        }

        .slider-container {
            padding: 16px;
            background: var(--bg-secondary);
            border-radius: 12px;
        }

        .slider-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
        }

        .slider-value {
            font-weight: 600;
            color: var(--accent);
        }

        input[type="range"] {
            width: 100%;
            height: 8px;
            background: var(--bg-card);
            border-radius: 4px;
            outline: none;
            -webkit-appearance: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 24px;
            height: 24px;
            background: var(--accent);
            border-radius: 50%;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(59, 130, 246, 0.4);
        }

        input[type="range"]:disabled {
            opacity: 0.5;
        }

        input[type="range"]:disabled::-webkit-slider-thumb {
            cursor: not-allowed;
            background: var(--text-secondary);
        }

        .chart-container {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid var(--border);
        }

        .chart-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .chart-title {
            font-size: 18px;
            font-weight: 600;
        }

        .time-selector {
            display: flex;
            gap: 8px;
        }

        .time-btn {
            padding: 8px 16px;
            background: var(--bg-secondary);
            border: none;
            border-radius: 8px;
            color: var(--text-secondary);
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }

        .time-btn:hover {
            background: var(--border);
        }

        .time-btn.active {
            background: var(--accent);
            color: white;
        }

        .chart-wrapper {
            position: relative;
            height: 300px;
        }

        .bounds-indicator {
            display: flex;
            gap: 24px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
        }

        .bound-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .bound-color {
            width: 12px;
            height: 12px;
            border-radius: 3px;
        }

        .bound-color.min {
            background: var(--success);
        }

        .bound-color.max {
            background: var(--danger);
        }

        .mode-indicator {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
        }

        .mode-indicator.lux {
            background: rgba(34, 197, 94, 0.2);
            color: var(--success);
        }

        .mode-indicator.analog {
            background: rgba(245, 158, 11, 0.2);
            color: var(--warning);
        }

        .mode-indicator.manual {
            background: rgba(59, 130, 246, 0.2);
            color: var(--accent);
        }

        footer {
            text-align: center;
            padding: 24px;
            color: var(--text-secondary);
            font-size: 14px;
        }

        @media (max-width: 768px) {
            .container {
                padding: 16px;
            }

            header {
                flex-direction: column;
                gap: 16px;
                align-items: flex-start;
            }

            .metric-value {
                font-size: 36px;
            }

            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">
                    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                </div>
                <h1>Chamber Control</h1>
            </div>
            <div class="status-badge">
                <div class="status-dot" id="connectionStatus"></div>
                <span id="connectionText">Connecting...</span>
            </div>
        </header>

        <div class="grid">
            <!-- Live Lux Card -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Live Light Intensity</span>
                    <div class="card-icon">
                        <svg viewBox="0 0 24 24"><path d="M12 7c-2.76 0-5 2.24-5 5s2.24 5 5 5 5-2.24 5-5-2.24-5-5-5zM2 13h2c.55 0 1-.45 1-1s-.45-1-1-1H2c-.55 0-1 .45-1 1s.45 1 1 1zm18 0h2c.55 0 1-.45 1-1s-.45-1-1-1h-2c-.55 0-1 .45-1 1s.45 1 1 1zM11 2v2c0 .55.45 1 1 1s1-.45 1-1V2c0-.55-.45-1-1-1s-1 .45-1 1zm0 18v2c0 .55.45 1 1 1s1-.45 1-1v-2c0-.55-.45-1-1-1s-1 .45-1 1z"/></svg>
                    </div>
                </div>
                <div class="metric">
                    <div>
                        <span class="metric-value" id="luxValue">--</span>
                        <span class="metric-unit">lux</span>
                    </div>
                    <span class="metric-label">Clamped: <span id="clampedValue">--</span> lux</span>
                </div>
                <div class="bounds-indicator">
                    <div class="bound-item">
                        <div class="bound-color min"></div>
                        <span>Min: <span id="boundsMin">--</span></span>
                    </div>
                    <div class="bound-item">
                        <div class="bound-color max"></div>
                        <span>Max: <span id="boundsMax">--</span></span>
                    </div>
                </div>
            </div>

            <!-- PWM Output Card -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">LED Output</span>
                    <div class="card-icon">
                        <svg viewBox="0 0 24 24"><path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7z"/></svg>
                    </div>
                </div>
                <div class="metric">
                    <div>
                        <span class="metric-value" id="pwmValue">--</span>
                        <span class="metric-unit">/ 1023</span>
                    </div>
                    <span class="metric-label"><span id="pwmPercent">--</span>% brightness</span>
                </div>
                <div style="margin-top: 16px">
                    <span class="mode-indicator" id="modeIndicator">--</span>
                </div>
            </div>

            <!-- Manual Control Card -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Web Manual Control</span>
                    <div class="card-icon">
                        <svg viewBox="0 0 24 24"><path d="M7 24h2v-2H7v2zm4 0h2v-2h-2v2zm4 0h2v-2h-2v2zM16 .01L8 0C6.9 0 6 .9 6 2v16c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V2c0-1.1-.9-1.99-2-1.99zM16 16H8V4h8v12z"/></svg>
                    </div>
                </div>
                <div class="control-section">
                    <div class="toggle-container">
                        <span class="toggle-label">Enable Web Control</span>
                        <label class="toggle">
                            <input type="checkbox" id="webManualToggle" onchange="toggleWebManual()">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="slider-container">
                        <div class="slider-header">
                            <span>Manual Brightness</span>
                            <span class="slider-value" id="manualPwmDisplay">0</span>
                        </div>
                        <input type="range" id="manualPwmSlider" min="0" max="1023" value="0"
                               oninput="updateManualPwm()" disabled>
                    </div>
                </div>
            </div>

            <!-- System Status Card -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">System Status</span>
                    <div class="card-icon">
                        <svg viewBox="0 0 24 24"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z"/></svg>
                    </div>
                </div>
                <div class="metric-row">
                    <span>Physical Mode Switch</span>
                    <span id="sw1Status">--</span>
                </div>
                <div class="metric-row">
                    <span>Physical PWM Switch</span>
                    <span id="sw2Status">--</span>
                </div>
                <div class="metric-row">
                    <span>Potentiometer</span>
                    <span id="potValue">--</span>
                </div>
            </div>
        </div>

        <!-- Chart Section -->
        <div class="chart-container">
            <div class="chart-header">
                <span class="chart-title">Light Intensity History</span>
                <div class="time-selector">
                    <button class="time-btn" onclick="loadHistory(1)">1H</button>
                    <button class="time-btn active" onclick="loadHistory(6)">6H</button>
                    <button class="time-btn" onclick="loadHistory(24)">24H</button>
                    <button class="time-btn" onclick="loadHistory(168)">7D</button>
                </div>
            </div>
            <div class="chart-wrapper">
                <canvas id="luxChart"></canvas>
            </div>
        </div>

        <footer>
            <p>Chamber Control System &bull; Nitrogen Fixation Lab</p>
        </footer>
    </div>

    <script>
        // Chart setup
        const ctx = document.getElementById('luxChart').getContext('2d');
        const luxChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Raw Lux',
                        data: [],
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 0
                    },
                    {
                        label: 'Clamped Lux',
                        data: [],
                        borderColor: '#22c55e',
                        backgroundColor: 'transparent',
                        borderDash: [5, 5],
                        tension: 0.4,
                        pointRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: '#a0a0a0',
                            usePointStyle: true
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: '#333333'
                        },
                        ticks: {
                            color: '#a0a0a0',
                            maxTicksLimit: 10
                        }
                    },
                    y: {
                        grid: {
                            color: '#333333'
                        },
                        ticks: {
                            color: '#a0a0a0'
                        },
                        beginAtZero: true
                    }
                }
            }
        });

        // SSE Connection
        let eventSource = null;
        let reconnectTimeout = null;

        function connectSSE() {
            if (eventSource) {
                eventSource.close();
            }

            eventSource = new EventSource('/api/stream');

            eventSource.onopen = () => {
                document.getElementById('connectionStatus').classList.remove('disconnected');
                document.getElementById('connectionText').textContent = 'Connected';
                if (reconnectTimeout) {
                    clearTimeout(reconnectTimeout);
                    reconnectTimeout = null;
                }
            };

            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateUI(data);
            };

            eventSource.onerror = () => {
                document.getElementById('connectionStatus').classList.add('disconnected');
                document.getElementById('connectionText').textContent = 'Disconnected';
                eventSource.close();

                // Reconnect after 3 seconds
                reconnectTimeout = setTimeout(connectSSE, 3000);
            };
        }

        function updateUI(data) {
            // Update lux values
            document.getElementById('luxValue').textContent = data.raw_lux;
            document.getElementById('clampedValue').textContent = data.clamped_lux;
            document.getElementById('boundsMin').textContent = data.bounds_min;
            document.getElementById('boundsMax').textContent = data.bounds_max;

            // Update PWM
            document.getElementById('pwmValue').textContent = data.pwm_value;
            const percent = ((data.pwm_value / 1023) * 100).toFixed(1);
            document.getElementById('pwmPercent').textContent = percent;

            // Update mode indicator
            const modeEl = document.getElementById('modeIndicator');
            if (data.web_manual_enabled) {
                modeEl.textContent = 'WEB MANUAL';
                modeEl.className = 'mode-indicator manual';
            } else if (data.mode === 'analog') {
                modeEl.textContent = 'ANALOG';
                modeEl.className = 'mode-indicator analog';
            } else {
                modeEl.textContent = 'AUTO LUX';
                modeEl.className = 'mode-indicator lux';
            }

            // Update system status
            document.getElementById('sw1Status').textContent = data.sw1 ? 'ANALOG' : 'LUX';
            document.getElementById('sw2Status').textContent = data.sw2 ? 'OFF' : 'ON';
            document.getElementById('potValue').textContent = (data.pot_value * 100).toFixed(1) + '%';

            // Update web control state
            document.getElementById('webManualToggle').checked = data.web_manual_enabled;
            document.getElementById('manualPwmSlider').disabled = !data.web_manual_enabled;
            if (!document.getElementById('manualPwmSlider').matches(':active')) {
                document.getElementById('manualPwmSlider').value = data.web_manual_pwm;
                document.getElementById('manualPwmDisplay').textContent = data.web_manual_pwm;
            }
        }

        function toggleWebManual() {
            const enabled = document.getElementById('webManualToggle').checked;
            const pwm = parseInt(document.getElementById('manualPwmSlider').value);

            document.getElementById('manualPwmSlider').disabled = !enabled;

            fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled: enabled, pwm: pwm})
            });
        }

        function updateManualPwm() {
            const pwm = parseInt(document.getElementById('manualPwmSlider').value);
            document.getElementById('manualPwmDisplay').textContent = pwm;

            const enabled = document.getElementById('webManualToggle').checked;
            if (enabled) {
                fetch('/api/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({enabled: true, pwm: pwm})
                });
            }
        }

        function loadHistory(hours) {
            // Update active button
            document.querySelectorAll('.time-btn').forEach(btn => {
                btn.classList.remove('active');
                if (btn.textContent === (hours === 168 ? '7D' : hours + 'H')) {
                    btn.classList.add('active');
                }
            });

            fetch(`/api/history?hours=${hours}&limit=500`)
                .then(res => res.json())
                .then(data => {
                    const labels = data.map(d => {
                        const date = new Date(d.timestamp * 1000);
                        return date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
                    });

                    luxChart.data.labels = labels;
                    luxChart.data.datasets[0].data = data.map(d => d.raw_lux);
                    luxChart.data.datasets[1].data = data.map(d => d.clamped_lux);
                    luxChart.update();
                });
        }

        // Initialize
        connectSSE();
        loadHistory(6);

        // Refresh history every 30 seconds
        setInterval(() => {
            const activeBtn = document.querySelector('.time-btn.active');
            const hours = activeBtn.textContent === '7D' ? 168 : parseInt(activeBtn.textContent);
            loadHistory(hours);
        }, 30000);
    </script>
</body>
</html>
"""


def run_server(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask server."""
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=True)