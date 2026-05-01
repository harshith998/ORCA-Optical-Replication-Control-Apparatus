#!/bin/bash

# ─────────────────────────────────────────────────────────────
#  chamber-help.sh — List all global ORCA commands
#  Place this file at: /usr/local/bin/chamber-help (done by setup.sh)
#  Usage: chamber-help
# ─────────────────────────────────────────────────────────────

echo "──────────────────────────────────────"
echo " ORCA Chamber-Pi — Commands"
echo "──────────────────────────────────────"
echo ""
echo " Application"
echo "   start                    Start ORCA (stops service if running)"
echo "   update                   Pull latest code + sync dependencies"
echo ""
echo " Networking"
echo "   hotspot                  Switch to AP mode (boots into this by default)"
echo "   wifi <ssid>              Connect to an open WiFi network"
echo "   wifi <ssid> <password>   Connect to a secured WiFi network"
echo ""
echo " Hotspot Details"
echo "   SSID:      ORCA-Pi"
echo "   Password:  orca1234"
echo "   Pi IP:     10.42.0.1"
echo "   Dashboard: http://10.42.0.1:5000"
echo "   SSH:       ssh pi@10.42.0.1"
echo ""
echo " Systemd Service"
echo "   sudo systemctl status orca     Check if ORCA is running"
echo "   sudo systemctl stop orca       Stop the service"
echo "   sudo systemctl restart orca    Restart the service"
echo "   sudo journalctl -u orca -f     Live log output"
echo ""
echo " Raspberry Pi"
echo "   sudo raspi-config              Configure SPI / I2C / other interfaces"
echo "   ls -la /dev/serial0            Verify UART points to ttyAMA0"
echo "──────────────────────────────────────"
