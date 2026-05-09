"""
Flask web server with REST API and Server-Sent Events for live updates.
"""

import json
import os
import time
import threading
import queue
from flask import Flask, jsonify, request, Response, render_template_string
from typing import Generator

from database import db
from config import MAX_PWM_VALUE
from usb_logger import usb_logger
from functools import lru_cache
from solar_check import get_expected_clear

@lru_cache(maxsize=2048)
def _cached_solar_max(lat: float, lon: float, unix_time: int):
    """Memoised wrapper — lat/lon rounded to 0.01° (~1 km), time to 60 s."""
    return get_expected_clear(lat, lon, unix_time)


_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

app = Flask(__name__)

# SSE subscribers
sse_subscribers: list[queue.Queue] = []
sse_lock = threading.Lock()

# Current state cache (updated by main loop)
current_state = {
    'raw_lux': 0,
    'pwm_value': 0,
    'mode': 'lux',
    'sw1': False,
    'sw2': False,
    'sw3': False,
    'web_manual_enabled': False,
    'web_manual_pwm': 0,
    'sanity_flag': False,
    'wired_connected': False,
    'gps': {'valid': False, 'latitude': 0.0, 'longitude': 0.0, 'unix_time': 0},
    'timestamp': time.time()
}
state_lock = threading.Lock()


def get_web_control():
    """Return (web_manual_enabled, web_manual_pwm) from the shared state cache."""
    with state_lock:
        return current_state['web_manual_enabled'], current_state['web_manual_pwm']


def set_web_control(enabled: bool, pwm: int):
    """Update web manual control state in the shared cache."""
    with state_lock:
        current_state['web_manual_enabled'] = enabled
        current_state['web_manual_pwm'] = pwm


def update_current_state(raw_lux: int, pwm_value: int,
                         mode: str,
                         sw1: bool, sw2: bool, sw3: bool,
                         sanity_flag: bool = False,
                         wired_connected: bool = False,
                         gps: dict = None,
                         web_manual_enabled: bool = None,
                         web_manual_pwm: int = None,
                         physical_change: bool = False):
    """Update current state and notify SSE subscribers."""
    with state_lock:
        current_state['raw_lux'] = raw_lux
        current_state['pwm_value'] = pwm_value
        current_state['mode'] = mode
        current_state['sw1'] = sw1
        current_state['sw2'] = sw2
        current_state['sw3'] = sw3
        current_state['sanity_flag'] = sanity_flag
        current_state['wired_connected'] = wired_connected
        if gps is not None:
            current_state['gps'] = gps
        if web_manual_enabled is not None:
            current_state['web_manual_enabled'] = web_manual_enabled
        if web_manual_pwm is not None:
            current_state['web_manual_pwm'] = web_manual_pwm
        current_state['timestamp'] = time.time()
        state_copy = current_state.copy()

    state_copy['physical_change'] = physical_change
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

        for q in dead_queues:
            sse_subscribers.remove(q)


def sse_stream() -> Generator[str, None, None]:
    """Generator for SSE stream."""
    q: queue.Queue = queue.Queue(maxsize=100)

    with sse_lock:
        sse_subscribers.append(q)

    try:
        with state_lock:
            yield f"data: {json.dumps(current_state)}\n\n"

        while True:
            try:
                message = q.get(timeout=30)
                yield message
            except queue.Empty:
                yield ": keepalive\n\n"
    finally:
        with sse_lock:
            if q in sse_subscribers:
                sse_subscribers.remove(q)


# ============== API Routes ==============

@app.route('/api/status')
def api_status():
    with state_lock:
        return jsonify(current_state)


@app.route('/api/control', methods=['GET', 'POST'])
def api_control():
    if request.method == 'GET':
        enabled, pwm = get_web_control()
        return jsonify({'enabled': enabled, 'pwm': pwm})

    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    pwm = max(0, min(MAX_PWM_VALUE, int(data.get('pwm', 0))))
    set_web_control(enabled, pwm)
    return jsonify({'success': True, 'enabled': enabled, 'pwm': pwm})


