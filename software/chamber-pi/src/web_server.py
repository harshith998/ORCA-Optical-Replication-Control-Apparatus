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

# ---------------------------------------------------------------------------
# Water / Solenoid Scheduler
# ---------------------------------------------------------------------------

_solenoid_setter = None  # injected by main.py: callable (bool) -> None


def register_solenoid_setter(fn):
    global _solenoid_setter
    _solenoid_setter = fn


class WaterScheduler:
    """Background thread that drives the solenoid in auto or manual mode."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._valve_open = False
        self._lock = threading.Lock()

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._set_valve(False)

    def _set_valve(self, on: bool):
        with self._lock:
            self._valve_open = on
        if _solenoid_setter:
            _solenoid_setter(on)

    def get_valve_open(self) -> bool:
        with self._lock:
            return self._valve_open

    def _run(self):
        while not self._stop_event.is_set():
            state = db.get_water_control_state()
            if state['mode'] == 'manual':
                self._set_valve(state['manual_open'])
                self._stop_event.wait(0.5)
            else:  # auto
                interval = max(1, state['auto_interval_s'])
                duration = max(1, state['auto_duration_s'])
                self._set_valve(True)
                self._stop_event.wait(duration)
                if self._stop_event.is_set():
                    break
                self._set_valve(False)
                self._stop_event.wait(max(0, interval - duration))
        self._set_valve(False)


water_scheduler = WaterScheduler()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')

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
    'sw1': False,
    'sw2': False,
    'web_manual_enabled': False,
    'web_manual_pwm': 0,
    'sanity_flag': False,
    'wired_connected': False,
    'gps': {'valid': False, 'latitude': 0.0, 'longitude': 0.0, 'unix_time': 0},
    'timestamp': time.time()
}
state_lock = threading.Lock()


def update_current_state(raw_lux: int, clamped_lux: int, pwm_value: int,
                         mode: str, bounds_min: int, bounds_max: int,
                         sw1: bool, sw2: bool,
                         sanity_flag: bool = False,
                         wired_connected: bool = False,
                         gps: dict = None):
    """Update current state and notify SSE subscribers."""
    with state_lock:
        current_state['raw_lux'] = raw_lux
        current_state['clamped_lux'] = clamped_lux
        current_state['pwm_value'] = pwm_value
        current_state['mode'] = mode
        current_state['bounds_min'] = bounds_min
        current_state['bounds_max'] = bounds_max
        current_state['sw1'] = sw1
        current_state['sw2'] = sw2
        current_state['sanity_flag'] = sanity_flag
        current_state['wired_connected'] = wired_connected
        if gps is not None:
            current_state['gps'] = gps
        current_state['timestamp'] = time.time()
        state_copy = current_state.copy()

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
        return jsonify(db.get_web_control_state())

    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    pwm = max(0, min(MAX_PWM_VALUE, int(data.get('pwm', 0))))

    db.set_web_control_state(enabled, pwm)

    with state_lock:
        current_state['web_manual_enabled'] = enabled
        current_state['web_manual_pwm'] = pwm

    return jsonify({'success': True, 'enabled': enabled, 'pwm': pwm})


@app.route('/api/history')
def api_history():
    hours = request.args.get('hours', 24, type=float)
    limit = request.args.get('limit', 1000, type=int)
    start_time = time.time() - (hours * 3600)
    return jsonify(db.get_history(start_time=start_time, limit=limit))


@app.route('/api/stats')
def api_stats():
    hours = request.args.get('hours', 24, type=int)
    return jsonify(db.get_stats(hours))


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


@app.route('/api/water', methods=['GET', 'POST'])
def api_water():
    if request.method == 'GET':
        state = db.get_water_control_state()
        state['valve_open'] = water_scheduler.get_valve_open()
        return jsonify(state)

    data = request.get_json() or {}
    mode = data.get('mode', 'manual')
    if mode not in ('manual', 'auto'):
        return jsonify({'error': 'mode must be manual or auto'}), 400

    manual_open = bool(data.get('manual_open', False))
    auto_interval_s = max(1, int(data.get('auto_interval_s', 7200)))
    auto_duration_s = max(1, int(data.get('auto_duration_s', 10)))

    db.set_water_control_state(mode, manual_open, auto_interval_s, auto_duration_s)
    return jsonify({'success': True, 'mode': mode, 'manual_open': manual_open,
                    'auto_interval_s': auto_interval_s, 'auto_duration_s': auto_duration_s})


@app.route('/api/spectrum')
def api_spectrum():
    hours = request.args.get('hours', 6, type=float)
    limit = request.args.get('limit', 500, type=int)
    return jsonify(db.get_spectral_history(hours=hours, limit=limit))


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
    --sb:           280px;
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
.tb-logo{
    display:flex;
    align-items:center;
    gap:9px;
}
.tb-mark{
    width:26px;height:26px;
    background:var(--accent);
    border-radius:5px;
    display:flex;align-items:center;justify-content:center;
}
.tb-mark svg{width:14px;height:14px;fill:white;}
.tb-name{
    font-size:14px;font-weight:700;
    letter-spacing:0.06em;
    color:var(--text-hi);
}
.tb-sep{width:1px;height:18px;background:var(--rim2);}
.tb-sub{font-size:12px;color:var(--text-mid);}
.tb-sp{flex:1;}
.tb-badge{
    display:flex;align-items:center;gap:6px;
    padding:4px 11px;
    border-radius:3px;
    font-size:10px;font-weight:700;
    letter-spacing:0.09em;text-transform:uppercase;
    border:1px solid transparent;
}
.tb-badge.wired{background:var(--accent-dim);color:#6fa3ff;border-color:var(--accent-rim);}
.tb-badge.wireless{background:rgba(168,85,247,0.1);color:#c084fc;border-color:rgba(168,85,247,0.25);}
.tb-badge.live{background:var(--ok-dim);color:var(--ok);border-color:var(--ok-rim);}
.tb-badge.offline{background:var(--err-dim);color:var(--err);border-color:var(--err-rim);}
.tb-time{font-size:12px;color:var(--text-mid);font-variant-numeric:tabular-nums;letter-spacing:0.03em;}
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

.sb-sec{padding:18px 18px 14px;border-bottom:1px solid var(--rim);}
.sb-sec:last-child{border-bottom:none;flex:1;}

.lbl{
    font-size:9px;font-weight:700;
    letter-spacing:0.14em;text-transform:uppercase;
    color:var(--text-lo);
    margin-bottom:10px;
}

/* Status row */
.status-row{display:flex;align-items:center;gap:8px;margin-bottom:5px;}
.status-txt{font-size:19px;font-weight:600;color:var(--text-hi);}

/* Big metric */
.big-val{
    font-size:42px;font-weight:700;line-height:1;
    color:var(--text-hi);font-variant-numeric:tabular-nums;
}
.big-unit{font-size:14px;font-weight:400;color:var(--text-mid);margin-left:3px;}
.big-sub{font-size:11px;color:var(--text-mid);margin-top:5px;}

/* Rows */
.row{display:flex;justify-content:space-between;align-items:baseline;padding:5px 0;}
.row-k{font-size:11px;color:var(--text-mid);}
.row-v{font-size:12px;color:var(--text-hi);font-weight:500;font-variant-numeric:tabular-nums;}

/* Mode pill */
.pill{
    display:inline-flex;align-items:center;gap:5px;
    padding:3px 9px;
    border-radius:3px;
    font-size:10px;font-weight:700;
    letter-spacing:0.09em;text-transform:uppercase;
}
.pill.auto{background:var(--ok-dim);color:var(--ok);border:1px solid var(--ok-rim);}
.pill.manual{background:var(--accent-dim);color:#6fa3ff;border:1px solid var(--accent-rim);}

/* ── MAIN ── */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;}

/* Chart area */
.chart-area{
    flex:1;min-height:0;
    padding:16px 18px 14px;
    display:flex;flex-direction:column;
}
.chart-panel{
    flex:1;min-height:0;
    background:var(--bg-card);
    border:1px solid var(--rim2);
    border-radius:7px;
    padding:14px 16px;
    display:flex;flex-direction:column;
}
.chart-hdr{
    display:flex;align-items:center;justify-content:space-between;
    margin-bottom:10px;flex-shrink:0;
}
.chart-ttl{
    font-size:10px;font-weight:700;
    letter-spacing:0.12em;text-transform:uppercase;
    color:var(--text-mid);
}
.chart-ctrls{display:flex;align-items:center;gap:8px;}
.ch-sel{
    padding:3px 8px;
    background:var(--bg-raised);
    border:1px solid var(--rim2);
    border-radius:3px;
    color:var(--text-hi);
    font-size:10px;
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
    padding:3px 10px;border:none;background:transparent;
    color:var(--text-mid);font-size:10px;font-weight:700;
    cursor:pointer;letter-spacing:0.06em;transition:all 0.12s;
}
.tbtn:hover{color:var(--text-hi);}
.tbtn.active{background:var(--accent);color:#fff;}
.chart-wrap{flex:1;min-height:0;position:relative;}

/* Sanity warning (in chart area) */
.sanity{
    display:none;
    padding:5px 10px;
    background:var(--warn-dim);
    border:1px solid rgba(255,171,64,0.25);
    border-radius:3px;
    color:var(--warn);
    font-size:10px;
    margin-bottom:8px;
    flex-shrink:0;
}

/* ── BOTTOM ROW ── */
.bot{
    display:flex;
    border-top:1px solid var(--rim2);
    flex-shrink:0;
    height:190px;
}
.bot-panel{
    flex:1;
    padding:14px 16px;
    border-right:1px solid var(--rim2);
    overflow-y:auto;
    min-width:0;
}
.bot-panel:last-child{border-right:none;}
.bot-panel::-webkit-scrollbar{width:3px;}
.bot-panel::-webkit-scrollbar-track{background:transparent;}
.bot-panel::-webkit-scrollbar-thumb{background:var(--rim2);}

.bot-ttl{
    font-size:9px;font-weight:700;
    letter-spacing:0.14em;text-transform:uppercase;
    color:var(--text-lo);
    margin-bottom:11px;
    display:flex;align-items:center;justify-content:space-between;
}

/* Toggle */
.tog-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px;}
.tog-lbl{font-size:12px;color:var(--text-mid);}
.tog{position:relative;width:38px;height:20px;flex-shrink:0;}
.tog input{opacity:0;width:0;height:0;}
.tog-track{
    position:absolute;inset:0;
    background:var(--bg-raised);
    border:1px solid var(--rim2);
    border-radius:10px;cursor:pointer;transition:0.18s;
}
.tog-track::before{
    content:'';position:absolute;
    width:14px;height:14px;top:2px;left:2px;
    background:var(--text-mid);border-radius:50%;transition:0.18s;
}
.tog input:checked + .tog-track{background:var(--accent-dim);border-color:var(--accent-rim);}
.tog input:checked + .tog-track::before{background:var(--accent);transform:translateX(18px);}

/* Slider */
.sld-row{display:flex;align-items:center;gap:8px;}
.sld-lbl{font-size:10px;color:var(--text-mid);flex-shrink:0;}
.sld-row input[type=range]{
    flex:1;height:3px;-webkit-appearance:none;
    background:var(--bg-raised);border-radius:2px;outline:none;cursor:pointer;
}
.sld-row input[type=range]::-webkit-slider-thumb{
    -webkit-appearance:none;width:14px;height:14px;
    background:var(--accent);border-radius:50%;
    box-shadow:0 0 8px rgba(41,121,255,0.45);
}
.sld-row input[type=range]:disabled{opacity:0.25;cursor:not-allowed;}
.sld-row input[type=range]:disabled::-webkit-slider-thumb{background:var(--text-mid);box-shadow:none;}
.sld-val{font-size:12px;font-weight:600;color:var(--accent);min-width:32px;text-align:right;font-variant-numeric:tabular-nums;}

/* Buttons */
.btn-row{display:flex;gap:7px;margin-top:9px;}
.btn{
    flex:1;padding:7px 10px;
    border:1px solid var(--rim2);border-radius:3px;
    background:var(--bg-raised);color:var(--text-mid);
    font-size:10px;font-weight:700;letter-spacing:0.09em;text-transform:uppercase;
    cursor:pointer;transition:all 0.12s;
}
.btn:hover{color:var(--text-hi);}
.btn.ok{border-color:var(--ok-rim);color:var(--ok);}
.btn.ok:hover{background:var(--ok-dim);}
.btn.err{border-color:var(--err-rim);color:var(--err);}
.btn.err:hover{background:var(--err-dim);}
.btn.acc{background:var(--accent-dim);border-color:var(--accent-rim);color:#6fa3ff;}
.btn.acc:hover{background:rgba(41,121,255,0.2);}

/* Valve badge */
.vbadge{
    display:inline-flex;align-items:center;gap:4px;
    padding:2px 7px;border-radius:3px;
    font-size:9px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
}
.vbadge.open{background:var(--ok-dim);color:var(--ok);}
.vbadge.closed{background:var(--err-dim);color:var(--err);}

/* Fields */
.field-row{display:flex;gap:7px;margin-bottom:7px;}
.field{flex:1;}
.field label{display:block;font-size:9px;color:var(--text-lo);margin-bottom:3px;letter-spacing:0.06em;}
.field input[type=number]{
    width:100%;padding:5px 7px;
    background:var(--bg-input);
    border:1px solid var(--rim2);border-radius:3px;
    color:var(--text-hi);font-size:12px;outline:none;
}
.field input[type=number]:focus{border-color:var(--accent-rim);}

/* ── RESPONSIVE ── */
@media(max-width:860px){
    body{overflow:auto;height:auto;}
    .layout{flex-direction:column;overflow:visible;}
    .sb{width:100%;border-right:none;border-bottom:1px solid var(--rim2);overflow:visible;flex-direction:row;flex-wrap:wrap;}
    .sb-sec{flex:1;min-width:140px;border-bottom:none;border-right:1px solid var(--rim);}
    .main{overflow:visible;}
    .chart-area{min-height:320px;}
    .bot{flex-direction:column;height:auto;}
    .bot-panel{border-right:none;border-bottom:1px solid var(--rim2);}
    .bot-panel:last-child{border-bottom:none;}
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
            <div style="margin-top:7px;" id="modePill">
                <span class="pill auto"><span class="dot ok" style="width:5px;height:5px;"></span>&nbsp;Auto Lux</span>
            </div>
        </div>

        <!-- Light Intensity -->
        <div class="sb-sec">
            <div class="lbl">Light Intensity</div>
            <div>
                <span class="big-val" id="luxVal">--</span>
                <span class="big-unit">lux</span>
            </div>
            <div class="big-sub">Clamped: <span id="clampedVal">--</span> lux</div>
            <div style="margin-top:9px;">
                <div class="row"><span class="row-k">Bounds min</span><span class="row-v" id="boundsMin">--</span></div>
                <div class="row"><span class="row-k">Bounds max</span><span class="row-v" id="boundsMax">--</span></div>
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

        <!-- GPS / Satellite -->
        <div class="sb-sec">
            <div class="lbl">GPS / Satellite</div>
            <div class="row"><span class="row-k">Fix</span><span class="row-v" id="gpsFix">--</span></div>
            <div class="row"><span class="row-k">Latitude</span><span class="row-v" id="gpsLat">--</span></div>
            <div class="row"><span class="row-k">Longitude</span><span class="row-v" id="gpsLon">--</span></div>
        </div>

    </div>
    <!-- /SIDEBAR -->

    <!-- MAIN -->
    <div class="main">

        <!-- Chart -->
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

        <!-- Bottom controls -->
        <div class="bot">

            <!-- Web Manual Control -->
            <div class="bot-panel">
                <div class="bot-ttl">Web Manual Control</div>
                <div class="tog-row">
                    <span class="tog-lbl">Enable Web Override</span>
                    <label class="tog">
                        <input type="checkbox" id="webManualToggle" onchange="toggleWebManual()">
                        <span class="tog-track"></span>
                    </label>
                </div>
                <div class="sld-row">
                    <span class="sld-lbl">Brightness</span>
                    <input type="range" id="manualPwmSlider" min="0" max="1023" value="0"
                           oninput="updateManualPwm()" disabled>
                    <span class="sld-val" id="manualPwmDisplay">0</span>
                </div>
            </div>

            <!-- Water System -->
            <div class="bot-panel">
                <div class="bot-ttl">
                    <span>Water System</span>
                    <span class="vbadge closed" id="valveBadge">
                        <span class="dot err" style="width:5px;height:5px;"></span> Closed
                    </span>
                </div>
                <div class="tog-row">
                    <span class="tog-lbl">Auto Schedule</span>
                    <label class="tog">
                        <input type="checkbox" id="waterModeToggle" onchange="setWaterMode()">
                        <span class="tog-track"></span>
                    </label>
                </div>
                <div id="waterManualSection">
                    <div class="btn-row">
                        <button class="btn ok" onclick="setManualValve(true)">Open</button>
                        <button class="btn err" onclick="setManualValve(false)">Close</button>
                    </div>
                </div>
                <div id="waterAutoSection" style="display:none;">
                    <div class="field-row">
                        <div class="field">
                            <label>Interval (min)</label>
                            <input type="number" id="waterInterval" min="1" value="120">
                        </div>
                        <div class="field">
                            <label>Duration (sec)</label>
                            <input type="number" id="waterDuration" min="1" value="10">
                        </div>
                    </div>
                    <button class="btn acc" style="width:100%;margin-top:0;" onclick="saveAutoSchedule()">Save Schedule</button>
                </div>
            </div>

            <!-- USB Logger -->
            <div class="bot-panel">
                <div class="bot-ttl">USB Logger</div>
                <div class="row"><span class="row-k">Status</span><span class="row-v" id="usbStatus">--</span></div>
                <div class="row"><span class="row-k">Drive</span><span class="row-v" id="usbPath" style="font-size:10px;word-break:break-all;">--</span></div>
                <div class="row"><span class="row-k">File</span><span class="row-v" id="usbFile" style="font-size:10px;word-break:break-all;">--</span></div>
            </div>

        </div>
        <!-- /bot -->

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
                label: 'Raw Lux',
                data: [],
                borderColor: '#2979ff',
                backgroundColor: 'rgba(41,121,255,0.07)',
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5
            },
            {
                label: 'Clamped',
                data: [],
                borderColor: '#00e5a0',
                backgroundColor: 'transparent',
                borderDash: [4,4],
                tension: 0.3,
                pointRadius: 0,
                borderWidth: 1.5
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
                labels: {color:'#5a7a9e', usePointStyle:true, pointStyleWidth:10, font:{size:10}}
            },
            tooltip: {
                backgroundColor:'#0e1b2e',
                borderColor:'rgba(255,255,255,0.07)',
                borderWidth:1,
                titleColor:'#dce6f5',
                bodyColor:'#5a7a9e',
                titleFont:{size:10},
                bodyFont:{size:10}
            }
        },
        scales: {
            x: {
                grid:{color:'rgba(255,255,255,0.035)'},
                ticks:{color:'#2d4a64', maxTicksLimit:8, font:{size:9}},
                border:{color:'rgba(255,255,255,0.055)'}
            },
            y: {
                grid:{color:'rgba(255,255,255,0.035)'},
                ticks:{color:'#2d4a64', font:{size:9}},
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
        const now = Date.now();
        if (now - _lastChart > 10000) { _lastChart = now; loadHistory(_hrs); }
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
    // Sanity
    const sf = !!d.sanity_flag;
    document.getElementById('sanityWarn').style.display  = sf ? 'flex'  : 'none';
    document.getElementById('sanityChart').style.display = sf ? 'block' : 'none';

    // Lux
    document.getElementById('luxVal').textContent     = Number(d.raw_lux).toLocaleString();
    document.getElementById('clampedVal').textContent = Number(d.clamped_lux).toLocaleString();
    document.getElementById('boundsMin').textContent  = Number(d.bounds_min).toLocaleString();
    document.getElementById('boundsMax').textContent  = Number(d.bounds_max).toLocaleString();

    // PWM
    document.getElementById('pwmPct').textContent = ((d.pwm_value / 1023) * 100).toFixed(1);
    document.getElementById('pwmRaw').textContent  = d.pwm_value;

    // Mode
    const pill = document.getElementById('modePill');
    if (d.web_manual_enabled) {
        pill.innerHTML = '<span class="pill manual"><span class="dot acc" style="width:5px;height:5px;"></span>&nbsp;Web Manual</span>';
    } else {
        pill.innerHTML = '<span class="pill auto"><span class="dot ok" style="width:5px;height:5px;"></span>&nbsp;Auto Lux</span>';
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

    // Web manual sync (physical knob changes reflected in UI)
    document.getElementById('webManualToggle').checked = d.web_manual_enabled;
    const slider = document.getElementById('manualPwmSlider');
    slider.disabled = !d.web_manual_enabled;
    if (!slider.matches(':active')) {
        slider.value = d.web_manual_pwm;
        document.getElementById('manualPwmDisplay').textContent = d.web_manual_pwm;
    }
}

// ── Manual Control ──
function toggleWebManual() {
    const enabled = document.getElementById('webManualToggle').checked;
    const pwm     = parseInt(document.getElementById('manualPwmSlider').value);
    document.getElementById('manualPwmSlider').disabled = !enabled;
    fetch('/api/control', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({enabled, pwm})
    });
}

function updateManualPwm() {
    const pwm = parseInt(document.getElementById('manualPwmSlider').value);
    document.getElementById('manualPwmDisplay').textContent = pwm;
    if (document.getElementById('webManualToggle').checked) {
        fetch('/api/control', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({enabled:true, pwm})
        });
    }
}

// ── Chart history ──
let _hrs = 6, _lastChart = 0;

function loadHistory(hours) {
    _hrs = hours;
    document.querySelectorAll('.tbtn').forEach(b => {
        const tag = hours === 168 ? '7D' : hours + 'H';
        b.classList.toggle('active', b.textContent === tag);
    });

    const ch = document.getElementById('channelSelect').value;

    if (ch === 'clear') {
        fetch(`/api/history?hours=${hours}&limit=500`)
            .then(r => r.json())
            .then(data => {
                luxChart.data.labels             = data.map(d => fmt(d.timestamp));
                luxChart.data.datasets[0].label  = 'Raw Lux';
                luxChart.data.datasets[0].data   = data.map(d => d.raw_lux);
                luxChart.data.datasets[1].label  = 'Clamped';
                luxChart.data.datasets[1].data   = data.map(d => d.clamped_lux);
                luxChart.data.datasets[1].hidden = false;
                luxChart.update('none');
            });
    } else {
        fetch(`/api/spectrum?hours=${hours}&limit=500`)
            .then(r => r.json())
            .then(data => {
                const lbl = document.getElementById('channelSelect').selectedOptions[0].text;
                luxChart.data.labels             = data.map(d => fmt(d.timestamp));
                luxChart.data.datasets[0].label  = lbl;
                luxChart.data.datasets[0].data   = data.map(d => d[ch] ?? 0);
                luxChart.data.datasets[1].data   = [];
                luxChart.data.datasets[1].hidden = true;
                luxChart.update('none');
            });
    }
}

function fmt(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function onChannelChange() { loadHistory(_hrs); }

// ── Water System ──
function loadWaterState() {
    fetch('/api/water').then(r => r.json()).then(d => {
        const auto = d.mode === 'auto';
        document.getElementById('waterModeToggle').checked = auto;
        document.getElementById('waterManualSection').style.display = auto ? 'none'  : 'block';
        document.getElementById('waterAutoSection').style.display   = auto ? 'block' : 'none';
        document.getElementById('waterInterval').value = Math.round(d.auto_interval_s / 60);
        document.getElementById('waterDuration').value = d.auto_duration_s;
        updateValveBadge(d.valve_open);
    });
}

function updateValveBadge(open) {
    const b = document.getElementById('valveBadge');
    if (open) {
        b.className = 'vbadge open';
        b.innerHTML = '<span class="dot ok" style="width:5px;height:5px;"></span> Open';
    } else {
        b.className = 'vbadge closed';
        b.innerHTML = '<span class="dot err" style="width:5px;height:5px;"></span> Closed';
    }
}

function setWaterMode() {
    const auto = document.getElementById('waterModeToggle').checked;
    document.getElementById('waterManualSection').style.display = auto ? 'none'  : 'block';
    document.getElementById('waterAutoSection').style.display   = auto ? 'block' : 'none';
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

// ── USB Logger ──
function loadUsb() {
    fetch('/api/usb').then(r => r.json()).then(d => {
        const st  = document.getElementById('usbStatus');
        const ok  = d.usb_connected;
        st.textContent = ok ? 'Connected' : 'Not found';
        st.style.color = ok ? 'var(--ok)' : 'var(--text-mid)';
        document.getElementById('usbPath').textContent = d.usb_path  || '--';
        document.getElementById('usbFile').textContent = d.csv_path  || '--';
    }).catch(() => {});
}

// ── Init ──
connectSSE();
loadHistory(6);
loadWaterState();
loadUsb();
setInterval(() => loadHistory(_hrs), 30000);
setInterval(loadWaterState, 2000);
setInterval(loadUsb, 5000);
</script>
</body>
</html>"""


def run_server(host='0.0.0.0', port=5000, debug=False):
    """Run the Flask server."""
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=True)
