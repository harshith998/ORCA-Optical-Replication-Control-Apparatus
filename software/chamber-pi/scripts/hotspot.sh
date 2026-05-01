#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  hotspot.sh — Switch the Pi back to hotspot (AP) mode
#  Place this file at: /usr/local/bin/hotspot  (done by setup.sh)
#  Usage: hotspot
# ─────────────────────────────────────────────────────────────

echo "──────────────────────────────────────"
echo " Switching to Hotspot Mode"
echo "──────────────────────────────────────"

# ── 1. Verify the hotspot profile exists ───────────────────────
if ! sudo nmcli con show orca-hotspot &>/dev/null; then
    echo "[ERROR] orca-hotspot profile not found. Has setup.sh been run?"
    exit 1
fi

# ── 2. Tear down any active WiFi client connection ────────────
ACTIVE_WIFI=$(sudo nmcli -t -f NAME,TYPE,STATE con show --active \
    | grep ":802-11-wireless:activated" \
    | grep -v "^orca-hotspot:" \
    | cut -d: -f1)

if [ -n "$ACTIVE_WIFI" ]; then
    echo "[INFO] Disconnecting from: $ACTIVE_WIFI"
    sudo nmcli con down "$ACTIVE_WIFI" 2>/dev/null || true
fi

# ── 3. Bring up hotspot ────────────────────────────────────────
echo "[INFO] Starting hotspot..."
sudo nmcli con up orca-hotspot
if [ $? -eq 0 ]; then
    echo ""
    echo "[SUCCESS] Hotspot active"
    echo "  SSID:      ORCA-Pi"
    echo "  Password:  orca1234"
    echo "  Pi IP:     10.42.0.1"
    echo "  Dashboard: http://10.42.0.1:5000"
    echo "  SSH:       ssh pi@10.42.0.1"
else
    echo "[ERROR] Failed to start hotspot."
    exit 1
fi
echo "──────────────────────────────────────"