@app.route('/api/history')
def api_history():
    hours = request.args.get('hours', 24, type=float)
    limit = request.args.get('limit', 500, type=int)
    start_time = time.time() - (hours * 3600)
    bucket_secs = (hours * 3600) / limit
    return jsonify(db.get_chamber_history(start_time=start_time, bucket_secs=bucket_secs))


@app.route('/api/stats')
def api_stats():
    hours = request.args.get('hours', 24, type=int)
    return jsonify(db.get_stats(hours))


@app.route('/api/download/chamber')
def download_chamber():
    import csv, io
    rows = db.get_chamber_history()
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="chamber_history.csv"'}
    )


@app.route('/api/download/sensor')
def download_sensor():
    import csv, io
    rows = db.get_sensor_history(hours=24 * 365)  # all data
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="sensor_history.csv"'}
    )


@app.route('/api/stream')
def api_stream():
    return Response(
        sse_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/usb')
def api_usb():
    return jsonify(usb_logger.get_status())


@app.route('/api/spectrum')
def api_spectrum():
    hours = request.args.get('hours', 6, type=float)
    limit = request.args.get('limit', 500, type=int)
    bucket_secs = (hours * 3600) / limit
    rows = db.get_sensor_history(hours=hours, bucket_secs=bucket_secs)
    for row in rows:
        lat = round(row.get('gps_lat') or 0.0, 2)
        lon = round(row.get('gps_lon') or 0.0, 2)
        t   = int((row.get('gps_unix_time') or row.get('timestamp') or 0) // 60) * 60
        row['solar_max'] = _cached_solar_max(lat, lon, t)
    return jsonify(rows)


@app.route('/chart.js')
def serve_chartjs():
    """Serve Chart.js from local static file for offline operation."""
    path = os.path.join(_STATIC_DIR, 'chart.min.js')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return Response(f.read(), mimetype='application/javascript')
    return Response('console.warn("chart.js not found locally");', mimetype='application/javascript', status=404)


@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


# ============== Dashboard HTML ==============

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ORCA — Chamber Control</title>
<script src="/chart.js"></script>
<style>
:root {
    --bg:           #080f1c;
    --bg-panel:     #0b1525;
    --bg-card:      #0e1b2e;
    --bg-raised:    #152236;
    --bg-input:     #0a1220;
    --text-hi:      #dce6f5;
    --text-mid:     #5a7a9e;
    --text-lo:      #2d4a64;
    --accent:       #2979ff;
    --accent-dim:   rgba(41,121,255,0.12);
    --accent-rim:   rgba(41,121,255,0.28);
    --ok:           #00e5a0;
    --ok-dim:       rgba(0,229,160,0.12);
    --ok-rim:       rgba(0,229,160,0.25);
    --warn:         #ffab40;
    --warn-dim:     rgba(255,171,64,0.12);
    --err:          #ff5252;
    --err-dim:      rgba(255,82,82,0.12);
    --err-rim:      rgba(255,82,82,0.25);
    --rim:          rgba(255,255,255,0.055);
    --rim2:         rgba(255,255,255,0.09);
    --sb:           292px;
    --tb:           50px;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;}
body{
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
    background:var(--bg);
    color:var(--text-hi);
    display:flex;
    flex-direction:column;
    height:100vh;
    overflow:hidden;
}

/* ── TOPBAR ── */
.tb{
    height:var(--tb);
    background:var(--bg-panel);
    border-bottom:1px solid var(--rim2);
    display:flex;
    align-items:center;
    padding:0 20px;
    gap:14px;
    flex-shrink:0;
    z-index:10;
}
.tb-logo{display:flex;align-items:center;gap:9px;}
.tb-mark{
    width:26px;height:26px;
    background:var(--accent);
    border-radius:5px;
    display:flex;align-items:center;justify-content:center;
}
.tb-mark svg{width:14px;height:14px;fill:white;}
.tb-name{font-size:14px;font-weight:700;letter-spacing:0.06em;color:var(--text-hi);}
.tb-sep{width:1px;height:18px;background:var(--rim2);}
.tb-sub{font-size:13px;color:var(--text-mid);}
.tb-sp{flex:1;}
.tb-badge{
    display:flex;align-items:center;gap:6px;
    padding:4px 11px;
    border-radius:3px;
    font-size:11px;font-weight:700;
    letter-spacing:0.09em;text-transform:uppercase;
    border:1px solid transparent;
}
.tb-badge.wired{background:var(--accent-dim);color:#6fa3ff;border-color:var(--accent-rim);}
.tb-badge.wireless{background:rgba(168,85,247,0.1);color:#c084fc;border-color:rgba(168,85,247,0.25);}
.tb-badge.live{background:var(--ok-dim);color:var(--ok);border-color:var(--ok-rim);}
.tb-badge.offline{background:var(--err-dim);color:var(--err);border-color:var(--err-rim);}
.tb-time{font-size:13px;color:var(--text-mid);font-variant-numeric:tabular-nums;letter-spacing:0.03em;}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;display:inline-block;}
.dot.ok{background:var(--ok);}
.dot.err{background:var(--err);}
.dot.acc{background:var(--accent);}
.dot.pulse{animation:pulse 2s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.35;}}

/* ── LAYOUT ── */
.layout{flex:1;display:flex;overflow:hidden;}

/* ── SIDEBAR ── */
.sb{
    width:var(--sb);
    flex-shrink:0;
    background:var(--bg-panel);
    border-right:1px solid var(--rim2);
    display:flex;flex-direction:column;
    overflow-y:auto;overflow-x:hidden;
}
.sb::-webkit-scrollbar{width:3px;}
.sb::-webkit-scrollbar-track{background:transparent;}
.sb::-webkit-scrollbar-thumb{background:var(--rim2);border-radius:2px;}

.sb-sec{padding:18px 20px 15px;border-bottom:1px solid var(--rim);}
.sb-sec:last-child{border-bottom:none;flex:1;}

.lbl{
    font-size:10px;font-weight:700;
    letter-spacing:0.14em;text-transform:uppercase;
    color:var(--text-lo);
    margin-bottom:11px;
}

/* Status row */
.status-row{display:flex;align-items:center;gap:8px;}
.status-txt{font-size:20px;font-weight:600;color:var(--text-hi);}

/* Big metric */
.big-val{
    font-size:46px;font-weight:700;line-height:1;
    color:var(--text-hi);font-variant-numeric:tabular-nums;
}
.big-unit{font-size:16px;font-weight:400;color:var(--text-mid);margin-left:3px;}
.big-sub{font-size:12px;color:var(--text-mid);margin-top:5px;}

/* Rows */
.row{display:flex;justify-content:space-between;align-items:baseline;padding:5px 0;}
.row-k{font-size:12px;color:var(--text-mid);}
.row-v{font-size:13px;color:var(--text-hi);font-weight:500;font-variant-numeric:tabular-nums;}

/* Mode toggle row in sidebar */
.mode-row{
    display:flex;align-items:center;justify-content:space-between;
    margin-bottom:14px;
}
.mode-labels{display:flex;align-items:center;gap:8px;}
.mode-lbl{
    font-size:12px;font-weight:600;letter-spacing:0.04em;
    color:var(--text-mid);transition:color 0.15s;
}
.mode-lbl.active-auto{color:var(--ok);}
.mode-lbl.active-manual{color:#6fa3ff;}

/* Toggle */
.tog{position:relative;width:42px;height:22px;flex-shrink:0;}
.tog input{opacity:0;width:0;height:0;}
.tog-track{
    position:absolute;inset:0;
    background:var(--bg-raised);
    border:1px solid var(--rim2);
    border-radius:11px;cursor:pointer;transition:0.18s;
}
.tog-track::before{
    content:'';position:absolute;
    width:16px;height:16px;top:2px;left:2px;
    background:var(--text-mid);border-radius:50%;transition:0.18s;
}
.tog input:checked + .tog-track{background:var(--accent-dim);border-color:var(--accent-rim);}
.tog input:checked + .tog-track::before{background:var(--accent);transform:translateX(20px);}

/* Slider in sidebar */
.sld-row{display:flex;align-items:center;gap:10px;}
.sld-lbl{font-size:11px;color:var(--text-mid);flex-shrink:0;min-width:64px;}
.sld-row input[type=range]{
    flex:1;height:3px;-webkit-appearance:none;
    background:var(--bg-raised);border-radius:2px;outline:none;cursor:pointer;
}
.sld-row input[type=range]::-webkit-slider-thumb{
    -webkit-appearance:none;width:16px;height:16px;
    background:var(--accent);border-radius:50%;
    box-shadow:0 0 8px rgba(41,121,255,0.45);
}
.sld-row input[type=range]:disabled{opacity:0.22;cursor:not-allowed;}
.sld-row input[type=range]:disabled::-webkit-slider-thumb{background:var(--text-mid);box-shadow:none;}
.sld-val{
    font-size:13px;font-weight:600;color:var(--accent);
    min-width:34px;text-align:right;font-variant-numeric:tabular-nums;
}
.sld-val.dim{color:var(--text-mid);}

/* ── MAIN ── */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;}

/* Chart area — fills all available height */
.chart-area{
    flex:1;min-height:0;
    padding:18px 20px;
    display:flex;flex-direction:column;
}
.chart-panel{
    flex:1;min-height:0;
    background:var(--bg-card);
    border:1px solid var(--rim2);
    border-radius:7px;
    padding:16px 18px;
    display:flex;flex-direction:column;
}
.chart-hdr{
    display:flex;align-items:center;justify-content:space-between;
    margin-bottom:12px;flex-shrink:0;
}
.chart-ttl{
    font-size:11px;font-weight:700;
    letter-spacing:0.12em;text-transform:uppercase;
    color:var(--text-mid);
}
.chart-ctrls{display:flex;align-items:center;gap:8px;}
.ch-sel{
    padding:4px 9px;
    background:var(--bg-raised);
    border:1px solid var(--rim2);
    border-radius:3px;
    color:var(--text-hi);
    font-size:11px;
    cursor:pointer;outline:none;
}
.ch-sel option{background:var(--bg-raised);}
.time-grp{
    display:flex;
    background:var(--bg-raised);
    border:1px solid var(--rim2);
    border-radius:3px;overflow:hidden;
}
.tbtn{
    padding:4px 11px;border:none;background:transparent;
    color:var(--text-mid);font-size:11px;font-weight:700;
    cursor:pointer;letter-spacing:0.06em;transition:all 0.12s;
}
.tbtn:hover{color:var(--text-hi);}
.tbtn.active{background:var(--accent);color:#fff;}
.dl-btn{
    display:flex;align-items:center;gap:7px;width:100%;
    padding:7px 11px;border:1px solid var(--rim2);border-radius:3px;
    background:transparent;color:var(--text-mid);font-size:11px;font-weight:600;
    cursor:pointer;transition:all 0.12s;text-decoration:none;
    letter-spacing:0.04em;
}
.dl-btn:hover{border-color:var(--accent-rim);color:var(--text-hi);}
.dl-btn svg{flex-shrink:0;opacity:0.6;}
.chart-wrap{flex:1;min-height:0;position:relative;}

/* Sanity warning */
.sanity{
    display:none;
    padding:5px 10px;
    background:var(--warn-dim);
    border:1px solid rgba(255,171,64,0.25);
    border-radius:3px;
    color:var(--warn);
    font-size:11px;
    margin-bottom:9px;
    flex-shrink:0;
}

/* ── RESPONSIVE ── */
@media(max-width:860px){
    body{overflow:auto;height:auto;}
    .layout{flex-direction:column;overflow:visible;}
    .sb{width:100%;border-right:none;border-bottom:1px solid var(--rim2);overflow:visible;}
    .main{overflow:visible;}
    .chart-area{min-height:360px;}
}
</style>
</head>
<body>

<!-- ─── TOPBAR ─── -->
<div class="tb">
    <div class="tb-logo">
        <div class="tb-mark">
            <svg viewBox="0 0 24 24"><path d="M12 3L2 21h20L12 3zm0 3.5l7.5 13h-15L12 6.5z"/></svg>
        </div>
        <span class="tb-name">ORCA</span>
    </div>
    <div class="tb-sep"></div>
    <span class="tb-sub">Optical Replication &amp; Control Apparatus</span>
    <div class="tb-sp"></div>

    <div id="sanityWarn" class="tb-badge" style="display:none;background:var(--warn-dim);color:var(--warn);border-color:rgba(255,171,64,0.3);">
        &#9888;&nbsp;Sanity flag
    </div>

    <div id="dataLinkBadge" class="tb-badge wired" style="display:none;">
        <span class="dot acc"></span>
        <span id="dataLinkText">Wired</span>
    </div>

    <span class="tb-time" id="gpsTimeTb">--:--:-- UTC</span>

    <div id="connBadge" class="tb-badge live">
        <span class="dot ok pulse" id="connDot"></span>
        <span id="connText">Connecting</span>
    </div>
</div>

<!-- ─── LAYOUT ─── -->
<div class="layout">

    <!-- SIDEBAR -->
    <div class="sb">

        <!-- System Status -->
        <div class="sb-sec">
            <div class="lbl">System Status</div>
            <div class="status-row">
                <span class="dot ok pulse" id="statusDot"></span>
                <span class="status-txt" id="statusTxt">Operational</span>
            </div>
        </div>

        <!-- Light Intensity -->
        <div class="sb-sec">
            <div class="lbl">Light Intensity</div>
            <div>
                <span class="big-val" id="luxVal">--</span>
                <span class="big-unit">lux</span>
            </div>
        </div>

        <!-- LED Output -->
        <div class="sb-sec">
            <div class="lbl">LED Output</div>
            <div>
                <span class="big-val" id="pwmPct">--</span>
                <span class="big-unit">%</span>
            </div>
            <div class="big-sub">PWM <span id="pwmRaw">--</span> / 1023</div>
        </div>

        <!-- Control Mode -->
        <div class="sb-sec">
            <div class="lbl">Control Mode</div>
            <div class="mode-row">
                <div class="mode-labels">
                    <span class="mode-lbl active-auto" id="lblAuto">Auto</span>
                    <label class="tog">
                        <input type="checkbox" id="modeToggle" onchange="toggleMode()">
                        <span class="tog-track"></span>
                    </label>
                    <span class="mode-lbl" id="lblManual">Manual</span>
                </div>
            </div>
            <div class="sld-row">
                <span class="sld-lbl">Brightness</span>
                <input type="range" id="manualPwmSlider" min="0" max="1023" value="0"
                       oninput="updateManualPwm()" disabled>
                <span class="sld-val dim" id="manualPwmDisplay">0</span>
            </div>
        </div>

        <!-- GPS / Satellite -->
        <div class="sb-sec">
            <div class="lbl">GPS / Satellite</div>
            <div class="row"><span class="row-k">Fix</span><span class="row-v" id="gpsFix">--</span></div>
            <div class="row"><span class="row-k">Latitude</span><span class="row-v" id="gpsLat">--</span></div>
            <div class="row"><span class="row-k">Longitude</span><span class="row-v" id="gpsLon">--</span></div>
        </div>

        <!-- Download -->
        <div class="sb-sec" style="margin-top:auto;">
            <div class="lbl">Export Data</div>
            <div style="display:flex;flex-direction:column;gap:7px;">
                <a class="dl-btn" href="/api/download/chamber">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Chamber History
                </a>
                <a class="dl-btn" href="/api/download/sensor">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Sensor History
                </a>
            </div>
        </div>

    </div>
    <!-- /SIDEBAR -->

    <!-- MAIN -->
    <div class="main">
        <div class="chart-area">
            <div class="chart-panel">
                <div class="chart-hdr">
                    <span class="chart-ttl">Light Intensity History</span>
                    <div class="chart-ctrls">
                        <select class="ch-sel" id="channelSelect" onchange="onChannelChange()">
                            <option value="clear" selected>Clear (broadband)</option>
                            <option value="f1">F1 ~405 nm</option>
                            <option value="f2">F2 ~425 nm</option>
                            <option value="fz">FZ ~450 nm</option>
                            <option value="f3">F3 ~475 nm</option>
                            <option value="f4">F4 ~515 nm</option>
                            <option value="f5">F5 ~555 nm</option>
                            <option value="fy">FY ~590 nm</option>
                            <option value="f6">F6 ~630 nm</option>
                            <option value="fxl">FXL ~680 nm</option>
                            <option value="f7">F7 ~710 nm</option>
                            <option value="f8">F8 ~760 nm</option>
                            <option value="nir">NIR ~860 nm</option>
                        </select>
                        <div class="time-grp">
                            <button class="tbtn" onclick="loadHistory(1)">1H</button>
                            <button class="tbtn active" onclick="loadHistory(6)">6H</button>
                            <button class="tbtn" onclick="loadHistory(24)">24H</button>
                            <button class="tbtn" onclick="loadHistory(168)">7D</button>
                        </div>
                    </div>
                </div>
                <div class="sanity" id="sanityChart">&#9888; Reading is outside the expected solar range for current GPS position and time.</div>
                <div class="chart-wrap">
                    <canvas id="luxChart"></canvas>
                </div>
            </div>
        </div>

        <!-- Water system (commented out — re-enable when needed)
        <div class="bot" style="border-top:1px solid var(--rim2);padding:16px 20px;flex-shrink:0;">
            <div style="font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--text-lo);margin-bottom:11px;display:flex;align-items:center;justify-content:space-between;">
                <span>Water System</span>
                <span id="valveBadge">Closed</span>
            </div>
            <div id="waterManualSection">
                <button onclick="setManualValve(true)">Open</button>
                <button onclick="setManualValve(false)">Close</button>
            </div>
        </div>
        -->

    </div>
    <!-- /MAIN -->

</div>

<script>
// ── Chart ──
const ctx = document.getElementById('luxChart').getContext('2d');
const luxChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            {
                label: 'Clear (broadband)',
                data: [],
                borderColor: '#2979ff',
                backgroundColor: 'rgba(41,121,255,0.07)',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5,
                spanGaps: true
            },
            {
                label: 'LED Lux',
                data: [],
                borderColor: '#00e676',
                backgroundColor: 'transparent',
                fill: false,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5
            },
            {
                label: 'Solar Max (theoretical)',
                data: [],
                borderColor: '#ff9800',
                backgroundColor: 'transparent',
                fill: false,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5,
                borderDash: [5, 4],
                spanGaps: true
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: {duration: 0},
        interaction: {intersect: false, mode: 'index'},
        plugins: {
            legend: {
                position: 'top', align: 'end',
                labels: {color:'#5a7a9e', usePointStyle:true, pointStyle:'circle', pointStyleWidth:8, font:{size:11}}
            },
            tooltip: {
                backgroundColor:'#0e1b2e',
                borderColor:'rgba(255,255,255,0.07)',
                borderWidth:1,
                titleColor:'#dce6f5',
                bodyColor:'#5a7a9e',
                titleFont:{size:11},
                bodyFont:{size:11}
            }
        },
        scales: {
            x: {
                grid:{color:'rgba(255,255,255,0.035)'},
                ticks:{color:'#2d4a64', maxTicksLimit:8, font:{size:10}},
                border:{color:'rgba(255,255,255,0.055)'}
            },
            y: {
                grid:{color:'rgba(255,255,255,0.035)'},
                ticks:{color:'#2d4a64', font:{size:10}},
                border:{color:'rgba(255,255,255,0.055)'},
                beginAtZero:true
            }
        }
    }
});

// ── SSE ──
let es = null, reconnTimer = null;

function connectSSE() {
    if (es) es.close();
    es = new EventSource('/api/stream');
    es.onopen = () => {
        setConn(true);
        if (reconnTimer) { clearTimeout(reconnTimer); reconnTimer = null; }
    };
    es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        updateUI(d);
    };
    es.onerror = () => {
        setConn(false);
        es.close();
        reconnTimer = setTimeout(connectSSE, 3000);
    };
}

