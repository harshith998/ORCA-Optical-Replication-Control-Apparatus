#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  wifi.sh — Connect to a WiFi network (open or secured)
#  Place this file at: /usr/local/bin/wifi  (done by setup.sh)
#  Usage:
#    wifi "NetworkName"              # open (no password)
#    wifi "NetworkName" "password"   # WPA/WPA2
# ─────────────────────────────────────────────────────────────

SSID="$1"
PASSWORD="$2"

if [ -z "$SSID" ]; then
    echo "Usage: wifi <ssid> [password]"
    echo "  Open network:    wifi \"NetworkName\""
    echo "  Secured network: wifi \"NetworkName\" \"password\""
    exit 1
fi

echo "──────────────────────────────────────"
echo " Connecting to WiFi"
echo "──────────────────────────────────────"

# ── 1. Tear down hotspot if it is running ─────────────────────
if sudo nmcli con show --active | grep -q "^orca-hotspot"; then
    echo "[INFO] Stopping hotspot..."
    sudo nmcli con down orca-hotspot 2>/dev/null || true
fi

# ── 2. Connect ─────────────────────────────────────────────────
if [ -z "$PASSWORD" ]; then
    echo "[INFO] Connecting to open network: $SSID"
    sudo nmcli dev wifi connect "$SSID" ifname wlan0
else
    echo "[INFO] Connecting to: $SSID"
    sudo nmcli dev wifi connect "$SSID" password "$PASSWORD" ifname wlan0
fi

if [ $? -eq 0 ]; then
    IP=$(nmcli -t -f IP4.ADDRESS dev show wlan0 2>/dev/null | head -1 | cut -d: -f2 | cut -d/ -f1)
    echo ""
    echo "[SUCCESS] Connected to: $SSID"
    [ -n "$IP" ] && echo "  Pi IP: $IP"
    echo ""
    echo "[INFO] Run 'hotspot' to switch back to AP mode."
else
    echo "[ERROR] Failed to connect to: $SSID"
    echo "[INFO] Try running 'hotspot' to restore AP mode."
    exit 1
fi
echo "──────────────────────────────────────"