function setConn(ok) {
    const badge = document.getElementById('connBadge');
    const dot   = document.getElementById('connDot');
    const txt   = document.getElementById('connText');
    const sdot  = document.getElementById('statusDot');
    const stxt  = document.getElementById('statusTxt');
    if (ok) {
        badge.className = 'tb-badge live';
        dot.className   = 'dot ok pulse';
        txt.textContent = 'Live';
        sdot.className  = 'dot ok pulse';
        stxt.textContent = 'Operational';
    } else {
        badge.className = 'tb-badge offline';
        dot.className   = 'dot err';
        txt.textContent = 'Offline';
        sdot.className  = 'dot err';
        stxt.textContent = 'Disconnected';
    }
}

function updateUI(d) {
    // Sanity flag
    const sf = !!d.sanity_flag;
    document.getElementById('sanityWarn').style.display  = sf ? 'flex'  : 'none';
    document.getElementById('sanityChart').style.display = sf ? 'block' : 'none';

    // Lux
    document.getElementById('luxVal').textContent = Number(d.raw_lux).toLocaleString();

    // PWM — skip SSE update during the web-change lockout window
    if (Date.now() - _webChangedAt > 1000) {
        document.getElementById('pwmPct').textContent = ((d.pwm_value / 1023) * 100).toFixed(1);
        document.getElementById('pwmRaw').textContent  = d.pwm_value;
    }

    // Data link
    const lb   = document.getElementById('dataLinkBadge');
    const ltxt = document.getElementById('dataLinkText');
    lb.style.display = 'flex';
    if (d.wired_connected) {
        lb.className   = 'tb-badge wired';
        ltxt.textContent = 'Wired';
    } else {
        lb.className   = 'tb-badge wireless';
        ltxt.textContent = 'Wireless';
    }

    // GPS
    const gps = d.gps || {};
    const fixEl = document.getElementById('gpsFix');
    if (gps.valid) {
        fixEl.textContent = 'Fixed';
        fixEl.style.color = 'var(--ok)';
        document.getElementById('gpsLat').textContent = gps.latitude.toFixed(6) + '\u00b0';
        document.getElementById('gpsLon').textContent = gps.longitude.toFixed(6) + '\u00b0';
        if (gps.unix_time > 0) {
            const dt = new Date(gps.unix_time * 1000);
            const hh = String(dt.getUTCHours()).padStart(2,'0');
            const mm = String(dt.getUTCMinutes()).padStart(2,'0');
            const ss = String(dt.getUTCSeconds()).padStart(2,'0');
            document.getElementById('gpsTimeTb').textContent = `${hh}:${mm}:${ss} UTC`;
        }
    } else {
        fixEl.textContent = 'No Fix';
        fixEl.style.color = 'var(--err)';
        document.getElementById('gpsLat').textContent = '--';
        document.getElementById('gpsLon').textContent = '--';
    }

    // Sync control mode from SSE, but not within 1 s of a web-initiated change.
    // This prevents the stale server state from overwriting the UI before the
    // main loop has had a chance to pick up the POST and broadcast the new value.
    if (Date.now() - _webChangedAt > 1000) {
        const manual = !!d.web_manual_enabled;
        document.getElementById('modeToggle').checked = manual;
        document.getElementById('lblAuto').className   = manual ? 'mode-lbl'               : 'mode-lbl active-auto';
        document.getElementById('lblManual').className = manual ? 'mode-lbl active-manual' : 'mode-lbl';
        const slider = document.getElementById('manualPwmSlider');
        slider.disabled = !manual;
        document.getElementById('manualPwmDisplay').className = manual ? 'sld-val' : 'sld-val dim';
        slider.value = d.web_manual_pwm;
        document.getElementById('manualPwmDisplay').textContent = d.web_manual_pwm;
    }
}

// ── Mode toggle (equivalent to clicking rotary knob) ──
function toggleMode() {
    _webChangedAt = Date.now();
    const manual = document.getElementById('modeToggle').checked;
    const pwm    = parseInt(document.getElementById('manualPwmSlider').value);

    document.getElementById('lblAuto').className   = manual ? 'mode-lbl'               : 'mode-lbl active-auto';
    document.getElementById('lblManual').className = manual ? 'mode-lbl active-manual' : 'mode-lbl';

    const slider = document.getElementById('manualPwmSlider');
    slider.disabled = !manual;
    document.getElementById('manualPwmDisplay').className = manual ? 'sld-val' : 'sld-val dim';

    fetch('/api/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: manual, pwm: pwm})
    });
}

// ── Brightness slider (equivalent to turning rotary knob) ──
let _pwmDebounceTimer = null;
let _webChangedAt     = 0;   // timestamp of last web-initiated control change

function updateManualPwm() {
    _webChangedAt = Date.now();
    const pwm = parseInt(document.getElementById('manualPwmSlider').value);
    document.getElementById('manualPwmDisplay').textContent = pwm;
    // Update LED Output % immediately so it tracks the slider in real time
    document.getElementById('pwmPct').textContent = ((pwm / 1023) * 100).toFixed(1);
    document.getElementById('pwmRaw').textContent = pwm;
    if (document.getElementById('modeToggle').checked) {
        if (_pwmDebounceTimer) clearTimeout(_pwmDebounceTimer);
        _pwmDebounceTimer = setTimeout(() => {
            _pwmDebounceTimer = null;
            fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled: true, pwm: pwm})
            });
        }, 150);
    }
}

// ── Chart history ──
let _hrs = 6, _lastChart = 0;
let _chartAbort  = null;   // AbortController for in-flight fetch pair
let _chartDebounce = null; // debounce timer so rapid calls coalesce

function loadHistory(hours) {
    _hrs = hours;
    document.querySelectorAll('.tbtn').forEach(b => {
        const tag = hours === 168 ? '7D' : hours + 'H';
        b.classList.toggle('active', b.textContent === tag);
    });

    // Debounce: if another call arrives within 200 ms, cancel the pending one
    if (_chartDebounce) clearTimeout(_chartDebounce);
    _chartDebounce = setTimeout(() => {
        _chartDebounce = null;
        _fetchChart(hours);
    }, 200);
}

function _fetchChart(hours) {
    // Cancel any still-running fetch from a previous call
    if (_chartAbort) { _chartAbort.abort(); }
    _chartAbort = new AbortController();
    const sig = _chartAbort.signal;

    const ch  = document.getElementById('channelSelect').value;
    const lbl = document.getElementById('channelSelect').selectedOptions[0].text;

    Promise.all([
        fetch(`/api/history?hours=${hours}&limit=300`, {signal: sig}).then(r => r.json()),
        fetch(`/api/spectrum?hours=${hours}&limit=300`, {signal: sig}).then(r => r.json()),
    ]).then(([hist, spec]) => {
        const specMap  = new Map(spec.map(d => [d.timestamp, d[ch] ?? null]));
        const solarMap = new Map(spec.map(d => [d.timestamp, d.solar_max ?? null]));

        luxChart.data.labels            = hist.map(d => fmt(d.timestamp));
        luxChart.data.datasets[0].label = lbl;
        luxChart.data.datasets[0].data  = hist.map(d => specMap.get(d.timestamp)  ?? null);
        luxChart.data.datasets[1].data  = hist.map(d => d.led_lux);
        luxChart.data.datasets[2].data  = hist.map(d => solarMap.get(d.timestamp) ?? null);
        luxChart.update('none');
    }).catch(err => { if (err.name !== 'AbortError') console.error('loadHistory failed:', err); });
}

function fmt(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function onChannelChange() { loadHistory(_hrs); }

// ── Water system (commented out — re-enable when needed) ──
/*
function loadWaterState() {
    fetch('/api/water').then(r => r.json()).then(d => {
        const auto = d.mode === 'auto';
        document.getElementById('waterModeToggle').checked = auto;
        document.getElementById('waterManualSection').style.display = auto ? 'none'  : 'block';
        document.getElementById('waterAutoSection').style.display   = auto ? 'block' : 'none';
        document.getElementById('waterInterval').value = Math.round(d.auto_interval_s / 60);
        document.getElementById('waterDuration').value = d.auto_duration_s;
    });
}
function setWaterMode() {
    const auto = document.getElementById('waterModeToggle').checked;
    if (!auto) postWater({mode:'manual', manual_open:false});
}
function setManualValve(open) { postWater({mode:'manual', manual_open:open}); }
function saveAutoSchedule() {
    const mins = parseInt(document.getElementById('waterInterval').value) || 120;
    const dur  = parseInt(document.getElementById('waterDuration').value) || 10;
    postWater({mode:'auto', auto_interval_s:mins*60, auto_duration_s:dur});
}
function postWater(payload) {
    fetch('/api/water', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload)
    }).then(() => loadWaterState());
}
*/

// ── Init ──
connectSSE();
loadHistory(6);
setInterval(() => loadHistory(_hrs), 5000);
</script>
</body>
</html>"""


def run_server(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask server."""
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=True)
